// Pilota: el centro de operaciones. Las pestañas de arriba y dos de ellas: «Simular» (el pasado con tu monto y la prueba
// en vivo) y «Operar» (los requisitos, la llave de Binance y el interruptor del dinero de verdad).
// Nada de texto pegado: cada frase va completa, con sus marcadores, y su inglés en idiomas/en.json.
// Los dibujos son SVG con atributos (nunca style=""): la CSP «style-src 'self'» lo bloquearía.
window.PilotaCentro = (() => {
  "use strict";

  const PESTANAS = [
    ["ahora", "Ahora", "M4 14a8 8 0 0 1 16 0M12 14l4-4"],
    ["simular", "Simular", "M5 4v16l14-8z"],
    ["operar", "Operar", "M13 2 4 14h7l-1 8 9-12h-7z"],
    ["historial", "Historial", "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"],
    ["como", "Cómo pienso", "M12 3a6 6 0 0 0-3 11v3h6v-3a6 6 0 0 0-3-11zM10 21h4"],
  ];
  const MONTOS = [50, 100, 200, 500, 1000];
  const PERIODOS = [[30, "1 mes"], [90, "3 meses"], [180, "6 meses"], [365, "1 año"], [1095, "3 años"]];
  // Por qué una simulación no se pudo (bin/lib_simulacion.py: MOTIVOS).
  const MOTIVOS_SIM = {
    sin_monto: "Elige un monto entre 10 y 1.000.000 USDT.",
    sin_periodo: "Elige un período.",
    sin_minimos: "Primero calcula el capital mínimo viable (en «Cómo pienso»): sin los mínimos de Binance no puedo simular.",
    sin_historial: "Todavía no tengo historial: baja los 3 años en «Cómo pienso».",
    sin_operaciones: "En ese período mis reglas no habrían abierto ninguna operación: habrías quedado en USDT.",
  };
  // Los cinco requisitos para pasar a real (bin/lib_real.py: REQUISITOS).
  const REQUISITOS = {
    simulacion: "Simulaste el pasado con tu monto",
    prueba: "Probaste en vivo con dinero ficticio",
    llave: "Tu llave de Binance es segura",
    minimos: "Los mínimos de Binance están calculados",
    fondos: "Tienes fondos libres en Binance",
  };
  // Lo que puede responder el paso a real cuando no se pudo (bin/lib_real.py y bin/real.py).
  const ERRORES_REAL = {
    formato: "La llave y el secreto son solo letras y números (de 32 a 128). Revisa que los copiaste completos.",
    sin_llavero: "En este equipo no puedo guardar la llave de forma segura. Por ahora, el dinero real es solo en Mac.",
    no_guardo: "No pude guardar la llave en el llavero del sistema.",
    puede_retirar: "Esa llave puede retirar fondos, así que la borré. Crea una sin el permiso de retiro.",
    llave_rechazada: "Binance no aceptó la llave: revisa que esté activa y que tu IP esté en su lista.",
    sin_conexion: "No pude hablar con Binance. Revisa tu conexión y vuelve a intentar.",
    binance: "Binance dijo que no. Vuelve a intentar en un rato.",
    requisitos: "Todavía falta cumplir algún requisito.",
    frase: "Escribe la frase tal cual para encender el dinero real.",
    presupuesto: "El monto tiene que estar entre el capital mínimo viable y lo que tienes libre.",
    frenado: "La cuenta real está frenada: revísala antes de encender nada.",
    activo: "Primero vuelve a prueba: no puedo desconectar la llave con el dinero real encendido.",
    con_posiciones: "Hay posiciones reales abiertas: ciérralas primero o usa «Cerrar todo y volver a prueba».",
    llave_insegura: "Tu llave de Binance ahora puede retirar o transferir: no abro nada nuevo. Quítale ese permiso en Binance.",
    ocupado: "Estoy terminando otra revisión. Vuelve a intentar en un momento.",
    sin_llave: "No encuentro la llave de Binance en este equipo. Conéctala de nuevo.",
  };

  function crear({ i18n, esc, numero, usdt, porcentaje, fechaHora }) {
    const { Tp, frase } = i18n;
    const dia = (texto) => {
      const d = new Date(String(texto ?? ""));
      return isNaN(d.getTime()) ? "—" : d.toLocaleDateString(i18n.idioma, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
    };

    // ── Las pestañas ──
    function pestanas(actual, extra = {}) {
      return `<nav class="pestanas" role="tablist" aria-label="Secciones de Pilota">${PESTANAS.map(([id, nombre, icono]) => {
        const si = id === actual;
        return `<button type="button" role="tab" class="pestana" id="tab-${id}" data-pestana="${id}"
          aria-selected="${si}" aria-controls="pestana-${id}" tabindex="${si ? 0 : -1}">
          <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="${icono}" fill="none" stroke="currentColor"
            stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span>${nombre}</span>${id === "operar" && extra.real ? `<span class="pestana-real" aria-hidden="true"></span>` : ""}
          ${id === "ahora" && extra.esperando ? `<span class="pestana-cuenta" data-sin-traducir>${esc(numero(extra.esperando, 0))}</span>` : ""}</button>`;
      }).join("")}</nav>`;
    }
    function panel(id, actual, contenido) {
      return `<section role="tabpanel" class="pestana-panel" id="pestana-${id}" aria-labelledby="tab-${id}"${id === actual ? "" : " hidden"}>${contenido}</section>`;
    }

    // ── El gráfico de la simulación: la curva de Pilota y la de comprar BTC y esperar, sobre la línea del monto ──
    function grafico(r) {
      const p = ((r.pilota || {}).curva || []), b = ((r.btc || {}).curva || []);
      const todos = [...p, ...b];
      if (todos.length < 2) return "";
      const x0 = r.desde_ms, x1 = r.hasta_ms;
      let y0 = Math.min(r.monto, ...todos.map((q) => q[1])), y1 = Math.max(r.monto, ...todos.map((q) => q[1]));
      const margen = (y1 - y0) * 0.08 || 1;
      y0 -= margen; y1 += margen;
      const X = (v) => (8 + 584 * (v - x0) / Math.max(1, x1 - x0)).toFixed(1);
      const Y = (v) => (8 + 184 * (1 - (v - y0) / (y1 - y0))).toFixed(1);
      const linea = (q) => q.map(([x, y]) => `${X(x)},${Y(y)}`).join(" ");
      // Pilota cambia a escalones: el saldo se mueve solo al cerrar.
      const escalones = p.flatMap(([x, y], i) => (i ? [[x, p[i - 1][1]], [x, y]] : [[x, y]]));
      if (escalones.length) escalones.push([x1, escalones[escalones.length - 1][1]]);
      return `<figure class="sim-grafico">
        <svg viewBox="0 0 600 200" preserveAspectRatio="none" role="img" aria-label="${esc(Tp("La curva de tu saldo con Pilota y con comprar BTC y esperar"))}">
          <line class="sim-base" x1="8" x2="592" y1="${Y(r.monto)}" y2="${Y(r.monto)}" stroke-dasharray="4 4" vector-effect="non-scaling-stroke"/>
          ${b.length > 1 ? `<polyline class="sim-btc" points="${linea(b)}" fill="none" vector-effect="non-scaling-stroke"/>` : ""}
          ${escalones.length > 1 ? `<polyline class="sim-pilota" points="${linea(escalones)}" fill="none" vector-effect="non-scaling-stroke"/>` : ""}
        </svg>
        <figcaption class="sim-leyenda">
          <span class="ley-pilota">Pilota</span><span class="ley-btc">Comprar BTC y esperar</span>
          <span class="ley-base">${frase("Tu monto: {monto}", { monto: usdt(r.monto) })}</span></figcaption></figure>`;
    }
    function tarjetaResultado(nombre, clase, saldo, rendimiento, detalle) {
      const hay = typeof saldo === "number" && isFinite(saldo);
      const signo = !hay || Math.abs(rendimiento) < 1e-9 ? "igual" : (rendimiento > 0 ? "sube" : "baja");
      return `<div class="sim-tarjeta ${clase}" data-signo="${signo}">
        <p class="sim-tarjeta-nombre">${nombre}</p>
        <p class="sim-tarjeta-monto" data-sin-traducir>${hay ? esc(usdt(saldo)) : "–"}</p>
        <p class="sim-tarjeta-cambio" data-sin-traducir>${hay ? esc(`${rendimiento > 0 ? "+" : ""}${porcentaje(rendimiento, 1)}`) : ""}</p>
        ${detalle ? `<p class="sim-tarjeta-detalle" data-sin-traducir>${detalle}</p>` : ""}</div>`;
    }
    function resultado(r, corriendo) {
      if (corriendo) return `<div class="tarjeta sim-resultado sim-cargando"><p class="suave">Recorriendo el historial con tus reglas…</p></div>`;
      if (!r || !r.formato) {
        return `<div class="tarjeta sim-resultado sim-vacio"><p class="sim-vacio-titulo">Elige un monto y un período, y toca «Simular».</p>
          <p class="suave">Te muestro qué habría hecho Pilota con ese monto, al lado de quedarte en USDT y de comprar BTC y esperar.</p></div>`;
      }
      if (!r.listo) {
        return `<div class="tarjeta sim-resultado sim-vacio"><p class="sim-vacio-titulo" data-sin-traducir>${esc(Tp(MOTIVOS_SIM[r.motivo] || "No pude simular."))}</p></div>`;
      }
      const p = r.pilota || {}, s = p.saltadas || {};
      const frenados = (s.diario || 0) + (s.racha || 0) + (s.piso || 0);
      return `<div class="tarjeta sim-resultado">
        <p class="sim-periodo">${frase("Del {desde} al {hasta} ({dias} días)", { desde: dia(r.desde), hasta: dia(r.hasta), dias: numero(r.dias_reales, 0) })}</p>
        <div class="sim-tarjetas">
          ${tarjetaResultado("Con Pilota", "es-pilota", p.saldo, p.rendimiento,
            frase("{n} operaciones · ganó {g} y perdió {q}", { n: numero(p.operaciones, 0), g: numero(p.ganadas, 0), q: numero(p.perdidas, 0) }))}
          ${tarjetaResultado("Quedarte en USDT", "es-usdt", r.usdt.saldo, 0, esc(Tp("Sin riesgo y sin ganancia")))}
          ${tarjetaResultado("Comprar BTC y esperar", "es-btc", r.btc.saldo, r.btc.rendimiento || 0,
            typeof r.btc.caida_maxima === "number" ? frase("Peor caída: {n}", { n: porcentaje(r.btc.caida_maxima, 1) }) : "")}
        </div>
        ${grafico(r)}
        <ul class="sim-datos">
          <li><span>Peor caída con Pilota</span><strong data-sin-traducir>${esc(porcentaje(p.caida_maxima || 0, 1))}</strong></li>
          <li><span>Mejor operación</span><strong data-sin-traducir>${esc(typeof p.mejor === "number" ? usdt(p.mejor) : "–")}</strong></li>
          <li><span>Peor operación</span><strong data-sin-traducir>${esc(typeof p.peor === "number" ? usdt(p.peor) : "–")}</strong></li>
          <li><span>Frenos que me pararon</span><strong data-sin-traducir>${esc(numero(frenados, 0))}</strong></li>
        </ul>
        <details class="que-es" id="sim-letra-chica"><summary>Lo que tienes que saber de este resultado</summary>
          <p class="ayuda">Es el pasado, no una promesa: el mercado que viene puede hacer cosas que estos días no hicieron.</p>
          <p class="ayuda">Usé las reglas de hoy: la reserva del 40 % en USDT, dos posiciones a la vez, 2 % de riesgo por operación, los mínimos de Binance, las comisiones y los frenos.</p>
          ${r.sin_exigencia ? `<p class="ayuda">Mi puntaje todavía no está calibrado, así que simulé todas las señales permitidas, sin exigencia.</p>` : ""}
          ${r.topado ? `<p class="ayuda">${frase("Mientras el modelo no esté validado, cada operación usa como máximo {n}. Por eso, con montos grandes, el resultado crece poco.", { n: usdt(r.tope) })}</p>` : ""}
          ${(s.tamano || 0) ? `<p class="ayuda">${frase("{n} oportunidades no alcanzaron el mínimo de Binance con tu monto.", { n: numero(s.tamano, 0) })}</p>` : ""}
        </details></div>`;
    }

    function simular(E) {
      const s = E.sim || {};
      const r = s.ultima;
      const cuenta = ((E.estado || {}).cuentas || []).find((c) => c.ambiente === "prueba") || {};
      const motor = E.motor || {};
      return `<div class="centro">
        <header class="centro-cabeza"><h2>Simula antes de poner un peso</h2>
          <p class="ayuda">Primero mira qué habría hecho Pilota con tu monto en el pasado. Después pruébalo en vivo con dinero ficticio y precios de verdad.</p></header>
        <ol class="pasos-centro">
          <li class="paso-centro tarjeta">
            <p class="paso-numero" data-sin-traducir>1</p>
            <h3>Mira el pasado</h3>
            <label class="campo-monto"><span>¿Cuánto pondrías?</span>
              <span class="campo-monto-caja"><input id="sim-monto" type="number" inputmode="decimal" min="10" max="1000000" step="1" value="${esc(s.monto || 100)}"><span data-sin-traducir>USDT</span></span></label>
            <div class="chips" role="group" aria-label="Montos sugeridos">${MONTOS.map((m) => `<button type="button" class="chip" data-sim-monto="${m}" aria-pressed="${Number(s.monto) === m}" data-sin-traducir>${esc(numero(m, 0))}</button>`).join("")}</div>
            <p class="campo-titulo">¿Desde cuándo?</p>
            <div class="chips" role="group" aria-label="Período">${PERIODOS.map(([d, t]) => `<button type="button" class="chip" data-sim-dias="${d}" aria-pressed="${Number(s.dias || 90) === d}">${t}</button>`).join("")}</div>
            <button type="button" class="pz-boton pz-principal boton-ancho" id="sim-correr"${s.corriendo ? " disabled" : ""}>${s.corriendo ? "Simulando…" : "Simular"}</button>
          </li>
          <li class="paso-centro paso-resultado">${resultado(r, s.corriendo)}</li>
        </ol>
        <div class="paso-centro tarjeta paso-vivo">
          <p class="paso-numero" data-sin-traducir>2</p>
          <div class="paso-vivo-texto"><h3>Pruébalo en vivo</h3>
            <p class="ayuda">Pilota opera desde ahora con dinero ficticio y precios reales de Binance, con todas sus reglas. Así ves cómo se porta antes de arriesgar nada.</p>
            <p class="vivo-estado">${typeof cuenta.saldo === "number"
              ? frase("Tu cuenta de prueba: {saldo} · {n} operaciones cerradas", { saldo: usdt(cuenta.saldo), n: numero(cuenta.operaciones || 0, 0) })
              : "Todavía no tienes cuenta de prueba."}
              <span class="serie-estado" data-estado="${motor.activo ? "listo" : "vacio"}">${motor.activo ? "Operando en prueba" : (motor.corriendo ? "Motor dormido" : "Motor apagado")}</span></p></div>
          ${E.real && E.real.activo ? `<p class="freno-texto">Con el dinero real encendido no reinicio la prueba: el motor está operando tu cuenta de Binance.</p>` : ""}
          <button type="button" class="pz-boton pz-principal" id="sim-vivo"${E.reiniciando || (E.real && E.real.activo) ? " disabled" : ""}>${frase("Empezar con {monto} ficticios", { monto: usdt(Math.round(Number(s.monto) || 100)) })}</button>
        </div></div>`;
    }

    // ── Operar con dinero de verdad ──
    function requisito(q) {
      const detalle = {
        simulacion: q.cumple ? frase("Simulaste con {monto}.", { monto: usdt(q.n) }) : esc(Tp("Haz una simulación en la pestaña «Simular».")),
        prueba: frase("{dias} de {d} días y {ops} de {o} operaciones cerradas.", { dias: numero(q.dias, 0), d: numero(q.dias_pedidos, 0), ops: numero(q.operaciones, 0), o: numero(q.operaciones_pedidas, 0) }),
        llave: esc(!q.ok ? Tp("Conecta una llave de Binance aquí abajo.")
          : [q.lectura ? null : Tp("le falta permiso de lectura"), q.spot ? null : Tp("le falta permiso para operar spot"),
             q.retiro ? Tp("puede retirar: no se acepta") : null, q.ip ? null : Tp("no está limitada a tu IP")]
            .filter(Boolean).join(" · ") || Tp("Lee, opera spot, no puede retirar y está limitada a tu IP.")),
        minimos: q.cumple ? frase("Desde {n} se puede operar.", { n: usdt(q.minimo) }) : esc(Tp("Calcúlalos en «Cómo pienso».")),
        fondos: frase("{fondos} libres en USDT y FDUSD; el mínimo es {minimo}.", { fondos: usdt(q.fondos), minimo: usdt(q.minimo) }),
      }[q.id];
      return `<li class="requisito" data-cumple="${q.cumple ? 1 : 0}">
        <span class="requisito-marca" aria-hidden="true">${q.cumple
          ? `<svg viewBox="0 0 20 20"><path d="M5 10.5l3.2 3L15 6.5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>`
          : `<svg viewBox="0 0 20 20"><circle cx="10" cy="10" r="6.5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>`}</span>
        <span class="requisito-texto"><strong>${REQUISITOS[q.id]}</strong><span data-sin-traducir>${detalle}</span></span>
        <span class="visualmente-oculto">${q.cumple ? "Cumplido" : "Pendiente"}</span></li>`;
    }
    function llave(r) {
      if (!r.llavero) return `<p class="aviso-real">En este equipo no puedo guardar la llave de forma segura. Por ahora, el dinero real es solo en Mac.</p>`;
      if (r.conectado) {
        const c = r.conexion || {};
        return `<div class="llave-conectada">
          <p><strong>Llave conectada</strong> <span class="pista" data-sin-traducir>${esc(r.pista)}</span></p>
          ${c.ok ? `<p class="suave">${frase("Libre en Binance: {usdt} USDT · {fdusd} FDUSD", { usdt: numero(((c.libres || {}).USDT) || 0, 2), fdusd: numero(((c.libres || {}).FDUSD) || 0, 2) })}</p>` : ""}
          ${c.motivo ? `<p class="freno-texto" data-sin-traducir>${esc(Tp(ERRORES_REAL[c.motivo] || "Binance dijo que no. Vuelve a intentar en un rato."))}</p>` : ""}
          <div class="pz-pie"><button type="button" class="pz-boton" id="real-revisar">Revisar de nuevo</button>
            <button type="button" class="pz-boton" id="real-desconectar">Desconectar la llave</button></div></div>`;
      }
      return `<details class="guia-llave" id="guia-llave"><summary>Cómo crear una llave segura en Binance</summary>
          <ol class="guia-pasos">
            <li>Entra a Binance → Perfil → Administración de API → «Crear API» → «Generada por el sistema».</li>
            <li>Deja marcado solo «Habilitar lectura» y «Habilitar trading spot y de margen».</li>
            <li>Nunca marques «Habilitar retiros». Si la llave puede retirar, Pilota la borra.</li>
            <li>En «Restringir acceso a IP», elige «Solo IP de confianza» y agrega la IP de este equipo.</li>
            <li>Copia la API Key y la Secret Key aquí abajo. La Secret Key se muestra una sola vez.</li></ol></details>
        <div class="campos-llave">
          <label class="pz-campo"><span>API Key</span><input id="real-llave" type="text" autocomplete="off" spellcheck="false" maxlength="128"></label>
          <label class="pz-campo"><span>Secret Key</span><input id="real-secreto" type="password" autocomplete="off" spellcheck="false" maxlength="128"></label>
          <p class="ayuda">Se guardan en el llavero de tu Mac. Pilota no las escribe en ningún archivo ni las manda a ningún lado que no sea Binance.</p>
          <button type="button" class="pz-boton pz-principal" id="real-conectar">Conectar y revisar</button></div>`;
    }
    function encendido(r, E) {
      const c = r.cuenta || {}, ej = r.ejecutor || {};
      return `<div class="tarjeta real-encendido">
        <p class="real-insignia">Dinero real encendido</p>
        <p class="real-saldo" data-sin-traducir>${esc(usdt(c.saldo))}</p>
        <p class="suave">${frase("Pilota maneja {saldo} de tu cuenta de Binance · {n} operaciones cerradas · {p} posiciones ahora", { saldo: usdt(c.saldo), n: numero(c.operaciones, 0), p: numero(c.posiciones, 0) })}</p>
        ${(ej.motivos || []).map((m) => `<p class="freno-texto" data-sin-traducir>${esc(Tp(ERRORES_REAL[m.codigo] || "Ahora no abro ninguna entrada nueva."))}</p>`).join("")}
        <p class="ayuda">Lo que pasa minuto a minuto lo ves en «Ahora», igual que en prueba. Las protecciones quedan puestas en Binance aunque apagues el equipo.</p>
        <div class="pz-pie"><button type="button" class="pz-boton" id="real-desactivar"${E.realOcupado ? " disabled" : ""}>Volver a prueba</button>
          <button type="button" class="pz-boton pz-principal pz-peligro" id="real-emergencia"${E.realOcupado ? " disabled" : ""}>Cerrar todo y volver a prueba</button></div></div>`;
    }
    function operar(E) {
      const r = E.real;
      if (!r) return `<div class="centro"><p class="suave">Revisando tu conexión con Binance…</p></div>`;
      if (r.activo) return `<div class="centro"><header class="centro-cabeza"><h2>Operando con dinero real</h2></header>${encendido(r, E)}</div>`;
      const req = r.requisitos || [];
      const listos = req.filter((q) => q.cumple).length;
      const fondos = (req.find((q) => q.id === "fondos") || {});
      return `<div class="centro">
        <header class="centro-cabeza"><h2>Operar con dinero real</h2>
          <p class="ayuda">Pilota pasa a tu dinero de verdad solo cuando cumples los cinco pasos. Cada uno existe para que no pierdas plata por apuro.</p></header>
        <div class="operar-grilla">
          <div class="tarjeta requisitos-caja">
            <div class="requisitos-cabeza"><h3>Antes de empezar</h3>
              <span class="requisitos-cuenta" data-sin-traducir>${esc(`${listos}/${req.length}`)}</span></div>
            <div class="requisitos-barra" data-sin-traducir role="img" aria-label="${esc(Tp("{n} de {total} requisitos cumplidos", { n: listos, total: req.length }))}">
              <svg viewBox="0 0 100 6" preserveAspectRatio="none" aria-hidden="true"><rect class="pista" x="0" y="0" width="100" height="6" rx="3"/>
                <rect class="valor" x="0" y="0" width="${req.length ? (100 * listos / req.length).toFixed(1) : 0}" height="6" rx="3"/></svg></div>
            <ol class="requisitos">${req.map(requisito).join("")}</ol></div>
          <div class="tarjeta llave-caja"><h3>Tu llave de Binance</h3>${llave(r)}</div>
        </div>
        <div class="tarjeta activar-caja" data-listo="${r.listo ? 1 : 0}">
          <h3>Encender el dinero real</h3>
          ${r.listo ? `<p class="ayuda">${frase("Elige cuánto maneja Pilota. Tiene que ser al menos {minimo} y no más de lo que tienes libre ({fondos}).", { minimo: usdt(fondos.minimo), fondos: usdt(fondos.fondos) })}</p>
            <label class="campo-monto"><span>Monto para Pilota</span><span class="campo-monto-caja"><input id="real-presupuesto" type="number" inputmode="decimal" min="${esc(Math.ceil(fondos.minimo || 0))}" max="${esc(Math.floor(fondos.fondos || 0))}" step="1" value="${esc(Math.ceil(fondos.minimo || 0))}"><span data-sin-traducir>USDT</span></span></label>
            <label class="pz-campo"><span>${frase("Escribe «{frase}» para confirmar", { frase: r.frase })}</span><input id="real-frase" type="text" autocomplete="off" spellcheck="false" maxlength="40"></label>
            <button type="button" class="pz-boton pz-principal pz-peligro boton-ancho" id="real-activar"${E.realOcupado ? " disabled" : ""}>Encender dinero real</button>`
            : `<p class="suave">${frase("Cuando cumplas los {n} pasos, aquí eliges cuánto maneja Pilota y lo enciendes.", { n: numero(req.length, 0) })}</p>`}
        </div></div>`;
    }

    return { pestanas, panel, simular, operar, ERRORES_REAL, PESTANAS: PESTANAS.map((p) => p[0]) };
  }

  return { crear };
})();
