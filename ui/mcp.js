// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// Pieza «mcp»: la sección «Conectar a tu IA» de Ajustes. Conecta la app con la IA que la persona ya usa en su computador (Claude,
// ChatGPT/Codex, Gemini) para que le pregunte por sus datos desde ahí. Sin dependencias; script clásico (window.PiezaMCP) o Node.
// Devuelve HTML como texto (todo lo de afuera va escapado), con las clases de la pieza «componentes» (pz-fila, pz-boton…).
//
//   const mcpUI = PiezaMCP.crear({ i18n, host, pintar, app: "Prueba", aviso: (t, o) => ui.aviso(t, o),
//                                  ejemplo: "¿Qué tengo pendiente esta semana?" });
//   mcpUI.pedirEstado();                      // al abrir Ajustes (acción mcpEstado)
//   window.Prueba = { ..., mcpListo: mcpUI.recibir };   // la respuesta de mcpEstado y mcpConectar
//   html += mcpUI.html();                     // donde va la sección
//   if (mcpUI.manejarClic(ev)) return;        // en el manejador de clics de la app
(function (raiz, fabrica) {
  const m = fabrica();
  if (typeof module === "object" && module.exports) module.exports = m;
  else raiz.PiezaMCP = m;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const ID = /^[a-z][a-z0-9_]{0,30}$/;
  const HERRAMIENTA = /^[a-z][a-z0-9_]{0,63}$/;
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function crear(opciones = {}) {
    const { i18n } = opciones;
    if (!i18n || typeof i18n.T !== "function" || typeof i18n.Tp !== "function") throw new Error("mcp: falta «i18n» (la pieza i18n).");
    const T = (t, v) => i18n.T(t, v);
    const Tp = (t, v) => i18n.Tp(t, v);
    const tr = (t) => (typeof i18n.tr === "function" ? i18n.tr(t) : t);
    const L = (x) => esc(x);   // frase fija en español: la traduce traducirDOM con el resto de la app
    const F = (t, v, etiqueta = "span") => `<${etiqueta} data-sin-traducir>${T(t, v)}</${etiqueta}>`;
    const app = String(opciones.app || "").slice(0, 60);
    const enviar = (accion, datos) => opciones.host?.enviar?.(accion, datos);
    const pintar = () => opciones.pintar?.();
    const aviso = (t, o) => opciones.aviso?.(t, o);
    const E = { clientes: [], herramientas: [], actividad: [], escribir: false, ocupado: {}, error: {}, cargado: false };

    function pedirEstado() { enviar("mcpEstado", {}); }
    function conectar(id, orden = "conectar") {
      if (!ID.test(String(id || "")) || E.ocupado[id]) return false;
      E.ocupado[id] = true;
      delete E.error[id];
      enviar("mcpConectar", { orden, cliente: id });
      pintar();
      return true;
    }
    /** Que la IA también pueda cambiar cosas (solo las herramientas que la app marcó escribe=True). */
    function permitirEscribir(si) {
      E.escribir = !!si;
      enviar("config", { mcp_escribir: !!si });
      pedirEstado();
      pintar();
    }
    /** La respuesta de mcpEstado y de mcpConectar: {ok, clientes, herramientas, actividad, escribir, orden?, cliente?, error?, valores?, nota?}. */
    function recibir(r = {}) {
      const id = ID.test(String(r.cliente || "")) ? r.cliente : null;
      if (id) delete E.ocupado[id];
      if (Array.isArray(r.clientes)) E.clientes = r.clientes.filter((c) => c && ID.test(String(c.id)));
      if (Array.isArray(r.herramientas)) E.herramientas = r.herramientas.filter((h) => h && HERRAMIENTA.test(String(h.nombre)));
      if (Array.isArray(r.actividad)) E.actividad = r.actividad.filter((a) => a && HERRAMIENTA.test(String(a.herramienta))).slice(-20);
      if (typeof r.escribir === "boolean") E.escribir = r.escribir;
      E.cargado = true;
      if (id && !r.ok) E.error[id] = r.valores ? Tp(r.error || "No se pudo conectar.", r.valores) : tr(r.error || "No se pudo conectar.");
      else if (id && r.orden === "conectar") aviso(r.nota || "Listo: tu IA ya puede consultar {app}", r.nota ? {} : { valores: { app } });
      pintar();
    }

    function fila(c) {
      const ocupado = !!E.ocupado[c.id], error = E.error[c.id];
      const estado = error ? `<small class="pz-error-texto" data-sin-traducir>${esc(error)}</small>`
        : c.conectado ? (c.al_dia ? `<small class="pz-ok">${L("Conectada")}</small>` : `<small>${L("Conectada (actualizando la ruta…)")}</small>`)
          : `<small>${L("Instalada en este computador")}</small>`;
      const boton = c.conectado
        ? `<button type="button" class="pz-boton" data-pz-mcp-quitar="${esc(c.id)}" ${ocupado ? "disabled" : ""}>${L("Quitar")}</button>`
        : `<button type="button" class="pz-boton pz-principal" data-pz-mcp="${esc(c.id)}" ${ocupado ? "disabled" : ""}>${ocupado ? L("Conectando…") : L("Conectar")}</button>`;
      return `<div class="pz-fila"><span class="pz-txt"><b data-sin-traducir>${esc(tr(c.nombre || c.id))}</b>${estado}</span>${boton}</div>`;
    }

    function hora(iso) {
      const d = new Date(String(iso || ""));
      if (isNaN(d)) return "";
      try { return d.toLocaleString(i18n.idioma || undefined, { dateStyle: "short", timeStyle: "short" }); } catch { return d.toISOString().slice(0, 16).replace("T", " "); }
    }

    /** La sección completa. `ejemplo`: una pregunta en español que muestra para qué sirve (se traduce). */
    function html({ ejemplo = opciones.ejemplo, titulo = "Conectar a tu IA" } = {}) {
      const visibles = E.clientes.filter((c) => c.instalado || c.conectado);
      const alguna = E.clientes.some((c) => c.conectado);
      const lee = E.herramientas.filter((h) => !h.escribe), cambia = E.herramientas.filter((h) => h.escribe);
      const lista = (hs) => hs.map((h) => `<li data-sin-traducir>${esc(tr(h.titulo || h.nombre))}</li>`).join("");
      const filas = !E.cargado ? `<p class="pz-ayuda">${L("Buscando tus IA…")}</p>`
        : visibles.length ? `<div class="pz-filas">${visibles.map(fila).join("")}</div>`
          : `<p class="pz-ayuda">${L("No encontré ninguna IA de escritorio en este computador (Claude, ChatGPT/Codex o Gemini).")}</p>`;
      const prueba = alguna && ejemplo
        ? `<p class="pz-ayuda">${F("**Pruébalo:** abre tu IA y pregúntale «{ejemplo}». Si usas la app de Claude, ciérrala y vuelve a abrirla la primera vez.", { ejemplo: tr(ejemplo) })}</p>` : "";
      const permisos = E.herramientas.length ? `<details class="pz-mcp-permisos"><summary>${L("Qué puede hacer tu IA")}</summary>
        ${lee.length ? `<p><b>${L("Puede leer")}</b></p><ul>${lista(lee)}</ul>` : ""}
        ${cambia.length ? `<p><b>${L("Puede cambiar (si lo permites)")}</b></p><ul>${lista(cambia)}</ul>
          <label class="pz-fila"><input type="checkbox" data-pz-mcp-escribir ${E.escribir ? "checked" : ""}> <span class="pz-txt">${L("Permitir que mi IA cambie cosas")}<small>${L("Por defecto solo puede leer.")}</small></span></label>` : ""}
      </details>` : "";
      const act = E.actividad.length ? `<details class="pz-mcp-actividad"><summary>${L("Lo último que consultó")}</summary><ul>${E.actividad.slice().reverse().map((a) =>
        `<li data-sin-traducir>${esc(hora(a.fecha))} · ${esc(a.herramienta)}${a.ok ? "" : ` · ${esc(tr("no se pudo"))}`}</li>`).join("")}</ul></details>` : "";
      return `<section class="pz-mcp" aria-labelledby="pz-mcp-titulo"><h2 id="pz-mcp-titulo">${L(titulo)}</h2>
        <p>${F("Pregúntale a la IA que ya usas por tus datos de {app}, sin copiar ni pegar. Todo corre en tu computador.", { app })}</p>
        ${filas}${prueba}${permisos}${act}
        <p class="pz-ayuda">${F("Lo que tu IA lee de {app} viaja a tu proveedor de IA con tu cuenta, igual que si se lo escribieras. {app} no tiene servidores.", { app })}</p></section>`;
    }

    /** Clics y cambios de la sección. Devuelve true si eran suyos. */
    function manejarClic(ev) {
      const t = ev?.target;
      const el = t?.closest?.("[data-pz-mcp],[data-pz-mcp-quitar],[data-pz-mcp-escribir]");
      if (!el) return false;
      if (el.hasAttribute("data-pz-mcp-escribir")) { permitirEscribir(!!el.checked); return true; }
      ev.preventDefault?.();
      if (el.hasAttribute("data-pz-mcp")) conectar(el.getAttribute("data-pz-mcp"));
      else conectar(el.getAttribute("data-pz-mcp-quitar"), "quitar");
      return true;
    }

    return { pedirEstado, conectar, permitirEscribir, recibir, html, manejarClic, estado: E };
  }

  return { crear };
});
