// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// Pieza «universos»: usar un universo en la interfaz. Registra su tema en la pieza «tema» (tema.registrar) y da sus textos y
// listas con lo de la app como respaldo. Valida con las mismas reglas que python/universo_formato.py: solo datos, nunca HTML.
// Sin dependencias. Script clásico (window.PiezaUniversos) o Node (require).
//
//   const u = PiezaUniversos.crear({ tema });
//   u.usar(universo);                        // null si no sirve; registra «u-<id>» y lo aplica
//   T(u.texto("saludo", "Hola"))             // el texto del universo o el de la app (escápalo o pásalo por T, como todo)
//   u.lista("elogios", ["¡Bien!"])           // su lista o la de la app
//   u.dejar();                               // vuelve al tema de antes
(function (raiz, fabrica) {
  const m = fabrica();
  if (typeof module === "object" && module.exports) module.exports = m;
  else raiz.PiezaUniversos = m;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
  const CLAVE = /^[a-z][a-z0-9_]{0,30}$/;
  const HEX = /^#[0-9a-fA-F]{6}$/;
  const BASES = ["claro", "oscuro", "vidrio"];
  const TOKENS = ["fondo", "panel", "panel-2", "linea", "texto", "texto-suave", "tenue", "acento", "sobre-acento", "rojo", "verde"];
  const texto = (v, max) => typeof v === "string" && v.trim().length > 0 && v.length <= max && !v.includes("<") && !v.includes("\0");

  /** Un universo limpio ({id, nombre, emoji, idioma, descripcion, tema, textos, listas}) o null. Lo dudoso se descarta. */
  function validar(u) {
    if (!u || typeof u !== "object" || !ID.test(u.id || "") || u.id.length > 40 || !texto(u.nombre, 40)) return null;
    const t = u.tema || {};
    if (!BASES.includes(t.base)) return null;
    const colores = {};
    for (const [k, v] of Object.entries(t.colores || {})) if (TOKENS.includes(k) && HEX.test(v)) colores[k] = v.toLowerCase();
    const textos = {};
    for (const [k, v] of Object.entries(u.textos || {}).slice(0, 60)) if (CLAVE.test(k) && texto(v, 200)) textos[k] = v;
    const listas = {};
    for (const [k, v] of Object.entries(u.listas || {}).slice(0, 12)) {
      const xs = Array.isArray(v) ? v.slice(0, 30).filter((x) => texto(x, 120)) : [];
      if (CLAVE.test(k) && xs.length) listas[k] = xs;
    }
    return { id: u.id, nombre: u.nombre.trim(), emoji: texto(u.emoji, 8) ? u.emoji : "", idioma: u.idioma === "en" ? "en" : "es",
      descripcion: texto(u.descripcion, 200) ? u.descripcion : "", tema: { base: t.base, colores }, textos, listas };
  }

  function crear(opciones = {}) {
    const tema = opciones.tema || null;
    let actual = null, antes = null;

    function usar(u) {
      const limpio = validar(u);
      if (!limpio) return null;
      if (!actual && tema) antes = tema.valor;
      actual = limpio;
      if (tema) {
        // Con colores propios, su tema registrado; sin colores, la base de la pieza (claro, oscuro o vidrio).
        const id = ("u-" + limpio.id).slice(0, 31);
        const registrado = Object.keys(limpio.tema.colores).length
          ? tema.registrar({ id, nombre: limpio.nombre, base: limpio.tema.base, colores: limpio.tema.colores }) : null;
        tema.aplicar(registrado ? id : limpio.tema.base);
      }
      return limpio;
    }
    function dejar() {
      actual = null;
      if (tema) tema.aplicar(antes || "sistema");
      antes = null;
    }
    const textoDe = (clave, defecto) => (actual && Object.prototype.hasOwnProperty.call(actual.textos, clave) ? actual.textos[clave] : defecto);
    const listaDe = (clave, defecto) => (actual && Object.prototype.hasOwnProperty.call(actual.listas, clave) ? actual.listas[clave].slice() : defecto);
    return { usar, dejar, texto: textoDe, lista: listaDe, get actual() { return actual; } };
  }

  return { crear, validar, TOKENS };
});
