// Pilota: la app nativa (pieza «host-tauri»). Desde aquí es de la app: registra lo propio (acciones que no son un
// script, medios, menús) y deja lo demás al host. Lo que solo corre un script se declara en app.json → acciones.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod pieza;
#[path = "pieza/progreso.rs"]
mod progreso;
#[path = "pieza/actualizaciones.rs"]
mod actualizaciones;

use pieza::host::{arrancar, Opciones};
#[allow(unused_imports)]
use std::sync::Arc;

fn main() {
    let op = Opciones {
        global: Some("Pilota".into()),
        sitio: Some("https://pilota-app.github.io/pilota/".into()),
        codigo: Some("https://github.com/pilota-app/pilota".into()),
        lector_progreso: Some(Arc::new(progreso::Lector)),
        actualizaciones: actualizaciones::Actualizaciones::nuevas("pilota-app/pilota", "Pilota").ok().map(|a| Arc::new(a) as _),
        ..Default::default()
    };
    arrancar(tauri::generate_context!(), op, |_host| {
        // _host.registrar("exportar", |datos, host, ctx| { … host.llamar("exportado", serde_json::json!({"ok": true}), ctx.destino()); });
    });
}
