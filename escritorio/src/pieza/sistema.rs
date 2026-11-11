// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//! Pieza «host-tauri»: lo del sistema que usan dos apps o más, igual en Mac, Windows y Linux. Equivale a `Sistema.swift`
//! de «host-mac» y a la parte de `host.js` de «host-escritorio» que hace lo mismo.
//!   · Secretos: el llavero de cada sistema (Llavero de Mac, Administrador de credenciales de Windows, Secret Service de
//!     Linux). Nunca en texto plano: si el sistema no tiene llavero, no se guarda nada. En Mac, el mismo `servicio` que
//!     usaba «host-mac» (el nombre de la app): los secretos de siempre siguen ahí.
//!   · Avisos del sistema, el portapapeles, abrir un enlace https, mostrar un archivo en su carpeta y la papelera.

use std::path::Path;
use std::sync::{Arc, Mutex};
#[cfg(target_os = "macos")]
use std::sync::OnceLock;

/// Una cuenta dentro de un secreto: letras, números, «.», «@», «_» y «-».
pub fn es_cuenta(x: &str) -> bool {
    !x.is_empty() && x.len() <= 100 && x.chars().all(|c| c.is_ascii_alphanumeric() || "._@-".contains(c))
}

/// `host.secretos("Ana · conexiones")` o `Secretos::de_la_app(&host)`: un servicio del llavero; cada cuenta es un valor.
#[derive(Clone)]
pub struct Secretos {
    pub servicio: String,
}

impl Secretos {
    pub fn nuevo(servicio: &str) -> Self {
        Secretos { servicio: servicio.chars().take(120).collect() }
    }
    fn entrada(&self, cuenta: &str) -> Option<keyring::Entry> {
        es_cuenta(cuenta).then(|| keyring::Entry::new(&self.servicio, cuenta).ok()).flatten()
    }
    /// ¿Hay llavero? (En Linux sin gnome-keyring ni kwallet, no: ahí no se guarda nada.)
    pub fn disponible(&self) -> bool {
        match keyring::Entry::new(&self.servicio, "pieza-prueba") {
            Ok(e) => !matches!(e.get_password(), Err(keyring::Error::PlatformFailure(_)) | Err(keyring::Error::NoStorageAccess(_))),
            Err(_) => false,
        }
    }
    pub fn guardar(&self, cuenta: &str, valor: &str) -> bool {
        if valor.is_empty() || valor.len() > 100_000 {
            return false;
        }
        self.entrada(cuenta).is_some_and(|e| e.set_password(valor).is_ok())
    }
    pub fn leer(&self, cuenta: &str) -> Option<String> {
        self.entrada(cuenta)?.get_password().ok()
    }
    pub fn borrar(&self, cuenta: &str) {
        if let Some(e) = self.entrada(cuenta) {
            let _ = e.delete_credential();
        }
    }
}

// ───────────── Avisos del sistema ─────────────
type AlTocar = Arc<dyn Fn(&str) + Send + Sync>;
pub struct Notificaciones {
    pub al_tocar: Mutex<Option<AlTocar>>,
    identificador: String,
}

impl Notificaciones {
    /// `identificador`: el de la app (com.ana-app.ana), para que el aviso salga con su nombre y su ícono.
    pub fn nuevas(identificador: &str) -> Self {
        #[cfg(target_os = "macos")]
        {
            static UNA: OnceLock<()> = OnceLock::new();
            let id = identificador.to_string();
            UNA.get_or_init(move || {
                let _ = notify_rust::set_application(&id);
            });
        }
        Notificaciones { al_tocar: Mutex::new(None), identificador: identificador.to_string() }
    }
    pub fn soportado(&self) -> bool {
        true
    }
    /// Un aviso ya (`id`: para saber cuál tocó la persona). Quien llama revisa antes que ya se eligió el idioma.
    pub fn mostrar(&self, id: &str, titulo: &str, texto: &str, silencioso: bool) -> bool {
        if id.is_empty() || id.len() > 60 || !id.chars().all(|c| c.is_ascii_alphanumeric() || "_.-".contains(c)) {
            return false;
        }
        let mut n = notify_rust::Notification::new();
        n.summary(&titulo.chars().take(200).collect::<String>()).body(&texto.chars().take(1000).collect::<String>());
        #[cfg(all(unix, not(target_os = "macos")))]
        {
            n.appname(&self.identificador).action("default", "");
            if silencioso {
                n.hint(notify_rust::Hint::SuppressSound(true));
            }
        }
        #[cfg(target_os = "macos")]
        if !silencioso {
            n.sound_name("default");
        }
        #[cfg(windows)]
        {
            n.app_id(&self.identificador);
            let _ = silencioso;
        }
        #[cfg(all(unix, not(target_os = "macos")))]
        {
            let Ok(h) = n.show() else { return false };
            let al = self.al_tocar.lock().ok().and_then(|f| f.clone());
            let id = id.to_string();
            std::thread::spawn(move || {
                h.wait_for_action(|a| {
                    if a == "default" {
                        if let Some(f) = &al {
                            f(&id);
                        }
                    }
                })
            });
            true
        }
        #[cfg(not(all(unix, not(target_os = "macos"))))]
        {
            let _ = id;
            n.show().is_ok()
        }
    }
}

// ───────────── Lo demás ─────────────
/// Solo https, sin usuario ni clave: igual que en Mac y en Electron. Lo abre el navegador de la persona.
pub fn abrir_enlace(url: &str) -> bool {
    let Ok(u) = url::Url::parse(url) else { return false };
    if u.scheme() != "https" || u.host_str().is_none_or(str::is_empty) || !u.username().is_empty() || u.password().is_some() {
        return false;
    }
    opener::open_browser(u.as_str()).is_ok()
}

pub fn copiar(texto: &str) -> bool {
    if texto.is_empty() || texto.len() > 50 * 1024 * 1024 {
        return false;
    }
    arboard::Clipboard::new().and_then(|mut c| c.set_text(texto.to_string())).is_ok()
}

/// El archivo (o la carpeta), elegido en el Finder o el explorador. Solo rutas que la app ya revisó (host.dentro).
pub fn mostrar_en_carpeta(absoluta: &Path) -> bool {
    absoluta.is_absolute() && absoluta.exists() && opener::reveal(absoluta).is_ok()
}

/// A la Papelera del sistema (se puede recuperar). Solo rutas que la app ya revisó (host.dentro).
pub fn papelera(absoluta: &Path) -> bool {
    absoluta.is_absolute() && trash::delete(absoluta).is_ok()
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn solo_https() {
        // No abre nada: todas fallan antes de llegar al navegador.
        assert!(!abrir_enlace("http://ejemplo.cl"));
        assert!(!abrir_enlace("file:///etc/passwd"));
        assert!(!abrir_enlace("https://ana:clave@ejemplo.cl"));
        assert!(!abrir_enlace("javascript:alert(1)"));
    }

    #[test]
    fn cuentas() {
        assert!(es_cuenta("token.youtube"));
        assert!(!es_cuenta("a b"));
        assert!(!es_cuenta(""));
    }
}
