// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//! Pieza «host-tauri»: vigilar la carpeta de la persona (equivale a `Vigilante` de «host-mac» y a `vigilante.js` de
//! «host-escritorio»). Si un archivo que la app tiene abierto cambia en el disco (otro editor, git pull…), la app se entera;
//! si cambia algo más de la carpeta, también (para volver a listarla).
//!
//! La app recuerda el último texto que leyó o escribió de cada archivo abierto (`conocer(ruta, texto)`): así lo que escribe
//! ella misma nunca se avisa como un cambio de afuera (el texto queda conocido ANTES de escribirlo). Cuando el sistema avisa
//! algo que puede importar (un archivo con una de las `extensiones`, o una carpeta), se espera a que la carpeta quede quieta y:
//!   1. se relee cada archivo conocido; si su texto no es el conocido → `al_cambiar_archivo(ruta, texto)`;
//!   2. `al_cambiar(base)`: la app vuelve a listar si quiere.
//!
//! Usa el vigía nativo de cada sistema (FSEvents, ReadDirectoryChangesW, inotify) por el crate `notify`.

use super::enchufe::dentro;
use notify::{RecommendedWatcher, RecursiveMode, Watcher};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::Duration;

/// Carpetas que nunca cuentan (pesadas o con secretos).
pub const FUERA: &[&str] = &[
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache", ".tox", "dist", "build",
    ".next", ".nuxt", "target", ".gradle", ".idea", ".terraform", ".aws", ".ssh", ".gnupg", ".cache", "Pods", "DerivedData", ".build",
];

type AlArchivo = Arc<dyn Fn(&str, &str) + Send + Sync>;
type AlCambiar = Arc<dyn Fn(&Path) + Send + Sync>;

/// El texto de un archivo (UTF-8; lo que no lo es se reemplaza), o None si no es un archivo o pesa más que `maximo`.
pub fn leer_texto(ruta: &Path, maximo: u64) -> Option<String> {
    let m = fs::metadata(ruta).ok()?;
    if !m.is_file() || m.len() > maximo {
        return None;
    }
    Some(String::from_utf8_lossy(&fs::read(ruta).ok()?).into_owned())
}

struct Estado {
    base: Option<PathBuf>,
    conocidos: HashMap<String, String>,
    vigia: Option<RecommendedWatcher>,
    generacion: u64,
}

#[derive(Clone)]
pub struct Vigilante {
    extensiones: Option<Vec<String>>,
    espera: Duration,
    maximo: u64,
    pub al_cambiar_archivo: Arc<Mutex<Option<AlArchivo>>>,
    pub al_cambiar: Arc<Mutex<Option<AlCambiar>>>,
    estado: Arc<Mutex<Estado>>,
    revisar: Arc<Mutex<()>>,
}

impl Vigilante {
    /// `extensiones`: [".md", ".mmd"] — solo esos archivos (y las carpetas) cuentan. Sin esto, todo.
    pub fn nuevo(extensiones: Option<Vec<String>>, espera: Option<Duration>, maximo: Option<u64>) -> Self {
        Vigilante {
            extensiones: extensiones.map(|l| l.into_iter().map(|e| e.to_lowercase()).collect()),
            espera: espera.unwrap_or(Duration::from_millis(350)),
            maximo: maximo.unwrap_or(2 * 1024 * 1024),
            al_cambiar_archivo: Arc::new(Mutex::new(None)),
            al_cambiar: Arc::new(Mutex::new(None)),
            estado: Arc::new(Mutex::new(Estado { base: None, conocidos: HashMap::new(), vigia: None, generacion: 0 })),
            revisar: Arc::new(Mutex::new(())),
        }
    }

    fn est(&self) -> std::sync::MutexGuard<'_, Estado> {
        self.estado.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// ¿Puede importar este nombre (relativo a la carpeta)? Un archivo de las extensiones o algo sin extensión (una carpeta).
    pub fn importa(&self, relativa: &Path) -> bool {
        if relativa.components().any(|c| FUERA.contains(&c.as_os_str().to_string_lossy().as_ref())) {
            return false;
        }
        let Some(ex) = &self.extensiones else { return true };
        match relativa.extension() {
            None => true,
            Some(e) => ex.contains(&format!(".{}", e.to_string_lossy().to_lowercase())),
        }
    }

    pub fn base(&self) -> Option<PathBuf> {
        self.est().base.clone()
    }

    /// La ruta absoluta de `relativa` dentro de la carpeta vigilada (la guarda de nucleo.ruta_en), o None.
    pub fn absoluta(&self, relativa: &str) -> Option<PathBuf> {
        let base = self.base()?;
        let ex: Option<Vec<&str>> = self.extensiones.as_ref().map(|l| l.iter().map(String::as_str).collect());
        dentro(&base, relativa, ex.as_deref())
    }

    pub fn empezar(&self, base: &Path) {
        {
            let e = self.est();
            if e.base.as_deref() == Some(base) && e.vigia.is_some() {
                return;
            }
        }
        self.detener();
        let (tx, rx) = mpsc::channel::<PathBuf>();
        let mut vigia = match notify::recommended_watcher(move |r: notify::Result<notify::Event>| {
            if let Ok(ev) = r {
                for p in ev.paths {
                    let _ = tx.send(p);
                }
            }
        }) {
            Ok(w) => w,
            Err(e) => {
                eprintln!("vigilante: {e}");
                return;
            }
        };
        if vigia.watch(base, RecursiveMode::Recursive).is_err() {
            return;
        }
        let generacion = {
            let mut e = self.est();
            e.base = Some(base.to_path_buf());
            e.conocidos.clear();
            e.vigia = Some(vigia);
            e.generacion += 1;
            e.generacion
        };
        let yo = self.clone();
        let base = base.to_path_buf();
        thread::spawn(move || {
            // Un editor o git escriben varias veces seguidas: se espera a que la carpeta quede quieta.
            while let Ok(p) = rx.recv() {
                let mut importa = p.strip_prefix(&base).map(|r| yo.importa(r)).unwrap_or(false);
                loop {
                    match rx.recv_timeout(yo.espera) {
                        Ok(p) => importa |= p.strip_prefix(&base).map(|r| yo.importa(r)).unwrap_or(false),
                        Err(mpsc::RecvTimeoutError::Timeout) => break,
                        Err(mpsc::RecvTimeoutError::Disconnected) => return,
                    }
                }
                if yo.est().generacion != generacion {
                    return;
                }
                if importa {
                    yo.revisar_ahora();
                }
            }
        });
    }

    pub fn detener(&self) {
        let mut e = self.est();
        e.vigia = None;
        e.base = None;
        e.generacion += 1;
    }

    /// Recuerda el texto que la app leyó o escribió (así lo suyo no se avisa como un cambio de afuera). Sin texto, lo olvida.
    pub fn conocer(&self, ruta: &str, texto: Option<&str>) {
        let mut e = self.est();
        match texto {
            Some(t) => {
                e.conocidos.insert(ruta.to_string(), t.to_string());
            }
            None => {
                e.conocidos.remove(ruta);
            }
        }
    }
    pub fn conocido(&self, ruta: &str) -> Option<String> {
        self.est().conocidos.get(ruta).cloned()
    }
    pub fn olvidar(&self, ruta: &str) {
        self.conocer(ruta, None);
    }

    /// Relee los archivos conocidos y avisa lo que cambió afuera; después `al_cambiar(base)`.
    pub fn revisar_ahora(&self) {
        let _g = self.revisar.lock().unwrap_or_else(|e| e.into_inner());
        let (base, conocidos) = {
            let e = self.est();
            (e.base.clone(), e.conocidos.clone())
        };
        let Some(base) = base else { return };
        let al_archivo = self.al_cambiar_archivo.lock().ok().and_then(|f| f.clone());
        for (ruta, conocido) in conocidos {
            let Some(abs) = self.absoluta(&ruta) else { continue };
            let Some(texto) = leer_texto(&abs, self.maximo) else { continue };
            if texto == conocido {
                continue;
            }
            self.conocer(&ruta, Some(&texto));
            if let Some(f) = &al_archivo {
                f(&ruta, &texto);
            }
        }
        let al_cambiar = self.al_cambiar.lock().ok().and_then(|f| f.clone());
        if let Some(f) = al_cambiar {
            if self.base().as_deref() == Some(base.as_path()) {
                f(&base);
            }
        }
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn avisa_solo_lo_de_afuera() {
        let d = std::env::temp_dir().join(format!("pieza-vig-{}", super::super::enchufe::aleatorio_hex(4)));
        fs::create_dir_all(d.join(".git")).unwrap();
        fs::write(d.join("a.md"), "uno").unwrap();
        let d = fs::canonicalize(&d).unwrap();
        let v = Vigilante::nuevo(Some(vec![".md".into()]), Some(Duration::from_millis(100)), None);
        let (tx, rx) = mpsc::channel();
        *v.al_cambiar_archivo.lock().unwrap() = Some(Arc::new(move |r: &str, t: &str| {
            let _ = tx.send((r.to_string(), t.to_string()));
        }));
        assert!(!v.importa(Path::new(".git/x")));
        assert!(!v.importa(Path::new("a.txt")));
        v.empezar(&d);
        v.conocer("a.md", Some("dos"));
        fs::write(d.join("a.md"), "dos").unwrap();
        thread::sleep(Duration::from_millis(400));
        assert!(rx.try_recv().is_err(), "lo que escribió la app no se avisa");
        fs::write(d.join("a.md"), "tres").unwrap();
        let (r, t) = rx.recv_timeout(Duration::from_secs(5)).unwrap();
        assert_eq!((r.as_str(), t.as_str()), ("a.md", "tres"));
        v.detener();
    }
}
