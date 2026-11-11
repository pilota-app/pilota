// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//! Pieza «actualizaciones» (Mac, Windows y Linux, «host-tauri»). Versiones nuevas dentro de la app (nunca una alerta del
//! sistema): se revisa al abrir y cada 6 horas. Equivale a `actualizaciones.js` y a `Actualizaciones.swift`.
//!   · Mac: `<Base>-macOS.zip` se descomprime con `ditto`, se le quita la cuarentena y reemplaza la app cuando se cerró.
//!   · Windows: el instalador del Release (`<Base>-Windows.exe`, en silencio) cuando la app se cerró; después la abre.
//!   · Linux: el AppImage se reemplaza a sí mismo; la instalación de instalar.sh (~/.local/share/<Base>) se cambia entera.
//! Solo desde https://github.com/<repo>/releases/download/… y siempre verificado con su .sha256. Con llaves en app.json
//! (`"actualizaciones": {"llaves": ["<pública Ed25519 en base64>"]}`, hasta 2 para rotar), además exige `<archivo>.sig`: la
//! firma Ed25519 (base64, 64 bytes) de `<id>-actualizacion|<versión sin v>|<sha256>`. Sin firma válida no instala. La llave
//! privada vive fuera de GitHub (un secreto del entorno de publicación): quien entre a la cuenta no puede firmar. Los datos de la persona
//! viven fuera de la app: actualizar no borra nada. Nada de la app adentro: repo y nombre llegan como parámetros.
//!
//!   lector: …, actualizaciones: Some(Arc::new(actualizaciones::Actualizaciones::nuevas("ana-app/ana", "Ana")?)),

use crate::pieza::host::{Actualizador, Host};
use regex::Regex;
use serde_json::{json, Value};
use base64::Engine;
use ed25519_dalek::{Signature, VerifyingKey};
use sha2::{Digest, Sha256};
use ureq::ResponseExt;
use std::fs;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

/// Los textos van en español y con marcadores: la interfaz los traduce entera con T(texto, valores). Nunca van a un guion.
pub fn texto(codigo: &str) -> &'static str {
    match codigo {
        "version" => "Versión {v}",
        "bajando" => "Descargando la versión nueva…",
        "preparando" => "Preparando la versión nueva…",
        "instalando" => "Instalando: {app} se cerrará y volverá a abrirse sola",
        "errorBajar" => "No pude descargar la versión nueva. Revisa tu conexión e intenta de nuevo.",
        "sinDescarga" => "No encontré la descarga de la versión nueva.",
        "firma" => "La versión nueva no trae una firma válida. {app} sigue igual que antes: no la instalé por seguridad.",
        "mover" => "Para actualizar, mueve {app} a la carpeta Aplicaciones y ábrela desde ahí. Ahora macOS la abre desde una copia temporal que no se puede cambiar.",
        _ => "No pude preparar la versión nueva. {app} sigue igual que antes; intenta de nuevo más tarde.",
    }
}
const MAX_HUELLA: u64 = 4096;
const MAX_FIRMA: u64 = 1024;

/// Las llaves públicas de app.json → "actualizaciones" → "llaves" (base64 de 32 bytes, hasta 2). Las que no sirven se descartan.
pub fn llaves_de(app: &Value) -> Vec<VerifyingKey> {
    let b64 = base64::engine::general_purpose::STANDARD;
    app.get("actualizaciones")
        .and_then(|a| a.get("llaves"))
        .and_then(Value::as_array)
        .map(|l| {
            l.iter()
                .take(2)
                .filter_map(Value::as_str)
                .filter_map(|s| b64.decode(s.trim()).ok())
                .filter_map(|b| <[u8; 32]>::try_from(b.as_slice()).ok())
                .filter_map(|b| VerifyingKey::from_bytes(&b).ok())
                .collect()
        })
        .unwrap_or_default()
}

/// Lo que se firma: `<id>-actualizacion|<versión sin v>|<sha256 en minúsculas>`.
pub fn mensaje_firmado(id: &str, version: &str, huella: &str) -> String {
    format!("{id}-actualizacion|{}|{}", version.trim_start_matches('v'), huella.to_lowercase())
}

/// ¿La firma (base64 de 64 bytes, como viene en el .sig) es de alguna de las llaves? Estricta (verify_strict).
pub fn firma_valida(llaves: &[VerifyingKey], id: &str, version: &str, huella: &str, firma_b64: &str) -> bool {
    let Ok(bytes) = base64::engine::general_purpose::STANDARD.decode(firma_b64.trim()) else { return false };
    let Ok(firma) = Signature::from_slice(&bytes) else { return false };
    let m = mensaje_firmado(id, version, huella);
    llaves.iter().any(|k| k.verify_strict(m.as_bytes(), &firma).is_ok())
}
const MAX_DESCARGA: u64 = 2 << 30;

fn re(p: &'static str, c: &'static OnceLock<Regex>) -> &'static Regex {
    c.get_or_init(|| Regex::new(p).expect("patrón"))
}
pub fn es_repo(x: &str) -> bool {
    static C: OnceLock<Regex> = OnceLock::new();
    re(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$", &C).is_match(x)
}
pub fn es_base(x: &str) -> bool {
    static C: OnceLock<Regex> = OnceLock::new();
    re(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$", &C).is_match(x)
}

/// Texto entre comillas simples para bash: nada de lo que va adentro (rutas, URL) se interpreta como código.
pub fn comillas(x: &str) -> String {
    format!("'{}'", x.replace('\'', "'\\''"))
}

/// Solo se descarga desde los Releases de ESTE repo en github.com. GitHub después redirige a su almacenamiento: se sigue
/// solo por https y lo que llega se acepta únicamente si su SHA-256 es el del .sha256 publicado junto al archivo.
pub fn es_descarga_nuestra(u: &str, repo: &str) -> bool {
    if !es_repo(repo) {
        return false;
    }
    let Ok(x) = url::Url::parse(u) else { return false };
    x.scheme() == "https"
        && x.host_str() == Some("github.com")
        && x.port().is_none()
        && x.username().is_empty()
        && x.password().is_none()
        && x.query().is_none()
        && x.fragment().is_none()
        && x.path().starts_with(&format!("/{repo}/releases/download/"))
        && !x.path().contains("..")
        && !x.path().contains("%2")
}

/// «v1.10.0» → «1.10.0»; None si no es una versión de números.
pub fn limpiar_version(v: &str) -> Option<String> {
    static C: OnceLock<Regex> = OnceLock::new();
    let s = v.trim().trim_start_matches('v');
    re(r"^\d{1,6}(\.\d{1,6}){0,3}$", &C).is_match(s).then(|| s.to_string())
}

/// ¿a es más nueva que b? («0.10.0» > «0.9.3»). Lo que no es versión nunca es más nuevo.
pub fn es_mayor(a: &str, b: &str) -> bool {
    let Some(a) = limpiar_version(a) else { return false };
    let b = limpiar_version(b).unwrap_or_else(|| "0".into());
    let x: Vec<u64> = a.split('.').map(|n| n.parse().unwrap_or(0)).collect();
    let y: Vec<u64> = b.split('.').map(|n| n.parse().unwrap_or(0)).collect();
    for i in 0..x.len().max(y.len()) {
        let (p, q) = (x.get(i).copied().unwrap_or(0), y.get(i).copied().unwrap_or(0));
        if p != q {
            return p > q;
        }
    }
    false
}

/// El primer campo de un .sha256 («<64 hex>  archivo»), en minúsculas; None si no es una huella.
pub fn leer_huella(t: &str) -> Option<String> {
    let h = t.split_whitespace().next()?.to_lowercase();
    (h.len() == 64 && h.chars().all(|c| c.is_ascii_hexdigit())).then_some(h)
}

/// Sin tildes ni espacios: «Matías Café» → «MatiasCafe».
pub fn base_de(nombre: &str) -> String {
    nombre
        .chars()
        .map(|c| match c {
            'á' | 'à' | 'ä' | 'â' => 'a',
            'Á' | 'À' | 'Ä' | 'Â' => 'A',
            'é' | 'è' | 'ë' | 'ê' => 'e',
            'É' | 'È' | 'Ë' | 'Ê' => 'E',
            'í' | 'ì' | 'ï' | 'î' => 'i',
            'Í' | 'Ì' | 'Ï' | 'Î' => 'I',
            'ó' | 'ò' | 'ö' | 'ô' => 'o',
            'Ó' | 'Ò' | 'Ö' | 'Ô' => 'O',
            'ú' | 'ù' | 'ü' | 'û' => 'u',
            'Ú' | 'Ù' | 'Ü' | 'Û' => 'U',
            'ñ' => 'n',
            'Ñ' => 'N',
            otra => otra,
        })
        .filter(|c| c.is_ascii_alphanumeric() || "._-".contains(*c))
        .collect()
}

/// Cómo está instalada esta copia y qué archivo del Release la actualiza (None: desarrollo o puesta a mano, no se toca).
#[derive(Debug, Clone, PartialEq)]
pub enum Instalacion {
    Mac { app: PathBuf },
    Windows { exe: PathBuf },
    AppImage { destino: PathBuf },
    Tar { destino: PathBuf },
}
impl Instalacion {
    /// En Mac, una app que se abrió sin moverla (con la marca de cuarentena) corre desde /…/AppTranslocation/…, de solo lectura:
    /// ahí no se puede reemplazar.
    pub fn traslocada(&self) -> bool {
        matches!(self, Instalacion::Mac { app } if app.to_string_lossy().contains("/AppTranslocation/"))
    }

    pub fn archivo(&self, base: &str) -> String {
        match self {
            Instalacion::Mac { .. } => format!("{base}-macOS.zip"),
            Instalacion::Windows { .. } => format!("{base}-Windows.exe"),
            Instalacion::AppImage { .. } => format!("{base}-Linux.AppImage"),
            Instalacion::Tar { .. } => format!("{base}-Linux.tar.gz"),
        }
    }
}

pub fn instalacion(exe: &Path, casa: &Path, appimage: Option<PathBuf>, base: &str, ejecutable: &str) -> Option<Instalacion> {
    let texto = exe.to_string_lossy();
    if texto.contains("/target/") || texto.contains("\\target\\") {
        return None;
    }
    if cfg!(target_os = "macos") {
        // …/Ana.app/Contents/MacOS/ana
        let app = exe.parent()?.parent()?.parent()?;
        return (app.extension().is_some_and(|e| e == "app") && exe.parent()?.ends_with("Contents/MacOS")).then(|| Instalacion::Mac { app: app.to_path_buf() });
    }
    if cfg!(windows) {
        return Some(Instalacion::Windows { exe: exe.to_path_buf() });
    }
    if let Some(a) = appimage.filter(|a| a.is_absolute()) {
        return Some(Instalacion::AppImage { destino: a });
    }
    let dir = exe.parent()?;
    (dir == casa.join(".local").join("share").join(base) && exe.file_name()?.to_string_lossy() == ejecutable)
        .then(|| Instalacion::Tar { destino: dir.to_path_buf() })
}

pub struct Actualizaciones {
    pub repo: String,
    pub nombre: String,
    pub base: String,
    pub ejecutable: String,
    disponible: Mutex<Value>,
    /// (archivo, .sha256, versión) de la última revisión con algo nuevo.
    urls: Mutex<Option<(String, String, String)>>,
}

impl Actualizaciones {
    pub fn nuevas(repo: &str, nombre: &str) -> Result<Self, String> {
        let base = base_de(nombre);
        if !es_repo(repo) || nombre.is_empty() || !es_base(&base) {
            return Err("actualizaciones: faltan repo («dueño/repo»), nombre o una base válida.".into());
        }
        let ejecutable = base.to_lowercase();
        Ok(Actualizaciones {
            repo: repo.into(),
            nombre: nombre.into(),
            base,
            ejecutable,
            disponible: Mutex::new(json!({"hay": false})),
            urls: Mutex::new(None),
        })
    }
    fn inst(&self) -> Option<Instalacion> {
        let exe = std::env::current_exe().ok()?;
        let casa = crate::pieza::enchufe::casa();
        instalacion(&exe, &casa, std::env::var_os("APPIMAGE").map(PathBuf::from), &self.base, &self.ejecutable)
    }
    fn agente(&self) -> ureq::Agent {
        ureq::Agent::config_builder()
            .timeout_connect(Some(Duration::from_secs(15)))
            .timeout_recv_response(Some(Duration::from_secs(60)))
            .max_redirects(5)
            .https_only(true)
            .build()
            .into()
    }
    fn fin(&self, hay: bool, sin_conexion: bool, version: &str, notas: &str) -> Value {
        // `disponible` (lo que la app manda en su estado) tiene la misma forma que la respuesta.
        let d = json!({"hay": hay, "version": if hay { version } else { "" }, "notas": if hay { notas } else { "" },
            "texto": if hay && !version.is_empty() { texto("version") } else { "" }, "valores": {"v": if hay { version } else { "" }}, "desarrollo": false});
        if let Ok(mut x) = self.disponible.lock() {
            *x = d.clone();
        }
        let mut r = d;
        r["sinConexion"] = json!(sin_conexion);
        r
    }
    fn aviso(&self, paso: &str, codigo: &str) -> Value {
        json!({"paso": paso, "codigo": codigo, "texto": texto(codigo), "valores": {"app": self.nombre}, "total": 3})
    }
    /// Baja `url` a `destino` calculando su SHA-256 al vuelo.
    fn descargar(&self, url: &str, destino: &Path, progreso: &dyn Fn(f64)) -> Result<String, String> {
        let r = self.agente().get(url).call().map_err(|e| e.to_string())?;
        if r.get_uri().scheme_str() != Some("https") {
            return Err("redirección sin https".into());
        }
        let total: u64 = r.headers().get("content-length").and_then(|x| x.to_str().ok()).and_then(|x| x.parse().ok()).unwrap_or(0);
        let mut lector = r.into_body().into_reader().take(MAX_DESCARGA);
        let mut salida = fs::File::create(destino).map_err(|e| e.to_string())?;
        let mut h = Sha256::new();
        let (mut b, mut bytes) = (vec![0u8; 256 * 1024], 0u64);
        loop {
            let n = lector.read(&mut b).map_err(|e| e.to_string())?;
            if n == 0 {
                break;
            }
            h.update(&b[..n]);
            salida.write_all(&b[..n]).map_err(|e| e.to_string())?;
            bytes += n as u64;
            if total > 0 {
                progreso(bytes as f64 / total as f64);
            }
        }
        Ok(h.finalize().iter().map(|x| format!("{x:02x}")).collect())
    }
}

impl Actualizador for Actualizaciones {
    fn disponible(&self) -> Value {
        self.disponible.lock().map(|x| x.clone()).unwrap_or(json!({"hay": false}))
    }
    /// {hay, version, notas, sinConexion, texto, valores}. Sin empaquetar (desarrollo) o puesta a mano, nunca hay.
    fn revisar(&self, version: &str) -> Value {
        let Some(i) = self.inst() else { return self.fin(false, false, "", "") };
        let r = self
            .agente()
            .get(&format!("https://api.github.com/repos/{}/releases/latest", self.repo))
            .header("Accept", "application/vnd.github+json")
            .header("User-Agent", &format!("{}/{version}", self.base))
            .call();
        let d: Value = match r {
            Ok(mut r) => r.body_mut().read_json().unwrap_or(json!({})),
            Err(ureq::Error::StatusCode(404)) => return self.fin(false, false, "", ""), // aún no hay versiones
            Err(_) => return self.fin(false, true, "", ""),
        };
        let tag = d.get("tag_name").and_then(Value::as_str).and_then(limpiar_version);
        let archivo = i.archivo(&self.base);
        let url = |n: &str| -> Option<String> {
            d.get("assets")?.as_array()?.iter().find(|a| a.get("name").and_then(Value::as_str) == Some(n))?.get("browser_download_url")?.as_str().map(String::from)
        };
        let (Some(tag), Some(a), Some(h)) = (tag, url(&archivo), url(&format!("{archivo}.sha256"))) else { return self.fin(false, false, "", "") };
        if !es_mayor(&tag, version) || !es_descarga_nuestra(&a, &self.repo) || !es_descarga_nuestra(&h, &self.repo) {
            return self.fin(false, false, "", "");
        }
        if let Ok(mut u) = self.urls.lock() {
            *u = Some((a, h, tag.clone()));
        }
        let notas: String = d.get("body").and_then(Value::as_str).unwrap_or("").lines().take(4).collect::<Vec<_>>().join("\n").chars().take(1000).collect();
        self.fin(true, false, &tag, &notas)
    }
    /// Descarga, verifica e instala. Al final la app se cierra y se vuelve a abrir. Quien llama ya esperó a que no haya nada
    /// guardándose.
    fn instalar(&self, host: &Host, avisar: &dyn Fn(Value)) {
        let urls = self.urls.lock().ok().and_then(|u| u.clone());
        let (Some(i), Some((url, url_huella, version))) = (self.inst(), urls) else { return avisar(self.aviso("error", "sinDescarga")) };
        if i.traslocada() {
            // Abierta sin moverla (por ejemplo, desde Descargas): macOS la corre desde una copia de solo lectura.
            return avisar(self.aviso("error", "mover"));
        }
        if !es_descarga_nuestra(&url, &self.repo) || !es_descarga_nuestra(&url_huella, &self.repo) {
            return avisar(self.aviso("error", "sinDescarga"));
        }
        let tmp = std::env::temp_dir().join(format!("{}-actualizacion-{}", self.ejecutable, crate::pieza::enchufe::aleatorio_hex(6)));
        if fs::create_dir(&tmp).is_err() {
            return avisar(self.aviso("error", "errorArmar"));
        }
        crate::pieza::enchufe::solo_persona(&tmp);
        let borrar = || {
            let _ = fs::remove_dir_all(&tmp);
        };
        let archivo = tmp.join(i.archivo(&self.base));
        avisar(self.aviso("1", "bajando"));
        let ultimo = Mutex::new(std::time::Instant::now() - Duration::from_secs(1));
        let huella = self.descargar(&url, &archivo, &|p| {
            let mut u = ultimo.lock().unwrap_or_else(|e| e.into_inner());
            if u.elapsed() > Duration::from_millis(500) {
                *u = std::time::Instant::now();
                let mut a = self.aviso("1", "bajando");
                a["pct"] = json!((p * 100.0).round() as i64);
                avisar(a);
            }
        });
        let esperada = self
            .agente()
            .get(&url_huella)
            .call()
            .ok()
            .filter(|r| r.get_uri().scheme_str() == Some("https"))
            .and_then(|r| {
                let mut t = String::new();
                r.into_body().into_reader().take(MAX_HUELLA).read_to_string(&mut t).ok()?;
                leer_huella(&t)
            });
        let huella = match (huella, esperada) {
            (Ok(h), Some(e)) if h == e => h,
            _ => {
                borrar();
                return avisar(self.aviso("error", "errorBajar"));
            }
        };
        // Con llaves en app.json, la firma es obligatoria: <archivo>.sig, del mismo Release.
        let llaves = llaves_de(&host.app.crudo);
        if !llaves.is_empty() {
            let url_firma = format!("{url}.sig");
            let firma = Some(&url_firma)
                .filter(|u| es_descarga_nuestra(u, &self.repo))
                .and_then(|u| self.agente().get(u).call().ok())
                .filter(|r| r.get_uri().scheme_str() == Some("https"))
                .and_then(|r| {
                    let mut t = String::new();
                    r.into_body().into_reader().take(MAX_FIRMA).read_to_string(&mut t).ok()?;
                    Some(t)
                });
            if !firma.is_some_and(|f| firma_valida(&llaves, &host.app.id, &version, &huella, &f)) {
                borrar();
                return avisar(self.aviso("error", "firma"));
            }
        }
        avisar(self.aviso("2", "preparando"));
        let pid = std::process::id();
        let guion = match &i {
            Instalacion::Mac { app } => {
                let nueva = tmp.join("nueva");
                let ok = Command::new("/usr/bin/ditto").arg("-x").arg("-k").arg(&archivo).arg(&nueva).status().is_ok_and(|s| s.success());
                let app_nueva = fs::read_dir(&nueva).ok().and_then(|l| l.flatten().map(|d| d.path()).find(|p| p.extension().is_some_and(|e| e == "app")));
                let Some(app_nueva) = app_nueva.filter(|_| ok) else {
                    borrar();
                    return avisar(self.aviso("error", "errorArmar"));
                };
                let (q, a, n) = (comillas, app.to_string_lossy().into_owned(), app_nueva.to_string_lossy().into_owned());
                let ant = format!("{a}.anterior");
                format!(
                    "#!/bin/bash\nwhile kill -0 {pid} 2>/dev/null; do sleep 0.5; done\nxattr -dr com.apple.quarantine {n} 2>/dev/null || true\nrm -rf {ant}; mv {a} {ant} && ditto {n} {a} && rm -rf {ant} || {{ rm -rf {a}; mv {ant} {a}; }}\nrm -rf {t}\nopen -n {a}\n",
                    n = q(&n), a = q(&a), ant = q(&ant), t = q(&tmp.to_string_lossy())
                )
            }
            Instalacion::AppImage { destino } => {
                let nuevo = PathBuf::from(format!("{}.nueva", destino.to_string_lossy()));
                let ok = fs::copy(&archivo, &nuevo).is_ok() && permisos_ejecutar(&nuevo) && fs::rename(&nuevo, destino).is_ok();
                if !ok {
                    borrar();
                    return avisar(self.aviso("error", "errorArmar"));
                }
                format!("#!/bin/bash\nwhile kill -0 {pid} 2>/dev/null; do sleep 0.5; done\nrm -rf {t}\nexec {d}\n", t = comillas(&tmp.to_string_lossy()), d = comillas(&destino.to_string_lossy()))
            }
            Instalacion::Tar { destino } => {
                let nueva = tmp.join("nueva");
                let ok = fs::create_dir(&nueva).is_ok()
                    && Command::new("tar").arg("-xzf").arg(&archivo).arg("-C").arg(&nueva).args(["--strip-components=1", "--no-same-owner"]).status().is_ok_and(|s| s.success())
                    && nueva.join(&self.ejecutable).exists();
                if !ok {
                    borrar();
                    return avisar(self.aviso("error", "errorArmar"));
                }
                let (q, d) = (comillas, destino.to_string_lossy().into_owned());
                let ant = format!("{d}.anterior");
                let lanzador = crate::pieza::enchufe::casa().join(".local/bin").join(&self.ejecutable);
                format!(
                    "#!/bin/bash\nwhile kill -0 {pid} 2>/dev/null; do sleep 0.5; done\nrm -rf {ant}; mv {d} {ant} && mv {n} {d} && rm -rf {ant} || {{ rm -rf {d}; mv {ant} {d}; }}\nrm -rf {t}\nif [ -x {l} ]; then exec {l}; else exec {e}; fi\n",
                    ant = q(&ant), d = q(&d), n = q(&nueva.to_string_lossy()), t = q(&tmp.to_string_lossy()),
                    l = q(&lanzador.to_string_lossy()), e = q(&Path::new(&d).join(&self.ejecutable).to_string_lossy())
                )
            }
            Instalacion::Windows { exe } => {
                // El instalador por usuario (/S) reemplaza los archivos cuando la app ya se cerró; después se vuelve a abrir.
                let c = |x: &Path| x.to_string_lossy().replace('"', "");
                let cmd = tmp.join("actualizar.cmd");
                let texto = format!(
                    "@echo off\r\n:esperar\r\ntasklist /FI \"PID eq {pid}\" 2>NUL | find \"{pid}\" >NUL && (timeout /t 1 /nobreak >NUL & goto esperar)\r\n\"{i}\" /S\r\nstart \"\" \"{e}\"\r\n",
                    i = c(&archivo), e = c(exe)
                );
                if fs::write(&cmd, texto).is_err() {
                    borrar();
                    return avisar(self.aviso("error", "errorArmar"));
                }
                avisar(self.aviso("3", "instalando"));
                let mut p = Command::new("cmd");
                p.arg("/C").arg(&cmd).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
                #[cfg(windows)]
                {
                    use std::os::windows::process::CommandExt;
                    p.creation_flags(0x0800_0000 | 0x0000_0008); // sin ventana, desligado
                }
                if p.spawn().is_err() {
                    borrar();
                    return avisar(self.aviso("error", "errorArmar"));
                }
                std::thread::sleep(Duration::from_millis(1500));
                return salir(host);
            }
        };
        let ruta = tmp.join("actualizar.sh");
        if fs::write(&ruta, guion).is_err() || !permisos_ejecutar(&ruta) {
            borrar();
            return avisar(self.aviso("error", "errorArmar"));
        }
        avisar(self.aviso("3", "instalando"));
        let lanzado = Command::new("/bin/bash")
            .arg("-c")
            .arg(format!("nohup /bin/bash {} >/dev/null 2>&1 &", comillas(&ruta.to_string_lossy())))
            .stdin(Stdio::null())
            .status()
            .is_ok_and(|s| s.success());
        if !lanzado {
            borrar();
            return avisar(self.aviso("error", "errorArmar"));
        }
        std::thread::sleep(Duration::from_millis(1500));
        salir(host);
    }
}

fn salir(host: &Host) {
    match host.handle() {
        Some(h) => h.exit(0),
        None => std::process::exit(0),
    }
}

fn permisos_ejecutar(p: &Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(p, fs::Permissions::from_mode(0o700)).is_ok()
    }
    #[cfg(not(unix))]
    {
        let _ = p;
        true
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn solo_de_nuestro_repo() {
        let r = "ana-app/ana";
        assert!(es_descarga_nuestra("https://github.com/ana-app/ana/releases/download/v1.0.0/Ana-macOS.zip", r));
        assert!(!es_descarga_nuestra("http://github.com/ana-app/ana/releases/download/v1/x", r));
        assert!(!es_descarga_nuestra("https://github.com/otro/ana/releases/download/v1/x", r));
        assert!(!es_descarga_nuestra("https://github.com/ana-app/ana/releases/download/../x", r));
        assert!(!es_descarga_nuestra("https://github.com/ana-app/ana/releases/download/v1/x?y=1", r));
    }

    #[test]
    fn traslocada_no_se_puede_reemplazar() {
        let t = Instalacion::Mac { app: PathBuf::from("/private/var/folders/x/T/AppTranslocation/ABC/d/Ana.app") };
        assert!(t.traslocada());
        assert!(!Instalacion::Mac { app: PathBuf::from("/Applications/Ana.app") }.traslocada());
        assert!(!Instalacion::Windows { exe: PathBuf::from("C:/Ana/ana.exe") }.traslocada());
        assert!(texto("mover").contains("Aplicaciones"));
    }

    #[test]
    fn versiones_y_huellas() {
        assert!(es_mayor("v0.10.0", "0.9.3"));
        assert!(!es_mayor("0.9.3", "0.9.3"));
        assert!(!es_mayor("raro", "0"));
        assert_eq!(leer_huella(&format!("{}  Ana.zip", "A".repeat(64))), Some("a".repeat(64)));
        assert_eq!(leer_huella("corta"), None);
        assert_eq!(base_de("Matías Café"), "MatiasCafe");
        assert_eq!(comillas("a'b"), "'a'\\''b'");
    }

    #[test]
    fn firma_ed25519() {
        use ed25519_dalek::{Signer, SigningKey};
        let b64 = base64::engine::general_purpose::STANDARD;
        let llave = SigningKey::from_bytes(&[7u8; 32]);
        let otra = SigningKey::from_bytes(&[9u8; 32]);
        let publica = b64.encode(llave.verifying_key().to_bytes());
        let app = json!({"actualizaciones": {"llaves": [publica, "no-es-base64", b64.encode([1u8; 5])]}});
        let llaves = llaves_de(&app);
        assert_eq!(llaves.len(), 1, "solo las que sirven");
        let h = "ab".repeat(32);
        let m = mensaje_firmado("ana", "v1.2.0", &h.to_uppercase());
        assert_eq!(m, format!("ana-actualizacion|1.2.0|{h}"));
        let firma = b64.encode(llave.sign(m.as_bytes()).to_bytes());
        assert!(firma_valida(&llaves, "ana", "1.2.0", &h, &firma));
        assert!(!firma_valida(&llaves, "ana", "1.2.1", &h, &firma), "otra versión");
        assert!(!firma_valida(&llaves, "beto", "1.2.0", &h, &firma), "otra app");
        assert!(!firma_valida(&llaves, "ana", "1.2.0", &"cd".repeat(32), &firma), "otro archivo");
        let ajena = b64.encode(otra.sign(m.as_bytes()).to_bytes());
        assert!(!firma_valida(&llaves, "ana", "1.2.0", &h, &ajena), "otra llave");
        assert!(!firma_valida(&llaves, "ana", "1.2.0", &h, "basura"));
        assert!(llaves_de(&json!({})).is_empty(), "sin llaves, todo igual que antes");
    }

    #[test]
    fn firma_hecha_con_openssl() {
        // El mismo camino que publicar.yml: openssl pkeyutl -sign -rawin con una llave de `llave.sh`.
        let llaves = llaves_de(&json!({"actualizaciones": {"llaves": ["NBOgFlGpYRyMuv6i7605YbRsVYVvMu/28sWT0mY6W/4="]}}));
        let h = "ab".repeat(32);
        assert!(firma_valida(&llaves, "ana", "1.0.0", &h, "QqWlG2CVRPFypKVykz+B2rRiryZ214MIsb8Zys4Xa0PWeV+VWA4vdtq3lnX/hR5A47V1NlF4Pqqpm1vUD24/Cg=="));
        assert!(!firma_valida(&llaves, "ana", "1.0.1", &h, "QqWlG2CVRPFypKVykz+B2rRiryZ214MIsb8Zys4Xa0PWeV+VWA4vdtq3lnX/hR5A47V1NlF4Pqqpm1vUD24/Cg=="));
    }

    #[test]
    fn desarrollo_nunca_se_actualiza() {
        assert_eq!(instalacion(Path::new("/x/target/debug/ana"), Path::new("/casa/ana"), None, "Ana", "ana"), None);
    }
}
