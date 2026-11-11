// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//! Pieza «host-tauri»: corre los scripts de bin/ con el Python portátil de la app. Sin ventana adentro (se prueba con
//! `cargo test`). Equivale a `procesador.js` de «host-escritorio» y a `Procesador.swift` de «host-mac». Contrato
//! (nucleo.script): `script.py <args…> [entrada.json] <salida.json>`.
//!   · Lo que manda la interfaz va en el archivo de entrada, nunca como argumento (cualquier programa ve los argumentos).
//!   · Un secreto (la llave de un conector) va por la entrada estándar: nunca en un archivo, un argumento ni el entorno.
//!   · Ninguna variable <ID>_* de afuera llega al script: solo las que pone el host (<ID>_RECURSOS, <ID>_DATOS…) y las de la
//!     app (`entorno_app` para todos sus scripts, también los declarados; `entorno` por llamada), que nunca pisan las del host.
//!   · Todo tiene límite de tiempo: al cumplirse se corta el script y lo que haya lanzado (su grupo de procesos). Un trabajo
//!     largo (`latido`, «limite»: "trabajo") no tiene tope, pero tiene que latir (pieza «trabajos»: <ID>_LATIDO).
//!   · Al salir de la app se corta lo que siga corriendo (`cortar_todo`).
//!   · Entrada y salida viven en una carpeta temporal propia (0700) que se borra al terminar.

use super::enchufe::{aleatorio_hex, es_script, leer_json, solo_persona};
use regex::Regex;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant, SystemTime};

pub const LIMITE: &str = "Tardó demasiado y lo detuve. Intenta de nuevo.";
pub const LATIDO: &str = "Dejó de avanzar y lo detuve. Intenta de nuevo.";
pub const FALLO: &str = "No pude terminar. Intenta de nuevo.";
const MAX_SALIDA_ESTANDAR: usize = 1024 * 1024;
const MAX_ERROR: usize = 4000;

fn es_variable(x: &str) -> bool {
    static C: OnceLock<Regex> = OnceLock::new();
    C.get_or_init(|| Regex::new(r"^[A-Z][A-Z0-9_]{0,60}$").expect("patrón")).is_match(x)
}

/// Lo que da la pieza «trabajos» (progreso.rs): un archivo JSONL que el script llena y que se lee mientras corre.
pub trait LectorProgreso: Send + Sync {
    fn crear(&self, prefijo: &str, aviso: Box<dyn Fn(Vec<Value>) + Send + Sync>) -> Option<Box<dyn Progreso>>;
}
pub trait Progreso: Send {
    fn ruta(&self) -> PathBuf;
    fn terminar(self: Box<Self>);
}

/// Tiempos del latido, en segundos: un trabajo sin latido por más de `muerto` se corta (el primero tiene `primero`).
#[derive(Clone, Copy)]
pub struct TiemposLatido {
    pub muerto: u64,
    pub primero: u64,
    pub revisar: u64,
}
impl Default for TiemposLatido {
    fn default() -> Self {
        TiemposLatido { muerto: 45, primero: 120, revisar: 5 }
    }
}

/// Cómo correr un script.
#[derive(Default)]
pub struct Opciones {
    pub secreto: Option<String>,
    pub progreso: Option<Box<dyn Fn(Vec<Value>) + Send + Sync>>,
    /// Segundos (1 a 3600); sin decirlo, 120.
    pub limite: Option<u64>,
    /// Sin tope mientras el script lata.
    pub latido: bool,
    pub entorno: BTreeMap<String, String>,
    /// Lo que manda la interfaz: va en un archivo de entrada (después de `args`, antes de la salida).
    pub entrada: Option<Value>,
}

pub struct Resultado {
    pub respuesta: Value,
    pub salida_estandar: String,
    pub por_limite: bool,
}

type Traducir = Arc<dyn Fn(&str) -> String + Send + Sync>;
type Entorno = Arc<dyn Fn() -> BTreeMap<String, String> + Send + Sync>;

pub struct Procesador {
    pub python: PathBuf,
    pub recursos: PathBuf,
    pub id: String,
    pub datos: PathBuf,
    /// Los programas que trae la app (ffmpeg, whisper-cli…: `vendor/<os>/herramientas` al empaquetar). Llega a cada script en
    /// `<ID>_HERRAMIENTAS`, que la app no puede pisar.
    pub herramientas: Option<PathBuf>,
    prefijo: String,
    t: Traducir,
    lector: Option<Arc<dyn LectorProgreso>>,
    gracia: Duration,
    tiempos: TiemposLatido,
    /// Variables de la app para todos sus scripts (se leen en cada uno).
    pub entorno_app: Mutex<Option<Entorno>>,
    en_curso: AtomicUsize,
    vivos: Mutex<HashSet<u32>>,
}

impl Procesador {
    pub fn nuevo(python: PathBuf, recursos: PathBuf, id: &str, datos: PathBuf, t: Traducir) -> Self {
        Procesador {
            python,
            recursos,
            prefijo: format!("{}_", id.to_uppercase()),
            id: id.to_string(),
            datos,
            herramientas: None,
            t,
            lector: None,
            gracia: Duration::from_secs(3),
            tiempos: TiemposLatido::default(),
            entorno_app: Mutex::new(None),
            en_curso: AtomicUsize::new(0),
            vivos: Mutex::new(HashSet::new()),
        }
    }
    pub fn con_herramientas(mut self, h: Option<PathBuf>) -> Self {
        self.herramientas = h;
        self
    }
    pub fn con_lector(mut self, l: Option<Arc<dyn LectorProgreso>>) -> Self {
        self.lector = l;
        self
    }
    pub fn con_tiempos(mut self, t: TiemposLatido, gracia: Duration) -> Self {
        self.tiempos = t;
        self.gracia = gracia;
        self
    }
    pub fn hay_lector(&self) -> bool {
        self.lector.is_some()
    }
    /// Variables de la app para todos sus scripts: `host.procesador.poner_entorno(|| …)`.
    pub fn poner_entorno(&self, f: impl Fn() -> BTreeMap<String, String> + Send + Sync + 'static) {
        if let Ok(mut e) = self.entorno_app.lock() {
            *e = Some(Arc::new(f));
        }
    }
    pub fn en_curso(&self) -> usize {
        self.en_curso.load(Ordering::SeqCst)
    }
    /// Detiene todo lo que sigue corriendo (y lo que lanzó). Lo llama el host al salir.
    pub fn cortar_todo(&self) {
        let pids: Vec<u32> = self.vivos.lock().map(|v| v.iter().copied().collect()).unwrap_or_default();
        for p in pids {
            matar(p, false);
        }
    }

    fn falla(error: &str) -> Resultado {
        Resultado { respuesta: json!({"ok": false, "error": error}), salida_estandar: String::new(), por_limite: false }
    }
    fn error(&self, texto: &str, valores: Value) -> Value {
        json!({"ok": false, "codigo": if texto == FALLO { "fallo" } else { "limite" }, "texto": texto, "valores": valores, "error": (self.t)(texto)})
    }

    /// Lo de bajo nivel. Bloquea hasta que el script termina (llámalo desde un hilo propio, nunca desde el de la ventana).
    pub fn correr(&self, script: &str, args: &[String], o: Opciones) -> Resultado {
        if !es_script(script) {
            return Self::falla("script raro");
        }
        let ruta = self.recursos.join("bin").join(script);
        if !ruta.exists() {
            return Self::falla(&format!("no está bin/{script}"));
        }
        if args.iter().any(|a| a.contains('\0')) {
            return Self::falla("argumentos raros");
        }
        let segundos = o.limite.filter(|s| *s > 0).map(|s| s.min(3600)).unwrap_or(120);
        let dir = std::env::temp_dir().join(format!("{}-{}", self.id, aleatorio_hex(8)));
        if let Err(e) = fs::create_dir(&dir) {
            return Self::falla(&e.to_string());
        }
        solo_persona(&dir);
        let borrar = || {
            let _ = fs::remove_dir_all(&dir);
        };
        let salida = dir.join("salida.json");
        let mut todos: Vec<String> = args.to_vec();
        if let Some(entrada) = &o.entrada {
            let archivo = dir.join("entrada.json");
            if let Err(e) = escribir_nuevo(&archivo, entrada.to_string().as_bytes()) {
                borrar();
                return Self::falla(&e.to_string());
            }
            todos.push(archivo.to_string_lossy().into_owned());
        }
        todos.push(salida.to_string_lossy().into_owned());

        let mut c = Command::new(&self.python);
        c.arg(&ruta).args(&todos).current_dir(&dir);
        c.env_clear();
        for (k, v) in std::env::vars_os() {
            if !k.to_string_lossy().to_uppercase().starts_with(&self.prefijo) {
                c.env(k, v);
            }
        }
        let reservadas: Vec<String> = ["RECURSOS", "DATOS", "PROGRESO", "LATIDO", "HERRAMIENTAS"].iter().map(|x| format!("{}{x}", self.prefijo)).collect();
        let de_la_app = self.entorno_app.lock().ok().and_then(|e| e.clone()).map(|f| f()).unwrap_or_default();
        for (k, v) in de_la_app.iter().chain(o.entorno.iter()) {
            if es_variable(k) && !reservadas.contains(k) {
                c.env(k, v);
            }
        }
        c.env(format!("{}RECURSOS", self.prefijo), &self.recursos)
            .env(format!("{}DATOS", self.prefijo), &self.datos)
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
            .env("PYTHONDONTWRITEBYTECODE", "1");
        if let Some(h) = &self.herramientas {
            c.env(format!("{}HERRAMIENTAS", self.prefijo), h);
        }
        let lector = match (&self.lector, o.progreso) {
            (Some(l), Some(aviso)) => l.crear(&self.id, aviso),
            _ => None,
        };
        if let Some(l) = &lector {
            c.env(format!("{}PROGRESO", self.prefijo), l.ruta());
        }
        // Un trabajo late tocando este archivo (trabajos.latir_host): el host mira cuándo fue la última vez.
        let archivo_latido = dir.join("latido");
        if o.latido {
            let _ = escribir_nuevo(&archivo_latido, b"");
            c.env(format!("{}LATIDO", self.prefijo), &archivo_latido);
        }
        let con_secreto = o.secreto.is_some();
        c.stdin(if con_secreto { Stdio::piped() } else { Stdio::null() })
            .stdout(if con_secreto { Stdio::piped() } else { Stdio::null() })
            .stderr(Stdio::piped());
        grupo_propio(&mut c);

        self.en_curso.fetch_add(1, Ordering::SeqCst);
        let mut hijo = match c.spawn() {
            Ok(h) => h,
            Err(e) => {
                self.en_curso.fetch_sub(1, Ordering::SeqCst);
                borrar();
                if let Some(l) = lector {
                    l.terminar();
                }
                return Self::falla(&e.to_string());
            }
        };
        let pid = hijo.id();
        if let Ok(mut v) = self.vivos.lock() {
            v.insert(pid);
        }
        let err = hijo.stderr.take().map(|mut e| {
            thread::spawn(move || {
                let mut b = Vec::new();
                let _ = (&mut e).take(MAX_ERROR as u64).read_to_end(&mut b);
                let _ = std::io::copy(&mut e, &mut std::io::sink());
                String::from_utf8_lossy(&b).into_owned()
            })
        });
        let out = hijo.stdout.take().map(|mut s| {
            thread::spawn(move || {
                let mut b = Vec::new();
                let _ = (&mut s).take(MAX_SALIDA_ESTANDAR as u64).read_to_end(&mut b);
                let _ = std::io::copy(&mut s, &mut std::io::sink());
                String::from_utf8_lossy(&b).into_owned()
            })
        });
        if let (Some(s), Some(mut entrada)) = (o.secreto, hijo.stdin.take()) {
            let _ = entrada.write_all(s.as_bytes());
        }

        let inicio = Instant::now();
        let inicio_reloj = SystemTime::now();
        let mut por_limite = false;
        let mut corte: Option<Instant> = None;
        let mut ultima_revision = Instant::now();
        loop {
            match hijo.try_wait() {
                Ok(Some(_)) | Err(_) => break,
                Ok(None) => {}
            }
            if !por_limite {
                let cortar = if o.latido {
                    if ultima_revision.elapsed() >= Duration::from_secs(self.tiempos.revisar) {
                        ultima_revision = Instant::now();
                        // Sin tope, pero si el latido no se tocó hace más de `muerto` (el primero tiene `primero`), se corta.
                        let tocado = fs::metadata(&archivo_latido).and_then(|m| m.modified()).unwrap_or(inicio_reloj);
                        let gracia_primero = inicio_reloj + Duration::from_secs(self.tiempos.primero.saturating_sub(self.tiempos.muerto));
                        let ultimo = tocado.max(gracia_primero);
                        SystemTime::now().duration_since(ultimo).map(|d| d > Duration::from_secs(self.tiempos.muerto)).unwrap_or(false)
                    } else {
                        false
                    }
                } else {
                    inicio.elapsed() >= Duration::from_secs(segundos)
                };
                if cortar {
                    por_limite = true;
                    matar(pid, false);
                    corte = Some(Instant::now() + self.gracia);
                }
            } else if corte.is_some_and(|c| Instant::now() >= c) {
                matar(pid, true);
                let _ = hijo.kill();
                corte = None;
            }
            thread::sleep(Duration::from_millis(40));
        }
        if let Ok(mut v) = self.vivos.lock() {
            v.remove(&pid);
        }
        self.en_curso.fetch_sub(1, Ordering::SeqCst);
        if let Some(l) = lector {
            l.terminar();
        }
        let err = err.and_then(|h| h.join().ok()).unwrap_or_default();
        let salida_estandar = out.and_then(|h| h.join().ok()).unwrap_or_default();
        let r = if por_limite { None } else { leer_json(&salida, 50 * 1024 * 1024) };
        if r.is_none() && !err.is_empty() && !por_limite {
            let cola: String = err.chars().rev().take(600).collect::<Vec<_>>().into_iter().rev().collect();
            eprintln!("{}: {script}: {cola}", self.id);
        }
        borrar();
        let respuesta = match r {
            _ if por_limite && o.latido => self.error(LATIDO, json!({})),
            _ if por_limite => self.error(LIMITE, json!({"s": segundos})),
            Some(v) if v.is_object() => v,
            _ => self.error(FALLO, json!({})),
        };
        Resultado { respuesta, salida_estandar, por_limite }
    }

    /// El JSON de salida del script (o {ok: false, codigo, texto, error}).
    pub fn correr_json(&self, script: &str, args: &[String], o: Opciones) -> Value {
        self.correr(script, args, o).respuesta
    }
    /// Lo que manda la interfaz va en un archivo de entrada.
    pub fn con_entrada(&self, script: &str, args: &[String], datos: Value, mut o: Opciones) -> Value {
        o.entrada = Some(if datos.is_object() { datos } else { json!({}) });
        self.correr(script, args, o).respuesta
    }
}

fn escribir_nuevo(ruta: &Path, b: &[u8]) -> std::io::Result<()> {
    let mut o = fs::OpenOptions::new();
    o.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        o.mode(0o600);
    }
    o.open(ruta)?.write_all(b)
}

#[cfg(unix)]
fn grupo_propio(c: &mut Command) {
    use std::os::unix::process::CommandExt;
    // Un grupo propio: al cumplirse el límite se corta el script y lo que haya lanzado (la IA, ffmpeg…).
    c.process_group(0);
}
#[cfg(windows)]
fn grupo_propio(c: &mut Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
    c.creation_flags(CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP);
}

/// Corta el proceso y todo lo que lanzó.
pub fn matar(pid: u32, fuerte: bool) {
    #[cfg(unix)]
    unsafe {
        libc::kill(-(pid as i32), if fuerte { libc::SIGKILL } else { libc::SIGTERM });
    }
    #[cfg(windows)]
    {
        let _ = fuerte;
        let mut c = Command::new("taskkill");
        c.args(["/pid", &pid.to_string(), "/T", "/F"]).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
        grupo_propio(&mut c);
        let _ = c.spawn();
    }
}

/// Una fila: las tareas corren de a una y en el orden en que llegaron (guardar nunca pisa un guardado más nuevo).
#[derive(Default)]
pub struct Fila {
    candado: Mutex<()>,
    pendientes: AtomicUsize,
}
impl Fila {
    pub fn agregar<T>(&self, tarea: impl FnOnce() -> T) -> T {
        self.pendientes.fetch_add(1, Ordering::SeqCst);
        let r = {
            let _g = self.candado.lock().unwrap_or_else(|e| e.into_inner());
            tarea()
        };
        self.pendientes.fetch_sub(1, Ordering::SeqCst);
        r
    }
    pub fn pendientes(&self) -> usize {
        self.pendientes.load(Ordering::SeqCst)
    }
}

/// Copia sin `ok` ni `error` (lo que suma el estado de bin/estado.py).
pub fn sin_ok(mut v: Map<String, Value>) -> Map<String, Value> {
    v.remove("ok");
    v.remove("error");
    v
}

#[cfg(all(test, unix))]
mod pruebas {
    use super::*;

    fn app(script: &str) -> (PathBuf, Procesador) {
        let d = std::env::temp_dir().join(format!("pieza-proc-{}", aleatorio_hex(4)));
        fs::create_dir_all(d.join("bin")).unwrap();
        fs::write(d.join("bin").join("x.py"), script).unwrap();
        let p = Procesador::nuevo("python3".into(), d.clone(), "ana", d.join("datos"), Arc::new(|x| x.to_string()));
        (d, p)
    }

    #[test]
    fn entrada_por_archivo_y_entorno_limpio() {
        let (_d, p) = app("import json,os,sys\nd=json.load(open(sys.argv[-2]))\njson.dump({'ok':True,'eco':d['t'],'arg':sys.argv[1],'fuga':os.environ.get('ANA_SECRETO'),'datos':bool(os.environ.get('ANA_DATOS'))},open(sys.argv[-1],'w'))\n");
        std::env::set_var("ANA_SECRETO", "no");
        let r = p.con_entrada("x.py", &["leer".into()], json!({"t": "hola"}), Opciones::default());
        assert_eq!(r["eco"], "hola");
        assert_eq!(r["arg"], "leer");
        assert!(r["fuga"].is_null());
        assert_eq!(r["datos"], true);
    }

    #[test]
    fn herramientas_de_la_app() {
        let (d, p) = app("import json,os,sys\njson.dump({'ok':True,'h':os.environ.get('ANA_HERRAMIENTAS')},open(sys.argv[-1],'w'))\n");
        assert!(p.correr_json("x.py", &[], Opciones::default())["h"].is_null(), "sin herramientas, nada");
        let h = d.join("herramientas");
        let p = p.con_herramientas(Some(h.clone()));
        std::env::set_var("ANA_HERRAMIENTAS", "/de/afuera");
        let o = Opciones { entorno: [("ANA_HERRAMIENTAS".to_string(), "/de/la/app".to_string())].into(), ..Default::default() };
        assert_eq!(p.correr_json("x.py", &[], o)["h"], h.to_string_lossy().as_ref(), "ni afuera ni la app la pisan");
    }

    #[test]
    fn limite_corta_al_script() {
        let (_d, p) = app("import time\ntime.sleep(30)\n");
        let p = p.con_tiempos(TiemposLatido::default(), Duration::from_millis(200));
        let t = Instant::now();
        let r = p.correr("x.py", &[], Opciones { limite: Some(1), ..Default::default() });
        assert!(r.por_limite);
        assert_eq!(r.respuesta["codigo"], "limite");
        assert!(t.elapsed() < Duration::from_secs(5));
    }

    #[test]
    fn secreto_por_la_entrada_estandar() {
        let (_d, p) = app("import json,sys\ns=sys.stdin.read()\njson.dump({'ok':True,'n':len(s)},open(sys.argv[-1],'w'))\n");
        let r = p.correr_json("x.py", &[], Opciones { secreto: Some("clave".into()), ..Default::default() });
        assert_eq!(r["n"], 5);
    }

    #[test]
    fn sin_salida_es_fallo() {
        let (_d, p) = app("raise SystemExit(3)\n");
        let r = p.correr_json("x.py", &[], Opciones::default());
        assert_eq!(r["codigo"], "fallo");
        assert_eq!(p.correr_json("../x.py", &[], Opciones::default())["ok"], false);
    }
}
