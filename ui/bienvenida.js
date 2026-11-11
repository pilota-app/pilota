// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// Pieza «bienvenida»: el primer uso por pasos, con el idioma SIEMPRE primero. Cada app (o cada pieza) suma sus pasos.
// Sin dependencias. Script clásico (window.PiezaBienvenida) o Node (require). Devuelve HTML como texto: la app lo pinta
// donde quiera (todo lo que viene de afuera va escapado) y le pasa los clics y las teclas.
//
//   const bv = PiezaBienvenida.crear({ i18n, guardarIdioma: (c) => host.enviar("config", { idioma_ui: c }), pintar,
//                                      terminar: () => host.enviar("config", { bienvenida: true }) });
//   bv.sumarPaso({ id: "hola", titulo: "Hola, esto es Ana", cuerpo: () => "<p>…</p>" });
//   bv.abrir({ config: E.config });            // decide si se muestra y desde qué paso
//   if (bv.soloIdioma) pintarSolo(bv.html());       // en el paso del idioma no se pinta nada más
//   else pintarTodo(app() + ui.envolver(bv.html(), { id: "t-bv", sinEsc: true }));   // con la pieza «componentes»
(function (raiz, fabrica) {
  const m = fabrica();
  if (typeof module === "object" && module.exports) module.exports = m;
  else raiz.PiezaBienvenida = m;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const CODIGO = /^[a-z]{2,3}(-[A-Z]{2})?$/;
  const ID = /^[a-z][a-z0-9-]{0,40}$/;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  /** Cada idioma escrito en su propio idioma (nunca se traduce), con la nota de «sugerido» también en ese idioma. Una app puede
   *  sumar `detalle` («Continuar en español»), que va debajo del nombre, también en ese idioma. */
  const IDIOMAS = [
    { codigo: "es", nombre: "Español", sugerido: "Sugerido" },
    { codigo: "en", nombre: "English", sugerido: "Suggested" },
  ];

  function crear(opciones = {}) {
    const { i18n } = opciones;
    if (!i18n || typeof i18n.T !== "function") throw new Error("bienvenida: falta «i18n» (la pieza i18n).");
    if (typeof opciones.guardarIdioma !== "function") throw new Error("bienvenida: falta «guardarIdioma(codigo)».");
    const idiomas = (opciones.idiomas || IDIOMAS).filter((x) => x && CODIGO.test(x.codigo) && typeof x.nombre === "string").slice(0, 9);
    if (!idiomas.length) throw new Error("bienvenida: no hay idiomas válidos.");
    const cargarIdioma = opciones.cargarIdioma || ((c) => i18n.cargar(c));
    const sistema = () => {
      const s = opciones.sistema ? opciones.sistema() : i18n.idiomaDelSistema?.(undefined, idiomas.map((x) => x.codigo));
      return idiomas.some((x) => x.codigo === s) ? s : idiomas[0].codigo;
    };
    const pintar = () => opciones.pintar?.();
    const documento = () => opciones.documento || (typeof document !== "undefined" ? document : null);
    const T = (t, v) => i18n.T(t, v);
    // Dónde se cambia lo elegido: «Ajustes» / «Settings» o lo que diga la app (una app para niños: «Para adultos»); false: sin nota.
    const ajustes = opciones.ajustes === false ? null
      : opciones.ajustes && typeof opciones.ajustes.es === "string" && typeof opciones.ajustes.en === "string" ? opciones.ajustes : null;
    const pasos = [];
    let paso = null, retenidos = [], guardado = null;

    if (opciones.listo !== false) {
      const l = opciones.listo || {};
      pasos.push({ id: "listo", titulo: l.titulo || "Todo listo", orden: Infinity,
        // Ya traducido con T: data-sin-traducir, así traducirDOM no lo cuenta como un texto que falta (lo veía en inglés).
        cuerpo: l.cuerpo || (() => `<p data-sin-traducir>${ajustes ? T("Ya puedes empezar. Todo lo que elegiste se cambia cuando quieras en {donde}.", { donde: T(ajustes.es) })
          : opciones.ajustes === false ? T("Ya puedes empezar.") : T("Ya puedes empezar. Todo lo que elegiste se cambia cuando quieras en Ajustes.")}</p>`),
        puede: () => true, saltable: false, alFinal: false, despues: "Lo hago después", fin: { texto: "Empezar", principal: true, accion: null } });
    }
    const lista = () => pasos.slice().sort((a, b) => a.orden - b.orden);
    const total = () => pasos.length + 1;

    function pasoIdioma() {
      const sugerido = guardado || sistema();
      // El sugerido lleva data-autofoco: con «componentes», ui.despuesDePintar() lo enfoca solo (sin bv.enfocar()).
      const opcion = (x, k) => {
        const es = x.codigo === sugerido;
        return `<button type="button" class="opcion-idioma${es ? " sugerido" : ""}" id="bv-idioma-${x.codigo}" data-bv-idioma="${x.codigo}" lang="${x.codigo}" aria-keyshortcuts="${k + 1}"${es ? " data-autofoco" : ""}>
          <span class="tecla" aria-hidden="true">${k + 1}</span><b>${esc(x.nombre)}</b>${es ? `<small>${esc(x.sugerido || "")}</small>` : ""}${typeof x.detalle === "string" && x.detalle ? `<span class="detalle-idioma">${esc(x.detalle)}</span>` : ""}</button>`;
      };
      const nota = opciones.ajustes === false ? ""
        : ajustes ? `<p class="nota-idioma"><span lang="es">Puedes cambiarlo cuando quieras en ${esc(ajustes.es)}.</span> <span lang="en">You can change it anytime in ${esc(ajustes.en)}.</span></p>`
          : `<p class="nota-idioma"><span lang="es">Puedes cambiarlo cuando quieras en Ajustes.</span> <span lang="en">You can change it anytime in Settings.</span></p>`;
      // `logo`: HTML de la app (suyo, no de afuera), arriba del título en el paso del idioma.
      const logo = typeof opciones.logo === "string" && opciones.logo ? `<div class="logo-bv" aria-hidden="true">${opciones.logo}</div>` : "";
      return `<div class="pieza-bv pieza-bv-idioma" data-pz-clave="bv-idioma" data-sin-traducir>${marcas()}${logo}
        <h2 id="t-bv" tabindex="-1"><span lang="es">Elige tu idioma</span> <span class="sep" aria-hidden="true">·</span> <span lang="en">Choose your language</span></h2>
        <div class="opciones-idioma" role="group" aria-labelledby="t-bv">${idiomas.map(opcion).join("")}</div>
        ${nota}</div>`;
    }
    function marcas() {
      return `<div class="pasos-bv" aria-hidden="true">${Array.from({ length: total() }, (_, i) => `<i class="${paso !== null && i <= paso ? "hecho" : ""}"></i>`).join("")}</div>`;
    }

    const bv = {
      IDIOMAS,
      get paso() { return paso; },
      get activa() { return paso !== null; },
      /** En el paso del idioma la app no pinta nada más: ni su pantalla detrás, ni avisos, ni pide permisos. */
      get soloIdioma() { return paso === 0; },
      get pasos() { return [{ id: "idioma" }, ...lista()].map((p) => p.id); },

      /** Suma un paso: {id, titulo (frase en español, se traduce), cuerpo: () => html, puede?: () => bool, orden? (50),
       *  saltable? (true: muestra «Lo hago después»; false para un paso que la app necesita sí o sí), despues? (otro texto para
       *  «Lo hago después»), fin? ({texto, principal, accion}: el botón que termina, si es el último paso)}.
       *  En el último paso (con `listo: false`) «Lo hago después» sale solo si el paso dice `saltable: true` o `despues`; `fin` le
       *  pone su texto («Empezar sin cartola»), `principal: false` lo deja secundario (el principal va en el cuerpo) y `accion` corre
       *  después de terminar.
       *  El cuerpo lo arma quien suma el paso (con esc() para lo de afuera); la app lo traduce con traducirDOM. */
      sumarPaso(p) {
        if (!p || !ID.test(p.id || "") || p.id === "idioma") throw new Error("bienvenida: el paso necesita un «id» (minúsculas y guiones).");
        if (pasos.some((x) => x.id === p.id)) throw new Error(`bienvenida: el paso «${p.id}» ya existe.`);
        if (typeof p.titulo !== "string" || typeof p.cuerpo !== "function") throw new Error("bienvenida: el paso necesita «titulo» y «cuerpo()».");
        const orden = Number.isFinite(p.orden) ? p.orden : 50;
        const fin = p.fin && typeof p.fin === "object" ? p.fin : {};
        pasos.push({ id: p.id, titulo: p.titulo, cuerpo: p.cuerpo, puede: typeof p.puede === "function" ? p.puede : () => true, orden,
          saltable: p.saltable !== false, alFinal: p.saltable === true || typeof p.despues === "string",
          despues: typeof p.despues === "string" && p.despues ? p.despues : "Lo hago después",
          fin: { texto: typeof fin.texto === "string" && fin.texto ? fin.texto : "Empezar", principal: fin.principal !== false,
            accion: typeof fin.accion === "function" ? fin.accion : null } });
        return bv;
      },

      /** Decide si se muestra: con «bienvenida» hecha, no; sin idioma, desde el idioma; con idioma, desde el paso siguiente
       *  (quien eligió y la dejó a medias no vuelve a elegir). `forzar` (p. ej. ?bienvenida) la abre desde el idioma. */
      abrir({ config = {}, forzar = false } = {}) {
        guardado = idiomas.some((x) => x.codigo === config.idioma_ui) ? config.idioma_ui : null;
        paso = forzar ? 0 : config.bienvenida ? null : guardado ? 1 : 0;
        if (paso !== null && paso >= total()) paso = total() - 1;
        return paso;
      },

      html() {
        if (paso === null) return "";
        if (paso === 0) return pasoIdioma();
        const p = lista()[paso - 1], ultimo = paso === total() - 1, puede = !!p.puede();
        // Clases de la pieza «componentes» (pz-pie, pz-boton, pz-principal, pz-izq); sin ella, bienvenida.css las dibuja igual.
        return `<div class="pieza-bv" data-paso="${esc(p.id)}" data-pz-clave="bv-${esc(p.id)}">${marcas()}
          <h2 id="t-bv" tabindex="-1" data-sin-traducir>${T(p.titulo)}</h2>
          <div class="cuerpo-bv">${p.cuerpo()}</div>
          <div class="pz-pie" data-sin-traducir><button type="button" class="pz-boton pz-izq" data-bv-ir="${paso - 1}">${T("Atrás")}</button>
            ${ultimo ? `${p.alFinal ? `<button type="button" class="pz-boton" data-bv-fin="despues">${T(p.despues)}</button>` : ""}<button type="button" class="pz-boton${p.fin.principal ? " pz-principal" : ""}" data-bv-fin>${T(p.fin.texto)}</button>`
              : `${p.saltable ? `<button type="button" class="pz-boton" data-bv-fin="despues">${T(p.despues)}</button>` : ""}<button type="button" class="pz-boton pz-principal" data-bv-ir="${paso + 1}"${puede ? "" : " disabled"}>${T("Siguiente")}</button>`}</div></div>`;
      },

      /** Guarda el idioma por el mismo camino que Ajustes, lo carga y sigue ya traducida. */
      async elegirIdioma(codigo) {
        if (!idiomas.some((x) => x.codigo === codigo)) return false;
        guardado = codigo;
        await opciones.guardarIdioma(codigo);
        await cargarIdioma(codigo);
        paso = total() > 1 ? 1 : null;
        if (paso === null) opciones.terminar?.();
        pintar();
        bv.enfocar();
        const avisos = retenidos; retenidos = [];
        if (avisos.length && opciones.mostrarAviso) opciones.mostrarAviso(...avisos[avisos.length - 1]);
        return true;
      },

      /** Va a un paso (adelante solo si el actual está listo). */
      ir(n) {
        if (paso === null || !Number.isInteger(n) || n < 0 || n >= total()) return false;
        if (n > paso && paso > 0 && !lista()[paso - 1].puede()) return false;
        if (n > paso && paso === 0) return false; // del idioma se sale eligiendo
        paso = n;
        pintar();
        bv.enfocar();
        return true;
      },
      /** Cierra la bienvenida. `como`: "fin" (el botón que termina) o "despues" («Lo hago después»): llega a
       *  `opciones.terminar(como, idDelPaso)`; con "fin" en un paso con `fin.accion`, esa acción corre después. */
      terminar(como = "fin") {
        if (paso === null) return;
        const p = paso > 0 ? lista()[paso - 1] : null;
        paso = null;
        opciones.terminar?.(como === "despues" ? "despues" : "fin", p ? p.id : "idioma");
        pintar();
        if (como !== "despues" && p && p.fin.accion) p.fin.accion();
      },

      /** Mientras se elige el idioma, los avisos esperan: retener(...) devuelve true y se muestra el último al elegir. */
      retener(...aviso) {
        if (paso !== 0) return false;
        retenidos.push(aviso);
        return true;
      },

      /** Para el manejador de clics de la app: devuelve true si el clic era de la bienvenida. */
      manejarClic(ev) {
        const el = ev?.target?.closest?.("[data-bv-idioma],[data-bv-ir],[data-bv-fin]");
        if (!el || paso === null) return false;
        ev.preventDefault?.();
        if (el.hasAttribute("data-bv-idioma")) bv.elegirIdioma(el.getAttribute("data-bv-idioma"));
        else if (el.hasAttribute("data-bv-ir")) bv.ir(Number(el.getAttribute("data-bv-ir")));
        else bv.terminar(el.getAttribute("data-bv-fin") === "despues" ? "despues" : "fin");
        return true;
      },

      /** Teclas en el paso del idioma: 1, 2… eligen; las flechas pasan de una opción a otra. Tab y Enter funcionan solos. */
      manejarTecla(ev) {
        if (paso !== 0 || !ev || ev.metaKey || ev.ctrlKey || ev.altKey || ev.target?.closest?.("input, textarea, select")) return false;
        if (/^[1-9]$/.test(ev.key) && Number(ev.key) <= idiomas.length) {
          ev.preventDefault?.();
          bv.elegirIdioma(idiomas[Number(ev.key) - 1].codigo);
          return true;
        }
        if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(ev.key)) {
          const d = documento(); if (!d) return false;
          const ops = Array.from(d.querySelectorAll("[data-bv-idioma]"));
          const i = ops.indexOf(d.activeElement), paso_ = ev.key === "ArrowLeft" || ev.key === "ArrowUp" ? -1 : 1;
          ev.preventDefault?.();
          ops[(i < 0 ? 0 : i + paso_ + ops.length) % ops.length]?.focus();
          return true;
        }
        return false;
      },

      /** Después de pintar: en el idioma, el foco en el sugerido; en los demás pasos, en el título. */
      enfocar() {
        const d = documento(); if (!d || paso === null) return;
        const el = paso === 0 ? d.querySelector(`#bv-idioma-${guardado || sistema()}`) : d.querySelector("#t-bv");
        el?.focus?.();
      },
    };
    return bv;
  }

  return { crear, IDIOMAS };
});
