// Pilota: el robot en vivo y la comparación de perfiles. Tres pestañas: «En vivo» (elige un perfil y un monto, y mira cómo
// opera con dinero ficticio y precios de ahora), «Comparar» (los cinco perfiles en el pasado, con la película de lo que
// hizo cada uno) y «Movimientos» (todo lo que hizo el robot, en palabras).
// Nada de texto pegado: cada frase va completa, con sus marcadores, y su inglés en idiomas/en.json.
// Los dibujos son SVG con atributos (nunca style=""): la CSP «style-src 'self'» lo bloquearía.
window.PilotaVivo = (() => {
  "use strict";

  // Los cinco perfiles (bin/lib_perfiles.py: ORDEN). El nombre, qué hace en una frase y qué tan rápido opera.
  const PERFILES = {
    holding: { nombre: "Holding", que: "Compra BTC y ETH por partes, una vez por semana, y los guarda. No vende.", ritmo: "Muy lento" },
    conservador: { nombre: "Conservador", que: "Pocas operaciones: solo las muy claras, en velas de 4 horas, donde puede ganar el doble de lo que arriesga.", ritmo: "Lento" },
    equilibrado: { nombre: "Equilibrado", que: "Operaciones medianas en velas de 1 y 4 horas. Es el punto de partida que te sugiero.", ritmo: "Medio" },
    trader: { nombre: "Trader", que: "Muchas operaciones chicas en velas de 1 hora.", ritmo: "Rápido" },
    scalper: { nombre: "Scalper", que: "El más rápido: velas de 5 minutos, entra y sale en minutos u horas. Más operaciones, más comisiones.", ritmo: "Muy rápido" },
  };
  const ORDEN = ["holding", "conservador", "equilibrado", "trader", "scalper"];
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
    const moneda = (par) => String(par || "").replace(/(FDUSD|USDT)$/, "");
    const dia = (ms) => {
      const d = new Date(Number(ms));
      return isNaN(d.getTime()) ? "—" : d.toLocaleDateString(i18n.idioma, { day: "numeric", month: "short", year: "numeric" });
    };
    const fechaMs = (ms) => fechaHora(new Date(Number(ms)).toISOString());
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
    function textoLinea(l) {
      const o = l.orden || {}, r = l.resultado || {}, m = moneda(l.par);
      switch (l.razon) {
        case "perfil_empezado": return frase("Empecé con {monto} ficticios, en perfil {perfil}.", { monto: usdt(r.saldo), perfil: Tp(nombre(r.perfil)) });
        case "perfil_detenido": return frase("Me detuviste (perfil {perfil}). Lo abierto sigue protegido.", { perfil: Tp(nombre(r.perfil)) });
        case "compra_holding": return frase("Compré {cantidad} {moneda} a {precio} ({monto}).", { cantidad: numero(o.cantidad, 6), moneda: m, precio: usdt(o.precio), monto: usdt(o.monto) });
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
      compra_holding: "compra", entrada_ruptura: "compra", entrada_rebote: "compra", rechazo: "nada", propuesta_vencida: "nada" })[l.razon] || "info";
    function filaLinea(l) {
      return `<li class="mov" data-tipo="${claseLinea(l)}"><span class="mov-punto" aria-hidden="true"></span>
        <span class="mov-cuando" data-sin-traducir>${esc(fechaHora(l.fecha))}</span>
        <span class="mov-texto">${textoLinea(l)}</span></li>`;
    }
    // Un movimiento de la simulación (bin/lib_simulacion.py: movimientos).
    function textoMov(v) {
      const m = moneda(v.par);
      if (v.que === "compra") {
        return v.estrategia === "holding"
          ? frase("Compré {monto} de {moneda} a {precio}.", { monto: usdt(v.monto), moneda: m, precio: usdt(v.precio) })
          : frase("Compré {monto} de {moneda} a {precio}, con stop en {stop} y objetivo en {objetivo}.", { monto: usdt(v.monto), moneda: m, precio: usdt(v.precio), stop: usdt(v.stop), objetivo: usdt(v.objetivo) });
      }
      return v.por === "objetivo"
        ? frase("Vendí {moneda} en el objetivo, a {precio}: gané {neto}. Saldo: {saldo}.", { moneda: m, precio: usdt(v.precio), neto: usdt(v.ganancia), saldo: usdt(v.saldo) })
        : frase("Vendí {moneda} en el stop, a {precio}: perdí {neto}. Saldo: {saldo}.", { moneda: m, precio: usdt(v.precio), neto: usdt(Math.abs(v.ganancia || 0)), saldo: usdt(v.saldo) });
    }
    const claseMov = (v) => (v.que === "compra" ? "compra" : (v.ganancia > 0 ? "gana" : "pierde"));

    // ── Elegir perfil y monto ──
    function selector(E, opciones = {}) {
      const elegido = E.vivoPerfil || "equilibrado";
      const monto = E.campos["vivo-monto"] || E.vivoMonto || 100;
      return `<div class="tarjeta vivo-elegir">
        <h3>${opciones.titulo || "Elige cómo quieres que opere"}</h3>
        <div class="perfiles" role="radiogroup" aria-label="Perfil">${ORDEN.map((p) => `
          <button type="button" class="perfil" role="radio" data-perfil="${p}" aria-checked="${p === elegido}">
            <span class="perfil-nombre">${PERFILES[p].nombre}</span>
            <span class="perfil-ritmo">${PERFILES[p].ritmo}</span>
            <span class="perfil-que">${PERFILES[p].que}</span></button>`).join("")}</div>
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
      return frase(plantilla, { motivo: Tp(motivoCorto(u.motivo)), n: numero(u.parte || 0, 0), fecha: dia(u.proxima_ms) });
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
    function radar(E) {
      const R = (E.vivo || {}).radar || {};
      const filas = R.filas || [];
      if (!filas.length) return "";
      const frena = R.filtro && !R.filtro.pasa;
      return `<div class="tarjeta radar">
        <h3>Qué estoy esperando</h3>
        ${frena ? `<p class="freno-texto">${frase("BTC viene cayendo: no compro nada hasta que se calme.", {})}</p>` : ""}
        <ul class="radar-filas">${filas.map((f) => {
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
        }).join("")}</ul>
        <p class="ayuda">Decido solo con velas cerradas: cuando una cierra donde dice arriba, compro en ese mismo segundo. La historia es el pasado, no una promesa.</p></div>`;
    }
    // Lo que el robot dice sobre un gráfico: comprado, casi casi, esperando, en pausa o sin jugada (la insignia del gráfico).
    function estadoFila(E, par, t) {
      const v = E.vivo || {}, R = v.radar || {};
      const f = (R.filas || []).find((x) => x.par === par && x.temporalidad === t);
      const abierta = (v.posiciones || []).find((p) => p.par === par && p.estado === "abierta");
      if (abierta) {
        return { estado: "comprado", animo: "operando", texto: frase("Comprado. Stop {stop} · objetivo {objetivo}.", { stop: usdt(abierta.stop), objetivo: usdt(abierta.objetivo) }) };
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
      conservador: "Mira velas de 4 horas de BTC y ETH. Compra solo si la operación puede ganar al menos 2 veces lo que arriesga, arriesga el 1 % del saldo y tiene como máximo 1 posición abierta.",
      equilibrado: "Mira velas de 1 y 4 horas. Compra si la operación puede ganar al menos 1,5 veces lo que arriesga, arriesga el 1,5 % del saldo y tiene como máximo 2 posiciones.",
      trader: "Mira velas de 1 hora. Compra si la operación gana al menos lo mismo que arriesga, arriesga el 2 % del saldo y tiene como máximo 2 posiciones.",
      scalper: "Mira velas de 5 minutos, armadas con las de 1 minuto. Compra si gana al menos lo mismo que arriesga, arriesga el 1 % del saldo y tiene como máximo 2 posiciones. Opera mucho: las comisiones pesan.",
    };
    function reglas(perfil) {
      if (!REGLAS[perfil]) return "";
      return `<details class="que-es" id="como-decide"><summary>${frase("Cómo decide el perfil {perfil}", { perfil: Tp(nombre(perfil)) })}</summary>
        <p class="ayuda">${REGLAS[perfil]}</p>
        ${perfil !== "holding" ? `<p class="ayuda">Rebote: cuando el precio va y viene sin rumbo (fuerza de tendencia baja) y una vela cierra pegada a la banda de abajo de Bollinger, compro ahí. Salgo en la media de la banda (objetivo) o 1 ATR más abajo (stop).</p>
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
        ${radar(E)}
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
    function tarjetaPerfil(p, monto, elegido) {
      const listo = p.listo !== false && typeof p.saldo === "number";
      return `<button type="button" class="tarjeta comp-perfil" data-comparar="${p.perfil}" aria-pressed="${p.perfil === elegido}" data-signo="${signo(p.rendimiento)}">
        <span class="comp-nombre">${PERFILES[p.perfil].nombre}</span>
        <span class="comp-monto" data-sin-traducir>${esc(listo ? usdt(p.saldo) : "–")}</span>
        <span class="comp-cambio" data-sin-traducir>${esc(listo ? conSigno(p.rendimiento, (x) => porcentaje(x, 1)) : "")}</span>
        <span class="comp-mini">${listo ? curva([{ clase: "sim-pilota", puntos: p.curva }], { base: monto, ancho: 160, alto: 48, etiqueta: Tp("Curva del perfil") }) : ""}</span>
        <span class="comp-detalle">${listo
          ? frase("{n} movimientos · peor caída {caida}", { n: numero(p.movimientos_total || p.operaciones || 0, 0), caida: porcentaje(p.caida_maxima || 0, 1) })
          : Tp(MOTIVOS_SIM[p.motivo] || "Sin datos.")}</span>
        ${p.recortado ? `<span class="comp-nota">${frase("Solo los últimos {n} días: es lo que hay de velas de 1 minuto.", { n: numero(Math.round((p.hasta_ms - p.desde_ms) / 86400000), 0) })}</span>` : ""}</button>`;
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
      if (s.corriendo) cuerpo = `<div class="tarjeta sim-resultado sim-cargando"><p class="suave">Recorriendo el historial con los cinco perfiles…</p></div>`;
      else if (!r.formato) cuerpo = `<div class="tarjeta sim-resultado sim-vacio"><p class="sim-vacio-titulo">Elige un monto y un período, y toca «Comparar».</p>
        <p class="suave">Te muestro qué habría hecho cada perfil con ese monto, al lado de quedarte en USDT y de comprar BTC y esperar.</p></div>`;
      else if (!(r.perfiles || []).length) cuerpo = `<div class="tarjeta sim-resultado sim-vacio"><p class="sim-vacio-titulo">${esc(Tp(MOTIVOS_SIM[r.motivo] || "No pude simular."))}</p></div>`;
      else {
        cuerpo = `<div class="sim-resultado">
          <p class="sim-periodo">${frase("Del {desde} al {hasta} ({dias} días) con {monto}", { desde: dia(r.desde_ms), hasta: dia(r.hasta_ms), dias: numero(r.dias_reales, 0), monto: usdt(r.monto) })}</p>
          <div class="comp-grilla">${r.perfiles.map((p) => tarjetaPerfil(p, r.monto, (E.peli || {}).perfil)).join("")}</div>
          <div class="comp-referencias">
            <p><span>Quedarte en USDT</span> <strong data-sin-traducir>${esc(usdt(r.monto))}</strong></p>
            <p><span>Comprar BTC y esperar</span> <strong data-sin-traducir>${esc(typeof (r.btc || {}).saldo === "number" ? `${usdt(r.btc.saldo)} (${conSigno(r.btc.rendimiento, (x) => porcentaje(x, 1))})` : "–")}</strong></p></div>
          <p class="ayuda">Toca un perfil para ver la película de lo que hizo, movimiento por movimiento.</p>
          <div id="peli">${pelicula(E)}</div>
          <details class="que-es" id="sim-letra-chica"><summary>Lo que tienes que saber de este resultado</summary>
            <p class="ayuda">Es el pasado, no una promesa: el mercado que viene puede hacer cosas que estos días no hicieron.</p>
            <p class="ayuda">Usé las mismas reglas que usa el robot en vivo: la reserva del 40 % en USDT, el máximo de posiciones de cada perfil, su riesgo por operación, los mínimos de Binance, las comisiones y los frenos.</p>
            <p class="ayuda">El scalper solo se puede mirar en los últimos 30 días: es lo que guardo de velas de 1 minuto.</p>
          </details></div>`;
      }
      return `<div class="centro">
        <header class="centro-cabeza"><h2>Compara los perfiles en el pasado</h2>
          <p class="ayuda">Los cinco perfiles con el mismo monto y el mismo período, con precios reales de Binance. Mira cuál se parece a lo que buscas.</p></header>
        <div class="tarjeta comp-elegir">
          <label class="campo-monto"><span>¿Cuánto pondrías?</span>
            <span class="campo-monto-caja"><input id="sim-monto" type="number" inputmode="decimal" min="10" max="1000000" step="1" value="${esc(monto)}"><span data-sin-traducir>USDT</span></span></label>
          <div class="chips" role="group" aria-label="Montos sugeridos">${MONTOS.map((m) => `<button type="button" class="chip" data-sim-monto="${m}" aria-pressed="${Number(monto) === m}" data-sin-traducir>${esc(numero(m, 0))}</button>`).join("")}</div>
          <p class="campo-titulo">¿Desde cuándo?</p>
          <div class="chips" role="group" aria-label="Período">${PERIODOS.map(([d, t]) => `<button type="button" class="chip" data-sim-dias="${d}" aria-pressed="${Number(s.dias || 90) === d}">${t}</button>`).join("")}</div>
          <button type="button" class="pz-boton pz-principal boton-ancho" id="sim-correr"${s.corriendo ? " disabled" : ""}>${s.corriendo ? "Comparando…" : "Comparar"}</button></div>
        ${cuerpo}</div>`;
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

    return { vivo, comparar, pelicula, movimientos, textoLinea, ERRORES_VIVO, ORDEN, narra, estadoFila };
  }
  return { crear };
})();
