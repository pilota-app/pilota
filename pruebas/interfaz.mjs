// La interfaz de Pilota en un navegador de verdad (Chromium con Playwright), servida con la misma CSP que la app y con los
// datos ficticios de ui/demo.json. Revisa: sin errores de JavaScript ni violaciones de la CSP; el primer uso parte por el idioma,
// solo en la pantalla; después, todo traducido al inglés (ningún texto sin traducir); la banda del modo, el estado de los datos,
// la descarga, el capital mínimo viable, los dos trabajos en segundo plano (los 3 años y el muestreo) de punta a punta, los
// indicadores por par y temporalidad con el contexto de BTC y el costo de ahora; las señales crudas de las tres estrategias con
// el filtro de BTC; el backtest de esas señales con su compuerta de casos, el empalme y la prueba de sensibilidad; el puntaje de
// cada oportunidad con sus siete notas, su probabilidad de ganar, su ganancia esperada y con qué modelo se puntúa; la
// calibración con su año apartado, sus ventanas, sus vueltas y la prueba final con su criterio revisión por revisión; el estado
// firmado de las dos cuentas con el registro que no se borra y el arranque frenado; el tamaño de cada operación; los frenos con
// el número que vigila cada uno, «Pausar» y el desbloqueo del piso; el motor con hace cuánto fue su última revisión y el resumen
// de lo que pasó mientras nadie miraba; la pantalla principal con su banda, el saldo con su línea del piso y su referencia en
// moneda local, los medidores de puntaje y exigencia por par, las posiciones con su protección, el historial con la orden de cada
// línea, el motor con su aviso, la cuenta atrás de las propuestas, la mascota y
// la línea diaria; Ajustes; y nada se sale a 390 px. Con CAPTURAS=<carpeta> guarda capturas para mirarlas a ojo (en GitHub quedan como artefacto).
//   PLAYWRIGHT=/ruta/a/node_modules/playwright node pruebas/interfaz.mjs
// La app: suma aquí lo propio (cada pantalla nueva, en español y en inglés).
import { createRequire } from "node:module";
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT || "playwright");
const UI = path.join(path.dirname(path.dirname(fileURLToPath(import.meta.url))), "ui");
const CAPTURAS = process.env.CAPTURAS || "";
const APP = "Pilota";

const CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'";
const TIPOS = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml" };
const servidor = http.createServer((q, r) => {
  const ruta = path.normalize(path.join(UI, decodeURIComponent(new URL(q.url, "http://x").pathname).replace(/^\/+/, "") || "index.html"));
  if (!ruta.startsWith(UI + path.sep) || !fs.existsSync(ruta) || fs.statSync(ruta).isDirectory()) { r.writeHead(404); return r.end(); }
  r.writeHead(200, { "Content-Type": TIPOS[path.extname(ruta)] || "application/octet-stream", "Content-Security-Policy": CSP });
  fs.createReadStream(ruta).pipe(r);
});
await new Promise((ok) => servidor.listen(0, "127.0.0.1", ok));
const BASE = `http://127.0.0.1:${servidor.address().port}/index.html`;

const navegador = await chromium.launch();
const errores = [];
async function abrir(consulta, ancho = 1280) {
  const page = await navegador.newPage({ viewport: { width: ancho, height: 800 } });
  page.on("pageerror", (e) => errores.push(`${consulta}: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") errores.push(`${consulta}: ${m.text()}`); });
  await page.addInitScript(() => document.addEventListener("securitypolicyviolation", (e) => console.error(`CSP: ${e.violatedDirective}`)));
  await page.goto(BASE + consulta);
  return page;
}
const capturar = async (page, nombre) => { if (CAPTURAS) { await page.waitForTimeout(400); fs.mkdirSync(CAPTURAS, { recursive: true }); await page.screenshot({ path: path.join(CAPTURAS, `${nombre}.png`) }); } };
// Un trabajo en segundo plano avanza solo: lo que se ve en medio (el botón «Detener», la etapa) dura lo que dura esa etapa. Se
// anota cada vez que la app pinta, así revisarlo no depende de mirar justo en ese momento (en un computador cargado no se alcanza).
const anotarAvance = (page, donde) => page.evaluate((d) => {
  window.__avance = [];
  const mirar = () => window.__avance.push({ linea: document.querySelector(`${d} .trabajo-linea`)?.textContent || "",
    detener: !!document.querySelector(`${d} [id$="-detener"], ${d} [id$="-apagar"]`) });
  mirar();
  new MutationObserver(mirar).observe(document.body, { childList: true, subtree: true, characterData: true });
}, donde);
const faltantes = (page) => page.evaluate((app) => [...window[app]._pruebas.faltantes], APP);
const sinDesborde = async (page, donde) => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${donde}: se sale a lo ancho`);

// 1. Primer uso: el idioma va primero y solo (nada de la app detrás).
let page = await abrir("?bienvenida");
await page.waitForSelector(".opciones-idioma");
assert.equal(await page.locator(".barra").count(), 0, "detrás del idioma no se pinta la app");
await capturar(page, "1-idioma");
await page.click('[data-bv-idioma="en"]');
await page.waitForSelector(".pieza-bv:not(.pieza-bv-idioma)");
await capturar(page, "2-bienvenida-en");
for (let i = 0; i < 10 && await page.locator(".pieza-bv [data-bv-ir].pz-principal").count(); i++) {
  await page.click(".pieza-bv [data-bv-ir].pz-principal");
}
await page.click(".pieza-bv [data-bv-fin]:not([data-bv-fin=despues])");
await page.waitForSelector("#descargar");

// 2. Los datos del mercado, de punta a punta (en la vista previa responde simular(), como lo haría la app).
assert.match(await page.textContent(".banda"), /Test mode: play money/, "la banda del modo tiene que estar siempre");
assert.match(await page.textContent("#datos-estado"), /I can't trade yet/, "si falta historial, se dice en vez de operar");
assert.match(await page.textContent("#datos-estado"), /BTCFDUSD 4 h: 12 candles missing/);
assert.equal(await page.locator("#datos-series .serie").count(), 12, "el estado va por par y temporalidad (4 × 3)");
await capturar(page, "3-datos-en");
await page.click("#descargar");
await page.waitForSelector("#datos-estado.listo");
assert.match(await page.textContent("#datos-estado"), /History complete and continuous/);
assert.equal(await page.locator('#datos-series .serie-estado[data-estado="listo"]').count(), 12);
await capturar(page, "4-datos-listos-en");
// 3. El capital mínimo viable: hasta calcularlo con los mínimos de Binance, se dice que falta.
assert.match(await page.textContent("#minimo"), /haven't worked it out yet/, "sin cálculo se dice, no se inventa un monto");
await page.click("#calcular-minimo");
await page.waitForSelector(".minimo-monto");
assert.match(await page.textContent(".minimo-monto"), /20 USDT/, "el capital mínimo viable, en USDT");
assert.match(await page.textContent(".minimo-cabe"), /200 USDT of test mode is enough/);
assert.equal(await page.locator('[aria-label="Minimum by pair"] .serie').count(), 2, "el mínimo va por par operado");
assert.match(await page.textContent("#minimo"), /Assumed fees/, "una cuenta con costos supuestos se dice");
await capturar(page, "5-minimo-en");
// 4. Los dos trabajos en segundo plano: el porcentaje, el tiempo que falta, «Detener» y «Seguir donde quedó».
assert.match(await page.textContent("#historial"), /Not downloaded yet/, "antes de empezar se dice cuánto va a tardar");
assert.equal(await page.locator("#historial .tramo").count(), 3, "el avance va por etapa (1 d, 4 h, 1 h)");
await anotarAvance(page, "#historial");
await page.click("#historial-bajar");
await page.waitForSelector('#historial progress[value="100"]');
const avance = await page.evaluate(() => window.__avance);
assert.ok(avance.some((a) => a.detener), "mientras baja, siempre se puede detener");
assert.ok(avance.some((a) => /Stage 2 of 3/.test(a.linea)), "mientras baja se dice la etapa y el tiempo que falta");
assert.match(await page.textContent("#historial .trabajo-linea"), /candles saved out of the three years/);
assert.equal(await page.locator('#historial .serie-estado[data-estado="listo"]').count(), 3);
await capturar(page, "6-historial-en");
// Un hoyo en medio no es «al día» aunque la ventana esté recorrida: la continuidad se revisa al terminar cada par
// (bin/historial.py) y lo que Binance no entregó se dice y se vuelve a pedir.
await page.evaluate(() => window.Pilota._probar((E) => {
  window.__continuo = E.historial;
  E.historial = { ...E.historial, huecos: 2, continuo: false,
    etapas: E.historial.etapas.map((e, i) => (i ? e : { ...e, huecos: 2 })) };
}));
assert.match(await page.textContent("#historial .trabajo-linea"), /2 gaps are left/, "los hoyos se dicen, no se tapan");
assert.match(await page.textContent("#historial-bajar"), /Fill in the gaps/, "y se pueden rellenar");
assert.equal(await page.locator('#historial .serie-estado[data-estado="incompleto"]').count(), 1);
await page.evaluate(() => window.Pilota._probar((E) => { E.historial = window.__continuo; }));
assert.equal(await page.locator('#historial .serie-estado[data-estado="listo"]').count(), 3);
assert.match(await page.textContent("#muestreo"), /can't be recovered later/, "el muestreo se explica antes de encenderlo");
await page.click("#muestreo-encender");
await page.waitForSelector('#muestreo progress[value="100"]');
assert.match(await page.textContent("#muestreo"), /4 samples saved since February 2026/);
assert.equal(await page.locator('[aria-label="1 m candles by pair"] .tramo').count(), 2, "las velas de 1 m van por par operado");
assert.match(await page.textContent("#muestreo"), /bid 95,010.2 · ask 95,010.5/, "la última muestra del libro");
assert.match(await page.textContent("#muestreo"), /Latest round: Feb 1\d, 2026/, "cuándo fue la última vuelta");
await page.click("#muestreo-apagar");
await page.waitForFunction(() => /isn't saving samples/.test(document.querySelector("#muestreo .trabajo-linea")?.textContent || ""));
await capturar(page, "7-muestreo-en");
// 5. Los indicadores de las siete familias: el valor de ahora de cada serie, o qué historial le falta.
const SERIES_IND = '[aria-label="Indicators by pair and timeframe"]';
assert.equal(await page.locator(`${SERIES_IND} .serie`).count(), 12, "los indicadores van por par y temporalidad (4 × 3)");
assert.match(await page.textContent("#indicadores"), /9 of 12 series with up-to-date indicators/);
assert.match(await page.textContent("#indicadores"), /averages 94,870.5 \/ 94,210.25 \/ 92,440.8/, "las tres medias");
assert.match(await page.textContent("#indicadores"), /strength 24.6 · RSI 56.3 · MACD 180.42/, "ADX, RSI y MACD");
assert.match(await page.textContent("#indicadores"), /band 94,420.2 to 95,320.8 · moves 210.4 per candle · volume 1.3 times normal/,
  "Bollinger, ATR y volumen relativo");
assert.match(await page.textContent("#indicadores"), /broke the ceiling of the last 20 candles: 94,830/, "el máximo roto");
assert.match(await page.textContent("#indicadores"), /between the 94,180.5 floor and the 95,180 ceiling of the last 20 candles/);
assert.match(await page.textContent("#indicadores"), /BTCFDUSD 1 d: 310 candles missing/, "sin historial no se muestra número");
assert.match(await page.textContent("#indicadores"), /ETHUSDT 1 d: no candles yet/);
assert.equal(await page.locator(`${SERIES_IND} .serie-estado[data-estado="listo"]`).count(), 9);
// El contexto de BTC y el costo de ahora: las dos familias que no son de una serie sola.
assert.match(await page.textContent("#indicadores"), /closed at 94,820.4 \(1.15 % over the last day\) and is 15.4 % above its 200 day average/,
  "el contexto es BTC en 1 d, con sus dos parámetros");
assert.match(await page.textContent("#indicadores"), /Assumed fees/, "un costo con comisiones supuestas se dice");
assert.equal(await page.locator('[aria-label="Cost by traded pair"] .serie').count(), 2, "el costo va por par operado");
assert.match(await page.textContent("#indicadores"), /0.0003 % between bid and ask · getting in and out costs 0.15 %/);
await page.click("#indicadores-calcular");
await page.waitForSelector("#indicadores-calcular:not([disabled])");
await capturar(page, "8-indicadores-en");
// 6. Las tres estrategias y el filtro de BTC: cada señal cruda con su nivel de entrada, su stop y su objetivo.
const SERIES_SEN = '[aria-label="Signals by pair and timeframe"]';
assert.equal(await page.locator(`${SERIES_SEN} .serie`).count(), 4,
  "las señales van por par operado y temporalidad de entrada (2 × 2)");
assert.match(await page.textContent("#senales"), /Signals to get in right now: 2/);
assert.match(await page.textContent("#senales"), /BTC is doing fine \(1.15 % over the last day/,
  "el filtro de BTC se dice siempre, deje entrar o no");
assert.match(await page.textContent("#senales"),
  /Breakout with volume and the day heading up: buy with a limit order back at 94,830, stop at 93,869.7 and target at 96,252.45./);
assert.match(await page.textContent("#senales"), /risks 1.01 % to make 1.5 % · the limit order waits 3 candles/);
assert.match(await page.textContent("#senales"),
  /Bounce off the lower band with the market going nowhere: buy with a limit order at 3,182.2, stop at 3,173.78 and target at the average, 3,198.4./);
assert.match(await page.textContent("#senales"), /ETHUSDT 1 d: history is missing to tell whether the day is heading up/,
  "sin la serie de 1 d, la ruptura de ese par no se mira y se dice cuál falta");
assert.equal(await page.locator(`${SERIES_SEN} .serie-estado[data-estado="listo"]`).count(), 2,
  "las dos señales se pueden entrar: el filtro de BTC deja");
assert.match(await page.textContent("#senales"), /Staying in USDT is an option too/, "la tercera estrategia siempre está");
await page.click("#senales-calcular");
await page.waitForSelector("#senales-calcular:not([disabled])");
await capturar(page, "9-senales-en");
// 7. El backtest de señales crudas: antes de correrlo no se muestra ningún número, y después el reporte completo.
assert.match(await page.textContent("#backtest"), /I haven't walked through the history yet/);
assert.match(await page.textContent("#backtest"), /asks for 300 cases per bucket/, "la compuerta se explica antes");
assert.equal(await page.locator('[aria-label="Cases per bucket"]').count(), 0, "sin correrlo no hay casos que mostrar");
// El puntaje existe antes del backtest, pero la probabilidad de ganar sale de esas operaciones: hasta correrlo, no hay.
assert.match(await page.textContent("#puntaje"), /I can't say how likely it is to win yet/,
  "sin historial recorrido se dice, en vez de inventar una probabilidad");
await page.click("#backtest-correr");
await page.waitForSelector('[aria-label="Cases per bucket"]');
assert.match(await page.textContent("#backtest"), /1,102 operations out of 1,840 raw signals, over 1,094 days of history/);
assert.match(await page.textContent("#backtest"), /It's right 55 % of the time and leaves 0.12 % per operation after costs \(getting in and out takes 0.15 %\)/);
assert.match(await page.textContent("#backtest"), /Assumed gap between bid and ask \(0.05 %\)/, "el costo supuesto se dice");
assert.match(await page.textContent("#backtest"), /With 59 more days of your own samples/);
assert.match(await page.textContent('[aria-label="Comparison"]'), /return 274 % · largest drop 18.6 % · 1,102 operations/);
assert.match(await page.textContent('[aria-label="Comparison"]'), /Staying in USDT.*return 0 % · largest drop 0 % · 0 operations/s,
  "el reporte compara siempre con no hacer nada");
assert.match(await page.textContent('[aria-label="Comparison"]'), /Buying BTC and waiting.*return 186 % · largest drop 34.2 %/s);
assert.match(await page.textContent("#backtest"), /Plan B: there weren't enough by pair either/, "el plan B no se tapa");
assert.match(await page.textContent("#backtest"), /Not validated/, "y se dice lo que eso obliga a la calibración");
assert.equal(await page.locator('[aria-label="Cases per bucket"] .tramo').count(), 2, "un tramo por estrategia (plan B)");
assert.match(await page.textContent('[aria-label="Cases per bucket"]'), /Bounce\s*all together\s*412 cases/);
assert.equal(await page.locator('[aria-label="Backtest by pair and timeframe"] .serie').count(), 4,
  "el backtest va por par operado y temporalidad de entrada (2 × 2)");
assert.match(await page.textContent('[aria-label="Backtest by pair and timeframe"]'),
  /612 signals · 380 filled · right 56 % of the time · leaves 0.13 % per operation/);
assert.match(await page.textContent('[aria-label="Backtest by pair and timeframe"]'),
  /9,421 candles borrowed from the pair against USDT \(with FDUSD costs\)/, "el empalme se marca siempre");
assert.match(await page.textContent('[aria-label="Sensitivity test"]'),
  /if touching the level were enough\s*1,612 of 1,840 signals fill/, "la prueba de sensibilidad, entera");
assert.match(await page.textContent("#backtest"), /46 candles hit the stop and the target at once/);
assert.match(await page.textContent("#backtest"), /the assumption was right 67 % of the time/,
  "el supuesto conservador queda marcado y validado con las velas de 1 m");
assert.match(await page.textContent("#backtest"), /It isn't a promise of profit/);
// Un tramo que no llega a los casos que pide la compuerta lo dice, y no se tapa con los que sí llegan.
await page.evaluate(() => window.Pilota._probar((E) => {
  E.backtest = { ...E.backtest, compuerta: { ...E.backtest.compuerta, plan: "normal", plan_b: false,
    tramos: [{ estrategia: "ruptura", par: "BTCFDUSD", temporalidad: "4h", operaciones: 240, casos: 212, faltan: 88, alcanza: false }] } };
}));
assert.match(await page.textContent('[aria-label="Cases per bucket"]'), /Breakout\s*BTCFDUSD · 4 h\s*212 cases\s*88 short of the 300 the gate asks for/);
assert.match(await page.textContent("#backtest"), /The gate passes/);
await capturar(page, "10-backtest-en");
// 8. El puntaje de cada oportunidad: las siete notas, la probabilidad de ganar y la ganancia esperada con su rango.
await page.waitForFunction(() => /It wins/.test(document.querySelector("#puntaje")?.textContent || ""));
assert.match(await page.textContent("#puntaje"), /What scores highest right now: Breakout on BTCFDUSD · 4 h, 84 out of 100/);
assert.match(await page.textContent("#puntaje"), /Staying in USDT scores 50 out of 100/,
  "quedarse en USDT es la vara con la que se comparan las demás");
assert.match(await page.textContent("#puntaje"),
  /The score is uncalibrated: the seven families weigh the same and, until it is calibrated with the history, the demand to get in is 85 out of 100/,
  "sin calibración se dice el estado del modelo y con qué exigencia se mira el puntaje");
assert.equal(await page.locator('[aria-label="Scored opportunities"] .serie').count(), 2, "una fila por oportunidad");
assert.match(await page.textContent('[aria-label="Scored opportunities"]'),
  /It wins 56 % of the time \(between 51 % and 61 %, with 355 cases from the history\)/);
assert.match(await page.textContent('[aria-label="Scored opportunities"]'),
  /Expected profit after costs: 0.25 % \(between 0.11 % and 0.38 %\)/);
assert.match(await page.textContent('[aria-label="Scored opportunities"]'),
  /If it reaches the target it leaves 1.4 % and if it goes to the stop it costs 1.21 %/);
assert.match(await page.textContent("#puntaje"), /The probability comes from a widened bucket \(plan B\)/,
  "el plan B del backtest llega hasta el puntaje");
assert.equal(await page.locator('[aria-label="Marks by family"]').count(), 2, "las siete notas van por oportunidad");
assert.match(await page.textContent('[aria-label="Marks by family"]'), /Trend\s*83 out of 100/);
assert.match(await page.textContent('[aria-label="Marks by family"]'), /Cost\s*80 out of 100/);
assert.match(await page.textContent('[aria-label="Scored opportunities"]'), /49 out of 100/,
  "y el rebote puntúa menos que quedarse quieto: 49 contra 50");
assert.match(await page.textContent("#puntaje"), /Of the 3 that have 1 m candles \(30 days are kept\), the assumption was right 67 %/,
  "el supuesto de las velas sin 1 m queda marcado con cuánto acertó");
assert.match(await page.textContent("#puntaje"), /A score isn't an order or a promise/);
await page.click("#puntaje-calcular");
await page.waitForSelector("#puntaje-calcular:not([disabled])");
await capturar(page, "11-puntaje-en");
// 9. La calibración del puntaje: antes de calibrar no hay ningún peso ni ningún número, y después está entero el camino
// —el tramo apartado, las ventanas, las vueltas que se dieron, la prueba final de una sola vez y su criterio—.
assert.match(await page.textContent("#calibracion"), /I haven't calibrated the score yet/);
assert.match(await page.textContent("#calibracion"),
  /the seven families weigh the same, the demand to get in is 85 out of 100 and the amount per position stays capped at 15 USDT/,
  "sin calibrar, la exigencia es la alta y el monto queda topado");
assert.match(await page.textContent("#calibracion"),
  /I set aside the last 365 days before looking at a single weight, fit with windows of 12 months and test with the 3 that follow, over at most 3 rounds/);
assert.equal(await page.locator('[aria-label="Approval criterion"]').count(), 0, "sin calibrar no hay criterio que revisar");
await page.click("#calibracion-correr");
await page.waitForSelector('[aria-label="Approval criterion"]');
assert.match(await page.textContent("#calibracion"),
  /Model not validated: the demand stays at 85 out of 100 and the amount per position, capped at 15 USDT/);
assert.match(await page.textContent("#calibracion"),
  /The backtest gate had to widen its buckets: with plan B the model doesn't end up validated/,
  "el plan B de la compuerta manda sobre lo que diga la prueba final");
assert.match(await page.textContent("#calibracion"),
  /I set aside 365 days \(.+\) before moving a weight: nobody looked at them until the final test/);
assert.match(await page.textContent("#calibracion"),
  /4 windows before that stretch: 12 months to fit the weights and the 3 that follow to test them, with 498 fitting cases/);
assert.match(await page.textContent("#calibracion"),
  /2 of 3: a weight only moves if it really improves things, and the winning round is chosen by the testing windows/);
assert.equal(await page.locator('[aria-label="Calibration rounds"] .tramo').count(), 2, "una fila por vuelta");
assert.match(await page.textContent('[aria-label="Calibration rounds"]'),
  /Round 1\s*Tested\s*demand 65 · over the testing windows it leaves 0\.26 % per operation with 96 cases\s*moved the weight of Trend, Volatility, Cost/);
assert.match(await page.textContent('[aria-label="Calibration rounds"]'), /Round 2\s*This is the one/,
  "la vuelta con la que quedó se dice cuál fue");
assert.match(await page.textContent('[aria-label="Weights by family"]'), /Trend\s*weighs 2/);
assert.match(await page.textContent('[aria-label="Weights by family"]'), /Volatility\s*weighs 0\.5/);
assert.match(await page.textContent("#calibracion"),
  /Only once, with the set-aside stretch \(.+\) and the criterion written before running it: 186 operations above the demand of 70/);
assert.match(await page.textContent('[aria-label="Final test comparison"]'),
  /The score with its demand\s*return 46 % · largest drop 11\.2 % · 186 operations/);
assert.match(await page.textContent('[aria-label="Final test comparison"]'),
  /Staying in USDT\s*return 0 % · largest drop 0 % · 0 operations/, "la vara es quedarse en USDT");
assert.match(await page.textContent('[aria-label="Final test comparison"]'),
  /Buying BTC and waiting\s*return 21 % · largest drop 28\.7 %/, "y comprar BTC y esperar se compara igual");
assert.equal(await page.locator('[aria-label="Approval criterion"] .tramo').count(), 6, "el criterio se revisa entero");
assert.match(await page.textContent('[aria-label="Approval criterion"]'),
  /Non-overlapping cases\s*Passes\s*151 of the 30 it asks for/);
assert.match(await page.textContent('[aria-label="Approval criterion"]'),
  /The gate passed without plan B\s*Doesn't pass\s*plan B: a single bucket per strategy/,
  "también se ve la revisión que no pasó, con lo que tenía");
assert.match(await page.textContent("#calibracion"),
  /Before the set-aside stretch: 528 operations out of 604 signals that reached the demand, right 56 % of the time and leaving 0\.28 % per operation/);
// Con la calibración hecha cambia con qué pesos y con qué exigencia se mira el puntaje: la pantalla lo dice ahí también.
await page.waitForFunction(() => /calibrated but not validated/.test(document.querySelector("#puntaje")?.textContent || ""));
await capturar(page, "12-calibracion-en");
// 10. El registro que no se borra y el estado firmado: las dos cuentas por separado, los campos fijos de cada línea,
// el reinicio del saldo de prueba (una confirmación y al tiro) y el arranque frenado cuando el archivo no es de fiar.
assert.match(await page.textContent("#estado"),
  /State up to date and with its fingerprint: 212\.4 USDT in the test account, in Manual mode/);
assert.match(await page.textContent("#estado"),
  /Reference capital 214\.8 USDT: the highest balance you've reached/, "el capital de referencia, siempre a la vista");
assert.equal(await page.locator('[aria-label="The two accounts"] .tramo').count(), 2, "siempre se ven las dos cuentas");
assert.match(await page.textContent('[aria-label="The two accounts"]'), /Live mode: real money\s*No state yet/,
  "la cuenta real todavía no existe, y se dice");
assert.match(await page.textContent("#estado"), /7 lines since .+, 9 days/);
assert.match(await page.textContent("#estado"),
  /date, pair, score, reason, order and result— and none is changed afterwards/, "los campos fijos, dichos");
assert.match(await page.textContent('[aria-label="Latest lines of the log"]'),
  /BTCFDUSD\s*score 84 out of 100 · order for 60 USDT · stop at 93,869\.7/, "una línea con su orden");
assert.match(await page.textContent('[aria-label="Latest lines of the log"]'),
  /It closed at the target\s*BTCFDUSD\s*score 84 out of 100 · closed by the target · left 0\.52 USDT/);
assert.match(await page.textContent('[aria-label="Latest lines of the log"]'),
  /I started braked in manual mode\s*reason: the fingerprint doesn't match/, "un arranque frenado queda en el registro");
await page.click("#estado-reiniciar");
await page.waitForSelector("[role=alertdialog]");
assert.match(await page.textContent("[role=alertdialog]"), /The play-money balance goes back to 200 USDT/,
  "reiniciar el saldo de prueba pide una confirmación");
await page.click('[data-pz-confirmar="si"]');
await page.waitForFunction(() => /200 USDT in the test account/.test(document.querySelector("#estado")?.textContent || ""));
assert.match(await page.textContent('[aria-label="Latest lines of the log"]'), /You reset the test balance/,
  "y el reinicio queda en el registro");
// Si el archivo de estado falta, su huella no cuadra o su fecha es futura, se arranca frenado en manual y se dice.
await page.evaluate(() => window.Pilota._probar((E) => {
  window.__estado = E.estado;
  E.estado = { ...E.estado, frenado: true, motivo: "huella_no_cuadra",
    cuentas: E.estado.cuentas.map((c) => (c.ambiente !== "prueba" ? c : { ...c, frenado: true, modo: "manual",
      motivo: "huella_no_cuadra", leido: { saldo: 99999, referencia: 99999, modo: "automatico", posiciones: 1 },
      arranque: { ...c.arranque, frenado: true, nuevo: false, motivo: "huella_no_cuadra" } })) };
}));
assert.match(await page.textContent("#estado"),
  /The state file's fingerprint doesn't match what it says inside: I started braked in manual mode/);
assert.match(await page.textContent("#estado"), /I'm not going to open anything: in manual mode I propose and you decide/);
assert.match(await page.textContent('[aria-label="The two accounts"]'),
  /Braked in manual\s*I don't trust its numbers: the file said balance 99,999 USDT/,
  "con la huella mala no se cree ningún número: se muestra marcado");
await capturar(page, "13-estado-en");
await page.evaluate(() => window.Pilota._probar((E) => { E.estado = window.__estado; }));
// 11. El tamaño de la operación: el orden fijo (los mínimos de Binance, la reserva del 40 %, las dos posiciones y el
// 2 % de riesgo), el monto en USDT de cada oportunidad y el tope mientras el modelo no esté validado.
assert.match(await page.textContent("#tamano"),
  /With 200 USDT of capital I put up to 60 USDT per position and risk at most 4 USDT on each operation/);
assert.equal(await page.locator('[aria-label="The order the size follows"] .tramo').count(), 5, "el orden fijo, entero");
assert.match(await page.textContent('[aria-label="The order the size follows"]'),
  /Binance's minimums\s*Up to date\s*the quantity has to work for the buy and for both legs of the protection: from 20 USDT of capital/);
assert.match(await page.textContent('[aria-label="The order the size follows"]'),
  /The USDT reserve\s*40 %\s*80 USDT always stays in USDT and 120 USDT is left to trade with/);
assert.match(await page.textContent('[aria-label="The order the size follows"]'),
  /Positions at a time\s*0 of 2\s*60 USDT per position/);
assert.match(await page.textContent('[aria-label="The order the size follows"]'),
  /The maximum risk\s*2 %\s*no more than 4 USDT per operation, counting what getting out at the stop costs/);
assert.match(await page.textContent('[aria-label="The order the size follows"]'),
  /The cap while the model isn't validated\s*15 USDT/, "sin modelo validado, el monto por posición queda topado");
assert.equal(await page.locator('[aria-label="Size by opportunity"] .serie').count(), 2, "un monto por oportunidad");
assert.match(await page.textContent('[aria-label="Size by opportunity"]'),
  /I'd buy 0\.00015 BTC at 94,830 with a stop at 93,869\.7: 14\.25 USDT including costs/);
assert.match(await page.textContent('[aria-label="Size by opportunity"]'),
  /If the stop is crossed I lose 0\.17 USDT, 0\.08 % of the capital/, "lo que se arriesga, con los costos adentro");
assert.match(await page.textContent('[aria-label="Size by opportunity"]'),
  /What cuts it is the cap of 15 USDT per position: the model isn't validated yet/);
assert.match(await page.textContent("#tamano"),
  /The highest scoring one that has an amount: Breakout on BTCFDUSD · 4 h, 14\.25 USDT with a stop at 93,869\.7/);
assert.match(await page.textContent("#tamano"), /An amount isn't an order/);
// Si con ese stop el monto queda bajo el mínimo de Binance no hay orden, y se dice cuánto haría falta.
await page.evaluate(() => window.Pilota._probar((E) => {
  window.__tamano = E.tamano;
  const o = E.tamano.oportunidades[0];
  E.tamano = { ...E.tamano, oportunidades: [{ ...o, puede: false, motivo: "bajo_minimo",
    tamano: { ...o.tamano, puede: false, motivo: "bajo_minimo", cantidad: 0, monto: 0 } }, E.tamano.oportunidades[1]] };
}));
assert.match(await page.textContent('[aria-label="Size by opportunity"]'),
  /No amount\s*Breakout\s*It comes out under Binance's minimum: with this stop the smallest position is 5\.7 USDT and opening it would need 19 USDT of capital/);
await capturar(page, "14-tamano-en");
await page.evaluate(() => window.Pilota._probar((E) => { E.tamano = window.__tamano; }));
// 12. Los frenos: los seis con el número que vigilan, los dos del mercado que en prueba solo avisan, «Pausar» sin tocar
// ninguna protección automática y el piso con su desbloqueo.
assert.match(await page.textContent("#frenos"), /Right now: Trading, in Manual mode/);
assert.match(await page.textContent("#frenos"), /I can open up to 2 more positions/);
assert.equal(await page.locator('[aria-label="The brakes"] .tramo').count(), 6, "los seis frenos, siempre los seis");
assert.match(await page.textContent('[aria-label="The brakes"]'),
  /The absolute floor\s*Passes\s*It brakes if the balance drops below 130 USDT: 35 % below what you paid in \(200 USDT\)/);
assert.match(await page.textContent('[aria-label="The brakes"]'),
  /The reference capital floor\s*Passes\s*It brakes if the balance drops below 161\.1 USDT: 25 % below the reference capital \(214\.8 USDT\)/);
assert.match(await page.textContent('[aria-label="The brakes"]'),
  /The daily brake\s*Passes\s*Today I started with 211\.88 USDT and I'm at 212\.4 USDT: it brakes on losing 5 % of the day/);
assert.match(await page.textContent('[aria-label="The brakes"]'),
  /The losing streak\s*Passes\s*0 losses in a row: at 4 I go back to manual/);
assert.match(await page.textContent('[aria-label="The brakes"]'),
  /The maker fee\s*Doesn't run in test mode/, "los dos del mercado no corren en prueba");
assert.match(await page.textContent('[aria-label="The brakes"]'),
  /In test mode it doesn't brake: there's no real money to look after/);
assert.match(await page.textContent('[aria-label="The brakes that are always on"]'),
  /No leverage\s*1x\s*Pilota only buys spot/);
await page.click("#frenos-pausar");
await page.waitForFunction(() => /Right now: Paused/.test(document.querySelector("#frenos")?.textContent || ""));
assert.match(await page.textContent("#frenos"),
  /You still have 0 protected positions: pausing cancels entries and doesn't touch any automatic protection/);
await capturar(page, "15-frenos-en");
await page.click("#frenos-pausar");
await page.waitForFunction(() => /Right now: Trading/.test(document.querySelector("#frenos")?.textContent || ""));
// Con el piso tocado no se abre nada, lo abierto se queda con su protección y aparece el desbloqueo.
await page.evaluate(() => window.Pilota._probar((E) => {
  window.__frenos = E.frenos;
  const c = E.frenos.cuentas.find((x) => x.ambiente === E.frenos.activo);
  const frenos = c.frenos.map((f) => (f.codigo !== "piso" ? f : { ...f, activo: true, pasado: true, valor: 150 }));
  E.frenos = { ...E.frenos, estado: "frenado", frenado: true, modo: "manual", motivo: "piso",
    entradas: { puede: false, motivo: "piso", quedan: 2 }, protegidas: 1,
    cuentas: E.frenos.cuentas.map((x) => (x !== c ? x : { ...x, estado: "frenado", frenado: true, frenos,
      activos: ["piso"], bloquean: ["piso"], entradas: { puede: false, motivo: "piso", quedan: 2 },
      desbloqueo: { ...x.desbloqueo, puede: true, listo: true, motivo: "" } })) };
}));
assert.match(await page.textContent("#frenos"), /Right now: Braked, in Manual mode/);
assert.match(await page.textContent("#frenos"), /The balance hit the reference capital floor: I'm not opening anything/);
assert.match(await page.textContent('[aria-label="The brakes"]'),
  /The reference capital floor\s*Braked\s*The balance \(150 USDT\) hit the floor \(161\.1 USDT\): I'm not opening anything\. What's open keeps its automatic protection/);
await page.click("#frenos-desbloquear");
await page.waitForSelector("[role=alertdialog]");
assert.match(await page.textContent("[role=alertdialog]"),
  /The reference capital becomes your balance right now/, "desbloquear el piso pide una confirmación");
await page.click('[data-pz-confirmar="no"]');
await page.evaluate(() => window.Pilota._probar((E) => { E.frenos = window.__frenos; }));
// 13. La pantalla principal: la banda, el saldo con su línea del piso y su referencia en moneda local, los medidores de
// puntaje y exigencia por par, las posiciones, las propuestas con su cuenta atrás, el motor, el registro y la mascota.
assert.match(await page.textContent(".banda"), /Test mode: play money/, "la banda, arriba de todo y siempre");
assert.match(await page.textContent("#panel .saldo-monto"), /212\.4 USDT/, "el saldo en USDT, primero");
assert.match(await page.textContent("#panel .saldo"),
  /The floor line is at 161\.1 USDT: 25 % below your reference capital \(214\.8 USDT\)/);
assert.match(await page.textContent("#panel .saldo"), /Today I started with 211\.88 USDT and the day closes if I lose 5 %/);
assert.match(await page.textContent("#panel .saldo-local"), /Tell me in Settings what one USDT is worth/,
  "sin tasa no se muestra ninguna equivalencia");
assert.match(await page.textContent("#panel .mascota-texto"), /I closed BTCFDUSD at the target: it left 0\.52 USDT/,
  "la mascota cuenta la última decisión, sin celebrarla");
assert.match(await page.textContent("#panel .mascota-animo"), /Closing/);
assert.match(await page.textContent("#panel .mascota-dia"), /Today I opened 1 and closed 1/, "la línea del día");
assert.equal(await page.locator('[aria-label="Score and threshold by pair"] .medidor').count(), 2,
  "un medidor por par operado, siempre los dos");
assert.match(await page.textContent('[aria-label="Score and threshold by pair"]'),
  /BTCFDUSD\s*84 out of 100 · threshold 85/, "el puntaje contra la exigencia");
assert.match(await page.textContent('[aria-label="Score and threshold by pair"]'),
  /It doesn't reach the threshold \(85\): I'm staying in USDT/);
assert.match(await page.textContent('[aria-label="Score and threshold by pair"]'), /Below the threshold/,
  "cada medidor dice con palabras si está sobre o bajo la exigencia");
assert.equal(await page.locator('[aria-label="Score and threshold by pair"] .medidor-barra').first().getAttribute("aria-label"),
  "BTCFDUSD: score 84 out of 100, threshold 85", "la barra es un dibujo: quien no la ve oye los dos números");
// La ayuda corta de cada término, al lado de lo que explica: con qué dinero se juega, el piso y el puntaje contra la exigencia.
assert.match(await page.textContent("#panel"), /Test mode: play money with real prices/, "la banda, explicada en dos frases");
assert.match(await page.textContent("#panel .saldo"),
  /Floor: the balance at which I stop opening anything, 25 % below your reference capital/, "la ayuda del piso");
assert.match(await page.textContent("#panel"), /Threshold: the minimum score to get in \(85 out of 100\), the mark on the bar/,
  "la ayuda del puntaje y de la exigencia");
// Las posiciones: cuántas hay de las que caben, qué pidió cada una y hasta cuándo espera la que no se ha llenado.
assert.match(await page.textContent("#panel"),
  /I have 0 open and 1 waiting, out of 2 that fit at a time: 0 with their automatic protection/,
  "cuántas posiciones hay y cuántas caben");
assert.match(await page.textContent('[aria-label="My positions"]'),
  /Buy waiting at 94,830 for 14\.25 USDT: until it fills, nothing is open/);
assert.match(await page.textContent('[aria-label="My positions"]'), /Stop at 93,869\.7 and target at 96,252\.45/);
assert.match(await page.textContent('[aria-label="My positions"]'),
  /It expires on .+: if the price doesn't reach that level, I cancel it and nothing stays open/,
  "una compra puesta no es una posición abierta, y se dice hasta cuándo espera");
assert.match(await page.textContent('[aria-label="Proposals waiting for your answer"]'),
  /It expires in \d:\d\d: if you don't answer, I let it go/, "la propuesta espera con su cuenta atrás");
assert.match(await page.textContent("#panel"), /2 proposals expired today: one nobody answers always expires/,
  "las propuestas vencidas se cuentan también cuando hay una esperando");
assert.match(await page.textContent("#panel .panel-motor"), /Engine off/);
assert.match(await page.textContent("#panel .panel-motor"), /Last check 9 h ago; I check every 5 min/);
assert.match(await page.textContent("#panel .panel-motor"), /Pilota only works with the computer on/,
  "el aviso del equipo encendido, siempre a la vista");
// El registro: cada línea con sus campos de siempre, incluida la orden que se pidió y cómo terminó.
assert.match(await page.textContent('[aria-label="The last thing I did"]'), /It closed at the target/);
assert.match(await page.textContent('[aria-label="The last thing I did"]'),
  /score 84 out of 100 · bought with a limit at 94,830 · order for 60 USDT · stop at 93,869\.7/,
  "la orden que se pidió, en palabras");
assert.match(await page.textContent('[aria-label="The last thing I did"]'),
  /closed by the target · left 0\.52 USDT · balance 212\.4 USDT/, "y cómo terminó");
assert.match(await page.textContent('[aria-label="The last thing I did"]'), /waited 15 min/,
  "una propuesta vencida también deja su línea");
await capturar(page, "16-panel-en");
// Una posición abierta y protegida, con lo que lleva ganado, y el motor mirando con el resumen de lo que se perdió.
await page.evaluate(() => window.Pilota._probar((E) => {
  window.__panel = E.panel;
  E.panel = { ...E.panel,
    posiciones: [{ ...E.panel.posiciones[0], estado: "abierta", protegida: true, valor: 14.67,
      ganancia: 0.42, ganancia_relativa: 0.0295 }],
    motor: { ...E.panel.motor, corriendo: true, activo: true, hace_min: 2,
      resumen: { hasta_ms: 1770732300000, dormido: true, dormido_ms: 32400000, stops: 1, vencidas: 2 } } };
}));
assert.match(await page.textContent('[aria-label="My positions"]'), /It's at 0\.42 USDT \(2\.95 %\)/,
  "lo que lleva ganado una posición abierta");
assert.match(await page.textContent('[aria-label="My positions"]'),
  /Protected: its automatic protection is in place/);
assert.equal(await page.locator('[aria-label="My positions"] .serie-estado[data-estado="listo"]').count(), 1,
  "una abierta y protegida se lee distinto de una sin protección");
assert.match(await page.textContent("#panel .panel-motor"), /Engine watching/);
assert.match(await page.textContent("#panel .panel-motor"), /You slept 9 h: 1 stop, 2 expired proposals/,
  "qué pasó mientras nadie miraba");
await page.evaluate(() => window.Pilota._probar((E) => { E.panel = window.__panel; }));
// La cuenta atrás corre sola: un segundo después queda menos tiempo, y la propuesta sigue esperando.
const antesCuenta = await page.textContent("#panel .cuenta");
await page.waitForFunction((t) => (document.querySelector("#panel .cuenta")?.textContent || "") !== t, antesCuenta,
  { timeout: 4000 });
// Si hoy no se operó, la línea diaria dice el mejor puntaje del día contra la exigencia.
await page.evaluate(() => window.Pilota._probar((E) => {
  window.__panel = E.panel;
  E.panel = { ...E.panel, dia: { ...E.panel.dia, opero: false, mejor_puntaje: 62, exigencia: 72 },
    mascota: { animo: "atento", cuento: "bajo_exigencia", datos: { par: "BTCFDUSD", puntaje: 62, exigencia: 72 } } };
}));
assert.match(await page.textContent("#panel .mascota-dia"), /I didn't trade today: best score 62, threshold 72/);
assert.match(await page.textContent("#panel .mascota-animo"), /Watching/);
// Los cinco ánimos, cada uno con su carita y la plantilla de lo que cuenta, armada con datos de verdad.
assert.equal(await page.locator("#panel .mascota").getAttribute("data-animo"), "atento");
assert.match(await page.textContent("#panel .mascota-texto"),
  /I'm watching: the best right now is BTCFDUSD with a score of 62 and the threshold is 72, so I'm staying in USDT/);
// Una propuesta esperando: la mascota duda, dice el monto y el stop, y por qué pregunta en vez de operar sola.
await page.evaluate(() => window.Pilota._probar((E) => {
  E.panel = { ...E.panel, dia: { ...E.panel.dia, opero: false, mejor_puntaje: 86, exigencia: 85, vencidas: 2 },
    mascota: { animo: "dudando", cuento: "esperando",
      datos: { n: 1, par: "BTCFDUSD", puntaje: 86, queda_min: 12, monto: 14.25, stop: 93869.7, motivo: "no_claro" } } };
}));
assert.equal(await page.locator("#panel .mascota").getAttribute("data-animo"), "dudando");
assert.match(await page.textContent("#panel .mascota-texto"),
  /I proposed BTCFDUSD to you with a score of 86: I buy 14\.25 USDT with a stop at 93,869\.7\. You have 12 min left to tell me/);
assert.match(await page.textContent("#panel .mascota-porque"),
  /The score is enough to enter, but it isn't clearly high/, "y por qué pregunta, en su propia frase");
assert.match(await page.textContent("#panel .mascota-dia"), /I let 2 proposals go without an answer/,
  "las propuestas que vencieron sin respuesta también son del día");
// Las dos posiciones que caben, abiertas: está operando y no abre nada más hasta que cierre una.
await page.evaluate(() => window.Pilota._probar((E) => {
  E.panel = { ...E.panel, mascota: { animo: "operando", cuento: "llenas",
    datos: { n: 2, maximas: 2, quedan: 0, par: "BTCFDUSD", ganancia: 0.42 } } };
}));
assert.equal(await page.locator("#panel .mascota").getAttribute("data-animo"), "operando");
assert.match(await page.textContent("#panel .mascota-texto"),
  /I have all 2 positions that fit open, and the one on BTCFDUSD is at 0\.42 USDT: until one closes, I open nothing else/);
// Lo que pasa la exigencia y no deja ningún monto se cuenta con su motivo: nunca se calla.
await page.evaluate(() => window.Pilota._probar((E) => {
  E.panel = { ...E.panel, mascota: { animo: "atento", cuento: "rechazada",
    datos: { par: "ETHFDUSD", puntaje: 91, exigencia: 85, motivo: "sin_disponible", n: 0 } } };
}));
assert.match(await page.textContent("#panel .mascota-texto"),
  /ETHFDUSD scores 91 and passes the threshold \(85\), but no amount comes out that I could open it with/);
assert.match(await page.textContent("#panel .mascota-porque"),
  /There's nothing available for another position/, "el motivo del tamaño, con sus palabras");
// Un aviso del mercado: en prueba no frena, pero se dice igual.
await page.evaluate(() => window.Pilota._probar((E) => {
  E.panel = { ...E.panel, mascota: { animo: "dudando", cuento: "aviso", datos: { aviso: "fdusd", n: 1 } } };
}));
assert.match(await page.textContent("#panel .mascota-texto"),
  /Careful with the price of FDUSD: in this account it doesn't brake me, but in live mode I wouldn't open anything/);
// Y con un freno puesto la mascota lo cuenta antes que nada.
await page.evaluate(() => window.Pilota._probar((E) => {
  E.panel = { ...E.panel, frenos: { ...E.panel.frenos, frenado: true, activos: ["piso"] },
    mascota: { animo: "frenado", cuento: "frenado", datos: { freno: "piso", n: 1 } } };
}));
assert.match(await page.textContent("#panel .mascota-texto"),
  /There's a brake applied \(the reference capital floor\): I'm not opening any new entry/);
await page.evaluate(() => window.Pilota._probar((E) => { E.panel = window.__panel; }));
await page.click("#abrir-ajustes");
await page.waitForSelector("[role=dialog]");
assert.match(await page.textContent(".pz-mcp"), /Connect your AI/, "Ajustes trae «Conectar a tu IA» (pieza mcp)");
assert.match(await page.textContent(".pz-mcp"), /Claude \(desktop app\)/, "las IA instaladas se ven");
// La moneda de referencia: el número lo pone la persona y se muestra al lado del saldo, nunca en vez de los USDT.
await page.fill("#local-tasa", "950");
await page.click("#local-guardar");
await page.waitForFunction(() => /for reference/.test(document.querySelector("#panel .saldo-local")?.textContent || ""));
assert.match(await page.textContent("#panel .saldo-local"),
  /≈ 201,780 CLP · for reference, the trade is in USDT/, "la referencia va al lado, con su nota");
await capturar(page, "17-ajustes-en");
assert.deepEqual(await faltantes(page), [], "textos sin traducir al inglés (súmalos a ui/idiomas/en.json)");

// 14. En español, sin la bienvenida (ya hecha en demo.json), y a lo ancho de un celular.
page = await abrir("?idioma=es", 390);
await page.waitForSelector("#descargar");
assert.match(await page.textContent(".banda"), /Prueba: dinero ficticio/);
// La pantalla principal, también en español y a lo ancho de un celular.
assert.match(await page.textContent("#panel .saldo-monto"), /212,4 USDT/);
assert.match(await page.textContent("#panel .saldo"),
  /La línea del piso está en 161,1 USDT: el 25 % bajo tu capital de referencia \(214,8 USDT\)/);
assert.match(await page.textContent("#panel .mascota-texto"), /Cerré BTCFDUSD por el objetivo: dejó 0,52 USDT/);
assert.match(await page.textContent("#panel .mascota-dia"), /Hoy abrí 1 y cerré 1/);
assert.match(await page.textContent('[aria-label="Puntaje y exigencia por par"]'),
  /ETHFDUSD\s*49 de 100 · exigencia 85/, "el puntaje de cada par contra la exigencia");
assert.match(await page.textContent('[aria-label="Puntaje y exigencia por par"]'), /Bajo la exigencia/,
  "y si está sobre o bajo ella, con palabras");
assert.match(await page.textContent("#panel .saldo"),
  /Piso: el saldo en el que dejo de abrir cosas, el 25 % bajo tu capital de referencia/, "la ayuda del piso, en español");
assert.match(await page.textContent("#panel"), /Prueba: dinero ficticio con precios de verdad/);
assert.match(await page.textContent('[aria-label="Propuestas esperando tu respuesta"]'),
  /Compro 14,25 USDT a 94\.830, con stop en 93\.869,7 y objetivo en 96\.252,45/);
assert.match(await page.textContent("#panel"), /Última revisión hace 9 h; reviso cada 5 min/);
assert.match(await page.textContent("#panel .panel-motor"),
  /Pilota solo trabaja con el equipo encendido: con la app cerrada o el equipo dormido nadie mira los cruces/,
  "el aviso del equipo encendido, también en español");
assert.match(await page.textContent("#panel"),
  /Tengo 0 abiertas y 1 esperando, de 2 que caben a la vez: 0 con su protección automática/);
assert.match(await page.textContent('[aria-label="Lo último que hice"]'),
  /puntaje 84 de 100 · compró con límite en 94\.830 · orden por 60 USDT/, "la orden de cada línea del registro");
assert.match(await page.textContent("#panel"), /El motor está apagado: nadie está mirando los cruces/,
  "lo que falta se dice en la misma pantalla");
await sinDesborde(page, "la pantalla principal a 390 px");
await capturar(page, "18-panel-390");
assert.match(await page.textContent("#minimo"), /Todavía no lo he calculado/, "el cálculo parte sin hacer en cada arranque");
await page.click("#calcular-minimo");
await page.waitForSelector(".minimo-monto");
assert.match(await page.textContent("#minimo"), /Desde 5,71 USDT por posición/, "el mínimo por posición de cada par");
assert.match(await page.textContent("#historial"), /Sin bajar todavía/, "los 3 años parten sin bajar");
assert.match(await page.textContent("#historial .trabajo-pct"), /0 % · 11\.058 de 135\.780 velas/);
assert.match(await page.textContent("#muestreo"), /Todavía no hay ninguna muestra guardada/);
await page.click("#historial-bajar");
await page.waitForSelector('#historial progress[value="100"]');
assert.match(await page.textContent("#historial .trabajo-linea"), /117\.800 velas guardadas de los 3 años/);
await page.click("#muestreo-encender");
await page.waitForSelector('#muestreo progress[value="100"]');
assert.match(await page.textContent("#muestreo .trabajo-linea"), /la próxima muestra, en/, "cuándo viene la siguiente");
assert.match(await page.textContent("#muestreo"), /ventanas sin muestras: 1/, "el rato que quedó sin muestras se dice");
assert.match(await page.textContent("#indicadores"), /9 de 12 series con indicadores al día/);
assert.match(await page.textContent("#indicadores"), /medias 94\.870,5 \/ 94\.210,25 \/ 92\.440,8/);
assert.match(await page.textContent("#indicadores"), /se mueve 210,4 por vela · volumen 1,3 veces lo normal/);
assert.match(await page.textContent("#indicadores"), /15,4 % por encima de su media de 200 días/, "el contexto de BTC");
assert.match(await page.textContent("#indicadores"), /entrar y salir cuesta 0,15 %/, "el costo de entrar y salir");
assert.match(await page.textContent("#indicadores"), /BTCFDUSD 1 d: faltan 310 velas/);
assert.match(await page.textContent("#senales"), /Señales para entrar ahora: 2/);
assert.match(await page.textContent("#senales"), /BTC viene bien/, "el filtro de BTC, en palabras");
assert.match(await page.textContent("#senales"),
  /compra con límite al volver a 94\.830, stop en 93\.869,7 y objetivo en 96\.252,45/, "la ruptura entra en el nivel roto");
assert.match(await page.textContent("#senales"), /arriesga 1,01 % para ganar 1,5 %/);
assert.match(await page.textContent("#senales"), /objetivo en la media, 3\.198,4/, "el rebote sale en la media");
assert.match(await page.textContent("#senales"), /ETHUSDT 1 d: falta historial para saber si el día viene al alza/);
assert.match(await page.textContent("#backtest"), /Todavía no he recorrido el historial/, "el backtest parte sin correr");
await page.click("#backtest-correr");
await page.waitForSelector('[aria-label="Casos por tramo"]');
assert.match(await page.textContent('[aria-label="Comparación"]'), /rendimiento 274 % · caída máxima 18,6 %/);
assert.match(await page.textContent('[aria-label="Comparación"]'), /Comprar BTC y esperar/, "y con comprar y esperar");
assert.match(await page.textContent("#backtest"), /Plan B: tampoco alcanzaba por par/, "el plan B queda dicho");
assert.match(await page.textContent('[aria-label="Casos por tramo"]'), /Rebote\s*todo junto\s*412 casos/);
assert.match(await page.textContent("#backtest"), /velas prestadas del par contra USDT/, "el empalme se marca");
assert.match(await page.textContent("#backtest"), /No es una promesa de ganancia/);
await page.waitForFunction(() => /Gana/.test(document.querySelector("#puntaje")?.textContent || ""));
assert.match(await page.textContent("#puntaje"), /Lo que más puntúa ahora: Ruptura en BTCFDUSD · 4 h, 84 de 100/);
assert.match(await page.textContent("#puntaje"), /Quedarse en USDT puntúa 50 de 100/, "la vara, siempre a la vista");
assert.match(await page.textContent("#puntaje"), /El puntaje está sin calibrar: las siete familias pesan lo mismo/,
  "el estado del modelo, también en español");
assert.match(await page.textContent('[aria-label="Oportunidades puntuadas"]'),
  /Gana 56 % de las veces \(entre 51 % y 61 %, con 355 casos del historial\)/);
assert.match(await page.textContent('[aria-label="Oportunidades puntuadas"]'),
  /Ganancia esperada después de costos: 0,25 % \(entre 0,11 % y 0,38 %\)/);
assert.match(await page.textContent('[aria-label="Notas por familia"]'), /Tendencia\s*83 de 100/, "nota por familia");
assert.match(await page.textContent("#puntaje"), /el supuesto acertó en 67 %/, "el supuesto de las velas sin 1 m");
assert.match(await page.textContent("#puntaje"), /Un puntaje no es una orden ni una promesa/);
assert.match(await page.textContent("#calibracion"), /Todavía no he calibrado el puntaje/, "la calibración parte sin hacer");
await page.click("#calibracion-correr");
await page.waitForSelector('[aria-label="Criterio de aprobación"]');
assert.match(await page.textContent("#calibracion"),
  /Modelo no validado: la exigencia queda en 85 de 100 y el monto por posición, topado en 15 USDT/);
assert.match(await page.textContent("#calibracion"), /La compuerta del backtest tuvo que ensanchar sus tramos/,
  "el motivo por el que no quedó validado, en español");
assert.match(await page.textContent("#calibracion"), /Aparté 365 días/, "el año apartado se dice siempre");
assert.match(await page.textContent('[aria-label="Vueltas de la calibración"]'), /Vuelta 2\s*Con esta quedó/);
assert.match(await page.textContent('[aria-label="Pesos por familia"]'), /Tendencia\s*pesa 2/);
assert.match(await page.textContent('[aria-label="Comparación de la prueba final"]'),
  /rendimiento 46 % · caída máxima 11,2 % · 186 operaciones/);
assert.match(await page.textContent('[aria-label="Criterio de aprobación"]'), /La compuerta pasó sin plan B\s*No pasa/);
await page.waitForFunction(() => /calibrado pero no validado/.test(document.querySelector("#puntaje")?.textContent || ""));
assert.match(await page.textContent("#estado"),
  /Estado al día y con su huella: 212,4 USDT en la cuenta de prueba, en modo Manual/);
assert.match(await page.textContent("#estado"), /7 líneas desde el .+, 9 días/, "el registro, también en español");
assert.match(await page.textContent('[aria-label="Las dos cuentas"]'), /Real: dinero de verdad\s*Sin estado todavía/);
assert.match(await page.textContent('[aria-label="Últimas líneas del registro"]'), /Cerró en el objetivo/);
await page.click("#estado-reiniciar");
await page.waitForSelector("[role=alertdialog]");
await page.click('[data-pz-confirmar="si"]');
await page.waitForFunction(() => /200 USDT en la cuenta de prueba/.test(document.querySelector("#estado")?.textContent || ""));
assert.match(await page.textContent('[aria-label="Últimas líneas del registro"]'), /Reiniciaste el saldo de prueba/,
  "una sola confirmación, al tiro, y queda en el registro");
assert.match(await page.textContent("#tamano"),
  /Con 200 USDT de capital pongo hasta 60 USDT por posición y arriesgo como máximo 4 USDT en cada operación/);
assert.match(await page.textContent('[aria-label="El orden del tamaño"]'),
  /La reserva en USDT\s*40 %\s*80 USDT se quedan siempre en USDT y quedan 120 USDT para operar/);
assert.match(await page.textContent('[aria-label="El orden del tamaño"]'),
  /El tope del modelo sin validar\s*15 USDT/, "el tope, también en español");
assert.match(await page.textContent('[aria-label="Tamaño por oportunidad"]'),
  /Compraría 0,00015 BTC a 94\.830 con stop en 93\.869,7: 14,25 USDT con sus costos/);
assert.match(await page.textContent('[aria-label="Tamaño por oportunidad"]'),
  /Si el stop se cruza pierdo 0,17 USDT, el 0,08 % del capital/);
assert.match(await page.textContent("#tamano"), /Un monto no es una orden/);
// Los frenos, también en español: el día en hora local, los dos del mercado que no corren en prueba y «Pausar».
assert.match(await page.textContent("#frenos"), /Ahora: Operando, en modo Manual/);
assert.match(await page.textContent('[aria-label="Los frenos"]'),
  /El piso del capital de referencia\s*Pasa\s*Frena si el saldo baja de 161,1 USDT: el 25 % bajo el capital de referencia \(214,8 USDT\)/);
assert.match(await page.textContent('[aria-label="Los frenos"]'),
  /El freno del día\s*Pasa\s*Hoy partí con 211,88 USDT y voy en 212,4 USDT/);
assert.match(await page.textContent('[aria-label="Los frenos"]'),
  /El precio de FDUSD\s*No corre en prueba\s*FDUSD vale 0,9998 USDT: frena bajo 0,995/);
assert.match(await page.textContent('[aria-label="Los frenos de siempre"]'), /Sin apalancamiento\s*1x/);
await page.click("#frenos-pausar");
await page.waitForFunction(() => /Ahora: En pausa/.test(document.querySelector("#frenos")?.textContent || ""));
assert.match(await page.textContent("#frenos"), /Sigues con 0 posiciones protegidas/,
  "«Pausar» cancela las entradas y no toca ninguna protección");
await page.click("#frenos-pausar");
await page.waitForFunction(() => /Ahora: Operando/.test(document.querySelector("#frenos")?.textContent || ""));
// El motor: hace cuánto fue la última revisión y, al revisar, qué pasó mientras nadie miraba.
assert.match(await page.textContent("#motor"), /Motor dormido/, "con el motor apagado nadie mira los cruces");
assert.match(await page.textContent("#motor .trabajo-linea"), /Última revisión hace 9 h/);
await page.click("#motor-revisar");
await page.waitForFunction(() => /Dormiste 9 h/.test(document.querySelector("#motor")?.textContent || ""));
assert.match(await page.textContent("#motor"), /2 propuestas vencidas/, "lo que pasó mientras nadie miraba");
assert.match(await page.textContent("#motor"), /540 min sin cubrir/, "la ventana sin cobertura queda escrita");
await sinDesborde(page, "inicio a 390 px");
await capturar(page, "19-trabajos-390");
await page.click("#abrir-ajustes");
await page.waitForSelector("[role=dialog]");
await sinDesborde(page, "Ajustes a 390 px");
await capturar(page, "20-ajustes-390");

await navegador.close();
servidor.close();
assert.deepEqual(errores, [], "errores de JavaScript o de la CSP");
console.log("Interfaz: todo bien");
