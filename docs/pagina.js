// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// Pieza «pagina»: el idioma de la página (?lang=en, lo que eligió antes o el del navegador) y la descarga según el sistema.
// Sin dependencias ni nada en línea (CSP script-src 'self'). Todo lo que necesita está en el HTML: data-titulo-es/en, data-alt-es/en
// y los enlaces .so[data-so] de «Descargar».
(() => {
  "use strict";
  const html = document.documentElement;
  const clave = `${html.dataset.id || "app"}-idioma`;
  const leer = () => { try { return localStorage.getItem(clave); } catch { return null; } };
  const guardar = (v) => { try { localStorage.setItem(clave, v); } catch { /* sin almacenamiento */ } };
  const pedido = new URLSearchParams(location.search).get("lang");
  const inicial = pedido === "en" || pedido === "es" ? pedido
    : leer() || ((navigator.language || "es").toLowerCase().startsWith("es") ? "es" : "en");
  const boton = document.getElementById("idioma");

  function poner(l) {
    html.lang = l;
    if (boton) boton.textContent = l === "es" ? "EN" : "ES";
    const t = html.dataset[l === "es" ? "tituloEs" : "tituloEn"];
    if (t) document.title = t;
    for (const img of document.querySelectorAll("img[data-alt-es]")) img.alt = img.dataset[l === "es" ? "altEs" : "altEn"] || img.alt;
  }
  boton?.addEventListener("click", () => { const l = html.lang === "es" ? "en" : "es"; poner(l); guardar(l); });
  poner(inicial);

  // Descarga según el sistema: el botón principal apunta al archivo de este computador (si la app lo tiene).
  function sistema() {
    const p = `${navigator.userAgentData?.platform || ""} ${navigator.platform || ""} ${navigator.userAgent || ""}`.toLowerCase();
    if (/android|iphone|ipad|ipod/.test(p) || (/mac/.test(p) && navigator.maxTouchPoints > 1)) return "movil";
    if (/mac/.test(p)) return "mac";
    if (/win/.test(p)) return "windows";
    if (/linux|x11|cros/.test(p)) return "linux";
    return "";
  }
  const so = sistema();
  const enlace = so && document.querySelector(`.so[data-so="${so}"]`);
  const principal = document.getElementById("descarga-principal");
  if (enlace && principal) {
    enlace.classList.add("tuyo");
    principal.href = enlace.href;
    const nombre = enlace.querySelector("b")?.textContent || "";
    principal.innerHTML = "";
    for (const [l, texto] of [["es", `Descargar para ${nombre}`], ["en", `Download for ${nombre}`]]) {
      const s = document.createElement("span");
      s.setAttribute(`data-${l}`, "");
      s.textContent = texto;
      principal.append(s);
    }
  }
})();
