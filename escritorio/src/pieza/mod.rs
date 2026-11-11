// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
//! Pieza «host-tauri»: la app nativa genérica para Mac, Windows y Linux (Rust + Tauri). En la app vive en
//! `escritorio/src/pieza/`; `main.rs` (de la app) hace `mod pieza;` y llama `pieza::host::arrancar`.
// Es una pieza: la app usa solo lo que necesita.
#![allow(dead_code)]
pub mod enchufe;
pub mod host;
pub mod procesador;
pub mod protocolo;
pub mod sistema;
pub mod vigilante;
