// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//! Pieza «host-tauri»: la lógica del host que no necesita una ventana (se prueba con `cargo test`). Equivale a `enchufe.js`
//! de «host-escritorio» y a `Host.swift` + `Enchufe.swift` de «host-mac», con las mismas reglas que `bin/nucleo.py` y
//! `herramientas/pieza.py`:
//!   · app.json: id, nombre, carpeta de datos y claves de config permitidas (lo demás se descarta);
//!   · idioma: el elegido o el del sistema, y las frases de ui/idiomas/<codigo>.json;
//!   · acciones declaradas (acciones.json): se validan al cargar y cada mensaje de la interfaz se valida contra sus reglas
//!     antes de correr nada;
//!   · dentro(base, relativa): la misma guarda que nucleo.ruta_en.

use regex::Regex;
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::{Component, Path, PathBuf};
use std::sync::{Mutex, OnceLock};

/// Lo que puede pesar la entrada de una acción, salvo que diga «maximo».
pub const MAXIMO_ENTRADA: u64 = 5 * 1024 * 1024;
/// «maximo» como mucho.
pub const TOPE_ENTRADA: u64 = 50 * 1024 * 1024;
const PROHIBIDOS: [&str; 3] = ["__proto__", "constructor", "prototype"];
const TIPOS: [&str; 7] = ["texto", "enum", "bool", "entero", "rutaRelativa", "base64", "lista"];
/// El entero más grande que JavaScript guarda exacto (Number.MAX_SAFE_INTEGER).
const SEGURO: i64 = 9_007_199_254_740_991;

fn re(patron: &'static str, celda: &'static OnceLock<Regex>) -> &'static Regex {
    celda.get_or_init(|| Regex::new(patron).expect("patrón del host"))
}
macro_rules! patron {
    ($nombre:ident, $p:expr) => {
        pub fn $nombre(x: &str) -> bool {
            static C: OnceLock<Regex> = OnceLock::new();
            re($p, &C).is_match(x)
        }
    };
}
patron!(es_id, r"^[a-z][a-z0-9]{0,30}$");
patron!(es_accion, r"^[A-Za-z][A-Za-z0-9]{0,60}$");
patron!(es_script, r"^\w+\.py$");
patron!(es_literal, r"^[\w.-]+$");
patron!(es_campo, r"^[A-Za-z_]\w{0,60}$");
patron!(es_extension, r"^\.\w{1,10}$");
patron!(es_idioma, r"^[a-z]{2,3}$");
/// Los nombres de función de `window.<App>` siguen la misma regla que las acciones.
pub fn es_funcion(x: &str) -> bool {
    es_accion(x)
}

pub fn es_objeto(v: &Value) -> bool {
    v.is_object()
}
fn prohibido(k: &str) -> bool {
    PROHIBIDOS.contains(&k)
}
/// Un entero de JavaScript «seguro» (sin decimales y dentro de Number.MAX_SAFE_INTEGER).
fn entero(v: &Value) -> Option<i64> {
    let n = v.as_i64().or_else(|| v.as_f64().filter(|f| f.fract() == 0.0 && f.abs() <= SEGURO as f64).map(|f| f as i64))?;
    (n.abs() <= SEGURO).then_some(n)
}

/// Un JSON del disco, o None (no existe, pesa más que `maximo` o no se entiende).
pub fn leer_json(ruta: &Path, maximo: u64) -> Option<Value> {
    let m = fs::metadata(ruta).ok()?;
    if m.len() > maximo {
        return None;
    }
    serde_json::from_slice(&fs::read(ruta).ok()?).ok()
}

/// Escribe de una vez: temporal en la misma carpeta + renombrar. Un archivo nuevo queda solo para la persona (0600).
pub fn escribir_atomico(ruta: &Path, contenido: &[u8], modo: u32) -> std::io::Result<()> {
    let dir = ruta.parent().unwrap_or(Path::new("."));
    fs::create_dir_all(dir)?;
    let tmp = dir.join(format!(".pieza-{}", aleatorio_hex(6)));
    {
        let mut o = fs::OpenOptions::new();
        o.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            o.mode(modo);
        }
        #[cfg(not(unix))]
        let _ = modo;
        let mut f = o.open(&tmp)?;
        f.write_all(contenido)?;
        f.sync_all()?;
    }
    fs::rename(&tmp, ruta).inspect_err(|_| {
        let _ = fs::remove_file(&tmp);
    })
}

/// Bytes al azar en hexadecimal (nombres temporales). Del sistema; si no hay, la hora y el proceso.
pub fn aleatorio_hex(n: usize) -> String {
    let mut b = vec![0u8; n];
    if getrandom(&mut b).is_err() {
        let t = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
        let semilla = t ^ ((std::process::id() as u128) << 64);
        for (i, x) in b.iter_mut().enumerate() {
            *x = (semilla >> ((i % 16) * 8)) as u8 ^ (i as u8).wrapping_mul(151);
        }
    }
    b.iter().map(|x| format!("{x:02x}")).collect()
}
#[cfg(unix)]
fn getrandom(b: &mut [u8]) -> std::io::Result<()> {
    use std::io::Read;
    fs::File::open("/dev/urandom")?.read_exact(b)
}
#[cfg(not(unix))]
fn getrandom(b: &mut [u8]) -> std::io::Result<()> {
    // Windows: RandomState lleva semillas del sistema (BCryptGenRandom) en cada instancia.
    use std::hash::{BuildHasher, Hasher};
    for trozo in b.chunks_mut(8) {
        let mut h = std::collections::hash_map::RandomState::new().build_hasher();
        h.write_u64(trozo.len() as u64);
        let v = h.finish().to_le_bytes();
        trozo.copy_from_slice(&v[..trozo.len()]);
    }
    Ok(())
}

// ───────────── app.json ─────────────
/// La descripción de la app (app.json), validada igual que nucleo.app().
#[derive(Clone, Debug)]
pub struct App {
    pub id: String,
    pub nombre: String,
    /// "sistema", "visible" o {"carpeta": "~/…"}.
    pub datos: Value,
    /// Las claves de config.json permitidas y su regla.
    pub config: Map<String, Value>,
    /// Todo app.json tal cual (para lo propio de la app: "privado", "version"…).
    pub crudo: Value,
}

impl App {
    pub fn version(&self) -> String {
        self.crudo.get("version").and_then(Value::as_str).unwrap_or("0.0.0").to_string()
    }
    pub fn privado(&self) -> bool {
        self.crudo.get("privado") == Some(&Value::Bool(true))
    }
}

/// Lanza un error si no sirve: sin app.json no hay app.
pub fn leer_app(recursos: &Path) -> Result<App, String> {
    let d = leer_json(&recursos.join("app.json"), 1024 * 1024).unwrap_or(Value::Null);
    let id = d.get("id").and_then(Value::as_str).filter(|x| es_id(x));
    let Some(id) = id else {
        return Err("app.json: falta o no sirve «id» (minúsculas y números, ej. «ana»).".into());
    };
    let nombre = d
        .get("nombre")
        .and_then(Value::as_str)
        .filter(|x| !x.is_empty())
        .map(String::from)
        .unwrap_or_else(|| {
            let mut c = id.chars();
            c.next().map(|p| p.to_uppercase().collect::<String>() + c.as_str()).unwrap_or_default()
        });
    Ok(App {
        id: id.to_string(),
        nombre,
        datos: d.get("datos").cloned().unwrap_or(json!("sistema")),
        config: d.get("config").and_then(Value::as_object).cloned().unwrap_or_default(),
        crudo: d,
    })
}

/// Las rutas de la persona que necesita `carpeta_datos` (se pasan para poder probarla).
pub struct Sistema {
    pub plataforma: &'static str,
    pub casa: PathBuf,
    pub appdata: Option<PathBuf>,
    pub xdg_config: Option<PathBuf>,
}

impl Sistema {
    pub fn actual() -> Self {
        let casa = casa();
        Sistema {
            plataforma: plataforma(),
            appdata: std::env::var_os("APPDATA").map(PathBuf::from),
            xdg_config: std::env::var_os("XDG_CONFIG_HOME").map(PathBuf::from).filter(|p| p.is_absolute()),
            casa,
        }
    }
}

/// "mac" | "windows" | "linux": lo mismo que ve la interfaz en `window.<ID>_HOST`.
pub fn plataforma() -> &'static str {
    if cfg!(target_os = "macos") {
        "mac"
    } else if cfg!(windows) {
        "windows"
    } else {
        "linux"
    }
}

pub fn casa() -> PathBuf {
    std::env::var_os(if cfg!(windows) { "USERPROFILE" } else { "HOME" })
        .map(PathBuf::from)
        .filter(|p| p.is_absolute())
        .unwrap_or_else(|| PathBuf::from("."))
}

/// La carpeta de datos de la app, la misma que nucleo.carpeta_datos() (sin la variable <ID>_DATOS: esa la pone el host).
pub fn carpeta_datos(a: &App, s: &Sistema) -> Result<PathBuf, String> {
    if let Some(o) = a.datos.as_object() {
        let casa_real = fs::canonicalize(&s.casa).unwrap_or_else(|_| s.casa.clone());
        let crudo = o.get("carpeta").and_then(Value::as_str).unwrap_or("");
        let ruta = if let Some(resto) = crudo.strip_prefix('~') {
            casa_real.join(resto.trim_start_matches(['/', '\\']))
        } else {
            PathBuf::from(crudo)
        };
        let ruta = normalizar(&ruta);
        if !ruta.starts_with(&casa_real) || ruta == casa_real {
            return Err("app.json: «datos.carpeta» tiene que estar dentro de la carpeta de la persona (~/…).".into());
        }
        return Ok(ruta);
    }
    if a.datos.as_str() == Some("visible") {
        return Ok(s.casa.join(&a.nombre).join(format!(".{}", a.id)));
    }
    Ok(match s.plataforma {
        "mac" => s.casa.join("Library").join("Application Support").join(&a.nombre),
        "windows" => s.appdata.clone().unwrap_or_else(|| s.casa.join("AppData").join("Roaming")).join(&a.nombre),
        _ => s.xdg_config.clone().unwrap_or_else(|| s.casa.join(".config")).join(&a.id),
    })
}

/// Quita «.» y «..» sin tocar el disco (como path.resolve).
pub fn normalizar(p: &Path) -> PathBuf {
    let mut r = PathBuf::new();
    for c in p.components() {
        match c {
            Component::ParentDir => {
                r.pop();
            }
            Component::CurDir => {}
            otro => r.push(otro.as_os_str()),
        }
    }
    r
}

/// Crea la carpeta solo para la persona (0700). Una carpeta propia de app.json se usa tal cual. Con `visible`,
/// ~/<Nombre> recién creada también queda 0700 (una que ya existía no se toca).
pub fn preparar_carpeta(ruta: &Path, propia: bool, visible: bool) -> std::io::Result<()> {
    if propia {
        return fs::create_dir_all(ruta);
    }
    if visible {
        if let Some(arriba) = ruta.parent() {
            if !arriba.exists() {
                fs::create_dir_all(arriba)?;
                solo_persona(arriba);
            }
        }
    }
    fs::create_dir_all(ruta)?;
    solo_persona(ruta);
    Ok(())
}

pub fn solo_persona(ruta: &Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(ruta, fs::Permissions::from_mode(0o700));
    }
    #[cfg(not(unix))]
    let _ = ruta;
}

// ───────────── Configuración (las mismas reglas que nucleo._valida) ─────────────
pub fn valida(regla: &Value, valor: &Value) -> bool {
    if let Some(r) = regla.as_object() {
        let max = r.get("max").and_then(entero).filter(|m| *m > 0 && (*m as u64) <= MAXIMO_ENTRADA).unwrap_or(2000) as usize;
        if r.get("tipo").and_then(Value::as_str) == Some("texto") {
            if let Some(p) = r.get("patron").and_then(Value::as_str) {
                let Ok(rx) = Regex::new(&format!("^(?:{p})$")) else { return false };
                return valor.as_str().is_some_and(|v| v.encode_utf16().count() <= max && rx.is_match(v));
            }
            if r.get("max").and_then(entero).is_some() {
                return valor.as_str().is_some_and(|v| v.encode_utf16().count() <= max);
            }
        }
        return r.get("tipo").is_some_and(|t| valida(t, valor));
    }
    if let Some(l) = regla.as_array() {
        return l.contains(valor);
    }
    match regla.as_str() {
        Some("bool") => valor.is_boolean(),
        Some("texto") => valor.as_str().is_some_and(|v| v.encode_utf16().count() <= 2000),
        Some("numero") => valor.as_f64().is_some_and(f64::is_finite),
        _ => false,
    }
}

pub fn limpiar_config(reglas: &Map<String, Value>, datos: &Value) -> Map<String, Value> {
    let mut r = Map::new();
    if let Some(o) = datos.as_object() {
        for (k, v) in o {
            if let Some(regla) = reglas.get(k) {
                if !prohibido(k) && valida(regla, v) {
                    r.insert(k.clone(), v.clone());
                }
            }
        }
    }
    r
}

/// config.json en la carpeta de datos, compartido con los scripts (nucleo.config()). Solo claves de app.json; lo que llega
/// de la interfaz nunca cambia una clave marcada "interfaz": false (esas las escribe la app con `desde_interfaz = false`).
pub struct Config {
    pub ruta: PathBuf,
    pub reglas: Map<String, Value>,
    preparar: Box<dyn Fn() + Send + Sync>,
    escribir: Mutex<()>,
}

impl Config {
    pub fn nueva(ruta: PathBuf, reglas: Map<String, Value>, preparar: Box<dyn Fn() + Send + Sync>) -> Self {
        Config { ruta, reglas, preparar, escribir: Mutex::new(()) }
    }
    fn crudo(&self) -> Map<String, Value> {
        leer_json(&self.ruta, 1024 * 1024).and_then(|v| v.as_object().cloned()).unwrap_or_default()
    }
    pub fn leer(&self) -> Map<String, Value> {
        limpiar_config(&self.reglas, &Value::Object(self.crudo()))
    }
    pub fn guardar(&self, cambios: &Value, desde_interfaz: bool) -> Map<String, Value> {
        let _g = self.escribir.lock().unwrap_or_else(|e| e.into_inner());
        let limpios: Map<String, Value> = limpiar_config(&self.reglas, cambios)
            .into_iter()
            .filter(|(k, _)| !(desde_interfaz && self.reglas.get(k).and_then(|r| r.get("interfaz")) == Some(&Value::Bool(false))))
            .collect();
        (self.preparar)();
        let mut d: BTreeMap<String, Value> = self.crudo().into_iter().collect();
        for (k, v) in &limpios {
            d.insert(k.clone(), v.clone());
        }
        // Igual que JSON.stringify(ordenado, null, 1): claves ordenadas, un espacio de sangría.
        let texto = json_sangria_1(&Value::Object(d.into_iter().collect())) + "\n";
        if let Err(e) = escribir_atomico(&self.ruta, texto.as_bytes(), 0o600) {
            eprintln!("config.json: {e}");
        }
        let mut r = self.leer();
        r.extend(limpios);
        r
    }
    /// Una clave que app.json no describe (un objeto con forma propia, p. ej. `inicio_mes`): la app la valida antes, y `leer`
    /// no la devuelve (sigue en el archivo para quien la use, p. ej. los scripts de Python). Lo demás queda igual.
    pub fn poner_propia(&self, clave: &str, valor: Value) {
        let nombre_ok = (1..=40).contains(&clave.len()) && clave.starts_with(|c: char| c.is_ascii_lowercase())
            && clave.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_');
        if self.reglas.contains_key(clave) || !nombre_ok {
            return;
        }
        let _g = self.escribir.lock().unwrap_or_else(|e| e.into_inner());
        (self.preparar)();
        let mut d: BTreeMap<String, Value> = self.crudo().into_iter().collect();
        d.insert(clave.into(), valor);
        let texto = json_sangria_1(&Value::Object(d.into_iter().collect())) + "\n";
        if let Err(e) = escribir_atomico(&self.ruta, texto.as_bytes(), 0o600) {
            eprintln!("config.json: {e}");
        }
    }
    /// Lo que hay en config.json tal cual (también las claves propias de la app).
    pub fn leer_todo(&self) -> Map<String, Value> {
        self.crudo()
    }
    pub fn texto(&self, clave: &str) -> String {
        self.leer().get(clave).and_then(Value::as_str).unwrap_or("").to_string()
    }
}

/// JSON con un espacio de sangría (lo mismo que escriben Electron y Python con indent=1).
pub fn json_sangria_1(v: &Value) -> String {
    let mut b = Vec::new();
    let f = serde_json::ser::PrettyFormatter::with_indent(b" ");
    let mut s = serde_json::Serializer::with_formatter(&mut b, f);
    serde::Serialize::serialize(v, &mut s).expect("JSON");
    String::from_utf8(b).unwrap_or_default()
}

// ───────────── Idioma (las claves son el texto en español, igual que en ui/idiomas) ─────────────
type Fuente = Box<dyn Fn() -> String + Send + Sync>;
pub struct Idioma {
    pub idiomas: Vec<String>,
    pub sistema: Mutex<String>,
    recursos: PathBuf,
    /// De dónde leer el idioma elegido si la app no lo guarda en config.json.
    elegido_de: Option<Fuente>,
    cache: Mutex<Option<(String, Map<String, Value>)>>,
}

impl Idioma {
    pub fn nuevo(config: &Config, recursos: &Path, elegido_de: Option<Fuente>) -> Self {
        let lista: Vec<String> = config
            .reglas
            .get("idioma_ui")
            .and_then(Value::as_array)
            .map(|l| l.iter().filter_map(Value::as_str).filter(|x| es_idioma(x)).map(String::from).collect())
            .unwrap_or_default();
        Idioma {
            idiomas: if lista.is_empty() { vec!["es".into(), "en".into()] } else { lista },
            sistema: Mutex::new("es".into()),
            recursos: recursos.to_path_buf(),
            elegido_de,
            cache: Mutex::new(None),
        }
    }
    fn elegido_ahora(&self, config: &Config) -> String {
        match &self.elegido_de {
            Some(f) => f(),
            None => config.texto("idioma_ui"),
        }
    }
    /// Solo uno de los idiomas de app.json (el archivo de traducciones se busca con este código: nunca otra cosa).
    pub fn codigo(&self, config: &Config) -> String {
        let e = self.elegido_ahora(config);
        if self.idiomas.contains(&e) {
            return e;
        }
        let s: String = self.sistema.lock().map(|s| s.to_lowercase()).unwrap_or_default().chars().take(2).collect();
        if self.idiomas.contains(&s) {
            return s;
        }
        if self.idiomas.iter().any(|x| x == "en") { "en".into() } else { self.idiomas[0].clone() }
    }
    /// Ya hay idioma: lo eligió (bienvenida o Ajustes) o terminó la bienvenida. Antes, nada corre solo ni se pide.
    pub fn elegido(&self, config: &Config) -> bool {
        !self.elegido_ahora(config).is_empty() || config.leer().get("bienvenida") == Some(&Value::Bool(true))
    }
    pub fn t(&self, config: &Config, texto: &str) -> String {
        let c = self.codigo(config);
        if c == "es" {
            return texto.to_string();
        }
        let mut cache = self.cache.lock().unwrap_or_else(|e| e.into_inner());
        if cache.as_ref().map(|(k, _)| k != &c).unwrap_or(true) {
            let j = leer_json(&self.recursos.join("ui").join("idiomas").join(format!("{c}.json")), 5 * 1024 * 1024);
            let textos = j.and_then(|j| j.get("textos").and_then(Value::as_object).cloned()).unwrap_or_default();
            *cache = Some((c, textos));
        }
        cache.as_ref().and_then(|(_, t)| t.get(texto)).and_then(Value::as_str).unwrap_or(texto).to_string()
    }
    /// Una frase con marcadores ({x}, {n}…): se traduce entera y después se ponen los valores.
    pub fn f(&self, config: &Config, plantilla: &str, valores: &Value) -> String {
        static C: OnceLock<Regex> = OnceLock::new();
        let rx = re(r"\{(\w+)\}", &C);
        let t = self.t(config, plantilla);
        rx.replace_all(&t, |m: &regex::Captures| match valores.get(&m[1]) {
            Some(Value::String(s)) => s.clone(),
            Some(v) => v.to_string(),
            None => m[0].to_string(),
        })
        .into_owned()
    }
    pub fn olvidar(&self) {
        if let Ok(mut c) = self.cache.lock() {
            *c = None;
        }
    }
}

// ───────────── Rutas que manda la interfaz (igual que nucleo.ruta_en) ─────────────
pub fn es_relativa(r: &str, maximo: usize) -> bool {
    if r.is_empty() || r.chars().count() > maximo || r.contains('\0') {
        return false;
    }
    let b = r.as_bytes();
    if b[0] == b'/' || b[0] == b'\\' || (b.len() >= 2 && b[0].is_ascii_alphabetic() && b[1] == b':') || Path::new(r).is_absolute() {
        return false;
    }
    r.split(['/', '\\']).all(|p| !p.is_empty() && p != "." && p != "..")
}

/// La ruta absoluta de `relativa` dentro de `base`, o None si se sale (absoluta, «..», enlaces hacia afuera). `extensiones`
/// limita el tipo de archivo. Si el archivo aún no existe, se revisa la carpeta que lo contendría.
pub fn dentro(base: &Path, relativa: &str, extensiones: Option<&[&str]>) -> Option<PathBuf> {
    if !es_relativa(relativa, 400) {
        return None;
    }
    if let Some(ex) = extensiones {
        let l = relativa.to_lowercase();
        if !ex.iter().any(|e| l.ends_with(&e.to_lowercase())) {
            return None;
        }
    }
    let raiz = fs::canonicalize(base).ok()?;
    let mut ruta = raiz.clone();
    for p in relativa.split(['/', '\\']) {
        ruta.push(p);
    }
    let ruta = match fs::canonicalize(&ruta) {
        Ok(r) => r,
        Err(_) => match (ruta.parent().and_then(|p| fs::canonicalize(p).ok()), ruta.file_name()) {
            (Some(p), Some(n)) => p.join(n),
            _ => ruta,
        },
    };
    let rel = ruta.strip_prefix(&raiz).ok()?;
    (!rel.as_os_str().is_empty() && !rel.components().any(|c| matches!(c, Component::ParentDir))).then_some(ruta)
}

// ───────────── Acciones declaradas (docs/enchufe.md, «Una acción») ─────────────
/// Una acción ya revisada.
#[derive(Clone, Debug)]
pub struct Accion {
    pub nombre: String,
    pub script: String,
    pub datos: Map<String, Value>,
    pub args: Vec<String>,
    pub entrada_archivo: bool,
    pub limite: Value,
    pub maximo: u64,
    pub inyectar: Map<String, Value>,
    pub vigilar: Option<String>,
    pub responde: Option<String>,
    pub progreso: Option<String>,
    pub eco: Vec<String>,
    pub despues: Vec<String>,
    pub cola_escritura: bool,
}

/// Las mismas reglas que herramientas/pieza.py (errores_accion): el host las vuelve a revisar al cargar, así un acciones.json
/// cambiado a mano nunca hace correr algo que pieza.py no habría aceptado.
pub fn errores_accion(nombre: &str, a: &Value) -> Vec<String> {
    let mut e = Vec::new();
    let donde = format!("acción «{nombre}»");
    if !es_accion(nombre) {
        e.push(format!("{donde}: nombre raro"));
    }
    let Some(a) = a.as_object() else { return vec![format!("{donde}: no es un objeto")] };
    if !a.get("script").and_then(Value::as_str).is_some_and(es_script) {
        e.push(format!("{donde}: «script» debe ser nombre.py"));
    }
    let vacio_o = json!({});
    let vacio_l = json!([]);
    let datos = a.get("datos").unwrap_or(&vacio_o);
    let args = a.get("args").unwrap_or(&vacio_l);
    if !datos.is_object() {
        e.push(format!("{donde}: «datos» es {{campo: regla}}"));
    }
    if !args.as_array().is_some_and(|l| l.iter().all(Value::is_string)) {
        e.push(format!("{donde}: «args» es una lista de textos"));
    }
    if !e.is_empty() {
        return e;
    }
    let datos = datos.as_object().expect("objeto");
    let args: Vec<&str> = args.as_array().expect("lista").iter().filter_map(Value::as_str).collect();
    let mut maximo = MAXIMO_ENTRADA;
    if let Some(m) = a.get("maximo") {
        match entero(m) {
            Some(x) if x >= 1 && (x as u64) <= TOPE_ENTRADA => maximo = x as u64,
            _ => e.push(format!("{donde}: «maximo» (bytes de la entrada) es un entero hasta {TOPE_ENTRADA}")),
        }
    }
    for (campo, regla) in datos {
        if campo == "*" {
            if regla.as_str() != Some("pasar") {
                e.push(format!("{donde}: «*» solo puede ser \"pasar\""));
            }
            continue;
        }
        if !es_campo(campo) || prohibido(campo) {
            e.push(format!("{donde}: campo raro «{campo}»"));
        }
        e.extend(errores_regla(&format!("{donde}: «{campo}»"), regla, maximo));
    }
    for arg in &args {
        if let Some(c) = arg.strip_prefix('$') {
            // Regla de oro: lo que escribe la persona nunca va como argumento del proceso, solo por el archivo de entrada.
            let tipo = datos.get(c).and_then(|r| r.get("tipo")).and_then(Value::as_str);
            if !matches!(tipo, Some("enum") | Some("entero")) {
                e.push(format!("{donde}: el argumento {arg} solo puede ser un campo enum o entero"));
            }
        } else if !es_literal(arg) {
            e.push(format!("{donde}: argumento literal raro «{arg}»"));
        }
    }
    let mut por_archivo: Vec<String> =
        datos.keys().filter(|k| k.as_str() == "*" || !args.contains(&format!("${k}").as_str())).cloned().collect();
    let inyectar = a.get("inyectar").cloned().unwrap_or(json!({}));
    let iny_ok = inyectar.as_object().is_some_and(|o| {
        o.iter().all(|(k, v)| es_campo(k) && !prohibido(k) && v.as_str().is_some_and(es_campo))
    });
    if !iny_ok {
        e.push(format!("{donde}: «inyectar» es {{campo: fuente}}"));
    } else {
        let o = inyectar.as_object().expect("objeto");
        for k in o.keys() {
            if datos.contains_key(k) {
                e.push(format!("{donde}: «{k}» lo pone el host: no puede venir también en «datos»"));
            }
        }
        por_archivo.extend(o.keys().cloned());
    }
    let entrada = a.get("entrada");
    let es_archivo = entrada.and_then(Value::as_str) == Some("archivo");
    if !por_archivo.is_empty() && !es_archivo {
        e.push(format!("{donde}: {} no van en args: necesita \"entrada\": \"archivo\"", por_archivo.join(", ")));
    }
    if entrada.is_some_and(|x| !x.is_null() && !es_archivo) {
        e.push(format!("{donde}: «entrada» es \"archivo\" o null"));
    }
    e.extend(errores_limite(&donde, a.get("limite"), datos));
    if let Some(v) = a.get("vigilar") {
        let tipo = |c: &str| datos.get(c).and_then(|r| r.get("tipo")).and_then(Value::as_str).map(String::from);
        let modo = v.as_str();
        let ok = matches!(modo, Some("lee") | Some("escribe"))
            && tipo("ruta").as_deref() == Some("rutaRelativa")
            && (modo != Some("escribe") || tipo("texto").as_deref() == Some("texto"));
        if !ok {
            e.push(format!(
                "{donde}: «vigilar» es \"lee\" o \"escribe\", con «ruta» (rutaRelativa) en datos (y «texto» para escribe)"
            ));
        }
    }
    if a.get("responde").is_some_and(|r| !r.is_null() && !r.as_str().is_some_and(es_funcion)) {
        e.push(format!("{donde}: «responde» es el nombre de una función"));
    }
    if a.get("progreso").is_some_and(|r| !r.as_str().is_some_and(es_funcion)) {
        e.push(format!("{donde}: «progreso» es el nombre de una función"));
    }
    for k in ["eco", "despues"] {
        if let Some(v) = a.get(k) {
            let ok = v.as_array().is_some_and(|l| {
                l.iter().all(|x| x.as_str().is_some_and(|s| if k == "eco" { es_campo(s) } else { es_accion(s) }))
            });
            if !ok {
                e.push(format!("{donde}: «{k}» es una lista de nombres"));
            }
        }
    }
    if a.get("cola").is_some_and(|c| c.as_str() != Some("escritura")) {
        e.push(format!("{donde}: «cola» solo puede ser \"escritura\""));
    }
    e
}

fn limite_ok(x: &Value) -> bool {
    x.as_str() == Some("trabajo") || entero(x).is_some_and(|n| (1..=3600).contains(&n))
}

/// «limite»: segundos (1 a 3600), "trabajo" (sin tope, mientras lata: pieza «trabajos») o según el valor de un campo enum.
pub fn errores_limite(donde: &str, limite: Option<&Value>, datos: &Map<String, Value>) -> Vec<String> {
    let malo = vec![format!(
        "{donde}: «limite» es obligatorio: segundos (1 a 3600), \"trabajo\" o {{\"segun\": campo, \"valores\": {{…}}, \"otro\": …}}"
    )];
    let Some(l) = limite else { return malo };
    let Some(o) = l.as_object() else { return if limite_ok(l) { vec![] } else { malo } };
    let regla = o.get("segun").and_then(Value::as_str).and_then(|s| datos.get(s));
    let valores_regla = regla.filter(|r| r.get("tipo").and_then(Value::as_str) == Some("enum")).and_then(|r| r.get("valores")).and_then(Value::as_array);
    let ok = o.keys().all(|k| ["segun", "valores", "otro"].contains(&k.as_str()))
        && valores_regla.is_some()
        && o.get("otro").is_some_and(limite_ok)
        && o.get("valores").and_then(Value::as_object).is_some_and(|v| {
            v.iter().all(|(k, x)| valores_regla.expect("enum").contains(&Value::String(k.clone())) && limite_ok(x))
        });
    if ok { vec![] } else { malo }
}

/// El límite de esta vez: segundos, o "trabajo" (sin tope mientras el script lata).
pub enum Limite {
    Segundos(u64),
    Trabajo,
}
pub fn limite_de(def: &Accion, entrada: &Map<String, Value>) -> Limite {
    let l = match def.limite.as_object() {
        None => &def.limite,
        Some(o) => {
            let campo = o.get("segun").and_then(Value::as_str).unwrap_or("");
            let v = entrada.get(campo).and_then(Value::as_str);
            v.and_then(|v| o.get("valores").and_then(|x| x.get(v))).unwrap_or_else(|| o.get("otro").unwrap_or(&Value::Null))
        }
    };
    if l.as_str() == Some("trabajo") {
        Limite::Trabajo
    } else {
        Limite::Segundos(entero(l).filter(|n| *n >= 1).map(|n| n.min(3600) as u64).unwrap_or(120))
    }
}

pub fn errores_regla(donde: &str, r: &Value, maximo: u64) -> Vec<String> {
    let tipo = r.get("tipo").and_then(Value::as_str);
    if !r.is_object() || !tipo.is_some_and(|t| TIPOS.contains(&t)) {
        return vec![format!("{donde}: tipo desconocido")];
    }
    let mut e = Vec::new();
    let num = |k: &str| r.get(k).and_then(entero);
    match tipo.expect("tipo") {
        "texto" if !num("max").is_some_and(|m| m > 0 && (m as u64) <= maximo) => e.push(format!("{donde}: un texto necesita «max»")),
        "enum" => {
            let ok = r.get("valores").and_then(Value::as_array).is_some_and(|l| {
                !l.is_empty() && l.iter().all(|x| x.as_str().is_some_and(es_literal))
            });
            if !ok {
                e.push(format!("{donde}: un enum necesita «valores» (textos simples)"));
            }
        }
        "entero" => {
            if ["min", "max"].iter().any(|k| r.get(*k).is_some_and(|v| entero(v).is_none())) {
                e.push(format!("{donde}: «min»/«max» son enteros"));
            }
        }
        "base64" if !num("maxBytes").is_some_and(|m| m > 0 && (m as u64) <= maximo) => {
            e.push(format!("{donde}: base64 necesita «maxBytes»"))
        }
        "rutaRelativa" => {
            if r.get("extensiones").is_some_and(|x| !x.as_array().is_some_and(|l| l.iter().all(|y| y.as_str().is_some_and(es_extension)))) {
                e.push(format!("{donde}: «extensiones» es una lista como [\".md\"]"));
            }
        }
        "lista" => {
            if r.get("max").is_some_and(|m| !entero(m).is_some_and(|n| n > 0 && n <= 10000)) {
                e.push(format!("{donde}: «max» de una lista es un entero"));
            }
            if let Some(de) = r.get("de") {
                if de.get("tipo").and_then(Value::as_str) == Some("lista") {
                    e.push(format!("{donde}: una lista de listas no"));
                } else {
                    e.extend(errores_regla(&format!("{donde} (cada uno)"), de, maximo));
                }
            }
        }
        _ => {}
    }
    e
}

/// acciones.json de la app (junto a app.json). Las que no pasan se descartan y se avisan; un script que no está en bin/
/// también. Sin el archivo, no hay acciones declaradas (la app puede registrar las suyas).
pub fn cargar_acciones(recursos: &Path) -> (BTreeMap<String, Accion>, Vec<String>) {
    let mut acciones = BTreeMap::new();
    let mut errores = Vec::new();
    let Some(d) = leer_json(&recursos.join("acciones.json"), 2 * 1024 * 1024) else { return (acciones, errores) };
    let lista = d.get("acciones").and_then(Value::as_object);
    if d.get("formato").and_then(Value::as_i64) != Some(1) || lista.is_none() {
        return (acciones, vec!["acciones.json: formato desconocido".into()]);
    }
    for (nombre, a) in lista.expect("acciones") {
        let mut e = errores_accion(nombre, a);
        let script = a.get("script").and_then(Value::as_str).unwrap_or("");
        if e.is_empty() && !recursos.join("bin").join(script).exists() {
            e.push(format!("acción «{nombre}»: no está bin/{script}"));
        }
        if !e.is_empty() {
            errores.extend(e);
            continue;
        }
        let lista_txt = |k: &str| -> Vec<String> {
            a.get(k).and_then(Value::as_array).map(|l| l.iter().filter_map(Value::as_str).map(String::from).collect()).unwrap_or_default()
        };
        let txt = |k: &str| a.get(k).and_then(Value::as_str).map(String::from);
        acciones.insert(
            nombre.clone(),
            Accion {
                nombre: nombre.clone(),
                script: script.into(),
                datos: a.get("datos").and_then(Value::as_object).cloned().unwrap_or_default(),
                args: lista_txt("args"),
                entrada_archivo: txt("entrada").as_deref() == Some("archivo"),
                limite: a.get("limite").cloned().unwrap_or(Value::Null),
                maximo: a.get("maximo").and_then(entero).map(|m| m as u64).unwrap_or(MAXIMO_ENTRADA),
                inyectar: a.get("inyectar").and_then(Value::as_object).cloned().unwrap_or_default(),
                vigilar: txt("vigilar"),
                responde: txt("responde"),
                progreso: txt("progreso"),
                eco: lista_txt("eco"),
                despues: lista_txt("despues"),
                cola_escritura: txt("cola").as_deref() == Some("escritura"),
            },
        );
    }
    (acciones, errores)
}

// ───────────── Validar lo que manda la interfaz ─────────────
pub fn validar_valor(r: &Value, v: &Value) -> Option<Value> {
    let num = |k: &str| r.get(k).and_then(entero);
    match r.get("tipo").and_then(Value::as_str)? {
        "texto" => {
            let s = v.as_str()?;
            let max = num("max").unwrap_or(0).max(0) as usize;
            if s.encode_utf16().count() > max {
                if r.get("recortar") == Some(&Value::Bool(true)) {
                    return Some(Value::String(recortar_utf16(s, max)));
                }
                return None;
            }
            Some(v.clone())
        }
        "enum" => r.get("valores").and_then(Value::as_array).filter(|l| l.contains(v)).map(|_| v.clone()),
        "bool" => v.is_boolean().then(|| v.clone()),
        "entero" => {
            let n = entero(v)?;
            if num("min").is_some_and(|m| n < m) || num("max").is_some_and(|m| n > m) {
                return None;
            }
            Some(json!(n))
        }
        "rutaRelativa" => {
            let s = v.as_str()?;
            if !es_relativa(s, 400) {
                return None;
            }
            if let Some(ex) = r.get("extensiones").and_then(Value::as_array) {
                let l = s.to_lowercase();
                if !ex.iter().filter_map(Value::as_str).any(|e| l.ends_with(&e.to_lowercase())) {
                    return None;
                }
            }
            Some(v.clone())
        }
        "base64" => {
            let s = v.as_str()?;
            let max = num("maxBytes").unwrap_or(0).max(0) as usize;
            static C: OnceLock<Regex> = OnceLock::new();
            if s.len() > max.div_ceil(3) * 4 + 4 || !re(r"^[A-Za-z0-9+/]*={0,2}$", &C).is_match(s) || s.len() % 4 == 1 {
                return None;
            }
            (largo_base64(s) <= max).then(|| v.clone())
        }
        "lista" => {
            let l = v.as_array()?;
            if l.len() > num("max").unwrap_or(100).max(0) as usize {
                return None;
            }
            let defecto = json!({"tipo": "texto", "max": 2000});
            let de = r.get("de").unwrap_or(&defecto);
            l.iter().map(|x| validar_valor(de, x)).collect::<Option<Vec<_>>>().map(Value::Array)
        }
        _ => None,
    }
}

/// Lo que mide String.length en JavaScript (unidades UTF-16): así el recorte es el mismo que en Electron y en Mac.
fn recortar_utf16(s: &str, max: usize) -> String {
    let mut n = 0;
    let mut r = String::new();
    for c in s.chars() {
        n += c.len_utf16();
        if n > max {
            break;
        }
        r.push(c);
    }
    r
}

/// Los bytes que decodifica un base64 ya revisado (como Buffer.from(v, "base64").length).
fn largo_base64(s: &str) -> usize {
    let relleno = s.bytes().rev().take_while(|b| *b == b'=').count();
    let datos = s.len() - relleno;
    datos * 3 / 4
}

/// Por qué no pasaron los datos.
#[derive(Debug, PartialEq)]
pub struct DatosMalos {
    pub campo: String,
    pub codigo: &'static str,
}

/// Solo lo declarado, con su tipo. Un campo que va en args ($campo) es obligatorio; los demás, solo si dicen "requerido".
/// "*": "pasar" deja pasar el resto (el script valida todo). Lo de «inyectar» nunca viene de la interfaz.
pub fn validar_datos(def: &Accion, datos: &Value) -> Result<Map<String, Value>, DatosMalos> {
    let vacio = Map::new();
    let datos = datos.as_object().unwrap_or(&vacio);
    let mut entrada = Map::new();
    let en_args: Vec<&str> = def.args.iter().filter_map(|x| x.strip_prefix('$')).collect();
    for (campo, r) in &def.datos {
        if campo == "*" {
            continue;
        }
        match datos.get(campo) {
            None | Some(Value::Null) => {
                if en_args.contains(&campo.as_str()) || r.get("requerido") == Some(&Value::Bool(true)) {
                    return Err(DatosMalos { campo: campo.clone(), codigo: "falta" });
                }
            }
            Some(v) => match validar_valor(r, v) {
                Some(x) => {
                    entrada.insert(campo.clone(), x);
                }
                None => return Err(DatosMalos { campo: campo.clone(), codigo: "invalido" }),
            },
        }
    }
    if def.datos.get("*").and_then(Value::as_str) == Some("pasar") {
        for (k, v) in datos {
            if def.datos.contains_key(k) || def.inyectar.contains_key(k) || !es_campo(k) || prohibido(k) {
                continue;
            }
            entrada.insert(k.clone(), v.clone());
        }
    }
    let texto = serde_json::to_vec(&entrada).map_err(|_| DatosMalos { campo: "*".into(), codigo: "invalido" })?;
    if texto.len() as u64 > def.maximo {
        return Err(DatosMalos { campo: "*".into(), codigo: "grande" });
    }
    Ok(entrada)
}

/// Los campos de «eco» que se pueden devolver aunque los datos no pasen: solo los que son válidos por sí solos.
pub fn eco_valido(def: &Accion, datos: &Value) -> Map<String, Value> {
    let mut r = Map::new();
    for k in &def.eco {
        if let (Some(regla), Some(v)) = (def.datos.get(k), datos.get(k)) {
            if let Some(x) = validar_valor(regla, v) {
                r.insert(k.clone(), x);
            }
        }
    }
    r
}

/// Los argumentos del script: literales, o el valor de un campo enum/entero ya validado. Nada más.
pub fn armar_args(def: &Accion, entrada: &Map<String, Value>) -> Vec<String> {
    def.args
        .iter()
        .map(|a| match a.strip_prefix('$') {
            Some(c) => match entrada.get(c) {
                Some(Value::String(s)) => s.clone(),
                Some(v) => v.to_string(),
                None => String::new(),
            },
            None => a.clone(),
        })
        .collect()
}

/// «ana» → «Ana» (el objeto window.<App> de la pieza «host-ui»).
pub fn global_de(id: &str) -> String {
    let mut c = id.chars();
    c.next().map(|p| p.to_ascii_uppercase().to_string() + c.as_str()).unwrap_or_default()
}

/// Solo el nombre (sin carpetas), con la extensión.
pub fn nombre_archivo(valor: &str, ext: &str) -> String {
    let mut n: String = valor
        .chars()
        .map(|c| if "\\/:*?\"<>|\0".contains(c) { '-' } else { c })
        .collect::<String>()
        .trim()
        .chars()
        .take(120)
        .collect();
    if n.is_empty() || n.starts_with('.') {
        n = format!("archivo{n}");
    }
    if !n.to_lowercase().ends_with(&format!(".{}", ext.to_lowercase())) {
        n = format!("{n}.{ext}");
    }
    n
}

#[cfg(test)]
mod pruebas {
    use super::*;

    fn accion(v: Value) -> Accion {
        let dir = std::env::temp_dir().join(format!("pieza-acc-{}", aleatorio_hex(4)));
        fs::create_dir_all(dir.join("bin")).unwrap();
        fs::write(dir.join("bin").join("x.py"), "").unwrap();
        fs::write(dir.join("acciones.json"), json!({"formato": 1, "acciones": {"a": v}}).to_string()).unwrap();
        let (mut a, e) = cargar_acciones(&dir);
        assert!(e.is_empty(), "{e:?}");
        a.remove("a").unwrap()
    }

    #[test]
    fn regla_de_oro() {
        let e = errores_accion("a", &json!({"script": "x.py", "datos": {"t": {"tipo": "texto", "max": 9}}, "args": ["$t"], "limite": 5}));
        assert!(e.iter().any(|x| x.contains("solo puede ser un campo enum o entero")));
        let e = errores_accion("a", &json!({"script": "x.py", "datos": {"o": {"tipo": "enum", "valores": ["a"]}}, "args": ["$o"], "limite": 5}));
        assert!(e.is_empty(), "{e:?}");
    }

    #[test]
    fn limite_obligatorio() {
        assert!(!errores_accion("a", &json!({"script": "x.py"})).is_empty());
        assert!(errores_accion("a", &json!({"script": "x.py", "limite": "trabajo"})).is_empty());
        let d = json!({"o": {"tipo": "enum", "valores": ["leer", "doc"]}});
        let a = json!({"script": "x.py", "datos": d, "args": ["$o"], "limite": {"segun": "o", "valores": {"doc": "trabajo"}, "otro": 60}});
        assert!(errores_accion("a", &a).is_empty());
    }

    #[test]
    fn validar() {
        let a = accion(json!({"script": "x.py", "datos": {"t": {"tipo": "texto", "max": 3, "recortar": true}, "n": {"tipo": "entero", "min": 0}, "*": "pasar"},
            "entrada": "archivo", "limite": 5, "eco": ["n"]}));
        let r = validar_datos(&a, &json!({"t": "hola", "n": 2, "otro": 1, "__proto__": 1})).unwrap();
        assert_eq!(r["t"], "hol");
        assert_eq!(r["otro"], 1);
        assert!(!r.contains_key("__proto__"));
        assert_eq!(validar_datos(&a, &json!({"n": -1})).unwrap_err().codigo, "invalido");
        assert_eq!(eco_valido(&a, &json!({"n": 3})), json!({"n": 3}).as_object().unwrap().clone());
    }

    #[test]
    fn rutas() {
        assert!(!es_relativa("../x", 400));
        assert!(!es_relativa("/x", 400));
        assert!(!es_relativa("C:x", 400));
        assert!(es_relativa("a/b.md", 400));
        let d = std::env::temp_dir().join(format!("pieza-dentro-{}", aleatorio_hex(4)));
        fs::create_dir_all(&d).unwrap();
        assert!(dentro(&d, "nuevo.md", Some(&[".md"])).is_some());
        assert!(dentro(&d, "nuevo.txt", Some(&[".md"])).is_none());
    }

    #[test]
    fn config_y_idioma() {
        let d = std::env::temp_dir().join(format!("pieza-config-{}", aleatorio_hex(4)));
        let reglas = json!({"idioma_ui": ["es", "en"], "carpeta": {"tipo": "texto", "max": 10, "interfaz": false}, "tema": ["claro", "oscuro"]});
        let c = Config::nueva(d.join("config.json"), reglas.as_object().unwrap().clone(), Box::new(|| {}));
        c.guardar(&json!({"carpeta": "/x", "tema": "claro", "raro": 1}), true);
        assert_eq!(Value::Object(c.leer()), json!({"tema": "claro"}));
        c.guardar(&json!({"carpeta": "/x"}), false);
        assert_eq!(c.texto("carpeta"), "/x");
        fs::create_dir_all(d.join("ui/idiomas")).unwrap();
        fs::write(d.join("ui/idiomas/en.json"), r#"{"textos": {"Hola {n}": "Hi {n}"}}"#).unwrap();
        let i = Idioma::nuevo(&c, &d, None);
        assert!(!i.elegido(&c));
        c.guardar(&json!({"idioma_ui": "en"}), true);
        assert_eq!(i.f(&c, "Hola {n}", &json!({"n": 2})), "Hi 2");
        // Una clave propia de la app (un objeto que app.json no describe): queda en el archivo y sobrevive a los guardados.
        c.poner_propia("inicio_mes", json!({"modo": "dia", "dia": 25}));
        c.poner_propia("tema", json!("rosado"));
        c.guardar(&json!({"tema": "oscuro"}), true);
        assert_eq!(c.leer_todo()["inicio_mes"], json!({"modo": "dia", "dia": 25}));
        assert!(!c.leer().contains_key("inicio_mes"));
        assert_eq!(c.texto("tema"), "oscuro");
    }

    #[test]
    fn datos_de_la_app() {
        let s = Sistema { plataforma: "linux", casa: PathBuf::from("/casa/ana"), appdata: None, xdg_config: None };
        let a = App { id: "ana".into(), nombre: "Ana".into(), datos: json!("sistema"), config: Map::new(), crudo: json!({}) };
        assert_eq!(carpeta_datos(&a, &s).unwrap(), PathBuf::from("/casa/ana/.config/ana"));
        let a = App { datos: json!({"carpeta": "~/../x"}), ..a };
        assert!(carpeta_datos(&a, &s).is_err());
    }
}
