// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//! Pieza «host-tauri»: el protocolo propio de la app. La interfaz vive en `<id>://localhost/ui/…` (en Windows,
//! `http://<id>.localhost/ui/…`: así lo pide WebView2) y los medios que la app aprueba, en `…/<nombre>/<ruta>` del mismo
//! origen (sin CORS). La interfaz arma esas direcciones con `host.medio(nombre, ruta)` de la pieza «host-ui».
//!   · `ui/` sirve solo archivos que de verdad están dentro de ui/ (sin «..» ni enlaces hacia afuera);
//!   · un medio sirve solo la ruta absoluta que devuelve el resolvedor de la app (o 404);
//!   · con rangos y en trozos de 4 MB como mucho (para adelantar un video).

use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

pub const TROZO: u64 = 4 << 20;

pub struct Respuesta {
    pub estado: u16,
    pub cabeceras: Vec<(&'static str, String)>,
    pub cuerpo: Vec<u8>,
}

pub fn no() -> Respuesta {
    Respuesta { estado: 404, cabeceras: vec![("Content-Type", "text/plain".into())], cuerpo: b"no".to_vec() }
}

pub fn tipo_de(ruta: &Path) -> &'static str {
    let ext = ruta.extension().map(|e| e.to_string_lossy().to_lowercase()).unwrap_or_default();
    match ext.as_str() {
        "mp4" => "video/mp4",
        "webm" => "video/webm",
        "mov" => "video/quicktime",
        "m4a" => "audio/mp4",
        "mp3" => "audio/mpeg",
        "wav" => "audio/wav",
        "ogg" => "audio/ogg",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "webp" => "image/webp",
        "gif" => "image/gif",
        "svg" => "image/svg+xml",
        "ico" => "image/x-icon",
        "pdf" => "application/pdf",
        "html" => "text/html; charset=utf-8",
        "js" | "mjs" => "text/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "json" => "application/json",
        "woff2" => "font/woff2",
        "woff" => "font/woff",
        "ttf" => "font/ttf",
        "otf" => "font/otf",
        "txt" | "md" => "text/plain; charset=utf-8",
        _ => "application/octet-stream",
    }
}

/// «%C3%A1» → «á». None si no es UTF-8 o trae un byte nulo.
pub fn decodificar(s: &str) -> Option<String> {
    let b = s.as_bytes();
    let mut r = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            let h = std::str::from_utf8(&b[i + 1..i + 3]).ok()?;
            r.push(u8::from_str_radix(h, 16).ok()?);
            i += 3;
        } else if b[i] == b'%' {
            return None;
        } else {
            r.push(b[i]);
            i += 1;
        }
    }
    let t = String::from_utf8(r).ok()?;
    (!t.contains('\0')).then_some(t)
}

/// Un archivo de ui/ (ruta ya sin «/ui/»). Solo lo que de verdad está adentro.
pub fn archivo_ui(raiz: &Path, rel: &str) -> Option<PathBuf> {
    let rel = decodificar(rel)?;
    let rel = if rel.is_empty() || rel.ends_with('/') { format!("{rel}index.html") } else { rel };
    if rel.split('/').any(|p| p.is_empty() || p == "." || p == ".." || p.contains('\\')) {
        return None;
    }
    let raiz_real = fs::canonicalize(raiz).ok()?;
    let ruta = fs::canonicalize(raiz.join(&rel)).ok()?;
    (ruta.starts_with(&raiz_real) && ruta.is_file()).then_some(ruta)
}

/// Un archivo con rangos (para adelantar un video) en trozos de 4 MB como mucho.
pub fn servir_archivo(archivo: &Path, rango: Option<&str>) -> Respuesta {
    let Ok(m) = fs::metadata(archivo) else { return no() };
    if !m.is_file() {
        return no();
    }
    let total = m.len();
    let tipo = tipo_de(archivo).to_string();
    let (mut desde, mut hasta, mut con_rango) = (0u64, total.saturating_sub(1), false);
    if let Some(r) = rango.and_then(|r| r.strip_prefix("bytes=")) {
        if let Some((a, b)) = r.split_once('-') {
            if a.chars().all(|c| c.is_ascii_digit()) && b.chars().all(|c| c.is_ascii_digit()) && !(a.is_empty() && b.is_empty()) {
                con_rango = true;
                if a.is_empty() {
                    desde = total.saturating_sub(b.parse::<u64>().unwrap_or(0));
                } else {
                    desde = a.parse().unwrap_or(u64::MAX);
                    if !b.is_empty() {
                        hasta = b.parse::<u64>().unwrap_or(hasta).min(total.saturating_sub(1));
                    }
                }
            }
        }
    }
    if total == 0 || desde > hasta || desde >= total {
        return Respuesta {
            estado: if total == 0 { 200 } else { 416 },
            cabeceras: vec![("Content-Type", tipo), ("Content-Range", format!("bytes */{total}"))],
            cuerpo: vec![],
        };
    }
    hasta = hasta.min(desde + TROZO - 1);
    let largo = hasta - desde + 1;
    let parcial = con_rango || largo < total;
    let mut cuerpo = vec![0u8; largo as usize];
    let leido = fs::File::open(archivo).and_then(|mut f| {
        f.seek(SeekFrom::Start(desde))?;
        f.read_exact(&mut cuerpo)
    });
    if leido.is_err() {
        return no();
    }
    let mut cabeceras = vec![
        ("Content-Type", tipo),
        ("Content-Length", largo.to_string()),
        ("Accept-Ranges", "bytes".into()),
        ("Cache-Control", "no-store".into()),
    ];
    if parcial {
        cabeceras.push(("Content-Range", format!("bytes {desde}-{hasta}/{total}")));
    }
    Respuesta { estado: if parcial { 206 } else { 200 }, cabeceras, cuerpo }
}

/// La dirección base de la app en esta plataforma: `<id>://localhost/` o, en Windows, `http://<id>.localhost/`.
pub fn base(id: &str) -> String {
    if cfg!(windows) {
        format!("http://{id}.localhost/")
    } else {
        format!("{id}://localhost/")
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;

    #[test]
    fn ui_no_se_sale() {
        let d = std::env::temp_dir().join(format!("pieza-proto-{}", super::super::enchufe::aleatorio_hex(4)));
        fs::create_dir_all(d.join("ui")).unwrap();
        fs::write(d.join("ui/index.html"), "<p>").unwrap();
        fs::write(d.join("secreto.txt"), "x").unwrap();
        assert!(archivo_ui(&d.join("ui"), "").is_some());
        assert!(archivo_ui(&d.join("ui"), "../secreto.txt").is_none());
        assert!(archivo_ui(&d.join("ui"), "%2e%2e/secreto.txt").is_none());
        assert!(archivo_ui(&d.join("ui"), "x%00").is_none());
    }

    #[test]
    fn rangos() {
        let f = std::env::temp_dir().join(format!("pieza-rango-{}.mp4", super::super::enchufe::aleatorio_hex(4)));
        fs::write(&f, b"0123456789").unwrap();
        let r = servir_archivo(&f, Some("bytes=2-4"));
        assert_eq!((r.estado, r.cuerpo.as_slice()), (206, b"234".as_slice()));
        assert_eq!(servir_archivo(&f, Some("bytes=-3")).cuerpo, b"789");
        assert_eq!(servir_archivo(&f, Some("bytes=20-")).estado, 416);
        assert_eq!(servir_archivo(&f, None).estado, 200);
    }
}
