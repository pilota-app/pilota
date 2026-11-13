// Pilota: el robot en vivo y la comparación de perfiles. Tres pestañas: «En vivo» (elige un perfil y un monto, y mira cómo
// opera con dinero ficticio y precios de ahora), «Comparar» (los cinco perfiles en el pasado, con la película de lo que
// hizo cada uno) y «Movimientos» (todo lo que hizo el robot, en palabras).
// Nada de texto pegado: cada frase va completa, con sus marcadores, y su inglés en idiomas/en.json.
// Los dibujos son SVG con atributos (nunca style=""): la CSP «style-src 'self'» lo bloquearía.
window.PilotaVivo = (() => {
  "use strict";

  // Los seis perfiles (bin/lib_perfiles.py: ORDEN). El nombre, qué hace en una frase, qué tan rápido opera y con qué monedas.
  const PERFILES = {
    holding: { nombre: "Holding", que: "Compra BTC y ETH por partes, una vez por semana, y los guarda. No intenta adivinar: es lo que mejor resistió en los datos.", ritmo: "Muy lento" },
    conservador: { nombre: "Conservador", que: "Pocas operaciones: solo las muy claras, en velas de 4 horas, donde puede ganar el doble de lo que arriesga.", ritmo: "Lento" },
    equilibrado: { nombre: "Equilibrado", que: "Operaciones medianas en velas de 1 y 4 horas. Es el punto de partida que te sugiero.", ritmo: "Medio" },
    trader: { nombre: "Trader", que: "Muchas operaciones chicas en velas de 1 hora.", ritmo: "Rápido" },
    scalper: { nombre: "Scalper", que: "El más rápido: velas de 5 minutos, entra y sale en minutos u horas. Más operaciones, más comisiones.", ritmo: "Muy rápido" },
    holding_ocho: { nombre: "Holding 8 monedas", que: "Compra las 8 monedas en partes iguales, una vez por semana, y las guarda. Más repartido: si una se cae, pesa menos.", ritmo: "Muy lento" },
    compra_semanal: { nombre: "Compra semanal", que: "Compra BTC y ETH todas las semanas durante un año. Deja cada compra un 1 % más abajo; si el precio no llega, compra igual ese día.", ritmo: "Muy lento" },
    rebalanceo: { nombre: "Rebalanceo", que: "Mitad en BTC y ETH, mitad en USDT. Si cripto sube y pasa del 60 %, vende lo que sobra; si baja del 40 %, compra lo que falta.", ritmo: "Lento" },
    cosecha: { nombre: "Cosecha", que: "Compra BTC y ETH por partes. Cuando una sube 30 % sobre lo que pagó, vende un cuarto; si después cae 15 %, la vuelve a comprar.", ritmo: "Lento" },
    indice_eeuu: { nombre: "Índice EE. UU.", que: "Compra el S&P 500 (SPY) y el Nasdaq 100 (QQQ) por partes, una vez por semana, y los guarda. Son las 500 y las 100 empresas más grandes de EE. UU.", ritmo: "Muy lento" },
    indice_semanal: { nombre: "Índice semanal", que: "Compra el S&P 500 y el Nasdaq 100 todas las semanas durante un año, cada compra un 1 % más abajo.", ritmo: "Muy lento" },
    acciones_ocho: { nombre: "8 acciones grandes", que: "Apple, Microsoft, Nvidia, Amazon, Google, Meta, Tesla y Broadcom en partes iguales, por partes, y las guarda.", ritmo: "Muy lento" },
    semanal_rotacion: { nombre: "Semanal + Rotación", que: "La mitad en Compra semanal y la mitad en Rotación. Cada mitad sigue sus reglas por su lado.", ritmo: "Lento" },
    nucleo_satelite: { nombre: "Núcleo y satélite", que: "70 % guardado en BTC y ETH (el núcleo) y 30 % en Rotación (el satélite): lo grande no se mueve, lo chico prueba.", ritmo: "Lento" },
    cripto_acciones: { nombre: "Cripto + Acciones", que: "La mitad en Compra semanal de BTC y ETH y la mitad en Índice semanal de EE. UU. Dos mercados distintos que no siempre caen juntos.", ritmo: "Muy lento" },
    tendencia: { nombre: "Tendencia", que: "Experimento: BTC y ETH solo mientras su precio está sobre su promedio de 50 días, sin caídas fuertes en la semana y sin malas noticias de personas influyentes. Si no, esa parte espera en USDT. Sale antes de las caídas grandes y entra tarde en las subidas.", ritmo: "Lento" },
    rotacion: { nombre: "Rotación", que: "Experimento: tiene las 2 monedas que vienen más fuertes de las 8 y cambia a la que pasa adelante. Se parece a comprar BTC: a veces gana y a veces pierde, y puede caer tanto como BTC.", ritmo: "Lento" },
  };
  // Los que se ofrecen (bin/lib_perfiles.py: ORDEN). Los otros cuatro quedaron retirados: perdieron con datos reales. Sus
  // nombres siguen arriba para contar lo que ya pasó en el registro.
  const ORDEN = ["holding", "holding_ocho", "compra_semanal", "rebalanceo", "cosecha", "indice_eeuu", "indice_semanal",
    "acciones_ocho", "semanal_rotacion", "nucleo_satelite", "cripto_acciones", "tendencia", "rotacion"];
  // Cómo se agrupan en la pantalla: la familia holding primero (comprar y guardar) y aparte los experimentos.
  const GRUPOS = [["guardar", "Comprar y guardar", ["holding", "holding_ocho", "compra_semanal", "rebalanceo", "cosecha"]],
    ["acciones", "Acciones de EE. UU.", ["indice_eeuu", "indice_semanal", "acciones_ocho"]],
    ["mezclas", "Mezclas", ["semanal_rotacion", "nucleo_satelite", "cripto_acciones"]],
    ["experimento", "Experimentos", ["tendencia", "rotacion"]]];
  const GRUPO_AYUDA = {
    guardar: "Compran por partes y guardan. Cada uno cambia una sola cosa: qué monedas, cada cuánto compra o si vende una parte.",
    acciones: "Acciones tokenizadas de Binance: cada una respaldada por la acción real. Llegaron en junio de 2026, así que su historia es corta.",
    mezclas: "Reparten el monto entre dos perfiles. Cada parte sigue sus reglas y la pantalla muestra cuánto vale cada una.",
    experimento: "Compran y venden según el mercado. Se miden igual que los otros, pero su ventaja no está probada.",
  };
  // Las monedas de cada perfil (bin/lib_perfiles.py: «pares»). Todas contra USDT; el holding guarda BTC y ETH.
  const MONEDAS = {
    holding: ["BTC", "ETH"], holding_ocho: ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "TRX", "DOGE"],
    compra_semanal: ["BTC", "ETH"], rebalanceo: ["BTC", "ETH"], cosecha: ["BTC", "ETH"],
    indice_eeuu: ["SPY", "QQQ"], indice_semanal: ["SPY", "QQQ"],
    acciones_ocho: ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO"],
    semanal_rotacion: ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "TRX", "DOGE"],
    nucleo_satelite: ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "TRX", "DOGE"],
    cripto_acciones: ["BTC", "ETH", "SPY", "QQQ"], conservador: ["BTC", "ETH", "BNB"], equilibrado: ["BTC", "ETH", "BNB", "SOL", "XRP"],
    trader: ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "TRX", "DOGE"], scalper: ["BTC", "ETH", "SOL", "XRP", "DOGE"],
    rotacion: ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "TRX", "DOGE"], tendencia: ["BTC", "ETH"],
  };
  // Cripto y acciones se muestran aparte porque se comportan distinto (bin/lib_perfiles.py: mercado_de). Sale de las monedas
  // de cada perfil: solo acciones, solo cripto o las dos («mixto», que aparece en los dos lados).
  const ACCIONES = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO"];
  function mercadoDe(p) {
    const m = MONEDAS[p] || [], a = m.filter((x) => ACCIONES.includes(x)).length;
    return a === 0 ? "cripto" : (a === m.length ? "acciones" : "mixto");
  }
  const MERCADOS = [["cripto", "Cripto"], ["acciones", "Acciones de EE. UU."]];
  const MERCADO_AYUDA = {
    cripto: "Se compran y venden todo el día, todos los días, y se mueven mucho: caídas de 50 % o más ya pasaron varias veces. Hay historia en Binance desde 2017, así que las pruebas en el pasado son largas.",
    acciones: "Siguen el horario y las noticias de EE. UU. y se mueven menos que las criptos. En Binance existen desde junio de 2026: con tan poca historia todavía no se puede saber qué táctica funciona mejor.",
  };
  function mercadoElegido(E) {
    if (E.mercado === "cripto" || E.mercado === "acciones") return E.mercado;
    return mercadoDe(E.vivoPerfil || "holding") === "acciones" ? "acciones" : "cripto";
  }
  const enMercado = (p, m) => mercadoDe(p) === m || mercadoDe(p) === "mixto";
  function chipsMercado(E) {
    const m = mercadoElegido(E);
    return `<div class="mercado-elegir"><div class="chips" role="group" aria-label="Mercado">${MERCADOS.map(([id, t]) =>
      `<button type="button" class="chip" data-mercado="${id}" aria-pressed="${m === id}">${t}</button>`).join("")}</div>
      <p class="ayuda">${MERCADO_AYUDA[m]}</p></div>`;
  }
  const MONTOS = [50, 100, 200, 500, 1000];
  const PERIODOS = [[30, "1 mes"], [90, "3 meses"], [180, "6 meses"], [365, "1 año"], [1095, "3 años"]];
  // Lo que pensó el robot en su última vuelta (bin/lib_piloto.py: DECISIONES).
  const VUELTA = {
    sin_senal: "Miré el mercado: ahora no hay nada que cumpla las reglas de este perfil, así que espero en USDT.",
    sin_datos: "Me faltan velas al día para decidir: espero a que el muestreo las traiga.",
    entrada: "Vi una oportunidad que cumple las reglas y dejé una compra puesta, con su stop y su objetivo.",
    rechazo: "Vi una oportunidad, pero no entré: {motivo}.",
    frenado: "Hay un freno puesto: no abro nada nuevo. Lo abierto sigue con su protección.",
    compra: "Compré la parte {n} de este período.",
    esperando: "Ya compré esta semana. La próxima compra es el {fecha}.",
    completo: "Ya compré todas las partes: ahora solo mantengo.",
    rotacion: "Cambié de moneda: vendí {salen} y compré {entran}.",
    tendencia: "Hoy cambió el mercado: compré {compra} y vendí {vende}.",
    venta: "Vendí una parte: está en «Lo último que hizo».",
    mantiene: "Comparé las 8 y sigo con {tiene}: siguen entre las más fuertes.",
  };
  // Por qué no se pudo (bin/lib_simulacion.py: MOTIVOS y bin/lib_piloto.py).
  const MOTIVOS_SIM = {
    sin_monto: "Elige un monto entre 10 y 1.000.000 USDT.",
    sin_periodo: "Elige un período.",
    sin_minimos: "Todavía estoy preparando los datos de Binance. Vuelve a intentar en un momento.",
    sin_historial: "Todavía estoy bajando el historial de precios. Vuelve a intentar en unos minutos.",
    sin_operaciones: "En ese período este perfil no habría abierto ninguna operación: habría quedado en USDT.",
  };
  const ERRORES_VIVO = {
    sin_perfil: "Elige un perfil.",
    monto: "Elige un monto entre 10 y 1.000.000 USDT.",
    no_es_prueba: "Con el dinero real encendido no hago pruebas: primero vuelve a prueba.",
  };

  function crear({ i18n, esc, numero, usdt, porcentaje, fechaHora, robot, motivoCorto, grafico }) {
    const { Tp, frase } = i18n;
    const nombre = (p) => (PERFILES[p] || {}).nombre || "";
    const moneda = (par) => String(par || "").replace(/^(SPY|QQQ|AAPL|MSFT|NVDA|AMZN|GOOGL|META|TSLA|AVGO)BUSDT$/, "$1").replace(/(FDUSD|USDT)$/, "");
    const dia = (ms) => {
      const d = new Date(Number(ms));
      return isNaN(d.getTime()) ? "—" : d.toLocaleDateString(i18n.idioma, { day: "numeric", month: "short", year: "numeric" });
    };
    const fechaMs = (ms) => fechaHora(new Date(Number(ms)).toISOString());
    const hora = (ms) => {
      const d = new Date(Number(ms));
      return isNaN(d.getTime()) ? "—" : d.toLocaleTimeString(i18n.idioma, { hour: "2-digit", minute: "2-digit" });
    };
    let J = {};            // las jugadas del robot (lib_piloto: estrategia, velas, rr e historia de cada entrada)
    const TIEMPO = { "5m": "5 min", "1h": "1 hora", "4h": "4 horas" };
    // Lo que dice la historia de una jugada, en una frase. Sin historia, se dice.
    function historia(h) {
      if (!h || !h.n) return frase("Todavía no tengo historia de esta jugada.", {});
      return frase("En el pasado ganó {g} de {n} veces ({pct}) y dejó {neto} por operación en promedio.", {
        g: numero(h.ganadas, 0), n: numero(h.n, 0), pct: porcentaje(h.gana, 0),
        neto: `${h.neto_medio > 0 ? "+" : ""}${porcentaje(h.neto_medio, 2)}` });
    }
    const signo = (x) => (typeof x !== "number" || Math.abs(x) < 1e-9 ? "igual" : (x > 0 ? "sube" : "baja"));
    const conSigno = (x, f) => `${x > 0 ? "+" : ""}${f(x)}`;

    // ── Un gráfico de línea (la curva de un perfil, con BTC al lado si se pide) ──
    function curva(series, opciones = {}) {
      const todas = series.flatMap((s) => s.puntos || []);
      if (todas.length < 2) return "";
      const x0 = opciones.desde ?? Math.min(...todas.map((q) => q[0])), x1 = opciones.hasta ?? Math.max(...todas.map((q) => q[0]));
      // El eje vertical puede venir fijo (la película: que no salte mientras se dibuja).
      const ys = [...todas, ...(opciones.fijos || [])].map((q) => q[1]);
      let y0 = Math.min(opciones.base ?? Infinity, ...ys);
      let y1 = Math.max(opciones.base ?? -Infinity, ...ys);
      const margen = (y1 - y0) * 0.08 || 1;
      y0 -= margen; y1 += margen;
      const an = opciones.ancho || 600, al = opciones.alto || 200;
      const X = (v) => (4 + (an - 8) * (v - x0) / Math.max(1, x1 - x0)).toFixed(1);
      const Y = (v) => (4 + (al - 8) * (1 - (v - y0) / (y1 - y0))).toFixed(1);
      const linea = (q) => q.map(([x, y]) => `${X(x)},${Y(y)}`).join(" ");
      const marca = opciones.marca;
      return `<svg viewBox="0 0 ${an} ${al}" preserveAspectRatio="none" role="img" aria-label="${esc(opciones.etiqueta || "")}">
        ${opciones.base != null ? `<line class="sim-base" x1="4" x2="${an - 4}" y1="${Y(opciones.base)}" y2="${Y(opciones.base)}" stroke-dasharray="4 4" vector-effect="non-scaling-stroke"/>` : ""}
        ${series.filter((s) => (s.puntos || []).length > 1).map((s) => `<polyline class="${s.clase}" points="${linea(s.puntos)}" fill="none" vector-effect="non-scaling-stroke"/>`).join("")}
        ${marca ? `<line class="peli-marca" x1="${X(marca)}" x2="${X(marca)}" y1="4" y2="${al - 4}" vector-effect="non-scaling-stroke"/>` : ""}
      </svg>`;
    }

    // ── Los movimientos en palabras ──
    // Una línea del registro de prueba (bin/lib_registro.py), como la cuenta el robot.
    // El nombre de una persona desde su id del registro («donald-trump» → «Donald Trump»): el registro solo guarda códigos.
    const persona = (id) => esc(String(id || "").split("-").filter(Boolean).map((p) => p[0].toUpperCase() + p.slice(1)).join(" ") || Tp("una persona influyente"));
    function textoLinea(l) {
      const o = l.orden || {}, r = l.resultado || {}, m = moneda(l.par);
      switch (l.razon) {
        case "perfil_empezado": return frase("Empecé con {monto} ficticios, en perfil {perfil}.", { monto: usdt(r.saldo), perfil: Tp(nombre(r.perfil)) });
        case "perfil_detenido": return frase("Me detuviste (perfil {perfil}). Lo abierto sigue protegido.", { perfil: Tp(nombre(r.perfil)) });
        case "compra_holding": return ({
            limite: frase("Compré {cantidad} {moneda} a {precio} ({monto}): el precio bajó hasta mi orden.", { cantidad: numero(o.cantidad, 6), moneda: m, precio: usdt(o.precio), monto: usdt(o.monto) }),
            recompra: frase("Recompré {moneda} a {precio} ({monto}): cayó desde que coseché.", { moneda: m, precio: usdt(o.precio), monto: usdt(o.monto) }),
            rebalanceo: frase("Rebalanceo: compré {monto} de {moneda} a {precio} porque cripto quedó bajo su parte.", { moneda: m, precio: usdt(o.precio), monto: usdt(o.monto) }),
          })[r.por] || frase("Compré {cantidad} {moneda} a {precio} ({monto}).", { cantidad: numero(o.cantidad, 6), moneda: m, precio: usdt(o.precio), monto: usdt(o.monto) });
        case "venta_holding": return r.por === "rebalanceo"
          ? frase("Rebalanceo: vendí {monto} de {moneda} a {precio} porque cripto pasó de su parte.", { moneda: m, precio: usdt(o.precio), monto: usdt(o.monto) })
          : frase("Coseché {moneda}: vendí {monto} a {precio} y gané {neto}. Guardo esa plata para recomprar si baja.", { moneda: m, precio: usdt(o.precio), monto: usdt(o.monto), neto: usdt(r.neto || 0) });
        case "rotacion_compra": return frase("Pasé a {moneda}: compré {monto} a {precio}. Es la número {puesto} de las 8 en fuerza.", { moneda: m, monto: usdt(o.monto), precio: usdt(o.precio), puesto: numero(r.puesto || 0, 0) });
        case "rotacion_venta": {
          const gano = (r.neto || 0) >= 0, neto = usdt(Math.abs(r.neto || 0)), d = { moneda: m, precio: usdt(o.precio), neto, persona: persona(r.motivo), fecha: esc(r.fecha || "") };
          if (r.por === "noticia") return gano ? frase("Salí de {moneda} por una mala noticia de {persona} sobre BTC ({fecha}). Vendí a {precio} y gané {neto}.", d) : frase("Salí de {moneda} por una mala noticia de {persona} sobre BTC ({fecha}). Vendí a {precio} y perdí {neto}.", d);
          if (r.por === "btc") return gano ? frase("Salí de {moneda}: BTC viene cayendo. Vendí a {precio} y gané {neto}.", d) : frase("Salí de {moneda}: BTC viene cayendo. Vendí a {precio} y perdí {neto}.", d);
          return gano ? frase("Salí de {moneda}: se cayó del grupo de las más fuertes. Vendí a {precio} y gané {neto}.", d)
            : frase("Salí de {moneda}: se cayó del grupo de las más fuertes. Vendí a {precio} y perdí {neto}.", d);
        }
        case "tendencia_compra": return r.por === "ajuste"
          ? frase("Ajusté {moneda} a su parte: compré {monto} a {precio}.", { moneda: m, monto: usdt(o.monto), precio: usdt(o.precio) })
          : frase("{moneda} cerró sobre su promedio de 50 días: compré {monto} a {precio}.", { moneda: m, monto: usdt(o.monto), precio: usdt(o.precio) });
        case "tendencia_venta": {
          const d = { moneda: m, monto: usdt(o.monto), precio: usdt(o.precio), neto: usdt(Math.abs(r.neto || 0)), persona: persona(r.motivo), fecha: esc(r.fecha || "") };
          const porque = { bajo_media: "{moneda} cerró bajo su promedio de 50 días.", noticia: "Mala noticia de {persona} ({fecha}).",
            ajuste: "Ajusté {moneda} a su parte.", freno: "Hay un freno de la cuenta." }[r.por] || "";
          return `${porque ? frase(porque, d) + " " : ""}${(r.neto || 0) >= 0 ? frase("Vendí {monto} de {moneda} a {precio} y gané {neto}.", d) : frase("Vendí {monto} de {moneda} a {precio} y perdí {neto}.", d)}`;
        }
        case "tendencia_espera": return r.por === "noticia"
          ? frase("No compré {moneda}: hubo una mala noticia de {persona} ({fecha}). Espero en USDT unos días.", { moneda: m, persona: persona(r.motivo), fecha: esc(r.fecha || "") })
          : frase("No compré {moneda}: cayó {caida} en un día esta semana. Espero unos días.", { moneda: m, caida: porcentaje(Math.abs(r.caida || 0), 1) });
        case "entrada_ruptura": case "entrada_rebote":
          if (J[o.id] && o.estado !== "llenada") {
            return `${frase("Dejé una compra de {moneda} esperando en {precio} ({monto}), con stop en {stop} y objetivo en {objetivo}.", { moneda: m, precio: usdt(o.precio), monto: usdt(o.monto), stop: usdt(o.stop), objetivo: usdt(o.objetivo) })}
              <span class="mov-prob">${frase("Gano {rr} por cada 1 que arriesgo.", { rr: numero(J[o.id].rr, 1) })} ${historia(J[o.id].historia)}</span>`;
          }
          return o.estado === "llenada"
            ? frase("Se llenó mi compra de {moneda} a {precio} ({monto}). Queda protegida: stop en {stop} y objetivo en {objetivo}.", { moneda: m, precio: usdt(o.precio), monto: usdt(o.monto), stop: usdt(o.stop), objetivo: usdt(o.objetivo) })
            : frase("Dejé una compra de {moneda} esperando en {precio} ({monto}), con stop en {stop} y objetivo en {objetivo}.", { moneda: m, precio: usdt(o.precio), monto: usdt(o.monto), stop: usdt(o.stop), objetivo: usdt(o.objetivo) });
        case "objetivo": return frase("Vendí {moneda} en el objetivo, a {precio}: gané {neto}.", { moneda: m, precio: usdt(r.precio), neto: usdt(r.neto) });
        case "stop": return frase("Vendí {moneda} en el stop, a {precio}: perdí {neto}.", { moneda: m, precio: usdt(r.precio), neto: usdt(Math.abs(r.neto || 0)) });
        case "stop_movil": return frase("Vendí {moneda} con el stop móvil, a {precio}: dejó {neto}.", { moneda: m, precio: usdt(r.precio), neto: usdt(r.neto) });
        case "cierre_manual": return frase("Cerraste {moneda} a {precio}: dejó {neto}.", { moneda: m, precio: usdt(r.precio), neto: usdt(r.neto) });
        case "propuesta_vencida": return frase("Mi compra de {moneda} no se llenó a tiempo: la cancelé.", { moneda: m });
        case "rechazo": return frase("Vi una oportunidad en {moneda}, pero no entré: {motivo}.", { moneda: m || "—", motivo: Tp(motivoCorto(r.motivo)) });
        case "saldo_reiniciado": return frase("El saldo de prueba quedó en {monto}.", { monto: usdt(r.saldo) });
        case "freno_diario": return frase("Freno del día: perdí el 5 % hoy y no abro nada más hasta mañana.", {});
        case "freno_racha": return frase("Cuatro pérdidas seguidas: paro de abrir por hoy.", {});
        case "freno_piso": case "freno_piso_absoluto": return frase("Bajé del piso: no abro nada nuevo.", {});
        default: return frase("Quedó anotado.", {});
      }
    }
    const claseLinea = (l) => ({ objetivo: "gana", stop: "pierde", stop_movil: (l.resultado || {}).neto > 0 ? "gana" : "pierde",
      compra_holding: "compra", venta_holding: (l.resultado || {}).neto >= 0 ? "gana" : "pierde", rotacion_compra: "compra", rotacion_venta: (l.resultado || {}).neto >= 0 ? "gana" : "pierde", tendencia_compra: "compra", tendencia_venta: (l.resultado || {}).neto >= 0 ? "gana" : "pierde", tendencia_espera: "espera", entrada_ruptura: "compra", entrada_rebote: "compra", rechazo: "nada", propuesta_vencida: "nada" })[l.razon] || "info";
    function filaLinea(l) {
      return `<li class="mov" data-tipo="${claseLinea(l)}"><span class="mov-punto" aria-hidden="true"></span>
        <span class="mov-cuando" data-sin-traducir>${esc(fechaHora(l.fecha))}</span>
        <span class="mov-texto">${textoLinea(l)}</span></li>`;
    }
    // Un movimiento de la simulación (bin/lib_simulacion.py: movimientos).
    function textoMov(v) {
      const m = moneda(v.par);
      if (v.que === "venta" && (v.por === "cosecha" || v.por === "rebalanceo")) {
        return v.por === "cosecha"
          ? frase("Coseché {moneda} a {precio}: dejó {neto}. Saldo: {saldo}.", { moneda: m, precio: usdt(v.precio), neto: usdt(v.ganancia || 0), saldo: usdt(v.saldo) })
          : frase("Rebalanceo: vendí {moneda} a {precio} porque cripto pasó de su parte. Saldo: {saldo}.", { moneda: m, precio: usdt(v.precio), saldo: usdt(v.saldo) });
      }
      if (v.que === "venta" && v.por === "tendencia") {
        return frase("Vendí {moneda} a {precio}: cayó bajo su promedio o sobraba. Dejó {neto}. Saldo: {saldo}.", { moneda: m, precio: usdt(v.precio), neto: usdt(v.ganancia || 0), saldo: usdt(v.saldo) });
      }
      if (v.que === "venta" && v.por === "rotacion") {
        return frase("Vendí {moneda} a {precio}: pasé a una más fuerte. Dejó {neto}. Saldo: {saldo}.", { moneda: m, precio: usdt(v.precio), neto: usdt(v.ganancia || 0), saldo: usdt(v.saldo) });
      }
      if (v.que === "compra") {
        return v.estrategia === "holding" || v.estrategia === "rotacion" || !v.stop
          ? frase("Compré {monto} de {moneda} a {precio}.", { monto: usdt(v.monto), moneda: m, precio: usdt(v.precio) })
          : frase("Compré {monto} de {moneda} a {precio}, con stop en {stop} y objetivo en {objetivo}.", { monto: usdt(v.monto), moneda: m, precio: usdt(v.precio), stop: usdt(v.stop), objetivo: usdt(v.objetivo) });
      }
      return v.por === "objetivo"
        ? frase("Vendí {moneda} en el objetivo, a {precio}: gané {neto}. Saldo: {saldo}.", { moneda: m, precio: usdt(v.precio), neto: usdt(v.ganancia), saldo: usdt(v.saldo) })
        : frase("Vendí {moneda} en el stop, a {precio}: perdí {neto}. Saldo: {saldo}.", { moneda: m, precio: usdt(v.precio), neto: usdt(Math.abs(v.ganancia || 0)), saldo: usdt(v.saldo) });
    }
    const claseMov = (v) => (v.que === "compra" ? "compra" : (v.ganancia > 0 ? "gana" : "pierde"));

    // ── Elegir perfil y monto ──
    // ── Qué dijo el pasado de cada perfil (la última comparación): si le ganó a quedarse en USDT y a comprar BTC ──
    const diasDe = (p) => Math.max(1, Math.round(((p.hasta_ms || 0) - (p.desde_ms || 0)) / 86400000));
    // El período en palabras: «3 años» se entiende mejor que «1095 días».
    const periodo = (p) => {
      const d = diasDe(p), anos = Math.round(d / 365);
      if (d >= 330) return anos === 1 ? Tp("1 año") : Tp("{n} años", { n: numero(anos, 0) });
      if (d >= 58) return Tp("{n} meses", { n: numero(Math.round(d / 30), 0) });
      return Tp("{n} días", { n: numero(d, 0) });
    };
    function veredicto(p, r) {
      if (!p || p.listo === false || typeof p.rendimiento !== "number") return null;
      const btc = (r || {}).btc || {};
      // Contra BTC solo se compara en el mismo período: el scalper mira menos días y ahí no sería justo.
      const conBtc = !p.recortado && typeof btc.rendimiento === "number";
      if (p.rendimiento <= 0) return "pierde";
      return conBtc && p.rendimiento < btc.rendimiento ? "gana_usdt" : "gana_todo";
    }
    function textoVeredicto(v, p) {
      if (v === "pierde") return frase("Perdió {pct} en {periodo}: te habría ido mejor quedándote en USDT.", { pct: porcentaje(Math.abs(p.rendimiento), 1), periodo: periodo(p) });
      if (v === "gana_usdt") return frase("Ganó, pero menos que comprar BTC y esperar.", {});
      return frase("Le ganó a quedarte en USDT y a comprar BTC.", {});
    }
    // Los perfiles que perdieron en la última comparación: no se ofrecen como uno más, quedan aparte para experimentar.
    function perdedores(E) {
      const r = (E.sim || {}).ultima || {};
      return Object.fromEntries((r.perfiles || []).filter((p) => veredicto(p, r) === "pierde").map((p) => [p.perfil, p]));
    }
    // Sin elegir nada todavía, el perfil de partida es el que mejor le fue entre los que no perdieron.
    function perfilDePartida(E) {
      const fuera = perdedores(E);
      if (E.vivoPerfilTocado || !fuera[E.vivoPerfil]) return E.vivoPerfil || "holding";
      const r = (E.sim || {}).ultima || {};
      const mejor = (r.perfiles || []).filter((p) => !fuera[p.perfil] && typeof p.rendimiento === "number")
        .sort((a, b) => b.rendimiento - a.rendimiento)[0];
      if (mejor) E.vivoPerfil = mejor.perfil;
      return E.vivoPerfil;
    }
    function botonPerfil(p, elegido, perdio) {
      return `<button type="button" class="perfil" role="radio" data-perfil="${p}" aria-checked="${p === elegido}"${perdio ? ` data-perdio="1"` : ""}>
            <span class="perfil-nombre">${PERFILES[p].nombre}</span>
            <span class="perfil-ritmo">${PERFILES[p].ritmo}</span>
            <span class="perfil-que">${PERFILES[p].que}</span>
            <span class="perfil-monedas" data-sin-traducir>${esc(MONEDAS[p].join(" · "))}</span>
            ${perdio ? `<span class="perfil-perdio">${frase("Perdió {pct} en {periodo}", { pct: porcentaje(Math.abs(perdio.rendimiento), 1), periodo: periodo(perdio) })}</span>` : ""}</button>`;
    }
    function selector(E, opciones = {}) {
      const elegido = perfilDePartida(E);
      const fuera = perdedores(E);
      const buenos = ORDEN.filter((p) => !fuera[p]), malos = ORDEN.filter((p) => fuera[p] && enMercado(p, mercadoElegido(E)));
      const monto = E.campos["vivo-monto"] || E.vivoMonto || 100;
      return `<div class="tarjeta vivo-elegir">
        <h3>${opciones.titulo || "Elige cómo quieres que opere"}</h3>
        ${chipsMercado(E)}
        <div class="perfiles-grupos" role="radiogroup" aria-label="Perfil">${GRUPOS.map(([id, titulo, suyos]) => {
          const estos = suyos.filter((p) => buenos.includes(p) && enMercado(p, mercadoElegido(E)));
          return estos.length ? `<section class="perfiles-grupo" data-grupo="${id}"><h4>${titulo}</h4>
            <p class="ayuda">${GRUPO_AYUDA[id]}</p>
            <div class="perfiles">${estos.map((p) => botonPerfil(p, elegido)).join("")}</div></section>` : "";
        }).join("")}</div>
        ${malos.length ? `<details class="perfiles-perdedores"${fuera[elegido] ? " open" : ""}>
          <summary>${frase("Perfiles que perdieron en el pasado ({n}): solo para experimentar", { n: numero(malos.length, 0) })}</summary>
          <p class="ayuda">En la última comparación perdieron plata con sus reglas de hoy. Puedes probarlos con dinero ficticio para ver cómo operan, pero no son una buena opción para tu plata.</p>
          <div class="perfiles" role="radiogroup" aria-label="Perfiles que perdieron">${malos.map((p) => botonPerfil(p, elegido, fuera[p])).join("")}</div></details>` : ""}
        ${fuera[elegido] ? `<p class="freno-texto">${frase("Ojo: {perfil} perdió {pct} en la última comparación. Úsalo solo para ver cómo opera.", { perfil: Tp(nombre(elegido)), pct: porcentaje(Math.abs(fuera[elegido].rendimiento), 1) })}</p>` : ""}
        <label class="campo-monto"><span>¿Con cuánto dinero ficticio?</span>
          <span class="campo-monto-caja"><input id="vivo-monto" type="number" inputmode="decimal" min="10" max="1000000" step="1" value="${esc(monto)}"><span data-sin-traducir>USDT</span></span></label>
        <div class="chips" role="group" aria-label="Montos sugeridos">${MONTOS.map((m) => `<button type="button" class="chip" data-vivo-monto="${m}" aria-pressed="${Number(monto) === m}" data-sin-traducir>${esc(numero(m, 0))}</button>`).join("")}</div>
        ${E.real && E.real.activo ? `<p class="freno-texto">Con el dinero real encendido no hago pruebas: primero vuelve a prueba en «Dinero real».</p>` : ""}
        <button type="button" class="pz-boton pz-principal boton-ancho" id="vivo-empezar"${E.vivoOcupado || (E.real && E.real.activo) ? " disabled" : ""}>${E.vivoOcupado ? "Empezando…" : frase("Empezar con {monto} ficticios", { monto: usdt(Math.round(Number(monto) || 100)) })}</button>
        <p class="ayuda">Empezar deja tu saldo de prueba en ese monto. Nada de esto toca tu dinero de Binance.</p></div>`;
    }

    // ── En vivo ──
    function vuelta(v) {
      if (!v || !v.ultima || !v.ultima.decision) return "Todavía no doy mi primera vuelta: en unos minutos te cuento qué vi.";
      const u = v.ultima;
      const plantilla = VUELTA[u.decision];
      if (!plantilla) return "Estoy mirando.";
      const lista = (xs) => (xs || []).map(moneda).join(", ") || "—";
      if (v.perfil === "tendencia" && ["esperando", "mantiene", "sin_senal"].includes(u.decision)) {
        return frase("Ya miré los promedios hoy. Vuelvo a mirar cuando cierre la vela del día, a las {hora}.", { hora: hora(u.proxima_ms || (((v.tendencia || {}).dia_ms || 0) + 86400000)) });
      }
      if (u.decision === "esperando" && v.perfil === "rotacion") {
        return frase("Ya comparé las 8 hoy. Vuelvo a comparar cuando cierre la vela del día, a las {hora}.", { hora: hora(u.proxima_ms) });
      }
      return frase(plantilla, { motivo: Tp(motivoCorto(u.motivo)), n: numero(u.parte || 0, 0), fecha: dia(u.proxima_ms),
        salen: lista(u.salen), entran: lista(u.entran), tiene: lista(u.tiene), compra: lista(u.compra), vende: lista(u.vende) });
    }
    // ── Qué estoy esperando (bin/lib_radar.py): el gatillo de cada estrategia, cuánto falta, la operación y su historia ──
    const NOMBRE_ESTRATEGIA = { rebote: "rebote", ruptura: "ruptura" };
    function porQueNo(e, fila) {
      if (/^btc|^sin_contexto/.test(e.motivo || "")) return frase("BTC viene cayendo: no compro nada hasta que se calme.", {});
      switch (e.motivo) {
        case "dia_no_al_alza": return frase("Ruptura: no, el día no viene al alza.", {});
        case "con_rumbo": return frase("Rebote: no, el precio tiene rumbo (fuerza {adx}; pido {max} o menos para comprar en la banda de abajo).", { adx: numero(fila.adx || 0, 0), max: numero(e.adx_maximo || 20, 0) });
        case "sin_volumen": return frase("Ruptura: rompió el techo, pero sin volumen ({rel} veces lo normal; pido {pide}).", { rel: numero(fila.volumen_relativo || 0, 1), pide: numero(e.volumen_pide || 1.5, 1) });
        case "sin_datos": return frase("Me faltan velas para mirar esto.", {});
        default:
          if (e.sirve === false) {
            return e.estrategia === "rebote"
              ? frase("Rebote: aunque llegue, gana poco para lo que arriesga ({rr} por 1; este perfil pide {pide}).", { rr: numero(e.rr || 0, 1), pide: numero(e.rr_pide || 0, 1) })
              : frase("Ruptura: aunque rompa, gana poco para lo que arriesga ({rr} por 1; este perfil pide {pide}).", { rr: numero(e.rr || 0, 1), pide: numero(e.rr_pide || 0, 1) });
          }
          return "";
      }
    }
    // La operación posible en cinco cifras que se leen de un vistazo: entrada, stop, objetivo, ganancia por riesgo e historia.
    function cifras(e) {
      if (!(e.entrada > 0)) return "";
      const h = e.historia;
      const tono = !h || !h.n ? "igual" : (h.neto_medio > 0 ? "sube" : "baja");
      const celda = (titulo, valor, extra = "", clase = "") => `<div class="cifra ${clase}"><dt>${titulo}</dt><dd data-sin-traducir>${esc(valor)}</dd>${extra}</div>`;
      return `<dl class="radar-cifras">
        ${celda("Entraría en", usdt(e.entrada))}
        ${celda("Stop", usdt(e.stop), `<span class="cifra-nota baja" data-sin-traducir>${esc(porcentaje((e.stop - e.entrada) / e.entrada, 2))}</span>`)}
        ${celda("Objetivo", usdt(e.objetivo), `<span class="cifra-nota sube" data-sin-traducir>${esc(`+${porcentaje((e.objetivo - e.entrada) / e.entrada, 2)}`)}</span>`)}
        ${celda("Gana por cada 1 que arriesga", numero(e.rr || 0, 1))}
        ${celda("Ganó en el pasado", h && h.n ? porcentaje(h.gana, 0) : "–",
          h && h.n ? `<span class="cifra-nota">${frase("de {n} veces", { n: numero(h.n, 0) })}</span>` : "", `tono-${tono}`)}
      </dl>`;
    }
    function plan(e) {
      if (!(e.entrada > 0)) return "";
      return frase("Entraría en {entrada} · stop {stop} ({pierde}) · objetivo {objetivo} ({gana}) · gano {rr} por cada 1 que arriesgo.", {
        entrada: usdt(e.entrada), stop: usdt(e.stop), pierde: porcentaje((e.stop - e.entrada) / e.entrada, 2),
        objetivo: usdt(e.objetivo), gana: `+${porcentaje((e.objetivo - e.entrada) / e.entrada, 2)}`, rr: numero(e.rr || 0, 1) });
    }
    function gatillo(e, fila) {
      const m = moneda(fila.par), falta = porcentaje(Math.max(0, e.distancia || 0), 2);
      if (e.motivo === "listo") return frase("¡Se cumple! {moneda} cerró donde quería: pongo la compra ahora.", { moneda: m });
      if (fila.condicion === "con_rumbo") {
        return frase("Cuando el precio se calme (fuerza {adx} ahora; pido {max} o menos), compro {moneda} si una vela cierra en {precio} o menos.",
          { adx: numero(fila.adx || 0, 0), max: numero(e.adx_maximo || 20, 0), moneda: m, precio: usdt(e.gatillo) });
      }
      return e.estrategia === "rebote"
        ? frase("Compro {moneda} por rebote si una vela cierra en {precio} o menos (falta {falta}).", { moneda: m, precio: usdt(e.gatillo), falta })
        : frase("Compro {moneda} por ruptura si una vela cierra sobre {precio} con volumen (falta {falta}).", { moneda: m, precio: usdt(e.gatillo), falta });
    }
    // La cercanía como barra: llena cuando está en el gatillo, vacía a 2 % o más.
    function cercania(e) {
      const x = Math.max(0, Math.min(1, 1 - Math.max(0, e.distancia || 0) / 0.02));
      return `<svg class="radar-barra" viewBox="0 0 100 6" preserveAspectRatio="none" aria-hidden="true">
        <rect class="pista" x="0" y="0" width="100" height="6" rx="3"/><rect class="valor" x="0" y="0" width="${(x * 100).toFixed(1)}" height="6" rx="3"/></svg>`;
    }
    const rebote = (f) => (f.estrategias || []).find((e) => e.estrategia === "rebote" && e.sirve && e.gatillo > 0);
    // Lo más cerca de comprar va primero: «casi casi», después lo que espera (de lo más cerca a lo más lejos) y al final
    // lo que no tiene jugada. Así las primeras filas (y los gráficos de «Lo que ve el robot») son las que importan.
    const VISIBLES_RADAR = 4;
    function ordenFilas(filas) {
      const peso = (f) => (f.cerca ? 0 : (f.espera ? 1 : 2));
      const dist = (f) => {
        const e = (f.estrategias || []).find((x) => x.estrategia === f.espera);
        return e ? Math.abs(e.distancia || 0) : 9;
      };
      return [...filas].sort((a, b) => peso(a) - peso(b) || dist(a) - dist(b));
    }
    // La rotación no espera un precio: ordena las 8 por fuerza y tiene las mejores. Su tarjeta es ese ranking.
    function ranking(E) {
      const v = E.vivo || {}, r = v.rotacion || {}, filas = r.ranking || [];
      const tengo = new Set((v.tenencias || []).filter((t) => t.cantidad > 0).map((t) => t.par));
      if (!filas.length) {
        return `<div class="tarjeta ranking"><h3>Ranking de fuerza</h3>
          <p class="suave">Estoy preparando las 8 monedas. En cuanto tenga sus velas diarias, las ordeno de la más fuerte a la más débil.</p></div>`;
      }
      const maximo = Math.max(...filas.map((f) => Math.abs(f.fuerza || 0)), 0.0001);
      return `<div class="tarjeta ranking"><h3>Ranking de fuerza</h3>
        ${r.noticia ? `<p class="freno-texto">${frase("Mala noticia de {persona} sobre BTC ({fecha}): no tengo ninguna moneda y espero en USDT unos días.", { persona: esc(r.noticia.persona || ""), fecha: esc(r.noticia.fecha || "") })}</p>` : ""}
        ${Object.keys(r.golpes || {}).length ? `<p class="suave">${frase("No compro {monedas} por unos días: cayeron 5 % o más en un día esta semana.", { monedas: esc(Object.keys(r.golpes).map(moneda).join(", ")) })}</p>` : ""}
        ${r.pasa_btc === false ? `<p class="freno-texto">${frase("BTC viene cayendo: no tengo ninguna moneda y espero en USDT.", {})}</p>`
          : `<p class="suave">${frase("Tengo las 2 primeras que están sobre su promedio. Vuelvo a comparar cuando cierra la vela del día, a las {hora}.", { hora: hora((r.dia_ms || 0) + 86400000) })}</p>`}
        <ol class="ranking-filas">${filas.map((f) => {
          const estado = tengo.has(f.par) ? "tengo" : (f.elegible ? "puede" : "no");
          const ancho = Math.max(2, Math.round(Math.abs(f.fuerza || 0) / maximo * 100));
          return `<li class="ranking-fila" data-estado="${estado}">
            <span class="ranking-puesto" data-sin-traducir>${esc(numero(f.puesto, 0))}</span>
            <strong class="ranking-moneda" data-sin-traducir>${esc(moneda(f.par))}</strong>
            <svg class="ranking-barra" viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true" focusable="false">
              <rect x="0" y="0" width="100" height="8" rx="4" class="ranking-fondo"/>
              <rect x="0" y="0" width="${ancho}" height="8" rx="4" class="ranking-relleno" data-signo="${signo(f.fuerza || 0)}"/></svg>
            <span class="ranking-cambio" data-signo="${signo(f.retorno || 0)}" data-sin-traducir>${esc(conSigno(f.retorno || 0, (x) => porcentaje(x, 1)))}</span>
            <span class="radar-estado" data-estado="${estado === "tengo" ? "casi" : (estado === "puede" ? "espera" : "nada")}">${
              estado === "tengo" ? "La tengo" : (estado === "puede" ? "Podría entrar" : ((f.retorno || 0) <= 0 ? "Viene cayendo" : "Bajo su promedio"))}</span></li>`;
        }).join("")}</ol>
        <p class="ayuda">Fuerza: cuánto subió en 30 días, dividido por cuánto se movió en el camino. Gana la que sube más parejo, no la que más salta. Solo entra una moneda que está sobre su promedio de 50 días, y cambio una solo cuando se cae del grupo: cada cambio paga comisión.</p></div>`;
    }
    // La tendencia no espera un precio de entrada: mira si cada moneda está sobre su promedio de 50 días. Su tarjeta es eso.
    function cruce(E) {
      const v = E.vivo || {}, t = v.tendencia || {}, filas = t.filas || [];
      if (!filas.length) {
        return `<div class="tarjeta ranking"><h3>Sobre o bajo su promedio</h3>
          <p class="suave">Estoy preparando BTC y ETH. En cuanto tenga sus velas diarias, te muestro si están sobre su promedio de 50 días.</p></div>`;
      }
      return `<div class="tarjeta ranking"><h3>Sobre o bajo su promedio</h3>
        ${t.frenado ? `<p class="freno-texto">Hay un freno puesto: vendí todo y espero en USDT.</p>`
          : `<p class="suave">${frase("Vuelvo a mirar cuando cierra la vela del día, a las {hora}.", { hora: hora((t.dia_ms || 0) + 86400000) })}</p>`}
        <ol class="ranking-filas">${filas.map((f) => `<li class="ranking-fila" data-estado="${f.sobre ? "tengo" : "no"}">
            <span class="ranking-moneda" data-sin-traducir>${esc(moneda(f.par))}</span>
            <span class="ranking-cambio" data-signo="${signo(f.precio / f.media - 1)}" data-sin-traducir>${esc(conSigno(f.precio / f.media - 1, (x) => porcentaje(x, 1)))}</span>
            <span class="radar-estado" data-estado="${f.parte > 0 ? "casi" : "nada"}">${!f.sobre
              ? frase("Bajo su promedio ({media}): su {pct} espera en USDT", { media: usdt(f.media), pct: porcentaje(f.reparto, 0) })
              : f.motivo === "noticia" && f.noticia
                ? frase("Sobre su promedio, pero hubo una mala noticia de {persona} el {fecha}: su {pct} espera en USDT unos días", { persona: esc(f.noticia.persona), fecha: esc(f.noticia.fecha), pct: porcentaje(f.reparto, 0) })
                : f.motivo === "golpe"
                  ? frase("Sobre su promedio, pero esta semana cayó {caida} en un día: no compro su {pct} por unos días", { caida: porcentaje(Math.abs(f.golpe || 0), 1), pct: porcentaje(f.reparto, 0) })
                  : frase("Sobre su promedio ({media}): tengo {pct}", { media: usdt(f.media), pct: porcentaje(f.reparto, 0) })}</span></li>`).join("")}</ol>
        <p class="ayuda">El número es cuánto está el precio sobre o bajo su promedio de los últimos 50 días. Cuando pasa de un lado al otro, compro o vendo esa parte.</p></div>
        ${comoDecido()}
        ${quePaso(filas)}
        ${noticias(v.noticias)}`;
    }
    // Cómo pesa cada cosa en la decisión, con lo que mejoró en el estudio de nov 2026 (AGENTS.md: «Los perfiles y el robot
    // en vivo»). Los números son de las ventanas de prueba (desde nov 2023), las que nadie miró al elegir las reglas.
    function comoDecido() {
      const filas = [
        ["Precio sobre su promedio de 50 días", "Si está sobre, compro su parte; si está bajo, espera en USDT.", "Base: le ganó a BTC en 64 de cada 100 ventanas"],
        ["Un día de −5 % o peor en la semana", "No compro por 5 días; lo que ya tengo, lo mantengo.", "Ganancia típica: +28 % contra +24 %"],
        ["Mala noticia de una persona influyente", "Esa parte espera en USDT 5 días.", "Peor ventana de 1 año: −5 % contra −8 %"],
        ["Las tres juntas (lo que hago)", "", "Le ganó a BTC en 67 de cada 100 ventanas; ganancia típica +30 %"]];
      return `<div class="tarjeta como-decido"><h3>Cómo decido</h3>
        <div class="mapa-caja"><table class="mapa-tabla"><thead><tr><th scope="col">Qué miro</th><th scope="col">Qué hago</th><th scope="col">Qué cambió en las pruebas</th></tr></thead>
          <tbody>${filas.map(([a, b, c]) => `<tr><th scope="row">${Tp(a)}</th><td>${b ? Tp(b) : ""}</td><td>${Tp(c)}</td></tr>`).join("")}</tbody></table></div>
        <p class="ayuda">Probé 6.000 mezclas de indicadores con pesos y ninguna superó a estas reglas simples. Acertar si sube o baja sigue siendo 51 a 58 de cada 100 veces: la ventaja está en perder menos en las caídas.</p></div>`;
    }
    // Lo que pasó antes cuando cada moneda estaba del mismo lado de su promedio que hoy (lib_tendencia.historia_cruce).
    function quePaso(filas) {
      const con = filas.filter((f) => f.historia);
      if (!con.length) return "";
      const de100 = (x) => numero(Math.round(x * 100), 0);
      return `<div class="tarjeta pronostico"><h3>¿Qué pasó antes en un día como hoy?</h3>
        <ul class="pronostico-filas">${con.map((f) => { const h = f.historia; return `<li>
          <strong data-sin-traducir>${esc(moneda(f.par))}</strong> ${frase(h.sobre
            ? "Las {dias} veces que estuvo sobre su promedio, a los {h} días había subido {sube} de cada 100 veces (en promedio {medio}) y en {cae} de cada 100 cayó más de 10 % en el camino."
            : "Las {dias} veces que estuvo bajo su promedio, a los {h} días había subido {sube} de cada 100 veces (en promedio {medio}) y en {cae} de cada 100 cayó más de 10 % en el camino.",
            { dias: numero(h.dias, 0), h: numero(h.horizonte, 0), sube: de100(h.sube), medio: conSigno(h.medio, (x) => porcentaje(x, 1)), cae: de100(h.cae) })}</li>`; }).join("")}</ul>
        <p class="ayuda">Acertar si sube o baja es casi tirar una moneda: 51 a 58 de cada 100 veces, con o sin noticias. La ventaja de la tendencia está en otra parte: sobre el promedio, la ganancia media fue mayor y las caídas grandes, menos seguidas.</p></div>`;
    }
    // Las noticias de las personas que mueven el precio (bin/influencia.json, del repo pilota-app/influencia).
    function noticias(N) {
      if (!N) return "";
      const lista = N.eventos || [];
      return `<div class="tarjeta noticias"><h3>Noticias de personas influyentes</h3>
        ${lista.length ? `<ul class="noticias-filas">${lista.map((e) => `<li><span class="suave" data-sin-traducir>${esc(e.fecha)}</span>
            <strong data-sin-traducir>${esc(e.persona || "")}</strong> <span data-sin-traducir>${esc(e.que)}</span>
            ${e.dia == null ? "" : `<span class="ranking-cambio" data-signo="${signo(e.dia)}" data-sin-traducir>${esc(e.activo)} ${esc(conSigno(e.dia, (x) => porcentaje(x, 1)))}</span>`}</li>`).join("")}</ul>`
          : `<p class="suave">${frase("Ninguna con fecha y fuente en los últimos {n} días.", { n: numero(N.dias || 30, 0) })}</p>`}
        ${(N.ranking || []).length ? `<h4>Quién mueve más el precio hoy</h4><ol class="noticias-filas">${N.ranking.map((r) => `<li><strong data-sin-traducir>${esc(r.nombre)}</strong>
            <span class="suave">${frase("{n} noticias medidas, la última el {fecha}", { n: numero(r.eventos, 0), fecha: esc(r.ultimo || "–") })}</span></li>`).join("")}</ol>` : ""}
        <p class="ayuda">${frase("Una mala noticia de estas personas frena la compra de esa moneda por 5 días. El salto de un post pasa en minutos y muchas veces se borra el mismo día: por eso no compro por una buena noticia. Datos al {fecha}.", { fecha: esc(N.al || "–") })}</p></div>`;
    }
    function radar(E) {
      const v = E.vivo || {};
      if ((v.perfil || (v.radar || {}).perfil) === "tendencia") return cruce(E);
      if ((v.perfil || (v.radar || {}).perfil) === "rotacion") return ranking(E);
      const R = v.radar || {};
      const filas = ordenFilas(R.filas || []);
      if (!filas.length) return "";
      const frena = R.filtro && !R.filtro.pasa;
      const fila = (f) => {
          const espera = (f.estrategias || []).find((e) => e.estrategia === f.espera);
          const otras = (f.estrategias || []).filter((e) => (e !== espera || f.condicion) && !(frena && /^btc|^sin_contexto/.test(e.motivo || "")))
            .map((e) => porQueNo(e, f))
            .filter((t, i, todos) => t && todos.indexOf(t) === i)
            .filter((t) => !(f.condicion && /^Rebote|^Bounce/.test(t.replace(/<[^>]+>/g, ""))));
          return `<li class="radar-fila" data-cerca="${f.cerca ? 1 : 0}">
            <div class="radar-cabeza"><strong data-sin-traducir>${esc(moneda(f.par))}</strong>
              <span class="suave">${frase("velas de {t}", { t: Tp(TIEMPO[f.temporalidad] || f.temporalidad) })}</span>
              <span class="suave" data-sin-traducir>${esc(f.precio ? usdt(f.precio) : "")}</span>
              <span class="radar-estado" data-estado="${f.cerca ? "casi" : (frena ? "pausa" : (f.espera ? "espera" : "nada"))}">${
                f.cerca ? "Casi casi" : (frena ? "En pausa" : (f.espera ? "Esperando" : "Sin jugada"))}</span></div>
            ${espera ? `${cercania(espera)}<p class="radar-gatillo">${gatillo(espera, f)}</p>${cifras(espera)}`
              : (frena && rebote(f)
                ? `<p class="radar-gatillo">${frase("En pausa por BTC. Si no estuviera cayendo, compraría {moneda} por rebote si una vela cierra en {precio} o menos (falta {falta}).", { moneda: moneda(f.par), precio: usdt(rebote(f).gatillo), falta: porcentaje(Math.max(0, rebote(f).distancia || 0), 2) })}</p>
                  ${cifras(rebote(f))}`
                : `<p class="radar-gatillo">${frase("Nada que esperar en {moneda} por ahora: ninguna de mis dos jugadas sirve aquí.", { moneda: moneda(f.par) })}</p>`)}
            ${otras.length ? `<p class="radar-no suave">${otras.join(" ")}</p>` : ""}</li>`;
      };
      const resto = filas.slice(VISIBLES_RADAR);
      return `<div class="tarjeta radar">
        <h3>Qué estoy esperando</h3>
        ${frena ? `<p class="freno-texto">${frase("BTC viene cayendo: no compro nada hasta que se calme.", {})}</p>` : ""}
        <ul class="radar-filas">${filas.slice(0, VISIBLES_RADAR).map(fila).join("")}</ul>
        ${resto.length ? `<details class="radar-resto"><summary>${frase("Ver las otras {n}", { n: numero(resto.length, 0) })}</summary>
          <ul class="radar-filas">${resto.map(fila).join("")}</ul></details>` : ""}
        <p class="ayuda">Decido solo con velas cerradas: cuando una cierra donde dice arriba, compro en ese mismo segundo. La historia es el pasado, no una promesa.</p></div>`;
    }
    // ── El plan de un holding: cuántas compras lleva, qué orden dejó puesta y a qué precio vendería o recompraría ──
    // Sale del libro del holding (bin/lib_holding.py) y de las reglas del perfil: los mismos números que usa el robot.
    function plan(E) {
      const v = E.vivo || {}, h = v.holding || {}, R = v.reglas || {};
      if (R.tipo === "mezcla" && v.activo && (v.mezcla || []).length) {
        return `<div class="tarjeta plan" id="plan"><h3>Mi plan</h3>
          <ul class="plan-lineas">${v.mezcla.map((x) => `<li data-tipo="compra"><span class="plan-punto" aria-hidden="true"></span><span>${frase("{pct} en {perfil}: vale {valor}.", { pct: porcentaje(x.peso, 0), perfil: Tp(nombre(x.perfil)), valor: usdt(x.valor) })}</span></li>`).join("")}</ul></div>`;
      }
      if (R.tipo !== "acumular" || !v.activo) return "";
      const lineas = [];
      const partes = Number(h.partes) || 0, total = Number(R.partes) || 0;
      if (total && partes < total) {
        const prox = h.ultima_ms ? Number(h.ultima_ms) + (Number(R.cada_ms) || 604800000) : Date.now();
        lineas.push(["compra", frase("Llevo {n} de {total} compras. La próxima es el {fecha}.", { n: numero(partes, 0), total: numero(total, 0), fecha: dia(prox) })]);
      } else if (total) {
        lineas.push(["listo", frase("Ya hice las {total} compras: ahora guardo hasta que tú decidas.", { total: numero(total, 0) })]);
      }
      for (const [par, o] of Object.entries(h.pendiente || {})) {
        lineas.push(["espera", frase("Dejé una compra de {moneda} en {precio}. Si mañana el precio no llega, compro igual a ese precio.", { moneda: moneda(par), precio: usdt(o.limite) })]);
      }
      const co = R.cosecha;
      if (co) {
        for (const t of (v.tenencias || []).filter((x) => x.cantidad > 0 && x.precio_medio)) {
          if ((h.guardado || {})[t.par]) continue;
          const meta = t.precio_medio * (1 + co.sube);
          lineas.push(["espera", frase("Vendo un cuarto de {moneda} si llega a {precio} (falta {falta}).", { moneda: moneda(t.par), precio: usdt(meta), falta: porcentaje(Math.max(0, meta / (t.precio_ahora || meta) - 1), 1) })]);
        }
        for (const [par, g] of Object.entries(h.guardado || {})) {
          lineas.push(["guardado", frase("Guardé {monto} de {moneda}. Lo recompro si baja a {precio}.", { moneda: moneda(par), monto: usdt(g.monto), precio: usdt(g.precio * (1 - co.recompra)) })]);
        }
      }
      const rb = R.rebalanceo;
      if (rb && v.valor) {
        const parte = Math.max(0, (v.valor - (v.efectivo || 0)) / v.valor);
        lineas.push(["espera", frase("Ahora tengo {pct} en cripto. Vendo el sobrante si pasa de {alto} y compro si baja de {bajo}.", { pct: porcentaje(parte, 0), alto: porcentaje(rb.cripto + rb.banda, 0), bajo: porcentaje(rb.cripto - rb.banda, 0) })]);
      }
      if (!lineas.length) return "";
      return `<div class="tarjeta plan" id="plan"><h3>Mi plan</h3>
        <ul class="plan-lineas">${lineas.map(([tipo, t]) => `<li data-tipo="${tipo}"><span class="plan-punto" aria-hidden="true"></span><span>${t}</span></li>`).join("")}</ul></div>`;
    }
    // Lo que el robot dice sobre un gráfico: comprado, casi casi, esperando, en pausa o sin jugada (la insignia del gráfico).
    function estadoFila(E, par, t) {
      const v = E.vivo || {}, R = v.radar || {};
      const f = (R.filas || []).find((x) => x.par === par && x.temporalidad === t);
      const abierta = (v.posiciones || []).find((p) => p.par === par && p.estado === "abierta");
      if (abierta) {
        return { estado: "comprado", animo: "operando", texto: frase("Comprado. Stop {stop} · objetivo {objetivo}.", { stop: usdt(abierta.stop), objetivo: usdt(abierta.objetivo) }) };
      }
      const tengo = (v.tenencias || []).find((x) => x.cantidad > 0 && moneda(x.par) === moneda(par));
      const fila = (((v.rotacion || {}).ranking) || []).find((x) => x.par === par);
      if (tengo) {
        return { estado: "comprado", animo: "operando", texto: fila
          ? frase("La tengo: es la número {puesto} de las 8 en fuerza.", { puesto: numero(fila.puesto, 0) })
          : frase("La tengo: compré {cantidad} a {medio} en promedio.", { cantidad: numero(tengo.cantidad, 6), medio: tengo.precio_medio ? usdt(tengo.precio_medio) : "–" }) };
      }
      if (fila) {
        return fila.elegible
          ? { estado: "espera", animo: "atento", texto: frase("Número {puesto} en fuerza: podría entrar si pasa adelante.", { puesto: numero(fila.puesto, 0) }) }
          : { estado: "nada", animo: "dudando", texto: frase("Número {puesto} en fuerza: está bajo su promedio, no la compro.", { puesto: numero(fila.puesto, 0) }) };
      }
      const puesta = (v.posiciones || []).find((p) => p.par === par && p.estado === "puesta");
      if (puesta) return { estado: "casi", animo: "operando", texto: frase("Compra puesta en {precio}: espero que llegue.", { precio: usdt(puesta.precio) }) };
      if (!f) return null;
      if (R.filtro && !R.filtro.pasa) return { estado: "pausa", animo: "frenado", texto: frase("En pausa: BTC viene cayendo.", {}) };
      const e = (f.estrategias || []).find((x) => x.estrategia === f.espera);
      if (!e) return { estado: "nada", animo: "dudando", texto: frase("Mirando: aquí no hay jugada por ahora.", {}) };
      if (f.condicion === "con_rumbo") return { estado: "espera", animo: "dudando", texto: frase("Espero que se calme para comprar en {precio}.", { precio: usdt(e.gatillo) }) };
      return f.cerca
        ? { estado: "casi", animo: "atento", texto: frase("¡Casi casi! Compro si cierra en {precio}.", { precio: usdt(e.gatillo) }) }
        : { estado: "espera", animo: "atento", texto: frase("Esperando: compro en {precio} (falta {falta}).", { precio: usdt(e.gatillo), falta: porcentaje(Math.max(0, e.distancia || 0), 2) }) };
    }
    // La frase del robot: lo más cerca que está de comprar, o lo último que hizo.
    function narra(v) {
      if (v.perfil === "tendencia") {
        const filas = (v.tendencia || {}).filas || [];
        if (v.ultima && v.ultima.decision === "tendencia") return vuelta(v);
        const sobre = filas.filter((f) => f.sobre).map((f) => moneda(f.par)), bajo = filas.filter((f) => !f.sobre).map((f) => moneda(f.par));
        if (filas.length && sobre.length && bajo.length) return frase("Tengo {sobre}: está sobre su promedio. {bajo} está bajo el suyo y espero en USDT.", { sobre: sobre.join(" y "), bajo: bajo.join(" y ") });
        if (filas.length && sobre.length) return frase("Tengo {sobre}: están sobre su promedio de 50 días.", { sobre: sobre.join(" y ") });
        if (filas.length) return frase("BTC y ETH están bajo su promedio de 50 días: espero en USDT.", {});
        return vuelta(v);
      }
      if (v.perfil === "rotacion") {
        const tengo = (v.tenencias || []).filter((t) => t.cantidad > 0).map((t) => moneda(t.par));
        if (v.ultima && v.ultima.decision === "rotacion") return vuelta(v);
        const prox = hora(((v.rotacion || {}).dia_ms || 0) + 86400000);
        if (tengo.length) return frase("Tengo {monedas}: son las más fuertes de las 8. A las {hora} vuelvo a comparar y cambio si otra pasa adelante.", { monedas: tengo.join(" y "), hora: prox });
        if ((v.rotacion || {}).pasa_btc === false) return frase("BTC viene cayendo: espero en USDT. A las {hora} vuelvo a mirar.", { hora: prox });
        return vuelta(v);
      }
      const filas = ((v.radar || {}).filas || []).filter((f) => f.espera);
      const cerca = filas.filter((f) => f.cerca);
      const mejor = filas.map((f) => ({ f, e: f.estrategias.find((e) => e.estrategia === f.espera) }))
        .sort((a, b) => (a.e.distancia || 0) - (b.e.distancia || 0))[0];
      if (v.ultima && ["entrada", "compra", "frenado"].includes(v.ultima.decision)) return vuelta(v);
      if (v.radar && v.radar.filtro && !v.radar.filtro.pasa) {
        return frase("BTC viene cayendo, así que no compro nada: espero a que se calme. Cuando pase, te digo a qué precio compraría.", {});
      }
      if (cerca.length && mejor) return `${frase("¡Casi casi!", {})} ${gatillo(mejor.e, mejor.f)}`;
      if (mejor) return `${frase("Esperando:", {})} ${gatillo(mejor.e, mejor.f)}`;
      return vuelta(v);
    }
    // Cómo decide cada perfil, en palabras y con sus números.
    const REGLAS = {
      holding: "Compra BTC (60 %) y ETH (40 %) en 12 partes iguales, una por semana, al precio de ese momento. No vende ni pone stop: apuesta a que suben en años. Puede caer mucho en el camino.",
      conservador: "Mira velas de 4 horas. Compra solo si la operación puede ganar al menos 2 veces lo que arriesga, arriesga el 1 % del saldo y tiene como máximo 1 posición abierta.",
      equilibrado: "Mira velas de 1 y 4 horas. Compra si la operación puede ganar al menos 1,5 veces lo que arriesga, arriesga el 1,5 % del saldo y tiene como máximo 2 posiciones.",
      trader: "Mira velas de 1 hora. Compra si la operación gana al menos lo mismo que arriesga, arriesga el 2 % del saldo y tiene como máximo 2 posiciones.",
      scalper: "Mira velas de 5 minutos, armadas con las de 1 minuto. Compra si gana al menos lo mismo que arriesga, arriesga el 1 % del saldo y tiene como máximo 2 posiciones. Opera mucho: las comisiones pesan.",
      holding_ocho: "Compra las 8 monedas (BTC, ETH, BNB, SOL, XRP, ADA, TRX y DOGE) en partes iguales, en 12 compras, una por semana. No vende: guarda hasta que tú decidas.",
      compra_semanal: "Reparte el monto en 52 compras, una por semana, 60 % BTC y 40 % ETH. Cada compra se deja un 1 % bajo el precio del día; si al día siguiente el precio no llegó, compra a ese precio igual. Nunca se salta una semana.",
      rebalanceo: "Compra BTC y ETH en 12 partes hasta tener la mitad del monto en cripto. Después, una vez por semana: si cripto pasa del 60 % del total, vende el sobrante y lo deja en USDT; si baja del 40 %, compra lo que falta. Vende caro y compra barato por regla, sin adivinar.",
      cosecha: "Compra BTC y ETH en 12 partes. Cuando una moneda vale 30 % más de lo que pagaste en promedio, vende un cuarto y guarda esa plata. Si después cae 15 % desde esa venta, la vuelve a comprar. Si no cae, la plata queda esperando en USDT.",
      indice_eeuu: "Compra 60 % S&P 500 (SPY) y 40 % Nasdaq 100 (QQQ) en 12 partes, una por semana, y guarda. Son acciones tokenizadas de Binance, respaldadas 1:1 por las acciones reales.",
      indice_semanal: "Reparte el monto en 52 compras semanales de S&P 500 (60 %) y Nasdaq 100 (40 %). Cada compra se deja un 1 % más abajo; si al día siguiente no llega, compra igual.",
      acciones_ocho: "Compra Apple, Microsoft, Nvidia, Amazon, Google, Meta, Tesla y Broadcom en partes iguales, en 12 compras semanales, y guarda.",
      semanal_rotacion: "Mitad del monto en Compra semanal (BTC y ETH, 52 semanas) y mitad en Rotación (las 2 más fuertes de las 8). Cada mitad tiene su propia plata y sus propias reglas.",
      nucleo_satelite: "70 % compra BTC y ETH en 12 partes y los guarda; 30 % va a Rotación. Si la rotación falla, lo grande sigue guardado.",
      cripto_acciones: "Mitad en Compra semanal de BTC y ETH y mitad en Índice semanal de EE. UU. Si cripto cae fuerte, las acciones no siempre caen igual.",
      tendencia: "Una vez al día, cuando cierra la vela diaria, mira si BTC y ETH cerraron sobre su promedio de los últimos 50 días. La que está sobre su promedio se tiene con su parte (BTC 60 %, ETH 40 %); la que está bajo, esa parte espera en USDT. Si esa semana hubo un día de −5 % o peor, no compra por 5 días. Si una persona influyente dio una mala noticia sobre esa moneda o sobre BTC, esa parte espera en USDT 5 días. Si una parte se aleja más de 2 % de lo que le toca, la ajusta. Con un freno de la cuenta, vende todo.",
      rotacion: "Una vez al día, cuando cierra la vela diaria, ordena las 8 monedas por fuerza: cuánto subieron en 30 días, dividido por cuánto se movieron en el camino. Tiene las 2 primeras que estén sobre su promedio de 50 días, mitad y mitad. Cambia una solo cuando sale del grupo de las 3 mejores: cada cambio paga comisión. No pone stop: sale cuando la moneda pierde fuerza.",
    };
    function reglas(perfil) {
      if (!REGLAS[perfil]) return "";
      return `<details class="que-es" id="como-decide"><summary>${frase("Cómo decide el perfil {perfil}", { perfil: Tp(nombre(perfil)) })}</summary>
        <p class="ayuda">${REGLAS[perfil]}</p>
        <p class="ayuda">${frase("Monedas que mira: {monedas}. Todas contra USDT.", { monedas: (MONEDAS[perfil] || []).join(", ") })}</p>
        ${perfil === "rotacion" ? `<p class="ayuda">Siempre: si BTC viene cayendo, vende todo y espera en USDT. Los frenos de la cuenta (5 % al día, el piso) también la cortan.</p>` : ""}
        ${!ORDEN.includes(perfil) ? `<p class="ayuda">Rebote: cuando el precio va y viene sin rumbo (fuerza de tendencia baja) y una vela cierra pegada a la banda de abajo de Bollinger, compro ahí. Salgo en la media de la banda (objetivo) o 1 ATR más abajo (stop).</p>
        <p class="ayuda">Ruptura: cuando el día viene al alza y una vela cierra sobre el techo de las 20 anteriores con 1,5 veces el volumen normal, dejo una compra en ese techo: espero a que vuelva, no la persigo. Objetivo +1,5 %, stop 1,5 ATR más abajo; la mitad sale en el objetivo y la otra sigue con stop móvil.</p>
        <p class="ayuda">Siempre: si BTC viene cayendo, no compro nada. Cada compra lleva su stop y su objetivo desde el principio, el 40 % queda en USDT y los frenos (5 % al día, 4 pérdidas seguidas, el piso) cortan todo.</p>` : ""}</details>`;
    }
    function posiciones(v) {
      if ((v.tenencias || []).length) {
        return `<ul class="vivo-lista">${v.tenencias.map((t) => `<li class="vivo-fila">
          <span class="vivo-moneda" data-sin-traducir>${esc(moneda(t.par))}</span>
          <span>${frase("Tienes {cantidad} · compradas en promedio a {medio}", { cantidad: numero(t.cantidad, 6), medio: t.precio_medio ? usdt(t.precio_medio) : "–" })}</span>
          <span class="vivo-valor" data-signo="${signo((t.valor || 0) - t.gastado)}" data-sin-traducir>${esc(t.valor == null ? "–" : usdt(t.valor))}</span></li>`).join("")}</ul>`;
      }
      const abiertas = (v.posiciones || []).filter((p) => p.estado === "abierta" || p.estado === "puesta");
      if (!abiertas.length) return `<p class="suave">Ahora no tengo nada abierto: todo está en USDT.</p>`;
      return `<ul class="vivo-lista">${abiertas.map((p) => `<li class="vivo-fila">
          <span class="vivo-moneda" data-sin-traducir>${esc(moneda(p.par))}</span>
          <span>${p.estado === "puesta"
            ? frase("Compra esperando en {precio} ({monto})", { precio: usdt(p.precio), monto: usdt(p.monto) })
            : frase("Compré a {precio} · ahora {ahora} · stop {stop} · objetivo {objetivo}", { precio: usdt(p.precio), ahora: p.precio_ahora == null ? "–" : usdt(p.precio_ahora), stop: usdt(p.stop), objetivo: usdt(p.objetivo) })}
            ${J[p.id] ? `<span class="mov-prob">${historia(J[p.id].historia)}</span>` : ""}</span>
          <span class="vivo-valor" data-signo="${signo(p.ganancia)}" data-sin-traducir>${esc(p.estado === "puesta" || p.ganancia == null ? "" : conSigno(p.ganancia, usdt))}</span></li>`).join("")}</ul>`;
    }
    function vivo(E) {
      const v = E.vivo || {};
      J = v.jugadas || {};
      const hay = !!v.perfil && v.monto > 0;
      if (!hay || E.vivoElegir) {
        return `<div class="centro">
          <header class="centro-cabeza"><h2>Mira operar a tu robot</h2>
            <p class="ayuda">Elige un perfil y un monto. Pilota opera desde ahora con dinero ficticio y precios reales de Binance, con todas sus reglas y frenos. Así ves cómo se porta antes de arriesgar nada.</p></header>
          ${grafico ? grafico() : ""}
          ${selector(E)}
          ${hay ? `<button type="button" class="pz-boton" id="vivo-volver">Volver sin cambiar nada</button>` : ""}</div>`;
      }
      const activo = v.activo;
      const animo = !activo ? "neutral" : (v.ultima && v.ultima.decision === "frenado" ? "frenado"
        : ((v.posiciones || []).some((p) => p.estado === "abierta") || (v.tenencias || []).some((t) => t.cantidad > 0) ? "operando" : "atento"));
      const movs = (v.movimientos || []).slice(0, 6);
      const f = E.flujo || {};
      const conexion = f.conectado ? "en_vivo" : (f.corriendo ? "conectando" : "apagado");
      return `<div class="centro vivo">
        <div class="tarjeta vivo-cabeza">
          ${robot(animo)}
          <div class="vivo-cabeza-texto">
            <p class="vivo-perfil">${activo ? frase("Perfil {perfil} · operando desde el {fecha}", { perfil: Tp(nombre(v.perfil)), fecha: dia(v.desde_ms) })
              : frase("Perfil {perfil} · detenido", { perfil: Tp(nombre(v.perfil)) })}</p>
            <p class="vivo-piensa">${narra(v)}</p>
            <p class="conexion" data-estado="${conexion}"><span class="conexion-punto" aria-hidden="true"></span>${{
              en_vivo: "En vivo: conectado a Binance. Reacciono en el segundo en que cierra cada vela.",
              conectando: "Conectando con Binance…",
              apagado: "Sin conexión con Binance: el robot no está mirando. Solo opera con Pilota abierta.",
            }[conexion]}</p>
          </div></div>
        ${radar(E) || plan(E)}
        ${grafico ? grafico() : ""}
        <div class="tarjeta vivo-saldo" data-signo="${signo(v.ganancia)}">
          <p class="vivo-saldo-titulo">Cuánto vale ahora</p>
          <p class="vivo-saldo-monto" data-sin-traducir>${esc(v.valor == null ? "–" : usdt(v.valor))}</p>
          <p class="vivo-saldo-cambio" data-sin-traducir>${esc(v.ganancia == null ? "" : `${conSigno(v.ganancia, usdt)} · ${conSigno(v.ganancia_relativa, (x) => porcentaje(x, 2))}`)}</p>
          <p class="suave">${frase("Pusiste {monto} ficticios · en USDT ahora: {efectivo}", { monto: usdt(v.monto), efectivo: usdt(v.efectivo || 0) })}</p></div>
        <div class="tarjeta"><h3>Lo que tiene ahora</h3>${posiciones(v)}</div>
        <div class="tarjeta"><h3>Lo último que hizo</h3>
          ${movs.length ? `<ol class="movs">${movs.map(filaLinea).join("")}</ol>` : `<p class="suave">Todavía no hace nada: está esperando una oportunidad que cumpla sus reglas.</p>`}
          ${(v.movimientos || []).length > 6 ? `<button type="button" class="pz-boton" data-ir-pestana="movimientos">Ver todos los movimientos</button>` : ""}</div>
        <div class="vivo-acciones">
          ${activo ? `<button type="button" class="pz-boton" id="vivo-detener"${E.vivoOcupado ? " disabled" : ""}>Detener el robot</button>` : ""}
          <button type="button" class="pz-boton${activo ? "" : " pz-principal"}" id="vivo-cambiar">${activo ? "Cambiar de perfil" : "Empezar de nuevo"}</button></div>
        ${reglas(v.perfil)}
        <p class="ayuda">Es dinero ficticio con precios de verdad. Cuando te guste cómo opera, el paso a dinero real está en «Dinero real».</p></div>`;
    }

    // ── Comparar los perfiles en el pasado ──
    function tarjetaPerfil(p, monto, elegido, r) {
      const listo = p.listo !== false && typeof p.saldo === "number";
      return `<button type="button" class="tarjeta comp-perfil" data-comparar="${p.perfil}" aria-pressed="${p.perfil === elegido}" data-signo="${signo(p.rendimiento)}">
        <span class="comp-nombre">${PERFILES[p.perfil].nombre}</span>
        <span class="comp-monto" data-sin-traducir>${esc(listo ? usdt(p.saldo) : "–")}</span>
        <span class="comp-cambio" data-sin-traducir>${esc(listo ? conSigno(p.rendimiento, (x) => porcentaje(x, 1)) : "")}</span>
        <span class="comp-mini">${listo ? curva([{ clase: "sim-pilota", puntos: p.curva }], { base: monto, ancho: 160, alto: 48, etiqueta: Tp("Curva del perfil") }) : ""}</span>
        <span class="comp-detalle">${listo
          ? frase("{n} movimientos · peor caída {caida}", { n: numero(p.movimientos_total || p.operaciones || 0, 0), caida: porcentaje(p.caida_maxima || 0, 1) })
          : Tp(MOTIVOS_SIM[p.motivo] || "Sin datos.")}</span>
        ${veredicto(p, r) ? `<span class="comp-veredicto" data-veredicto="${veredicto(p, r)}">${textoVeredicto(veredicto(p, r), p)}</span>` : ""}
        ${p.recortado ? `<span class="comp-nota">${p.recorte === "acciones"
          ? frase("Solo los últimos {n} días: las acciones llegaron a Binance en junio de 2026.", { n: numero(Math.round((p.hasta_ms - p.desde_ms) / 86400000), 0) })
          : frase("Solo los últimos {n} días: es lo que hay de velas de 1 minuto.", { n: numero(Math.round((p.hasta_ms - p.desde_ms) / 86400000), 0) })}</span>` : ""}</button>`;
    }
    function pelicula(E) {
      const r = (E.sim || {}).ultima || {};
      const p = (r.perfiles || []).find((x) => x.perfil === (E.peli || {}).perfil);
      if (!p) return "";
      const movs = p.movimientos || [];
      const i = Math.min((E.peli || {}).i ?? movs.length, movs.length);
      const hasta = i >= movs.length ? p.hasta_ms : (movs[i - 1] || {}).ms || p.desde_ms;
      const puntos = (p.curva || []).filter((q) => q[0] <= hasta);
      const btc = ((r.btc || {}).curva || []).filter((q) => q[0] >= p.desde_ms && q[0] <= hasta);
      const vistos = movs.slice(0, i).reverse().slice(0, 40);
      const jugando = !!(E.peli || {}).jugando;
      return `<div class="tarjeta peli">
        <div class="peli-cabeza"><h3>${frase("Así operó {perfil}", { perfil: Tp(nombre(p.perfil)) })}</h3>
          <div class="peli-botones">
            <button type="button" class="pz-boton pz-principal" id="peli-play">${jugando ? "Pausa" : (i >= movs.length ? "Ver desde el principio" : "Seguir")}</button>
            <button type="button" class="pz-boton" data-usar-perfil="${p.perfil}">Usar este perfil en vivo</button></div></div>
        <p class="suave">${frase("Movimiento {i} de {n}", { i: numero(i, 0), n: numero(movs.length, 0) })}${p.movimientos_total > movs.length ? ` · ${frase("muestro los últimos {n}", { n: numero(movs.length, 0) })}` : ""}</p>
        <figure class="sim-grafico">
          ${curva([{ clase: "sim-btc", puntos: btc }, { clase: "sim-pilota", puntos: puntos }],
            { base: r.monto, desde: p.desde_ms, hasta: p.hasta_ms, marca: hasta,
              fijos: [...(p.curva || []), ...((r.btc || {}).curva || []).filter((q) => q[0] >= p.desde_ms)], etiqueta: Tp("La curva de tu saldo con Pilota y con comprar BTC y esperar") })}
          <figcaption class="sim-leyenda"><span class="ley-pilota">${PERFILES[p.perfil].nombre}</span><span class="ley-btc">Comprar BTC y esperar</span>
            <span class="ley-base">${frase("Tu monto: {monto}", { monto: usdt(r.monto) })}</span></figcaption></figure>
        ${vistos.length ? `<ol class="movs">${vistos.map((v) => `<li class="mov" data-tipo="${claseMov(v)}"><span class="mov-punto" aria-hidden="true"></span>
          <span class="mov-cuando" data-sin-traducir>${esc(fechaMs(v.ms))}</span><span class="mov-texto">${textoMov(v)}</span></li>`).join("")}</ol>`
          : `<p class="suave">Toca «Seguir» para ver sus movimientos uno por uno.</p>`}</div>`;
    }
    function comparar(E) {
      const s = E.sim || {};
      const r = s.ultima || {};
      const monto = E.campos["sim-monto"] || s.monto || 100;
      let cuerpo;
      if (s.corriendo) cuerpo = `<div class="tarjeta sim-resultado sim-cargando"><p class="suave">Recorriendo el historial con todos los perfiles…</p></div>`;
      else if (!r.formato) cuerpo = `<div class="tarjeta sim-resultado sim-vacio"><p class="sim-vacio-titulo">Elige un monto y un período, y toca «Comparar».</p>
        <p class="suave">Te muestro qué habría hecho cada perfil con ese monto, al lado de quedarte en USDT y de comprar BTC y esperar.</p></div>`;
      else if (!(r.perfiles || []).length) cuerpo = `<div class="tarjeta sim-resultado sim-vacio"><p class="sim-vacio-titulo">${esc(Tp(MOTIVOS_SIM[r.motivo] || "No pude simular."))}</p></div>`;
      else {
        cuerpo = `<div class="sim-resultado">
          <p class="sim-periodo">${frase("Del {desde} al {hasta} ({dias} días) con {monto}", { desde: dia(r.desde_ms), hasta: dia(r.hasta_ms), dias: numero(r.dias_reales, 0), monto: usdt(r.monto) })}</p>
          <div class="comp-grilla">${r.perfiles.filter((p) => enMercado(p.perfil, mercadoElegido(E))).map((p) => tarjetaPerfil(p, r.monto, (E.peli || {}).perfil, r)).join("")}</div>
          <div class="comp-referencias">
            <p><span>Quedarte en USDT</span> <strong data-sin-traducir>${esc(usdt(r.monto))}</strong></p>
            <p><span>Comprar BTC y esperar</span> <strong data-sin-traducir>${esc(typeof (r.btc || {}).saldo === "number" ? `${usdt(r.btc.saldo)} (${conSigno(r.btc.rendimiento, (x) => porcentaje(x, 1))})` : "–")}</strong></p></div>
          <p class="ayuda">Toca un perfil para ver la película de lo que hizo, movimiento por movimiento.</p>
          <div id="peli">${pelicula(E)}</div>
          <details class="que-es" id="sim-letra-chica"><summary>Lo que tienes que saber de este resultado</summary>
            <p class="ayuda">Es el pasado, no una promesa: el mercado que viene puede hacer cosas que estos días no hicieron.</p>
            <p class="ayuda">Usé las mismas reglas que usa el robot en vivo: la reserva del 40 % en USDT, el máximo de posiciones de cada perfil, su riesgo por operación, los mínimos de Binance, las comisiones y los frenos.</p>
          </details></div>`;
      }
      return `<div class="centro">
        <header class="centro-cabeza"><h2>Compara los perfiles en el pasado</h2>
          <p class="ayuda">Todos los perfiles con el mismo monto y el mismo período, con precios reales de Binance. Mira cuál se parece a lo que buscas.</p></header>
        <div class="tarjeta">${chipsMercado(E)}</div>
        <div class="tarjeta comp-elegir">
          <label class="campo-monto"><span>¿Cuánto pondrías?</span>
            <span class="campo-monto-caja"><input id="sim-monto" type="number" inputmode="decimal" min="10" max="1000000" step="1" value="${esc(monto)}"><span data-sin-traducir>USDT</span></span></label>
          <div class="chips" role="group" aria-label="Montos sugeridos">${MONTOS.map((m) => `<button type="button" class="chip" data-sim-monto="${m}" aria-pressed="${Number(monto) === m}" data-sin-traducir>${esc(numero(m, 0))}</button>`).join("")}</div>
          <p class="campo-titulo">¿Desde cuándo?</p>
          <div class="chips" role="group" aria-label="Período">${PERIODOS.map(([d, t]) => `<button type="button" class="chip" data-sim-dias="${d}" aria-pressed="${Number(s.dias || 90) === d}">${t}</button>`).join("")}</div>
          <button type="button" class="pz-boton pz-principal boton-ancho" id="sim-correr"${s.corriendo ? " disabled" : ""}>${s.corriendo ? "Comparando…" : "Comparar"}</button></div>
        ${cuerpo}
        ${probabilidades(E)}
        ${mapa(E)}</div>`;
    }

    // ── Qué tan seguido sale bien (bin/lib_simulacion.py: probabilidades): el mismo período en cientos de inicios ──
    // Un solo resultado depende mucho del día en que empezaste. Esto repite la cuenta empezando cada dos semanas desde 2018.
    function probabilidades(E) {
      const P = E.prob || {};
      if (!P.cargando && !P.datos && !P.error) return "";
      const titulo = `<h3>¿Qué tan seguido sale bien?</h3>`;
      if (P.cargando) return `<div class="tarjeta prob" id="prob">${titulo}<p class="suave">Repitiendo la cuenta con cientos de fechas de inicio…</p></div>`;
      if (!P.datos) return `<div class="tarjeta prob" id="prob">${titulo}<p class="suave">No pude calcular las probabilidades.</p></div>`;
      const D = P.datos, m = mercadoElegido(E);
      const periodo = Tp((PERIODOS.find(([d]) => d === D.dias) || [0, frase("{n} días", { n: numero(D.dias, 0) })])[1]);
      const filas = D.filas.filter((f) => (m === "cripto" ? mercadoDe(f.perfil) === "cripto" : enMercado(f.perfil, m)));
      const listas = filas.filter((f) => f.listo);
      const de100 = (x) => (x == null ? "–" : frase("{n} de 100", { n: numero(Math.round(x * 100), 0) }));   // frase ya escapa
      const pct = (x) => conSigno(x, (y) => porcentaje(y, 0));
      const tono = (x) => (x >= 0.2 ? "muy-bien" : (x >= 0 ? "bien" : (x >= -0.2 ? "mal" : "muy-mal")));
      const celdas = (f) => `<td>${de100(f.gana)}</td><td>${de100(f.gana_btc)}</td><td>${de100(f.pierde_grande)}</td>
        <td data-tono="${tono(f.malo)}" data-sin-traducir>${esc(pct(f.malo))}</td><td data-tono="${tono(f.tipico)}" data-sin-traducir>${esc(pct(f.tipico))}</td>
        <td data-tono="${tono(f.bueno)}" data-sin-traducir>${esc(pct(f.bueno))}</td>`;
      if (!listas.length) {
        return `<div class="tarjeta prob" id="prob">${titulo}
          <p class="ayuda">${frase("Con acciones todavía no se puede: llevan muy poco tiempo en Binance para repetir la cuenta con ventanas de {periodo}.", { periodo })}</p></div>`;
      }
      const n = Math.max(...listas.map((f) => f.n));
      return `<div class="tarjeta prob" id="prob">${titulo}
        <p class="ayuda">${frase("Un resultado solo depende mucho del día en que empiezas. Aquí repetí la cuenta empezando cada 2 semanas desde 2018 y esperando {periodo}: {n} inicios distintos, con comisiones.", { periodo, n: numero(n, 0) })}</p>
        <div class="mapa-caja"><table class="mapa-tabla prob-tabla">
          <thead><tr><th scope="col">Perfil</th><th scope="col">Terminó ganando</th><th scope="col">Le ganó a BTC</th><th scope="col">Perdió más de 20 %</th>
            <th scope="col">Si sale mal</th><th scope="col">Lo normal</th><th scope="col">Si sale bien</th></tr></thead>
          <tbody>${listas.map((f) => `<tr><th scope="row">${Tp(nombre(f.perfil))}</th>${celdas(f)}</tr>`).join("")}
            ${D.btc && D.btc.listo ? `<tr class="mapa-btc"><th scope="row">${Tp("Comprar BTC de una")}</th>${celdas({ ...D.btc, gana_btc: null })}</tr>` : ""}</tbody></table></div>
        <p class="ayuda">«Si sale mal» es lo que te pasa en 1 de cada 10 inicios, los peores. «Si sale bien», en 1 de cada 10, los mejores. Es lo que ya pasó, no una promesa: el mercado que viene puede ser distinto.</p></div>`;
    }

    // ── El mapa de inicios (bin/lib_simulacion.py: mapa): cuánto tendrías hoy según cuándo empezaste ──
    // Cada fila es un perfil y cada columna una fecha de inicio. Lo importante no es la mejor casilla (esa solo se conoce
    // mirando para atrás), sino qué fila aguanta mejor un mal comienzo: la que nunca queda muy abajo.
    function mapa(E) {
      const M = E.mapa || {};
      if (!M.formato) {
        return `<div class="tarjeta mapa" id="mapa"><h3>¿Importa cuándo empiezas?</h3>
          <p class="ayuda">Mira qué habría pasado con cada perfil si empezabas en distintas fechas desde 2018, hasta hoy. No sirve para adivinar el mejor momento: sirve para ver qué perfil aguanta mejor un mal comienzo.</p>
          <button type="button" class="pz-boton pz-principal" id="mapa-ver"${E.mapaCargando ? " disabled" : ""}>${E.mapaCargando ? "Calculando…" : "Ver el mapa de inicios"}</button></div>`;
      }
      if (mercadoElegido(E) === "acciones") {
        return `<div class="tarjeta mapa" id="mapa"><h3>¿Importa cuándo empiezas?</h3>
          <p class="ayuda">Con acciones todavía no se puede medir: en Binance existen desde junio de 2026 y el mapa necesita años de inicios distintos. Mira el mapa en «Cripto».</p></div>`;
      }
      const fecha = (ms) => new Date(Number(ms)).toLocaleDateString(i18n.idioma, { month: "short", year: "numeric", timeZone: "UTC" });
      const filas = [...M.filas.filter((f) => mercadoDe(f.perfil) === "cripto"), { perfil: "btc", valores: M.btc }];
      const tono = (x) => (x == null ? "nada" : (x >= 1 ? "muy-bien" : (x >= 0.2 ? "bien" : (x >= 0 ? "igual" : (x >= -0.3 ? "mal" : "muy-mal")))));
      const resumen = (f) => {
        const vals = f.valores.filter((x) => x != null);
        if (!vals.length) return Tp("Sin historia suficiente");
        const gana = f.valores.filter((x, i) => x != null && M.btc[i] != null && x > M.btc[i]).length;
        return frase("Peor inicio: {peor} · le ganó a BTC en {n} de {total}", { peor: conSigno(Math.min(...vals), (x) => porcentaje(x, 0)), n: numero(gana, 0), total: numero(vals.length, 0) });
      };
      return `<div class="tarjeta mapa" id="mapa"><h3>¿Importa cuándo empiezas?</h3>
        <p class="ayuda">${frase("Cuánto tendrías hoy si empezabas en cada fecha. Verde es ganar, rojo es perder. Fíjate en la peor casilla de cada fila: es lo que te pasa si empiezas en mal momento, y eso no se puede elegir.", {})}</p>
        <div class="mapa-caja"><table class="mapa-tabla">
          <thead><tr><th scope="col">Perfil</th>${M.inicios.map((ms) => `<th scope="col" data-sin-traducir>${esc(fecha(ms))}</th>`).join("")}<th scope="col">Resumen</th></tr></thead>
          <tbody>${filas.map((f) => `<tr${f.perfil === "btc" ? ` class="mapa-btc"` : ""}><th scope="row">${f.perfil === "btc" ? Tp("Comprar BTC de una") : Tp(nombre(f.perfil))}</th>
            ${f.valores.map((x) => `<td data-tono="${tono(x)}" data-sin-traducir>${x == null ? "·" : esc(conSigno(x, (y) => porcentaje(y, 0)))}</td>`).join("")}
            <td class="mapa-resumen">${f.perfil === "btc" ? "" : resumen(f)}</td></tr>`).join("")}</tbody></table></div>
        <p class="ayuda">Un punto es que esa moneda todavía no tenía historia. Es el pasado con comisiones, no una promesa.</p></div>`;
    }

    // ── Todos los movimientos del robot en vivo ──
    function movimientos(E, registro) {
      const v = E.vivo || {};
      J = v.jugadas || {};
      const movs = v.movimientos || [];
      const grupos = [];
      for (const l of movs) {
        const d = dia(l.ms);
        if (!grupos.length || grupos[grupos.length - 1].d !== d) grupos.push({ d, l: [] });
        grupos[grupos.length - 1].l.push(l);
      }
      return `<div class="centro">
        <header class="centro-cabeza"><h2>Todo lo que hizo tu robot</h2>
          <p class="ayuda">Cada compra, cada venta y cada vez que decidió no entrar, en palabras y con su hora. Lo más nuevo, arriba.</p></header>
        ${grupos.length ? grupos.map((g) => `<section class="tarjeta"><h3 data-sin-traducir>${esc(g.d)}</h3><ol class="movs">${g.l.map(filaLinea).join("")}</ol></section>`).join("")
          : `<div class="tarjeta"><p class="suave">Todavía no hay movimientos. Empieza en «En vivo» y aquí vas a ver todo lo que hace.</p></div>`}
        <details class="que-es" id="registro-completo"><summary>El registro completo (técnico)</summary>${registro}</details></div>`;
    }

    return { vivo, comparar, pelicula, movimientos, textoLinea, ERRORES_VIVO, ORDEN, narra, estadoFila, nombre, mercadoDe };
  }
  return { crear };
})();
