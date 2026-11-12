// Pilota: el gráfico de velas en vivo, como el de un trader. Velas de 1 m, 5 m, 1 h o 4 h; bandas de Bollinger, medias,
// volumen y RSI que se prenden con un botón; las compras y las ventas del robot como flechas de color; y las líneas de lo
// que está abierto (entrada, stop y objetivo). La vela en curso se mueve cada segundo con lo que empuja Binance.
// Se dibuja en un <canvas> (sin style="" en línea: la CSP lo bloquearía; el tamaño va en atributos).
// Las palabras dentro del dibujo pasan por Tp(): están traducidas aunque no vivan en el DOM.
window.PilotaGrafico = (() => {
  "use strict";

  const PARES = [["BTCFDUSD", "BTC"], ["ETHFDUSD", "ETH"]];
  const TEMPORALIDADES = [["1m", "1 min"], ["5m", "5 min"], ["1h", "1 hora"], ["4h", "4 horas"]];
  const PASO = { "1m": 60000, "5m": 300000, "1h": 3600000, "4h": 14400000 };
  // Los indicadores que se pueden prender: id, nombre y si viene prendido.
  const INDICADORES = [["bb", "Bandas de Bollinger", true], ["sma20", "Media 20", false], ["sma50", "Media 50", false],
    ["vol", "Volumen", true], ["rsi", "RSI", false]];
  const EJE = 74, ABAJO = 22, RSI_ALTO = 86;

  // ── Las cuentas (las mismas de bin/lib_indicadores*.py, sobre los cierres) ──
  function sma(xs, n) {
    const out = new Array(xs.length).fill(null);
    let suma = 0;
    for (let i = 0; i < xs.length; i++) {
      suma += xs[i];
      if (i >= n) suma -= xs[i - n];
      if (i >= n - 1) out[i] = suma / n;
    }
    return out;
  }
  function bollinger(xs, n = 20, k = 2) {
    const media = sma(xs, n);
    return xs.map((_, i) => {
      if (media[i] == null) return null;
      let v = 0;
      for (let j = i - n + 1; j <= i; j++) v += (xs[j] - media[i]) ** 2;
      const d = Math.sqrt(v / n);
      return [media[i] + k * d, media[i], media[i] - k * d];
    });
  }
  function rsi(xs, n = 14) {
    const out = new Array(xs.length).fill(null);
    let sube = 0, baja = 0;
    for (let i = 1; i < xs.length; i++) {
      const c = xs[i] - xs[i - 1];
      const s = Math.max(c, 0), b = Math.max(-c, 0);
      if (i <= n) { sube += s / n; baja += b / n; if (i < n) continue; }
      else { sube = (sube * (n - 1) + s) / n; baja = (baja * (n - 1) + b) / n; }
      out[i] = baja === 0 ? 100 : 100 - 100 / (1 + sube / baja);
    }
    return out;
  }

  function crear({ i18n, esc, numero, usdt }) {
    const { Tp } = i18n;
    let lienzo = null, sobre = null, pedido = false;
    let Eref = null;

    function estadoInicial() {
      return { par: "BTCFDUSD", temporalidad: "1m", datos: null, cargando: false, ancho: 9,
        ind: Object.fromEntries(INDICADORES.map(([id, , si]) => [id, si])), minutos: {}, precios: {}, cambio: {} };
    }

    // ── El HTML alrededor del lienzo (los botones y los precios, traducibles) ──
    function html(E) {
      const G = E.graf;
      return `<div class="tarjeta grafico">
        <div class="grafico-cabeza">
          <div class="grafico-pares" role="tablist" aria-label="Par">${PARES.map(([par, nombre]) => `
            <button type="button" class="graf-par" role="tab" data-graf-par="${par}" aria-selected="${G.par === par}">
              <span class="graf-par-nombre" data-sin-traducir>${nombre}</span>
              <span class="graf-par-precio" id="precio-${par}" data-tic="${G.cambio[par] || ""}" data-sin-traducir>${esc(G.precios[par] ? numero(G.precios[par], 2) : "–")}</span></button>`).join("")}</div>
          <div class="chips grafico-tiempos" role="group" aria-label="Velas de">${TEMPORALIDADES.map(([t, n]) => `
            <button type="button" class="chip" data-graf-t="${t}" aria-pressed="${G.temporalidad === t}">${n}</button>`).join("")}</div>
        </div>
        <div class="chips grafico-indicadores" role="group" aria-label="Indicadores">${INDICADORES.map(([id, n]) => `
          <button type="button" class="chip chip-ind" data-graf-ind="${id}" aria-pressed="${!!G.ind[id]}">${n}</button>`).join("")}</div>
        <div class="grafico-caja${G.ind.rsi ? " con-rsi" : ""}">
          <canvas id="grafico-lienzo" role="img" aria-label="Gráfico de velas en vivo"></canvas>
          <div class="grafico-destello" id="grafico-destello" hidden></div>
          ${!G.datos ? `<p class="grafico-vacio suave">${G.cargando ? "Cargando velas…" : "Todavía no hay velas para mostrar."}</p>` : ""}
        </div>
        <p class="grafico-dato suave" id="grafico-dato" data-sin-traducir> </p></div>`;
    }

    // ── Los colores salen del tema (claro y oscuro) ──
    // Una variable con light-dark() no se puede leer tal cual: se le pone a una muestra fuera de #app y se lee el color ya
    // resuelto. (Es CSSOM, no un atributo style: la CSP lo permite.)
    let muestra = null;
    function resolver(variable, defecto) {
      if (!muestra) {
        muestra = document.createElement("span");
        muestra.hidden = true;
        document.body.appendChild(muestra);
      }
      muestra.style.color = "";
      muestra.style.color = `var(${variable}, ${defecto})`;
      return getComputedStyle(muestra).color || defecto;
    }
    function colores() {
      return { gana: resolver("--gana", "#1f8a4c"), pierde: resolver("--pierde", "#c8402f"), acento: resolver("--acento", "#2f62d0"),
        texto: resolver("--texto", "#1b2230"), suave: resolver("--texto-suave", "#5b6474"), linea: resolver("--linea", "#dde2ea"),
        panel: resolver("--panel", "#fff"), sma20: resolver("--graf-media20", "#c98a12"), sma50: resolver("--graf-media50", "#8a4fd1") };
    }
    const alfa = (color, a) => {
      const m = /rgba?\(([^)]+)\)/.exec(color);
      if (!m) return color;
      const [r, g, b] = m[1].split(",").map((x) => x.trim());
      return `rgba(${r},${g},${b},${a})`;
    };

    // ── La vela en curso: lo que empuja Binance cada segundo, sumado a las velas cerradas ──
    function vela(E, par, v) {
      const G = E.graf;
      if (!Array.isArray(v) || v.length < 6) return;
      const antes = G.precios[par];
      G.precios[par] = v[4];
      if (antes != null && v[4] !== antes) G.cambio[par] = v[4] > antes ? "sube" : "baja";
      const el = document.getElementById(`precio-${par}`);
      if (el) {
        el.textContent = numero(v[4], 2);
        el.dataset.tic = "";
        void el.offsetWidth;            // reinicia la animación del destello del precio
        el.dataset.tic = G.cambio[par] || "";
      }
      if (!G.datos || G.datos.par !== par) return;
      const paso = G.datos.paso_ms, velas = G.datos.velas;
      const inicio = Math.floor(v[0] / paso) * paso;
      let nueva;
      if (paso === 60000) nueva = [...v];
      else {
        G.minutos[v[0]] = v;
        const mins = Object.values(G.minutos).filter((m) => m[0] >= inicio && m[0] < inicio + paso).sort((a, b) => a[0] - b[0]);
        for (const k of Object.keys(G.minutos)) if (Number(k) < inicio) delete G.minutos[k];
        const ultima = velas.length && velas[velas.length - 1][0] === inicio ? velas[velas.length - 1] : null;
        const abre = ultima ? ultima[1] : mins[0][1];
        nueva = [inicio, abre, Math.max(...mins.map((m) => m[2]), ultima ? ultima[2] : -Infinity),
          Math.min(...mins.map((m) => m[3]), ultima ? ultima[3] : Infinity), v[4],
          mins.reduce((a, m) => a + m[5], 0)];
      }
      nueva.enCurso = true;
      const ult = velas[velas.length - 1];
      if (ult && ult[0] === inicio) velas[velas.length - 1] = nueva;
      else if (!ult || ult[0] < inicio) velas.push(nueva);
      if (velas.length > 400) velas.shift();
      dibujar();
    }

    // ── Una compra o una venta que acaba de pasar: el destello de color y la flecha en el gráfico ──
    function destello(texto, tipo) {
      const el = document.getElementById("grafico-destello");
      if (!el) return;
      el.textContent = texto;
      el.dataset.tipo = tipo;
      el.hidden = false;
      el.classList.remove("anda");
      void el.offsetWidth;
      el.classList.add("anda");
      clearTimeout(destello.t);
      destello.t = setTimeout(() => { el.hidden = true; }, 6000);
    }
    function marca(E, m) {
      const G = E.graf;
      if (G.datos && G.datos.par === m.par) { G.datos.marcas.push(m); dibujar(); }
    }

    // ── Dibujar ──
    function dibujar() {
      if (pedido) return;
      pedido = true;
      (window.requestAnimationFrame || ((f) => setTimeout(f, 16)))(() => { pedido = false; pintarLienzo(); });
    }
    function montar(raiz, E) {
      Eref = E;
      lienzo = raiz.querySelector("#grafico-lienzo");
      if (!lienzo) return;
      if (!lienzo.dataset.listo) {
        lienzo.dataset.listo = "1";
        lienzo.addEventListener("mousemove", (ev) => { const r = lienzo.getBoundingClientRect(); sobre = [ev.clientX - r.left, ev.clientY - r.top]; dibujar(); });
        lienzo.addEventListener("mouseleave", () => { sobre = null; dibujar(); });
        lienzo.addEventListener("wheel", (ev) => {
          ev.preventDefault();
          E.graf.ancho = Math.max(3, Math.min(24, E.graf.ancho * (ev.deltaY > 0 ? 0.9 : 1.1)));
          dibujar();
        }, { passive: false });
      }
      pintarLienzo();
    }

    function pintarLienzo() {
      if (!lienzo || !lienzo.isConnected || !Eref) return;
      const G = Eref.graf, d = G.datos;
      const dpr = window.devicePixelRatio || 1;
      const W = lienzo.clientWidth, H = lienzo.clientHeight;
      if (!W || !H) return;
      if (lienzo.width !== Math.round(W * dpr) || lienzo.height !== Math.round(H * dpr)) {
        lienzo.width = Math.round(W * dpr);
        lienzo.height = Math.round(H * dpr);
      }
      const c = lienzo.getContext("2d");
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      c.clearRect(0, 0, W, H);
      if (!d || !d.velas || !d.velas.length) return;
      const col = colores();
      const fuente = "11px system-ui, -apple-system, sans-serif";
      c.font = fuente;

      const conRsi = !!G.ind.rsi;
      const altoRsi = conRsi ? RSI_ALTO : 0;
      const plotW = W - EJE, plotH = H - ABAJO - altoRsi;
      const todas = d.velas, cierres = todas.map((v) => v[4]);
      const n = Math.max(10, Math.min(todas.length, Math.floor(plotW / G.ancho)));
      const desde = todas.length - n;
      const vis = todas.slice(desde);
      const ancho = plotW / n;
      const X = (i) => (i - desde) * ancho + ancho / 2;
      const bb = G.ind.bb ? bollinger(cierres) : null;
      const m20 = G.ind.sma20 ? sma(cierres, 20) : null, m50 = G.ind.sma50 ? sma(cierres, 50) : null;

      // El rango de precios: las velas a la vista, las bandas y las líneas de lo abierto.
      let lo = Math.min(...vis.map((v) => v[3])), hi = Math.max(...vis.map((v) => v[2]));
      if (bb) for (let i = desde; i < todas.length; i++) if (bb[i]) { lo = Math.min(lo, bb[i][2]); hi = Math.max(hi, bb[i][0]); }
      for (const nv of d.niveles || []) { lo = Math.min(lo, nv.precio); hi = Math.max(hi, nv.precio); }
      const margen = (hi - lo) * 0.08 || hi * 0.001 || 1;
      lo -= margen; hi += margen;
      const volH = G.ind.vol ? plotH * 0.18 : 0;
      const Y = (p) => 6 + (plotH - 12 - volH) * (1 - (p - lo) / (hi - lo));

      // La grilla y el eje de precios.
      c.strokeStyle = alfa(col.linea, 0.9); c.fillStyle = col.suave; c.lineWidth = 1;
      c.textBaseline = "middle"; c.textAlign = "left";
      for (let k = 0; k <= 5; k++) {
        const p = lo + (hi - lo) * k / 5, y = Math.round(Y(p)) + 0.5;
        c.beginPath(); c.moveTo(0, y); c.lineTo(plotW, y); c.stroke();
        c.fillText(numero(p, p > 1000 ? 0 : 2), plotW + 6, y);
      }
      // El eje del tiempo: unas cinco marcas.
      c.textAlign = "center"; c.textBaseline = "top";
      const formato = d.paso_ms >= 3600000 ? { day: "numeric", month: "short" } : { hour: "2-digit", minute: "2-digit" };
      for (let k = 1; k < 6; k++) {
        const i = desde + Math.floor(n * k / 6);
        if (!todas[i]) continue;
        c.fillText(new Date(todas[i][0]).toLocaleString(i18n.idioma, formato), X(i), plotH + altoRsi + 5);
      }

      // Bollinger: el relleno entre las bandas y las tres líneas.
      if (bb) {
        c.beginPath();
        let primero = true;
        for (let i = desde; i < todas.length; i++) if (bb[i]) { const x = X(i), y = Y(bb[i][0]); primero ? c.moveTo(x, y) : c.lineTo(x, y); primero = false; }
        for (let i = todas.length - 1; i >= desde; i--) if (bb[i]) c.lineTo(X(i), Y(bb[i][2]));
        c.closePath(); c.fillStyle = alfa(col.acento, 0.07); c.fill();
        for (const [j, a, punteada] of [[0, 0.7, false], [1, 0.5, true], [2, 0.7, false]]) {
          c.beginPath(); c.setLineDash(punteada ? [4, 4] : []); c.strokeStyle = alfa(col.acento, a); c.lineWidth = 1.2;
          primero = true;
          for (let i = desde; i < todas.length; i++) if (bb[i]) { const x = X(i), y = Y(bb[i][j]); primero ? c.moveTo(x, y) : c.lineTo(x, y); primero = false; }
          c.stroke();
        }
        c.setLineDash([]);
      }
      // Volumen, abajo y suave.
      if (G.ind.vol) {
        const vmax = Math.max(...vis.map((v) => v[5])) || 1;
        for (let i = desde; i < todas.length; i++) {
          const v = todas[i], h = (volH - 4) * v[5] / vmax;
          c.fillStyle = alfa(v[4] >= v[1] ? col.gana : col.pierde, 0.28);
          c.fillRect(X(i) - ancho * 0.35, plotH - h, ancho * 0.7, h);
        }
      }
      // Las velas.
      for (let i = desde; i < todas.length; i++) {
        const v = todas[i], sube = v[4] >= v[1], color = sube ? col.gana : col.pierde, x = Math.round(X(i)) + 0.5;
        c.globalAlpha = v.enCurso ? 0.75 : 1;
        c.strokeStyle = color; c.fillStyle = color; c.lineWidth = 1;
        c.beginPath(); c.moveTo(x, Y(v[2])); c.lineTo(x, Y(v[3])); c.stroke();
        const y1 = Y(Math.max(v[1], v[4])), y2 = Y(Math.min(v[1], v[4]));
        c.fillRect(x - Math.max(1, ancho * 0.36), y1, Math.max(2, ancho * 0.72), Math.max(1, y2 - y1));
      }
      c.globalAlpha = 1;
      // Las medias.
      for (const [serie, color] of [[m20, col.sma20], [m50, col.sma50]]) {
        if (!serie) continue;
        c.beginPath(); c.strokeStyle = color; c.lineWidth = 1.5;
        let primero = true;
        for (let i = desde; i < todas.length; i++) if (serie[i] != null) { const x = X(i), y = Y(serie[i]); primero ? c.moveTo(x, y) : c.lineTo(x, y); primero = false; }
        c.stroke();
      }
      // Las líneas de lo abierto: compra esperando, entrada, stop y objetivo, con su nombre en el eje.
      const NIVEL = { espera: [col.acento, "Compra esperando"], entrada: [col.suave, "Entrada"], stop: [col.pierde, "Stop"],
        objetivo: [col.gana, "Objetivo"] };
      for (const nv of d.niveles || []) {
        const [color, nombre] = NIVEL[nv.tipo] || [col.suave, ""];
        const y = Math.round(Y(nv.precio)) + 0.5;
        c.setLineDash([6, 4]); c.strokeStyle = color; c.lineWidth = 1.2;
        c.beginPath(); c.moveTo(0, y); c.lineTo(plotW, y); c.stroke(); c.setLineDash([]);
        c.fillStyle = color; c.textAlign = "left"; c.textBaseline = "bottom";
        c.fillText(`${Tp(nombre)} ${numero(nv.precio, 2)}`, 6, y - 2);
      }
      // Las compras (flecha verde hacia arriba, bajo la vela) y las ventas (flecha hacia abajo, sobre la vela; verde si ganó).
      for (const m of d.marcas || []) {
        const t = Math.floor(m.ms / d.paso_ms) * d.paso_ms;
        let i = -1;
        for (let k = todas.length - 1; k >= desde; k--) if (todas[k][0] === t) { i = k; break; }
        if (i < 0) continue;
        const v = todas[i], x = X(i), compra = m.tipo === "compra";
        const color = compra ? col.gana : ((m.neto || 0) > 0 ? col.gana : col.pierde);
        const y = compra ? Y(v[3]) + 8 : Y(v[2]) - 8, s = 7;
        c.fillStyle = color; c.beginPath();
        if (compra) { c.moveTo(x, y); c.lineTo(x - s, y + s * 1.4); c.lineTo(x + s, y + s * 1.4); }
        else { c.moveTo(x, y); c.lineTo(x - s, y - s * 1.4); c.lineTo(x + s, y - s * 1.4); }
        c.closePath(); c.fill();
        c.textAlign = "center"; c.textBaseline = compra ? "top" : "bottom"; c.font = `600 ${fuente}`;
        c.fillText(compra ? Tp("Compra") : (m.neto != null ? `${m.neto > 0 ? "+" : ""}${numero(m.neto, 2)}` : Tp("Venta")),
          x, compra ? y + s * 1.4 + 2 : y - s * 1.4 - 2);
        c.font = fuente;
      }
      // El precio de ahora: una línea y su cajita en el eje, del color de la última vela.
      const ult = todas[todas.length - 1];
      const yp = Math.round(Y(ult[4])) + 0.5, colorP = ult[4] >= ult[1] ? col.gana : col.pierde;
      c.setLineDash([2, 3]); c.strokeStyle = colorP; c.beginPath(); c.moveTo(0, yp); c.lineTo(plotW, yp); c.stroke(); c.setLineDash([]);
      c.fillStyle = colorP; c.fillRect(plotW, yp - 9, EJE, 18);
      c.fillStyle = "#fff"; c.textAlign = "left"; c.textBaseline = "middle"; c.font = `700 ${fuente}`;
      c.fillText(numero(ult[4], 2), plotW + 6, yp); c.font = fuente;

      // El RSI, en su propio panel abajo.
      if (conRsi) {
        const r = rsi(cierres), top = plotH + 4, h = altoRsi - 8;
        const YR = (x) => top + h * (1 - x / 100);
        c.fillStyle = alfa(col.acento, 0.06); c.fillRect(0, YR(70), plotW, YR(30) - YR(70));
        c.strokeStyle = alfa(col.linea, 1); c.beginPath(); c.moveTo(0, top - 2.5); c.lineTo(W, top - 2.5); c.stroke();
        c.beginPath(); c.strokeStyle = col.acento; c.lineWidth = 1.3;
        let primero = true;
        for (let i = desde; i < todas.length; i++) if (r[i] != null) { const x = X(i), y = YR(r[i]); primero ? c.moveTo(x, y) : c.lineTo(x, y); primero = false; }
        c.stroke();
        c.fillStyle = col.suave; c.textAlign = "left"; c.textBaseline = "middle";
        c.fillText("70", plotW + 6, YR(70)); c.fillText("30", plotW + 6, YR(30));
        const ultR = r[r.length - 1];
        if (ultR != null) { c.fillStyle = col.acento; c.fillText(`RSI ${numero(ultR, 0)}`, 6, top + 8); }
      }

      // La cruz del mouse, con la vela que está debajo.
      const dato = document.getElementById("grafico-dato");
      if (sobre && sobre[0] < plotW) {
        const i = Math.max(desde, Math.min(todas.length - 1, desde + Math.floor(sobre[0] / ancho)));
        const v = todas[i];
        c.strokeStyle = alfa(col.suave, 0.6); c.setLineDash([3, 3]);
        c.beginPath(); c.moveTo(X(i), 0); c.lineTo(X(i), plotH + altoRsi); c.moveTo(0, sobre[1]); c.lineTo(plotW, sobre[1]); c.stroke();
        c.setLineDash([]);
        if (sobre[1] < plotH) {
          const p = lo + (hi - lo) * (1 - (sobre[1] - 6) / (plotH - 12 - volH));
          c.fillStyle = col.texto; c.fillRect(plotW, sobre[1] - 9, EJE, 18);
          c.fillStyle = col.panel; c.fillText(numero(p, 2), plotW + 6, sobre[1]);
        }
        if (dato) {
          dato.textContent = Tp("{fecha} · abre {o} · alto {h} · bajo {l} · cierra {c}", {
            fecha: new Date(v[0]).toLocaleString(i18n.idioma, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }),
            o: numero(v[1], 2), h: numero(v[2], 2), l: numero(v[3], 2), c: numero(v[4], 2) });
        }
      } else if (dato) {
        dato.textContent = Tp("Pasa el mouse sobre una vela para ver sus precios. Con la rueda acercas o alejas.");
      }
    }

    return { html, montar, dibujar, vela, destello, marca, estadoInicial, PARES, TEMPORALIDADES, PASO, INDICADORES };
  }
  return { crear };
})();
