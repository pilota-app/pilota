// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.
// Pieza «pagina»: la página pública servida como en GitHub Pages (docs/ en la raíz, ui/ en /demo/), sus imágenes y su revisión.
// Todo con los datos ficticios de la vista previa (ui/demo.json), nunca con datos reales.
//
//   node herramientas/pagina_capturas.mjs servir             → http://localhost:8790/ hasta que lo cortes
//   node herramientas/pagina_capturas.mjs capturas            → cada docs/pagina.json → «capturas» desde la vista previa (/demo/)
//   node herramientas/pagina_capturas.mjs imagenes            → docs/img/compartir.png (1200×630) y docs/apple-touch-icon.png (180×180)
//   node herramientas/pagina_capturas.mjs revisar [carpeta]   → la página en es/en, 1280 y 390 px, claro y oscuro: sin errores de
//                                                               JavaScript ni de CSP, sin desborde, sin textos sin traducir, con el
//                                                               JSON-LD igual a lo que se ve y contraste AA (y capturas si das carpeta)
//
// Una captura en docs/pagina.json (solo datos, nada se ejecuta):
//   {"archivo": "img/inicio.png", "alt": {"es": "…", "en": "…"}, "ancho": 1280, "alto": 800,
//    "demo": "?idioma=en#algo", "tema": "claro|oscuro", "tocar": ["#boton", "[data-vista=x]"], "hora": "2026-10-20T10:48:00-03:00"}
// Necesita Playwright (PLAYWRIGHT=/ruta/a/playwright si no está en node_modules).
import http from "node:http";

/** La intro en la imagen para compartir: hasta ~160 caracteres, cortada al final de una frase (o de una palabra, con «…»). */
function resumenCorto(t) {
  const s = String(t || "");
  if (s.length <= 160) return s;
  const corte = s.slice(0, 160);
  const fin = corte.lastIndexOf(". ");
  return fin > 60 ? corte.slice(0, fin + 1) : corte.replace(/\s+\S*$/, "") + "…";
}
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const RAIZ = process.env.PAGINA_APP ? path.resolve(process.env.PAGINA_APP) : path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const TIPOS = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".json": "application/json",
  ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".mp4": "video/mp4", ".xml": "application/xml", ".woff2": "font/woff2" };
const [modo = "servir", destino = ""] = process.argv.slice(2);

export function servir(puerto, raiz = RAIZ) {
  const s = http.createServer((q, r) => {
    let p = decodeURIComponent(new URL(q.url, "http://x").pathname);
    const base = p.startsWith("/demo/") ? path.join(raiz, "ui") : path.join(raiz, "docs");
    if (p.startsWith("/demo/")) p = p.slice(5);
    if (p.endsWith("/")) p += "index.html";
    const ruta = path.normalize(path.join(base, p));
    if (!ruta.startsWith(base + path.sep) || !fs.existsSync(ruta) || fs.statSync(ruta).isDirectory()) { r.writeHead(404); return r.end(); }
    r.writeHead(200, { "Content-Type": TIPOS[path.extname(ruta)] || "application/octet-stream" });
    fs.createReadStream(ruta).pipe(r);
  });
  return new Promise((ok) => s.listen(puerto, "127.0.0.1", () => ok(s)));
}

/** Revisa la página abierta en `p` (idioma `l`): devuelve una lista de problemas. La usan este archivo y las pruebas de Pieza. */
export async function revisarPagina(p, l, etiqueta) {
  return (await p.evaluate((l) => {
    const r = [];
    const visible = (el) => { for (let x = el; x && x.nodeType === 1; x = x.parentElement) { const c = getComputedStyle(x); if (c.display === "none" || c.visibility === "hidden") return false; } return true; };
    if (document.documentElement.scrollWidth > window.innerWidth + 1) r.push("se sale a lo ancho");
    // Textos sin traducir: cada texto visible tiene que estar dentro de un [data-es]/[data-en] del idioma, o marcado [data-sin-traducir].
    const recorrer = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = recorrer.nextNode(); n; n = recorrer.nextNode()) {
      const t = n.textContent.trim();
      if (!t || /^[\s·:,.()→/–—|«»"'+-]*$/.test(t) || !visible(n.parentElement)) continue;
      if (!n.parentElement.closest(`[data-${l}], [data-sin-traducir], script, style, noscript`)) r.push(`texto sin traducir: «${t.slice(0, 60)}»`);
    }
    // El JSON-LD dice lo mismo que se ve (las preguntas, en español).
    const ld = [...document.querySelectorAll('script[type="application/ld+json"]')].map((s) => JSON.parse(s.textContent));
    const faq = ld.flatMap((x) => x["@graph"] || [x]).find((x) => x["@type"] === "FAQPage");
    const vistas = [...document.querySelectorAll("#preguntas details")].map((d) => [d.querySelector("summary [data-es]").textContent, d.querySelector("p [data-es]").textContent]);
    const enLd = (faq?.mainEntity || []).map((q) => [q.name, q.acceptedAnswer.text]);
    if (JSON.stringify(vistas) !== JSON.stringify(enLd)) r.push("el JSON-LD (FAQPage) no dice lo mismo que las preguntas que se ven");
    // Contraste AA de cada texto visible sobre su fondo (sólido) más cercano.
    const rgb = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const v = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return v.length >= 3 ? v : null; };
    const lum = ([R, G, B]) => [R, G, B].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }).reduce((a, v, i) => a + v * [0.2126, 0.7152, 0.0722][i], 0);
    const fondo = (el) => { for (let x = el; x; x = x.parentElement) { const c = rgb(getComputedStyle(x).backgroundColor); if (c && (c[3] === undefined || c[3] > 0.9)) return c; } return rgb(getComputedStyle(document.body).backgroundColor); };
    const vistosC = new Set();
    for (const el of document.querySelectorAll("body *")) {
      if (!visible(el) || ![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
      const c = rgb(getComputedStyle(el).color), f = fondo(el);
      if (!c || !f) continue;
      const [a, b] = [lum(c), lum(f)].sort((x, y) => y - x);
      const tam = parseFloat(getComputedStyle(el).fontSize), negrita = Number(getComputedStyle(el).fontWeight) >= 700;
      const minimo = tam >= 24 || (tam >= 18.66 && negrita) ? 3 : 4.5;
      const razon = (a + 0.05) / (b + 0.05);
      const clave = el.tagName + el.className;
      if (razon < minimo && !vistosC.has(clave)) { vistosC.add(clave); r.push(`contraste ${razon.toFixed(2)} < ${minimo} en <${el.tagName.toLowerCase()} class="${el.className}">`); }
    }
    return r;
  }, l)).map((x) => `${etiqueta}: ${x}`);
}

function datos() {
  return JSON.parse(fs.readFileSync(path.join(RAIZ, "docs", "pagina.json"), "utf8"));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (modo === "servir") {
    await servir(8790);
    console.log("Página en http://localhost:8790/ (la vista previa en /demo/). Ctrl+C para cortar.");
  } else {
    const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT || "playwright");
    const s = await servir(0);
    const URL_BASE = `http://127.0.0.1:${s.address().port}/`;
    const navegador = await chromium.launch();
    const problemas = [];
    const d = datos();

    if (modo === "capturas") {
      for (const c of d.capturas || []) {
        if (!/^img\/[a-z0-9][a-z0-9._-]*\.(png|jpg|jpeg|webp)$/.test(c.archivo)) { problemas.push(`captura con archivo raro: ${c.archivo}`); continue; }
        const p = await navegador.newPage({ viewport: { width: c.ancho || 1280, height: c.alto || 800 }, deviceScaleFactor: 2, colorScheme: c.tema === "oscuro" ? "dark" : "light" });
        if (c.hora) await p.clock.setFixedTime(new Date(c.hora));
        p.on("pageerror", (e) => problemas.push(`${c.archivo}: JS ${e.message}`));
        await p.route(/^https?:\/\/(?!127\.0\.0\.1)/, (r) => r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));  // sin red
        await p.goto(URL_BASE + "demo/index.html" + (c.demo || ""));
        await p.waitForTimeout(800);
        for (const sel of c.tocar || []) { await p.click(sel); await p.waitForTimeout(500); }
        const ruta = path.join(RAIZ, "docs", c.archivo);
        fs.mkdirSync(path.dirname(ruta), { recursive: true });
        await p.screenshot({ path: ruta, ...(/\.jpe?g$/.test(ruta) ? { type: "jpeg", quality: 86 } : {}) });
        await p.close();
        console.log(`✓ docs/${c.archivo}`);
      }
    }

    if (modo === "imagenes") {
      const favicon = fs.readFileSync(path.join(RAIZ, "docs", "favicon.svg"), "utf8");
      const icono = await navegador.newPage({ viewport: { width: 180, height: 180 } });
      await icono.setContent(`<html><body style="margin:0">${favicon.replace("<svg ", '<svg width="180" height="180" ')}</body></html>`);
      await icono.screenshot({ path: path.join(RAIZ, "docs", "apple-touch-icon.png") });
      await icono.close();
      const app = JSON.parse(fs.readFileSync(path.join(RAIZ, "app.json"), "utf8"));
      const captura = d.compartir?.captura || d.capturas?.[0]?.archivo;
      const img = captura ? "data:image/png;base64," + fs.readFileSync(path.join(RAIZ, "docs", captura)).toString("base64") : "";
      const logo = "data:image/svg+xml;base64," + Buffer.from(favicon).toString("base64");
      const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
      const acento = /^#[0-9a-f]{6}$/i.test(d.acento?.claro || "") ? d.acento.claro : "#2f5fd0";
      const c = await navegador.newPage({ viewport: { width: 1200, height: 630 } });
      await c.setContent(`<html><head><style>
        body{margin:0;width:1200px;height:630px;overflow:hidden;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:#f6f7f9;color:#1b2230}
        .t{position:absolute;left:64px;top:76px;width:${img ? 470 : 1000}px}
        .m{display:flex;align-items:center;gap:14px;font-weight:800;font-size:34px;letter-spacing:-.02em}.m img{width:52px;height:52px}
        h1{font-size:54px;line-height:1.05;letter-spacing:-.03em;margin:34px 0 0;font-weight:850}
        p{font-size:22px;line-height:1.4;color:#556075;margin:22px 0 0}
        .s{position:absolute;left:64px;bottom:56px;font-size:18px;color:${acento};font-weight:700}
        .v{position:absolute;left:590px;top:64px;width:860px;border-radius:14px;overflow:hidden;box-shadow:0 22px 60px rgba(20,30,50,.22);border:1px solid #dde2ea}
        .v img{display:block;width:860px}
      </style></head><body><div class="t"><div class="m"><img src="${logo}" alt="">${esc(app.nombre)}</div>
        <h1>${esc((d.compartir?.frase || d.frase).es)}</h1><p>${esc(resumenCorto(d.intro.es))}</p></div>
        <div class="s">Gratis · Código abierto</div>${img ? `<div class="v"><img src="${img}" alt=""></div>` : ""}</body></html>`);
      await c.waitForTimeout(200);
      fs.mkdirSync(path.join(RAIZ, "docs", "img"), { recursive: true });
      await c.screenshot({ path: path.join(RAIZ, "docs", "img", "compartir.png") });
      await c.close();
      console.log("✓ docs/img/compartir.png y docs/apple-touch-icon.png (míralas antes de subirlas)");
    }

    if (modo === "revisar") {
      if (destino) fs.mkdirSync(destino, { recursive: true });
      for (const l of ["es", "en"]) for (const [ancho, alto, nombre] of [[1280, 800, "escritorio"], [390, 844, "celular"]]) for (const oscuro of [false, true]) {
        const etiqueta = `${l}, ${ancho} px, ${oscuro ? "oscuro" : "claro"}`;
        const p = await navegador.newPage({ viewport: { width: ancho, height: alto }, colorScheme: oscuro ? "dark" : "light", locale: l === "en" ? "en-US" : "es-CL" });
        p.on("pageerror", (e) => problemas.push(`${etiqueta}: JS ${e.message}`));
        p.on("console", (m) => { if (m.type() === "error" || /Content Security Policy/i.test(m.text())) problemas.push(`${etiqueta}: consola ${m.text().slice(0, 200)}`); });
        await p.goto(URL_BASE + (l === "en" ? "?lang=en" : ""));
        await p.evaluate(() => document.querySelectorAll("details").forEach((x) => { x.open = true; }));
        await p.waitForTimeout(150);
        problemas.push(...await revisarPagina(p, l, etiqueta));
        if (destino) await p.screenshot({ path: path.join(destino, `pagina-${l}-${nombre}-${oscuro ? "oscuro" : "claro"}.png`), fullPage: true });
        await p.close();
      }
      console.log(problemas.length ? "✗ " + problemas.join("\n✗ ") : "✓ Página: sin errores, sin desborde a 390 px, todo traducido, JSON-LD igual a lo que se ve y contraste AA");
    }
    await navegador.close();
    s.close();
    process.exit(problemas.length ? 1 : 0);
  }
}
