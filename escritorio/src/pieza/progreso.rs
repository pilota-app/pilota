// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//! Pieza «trabajos» (Mac, Windows y Linux, «host-tauri»): lee el archivo de progreso de un script (JSONL, lo escribe
//! trabajos.emitir) cada 0,5 s y pasa las líneas nuevas, como JSON, a `aviso(eventos)`. Equivale a `progreso.js` y a
//! `LectorProgreso.swift`. En `main.rs`: `lector_progreso: Some(std::sync::Arc::new(progreso::Lector))`.
//!
//! Límites: una línea de más de MAX_LINEA bytes se descarta entera y en cada vuelta se leen hasta MAX_VUELTA bytes.

use crate::pieza::enchufe::aleatorio_hex;
use crate::pieza::procesador::{LectorProgreso, Progreso};
use serde_json::Value;
use std::fs;
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

pub const MAX_LINEA: usize = 1024 * 1024;
pub const MAX_VUELTA: u64 = 4 * 1024 * 1024;

type Aviso = Box<dyn Fn(Vec<Value>) + Send + Sync>;

pub struct Lector;

impl LectorProgreso for Lector {
    fn crear(&self, prefijo: &str, aviso: Aviso) -> Option<Box<dyn Progreso>> {
        Archivo::nuevo(prefijo, aviso, Duration::from_millis(500)).map(|a| Box::new(a) as Box<dyn Progreso>)
    }
}

struct Estado {
    desde: u64,
    resto: Vec<u8>,
    saltando: bool,
}

pub struct Archivo {
    ruta: PathBuf,
    aviso: Arc<Aviso>,
    estado: Arc<Mutex<Estado>>,
    parar: Arc<AtomicBool>,
    hilo: Option<thread::JoinHandle<()>>,
}

impl Archivo {
    pub fn nuevo(prefijo: &str, aviso: Aviso, cada: Duration) -> Option<Self> {
        let p: String = prefijo.to_lowercase().chars().filter(|c| c.is_ascii_alphanumeric()).collect();
        let p = if p.is_empty() { "pieza".into() } else { p };
        let ruta = std::env::temp_dir().join(format!("{p}-progreso-{}.jsonl", aleatorio_hex(16)));
        let mut o = fs::OpenOptions::new();
        o.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            o.mode(0o600);
        }
        o.open(&ruta).ok()?.flush().ok()?;
        let estado = Arc::new(Mutex::new(Estado { desde: 0, resto: Vec::new(), saltando: false }));
        let aviso = Arc::new(aviso);
        let parar = Arc::new(AtomicBool::new(false));
        let (r, e, a, s) = (ruta.clone(), estado.clone(), aviso.clone(), parar.clone());
        let hilo = thread::spawn(move || {
            while !s.load(Ordering::SeqCst) {
                thread::sleep(cada);
                leer(&r, &e, &a);
            }
        });
        Some(Archivo { ruta, aviso, estado, parar, hilo: Some(hilo) })
    }
}

/// Devuelve true si quedó algo por leer (más de MAX_VUELTA).
fn leer(ruta: &PathBuf, estado: &Mutex<Estado>, aviso: &Aviso) -> bool {
    let mut e = estado.lock().unwrap_or_else(|x| x.into_inner());
    let Ok(mut f) = fs::File::open(ruta) else { return false };
    let tam = f.metadata().map(|m| m.len()).unwrap_or(0);
    if tam <= e.desde {
        return false;
    }
    let mut d = vec![0u8; (tam - e.desde).min(MAX_VUELTA) as usize];
    if f.seek(SeekFrom::Start(e.desde)).is_err() {
        return false;
    }
    let n = f.read(&mut d).unwrap_or(0);
    d.truncate(n);
    e.desde += n as u64;
    e.resto.extend_from_slice(&d);
    let mut eventos = Vec::new();
    while let Some(i) = e.resto.iter().position(|b| *b == b'\n') {
        let linea: Vec<u8> = e.resto.drain(..=i).collect();
        let linea = &linea[..linea.len() - 1];
        if e.saltando {
            // El final de una línea demasiado larga.
            e.saltando = false;
            continue;
        }
        if linea.len() > MAX_LINEA {
            continue;
        }
        if let Ok(j) = serde_json::from_slice::<Value>(linea) {
            if j.is_object() {
                eventos.push(j);
            }
        }
    }
    if e.resto.len() > MAX_LINEA {
        e.resto.clear();
        e.saltando = true;
    }
    let quedan = tam > e.desde;
    drop(e);
    if !eventos.is_empty() {
        aviso(eventos);
    }
    quedan
}

impl Progreso for Archivo {
    fn ruta(&self) -> PathBuf {
        self.ruta.clone()
    }
    /// Lo último que quedó, y se borra el archivo.
    fn terminar(mut self: Box<Self>) {
        self.parar.store(true, Ordering::SeqCst);
        if let Some(h) = self.hilo.take() {
            let _ = h.join();
        }
        for _ in 0..8 {
            if !leer(&self.ruta, &self.estado, &self.aviso) {
                break;
            }
        }
        let _ = fs::remove_file(&self.ruta);
    }
}

#[cfg(test)]
mod pruebas {
    use super::*;
    use std::sync::mpsc;

    #[test]
    fn lee_lineas_nuevas_y_descarta_lo_raro() {
        let (tx, rx) = mpsc::channel();
        let tx = Mutex::new(tx);
        let a = Archivo::nuevo("Ana", Box::new(move |e| {
            let _ = tx.lock().unwrap().send(e);
        }), Duration::from_millis(50))
        .unwrap();
        let ruta = a.ruta.clone();
        let mut f = fs::OpenOptions::new().append(true).open(&ruta).unwrap();
        writeln!(f, "{{\"paso\": 1}}\nno es json\n[1]\n{{\"paso\": 2}}").unwrap();
        let mut todos = Vec::new();
        while todos.len() < 2 {
            todos.extend(rx.recv_timeout(Duration::from_secs(3)).unwrap());
        }
        assert_eq!(todos[1]["paso"], 2);
        Box::new(a).terminar();
        assert!(!ruta.exists());
    }
}
