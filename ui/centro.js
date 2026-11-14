// Pilota: el centro de operaciones. Las pestañas de arriba y la de «Dinero real» (los requisitos, la llave de Binance y el
// interruptor). El robot en vivo, la comparación de perfiles y los movimientos viven en ui/vivo.js.
// Nada de texto pegado: cada frase va completa, con sus marcadores, y su inglés en idiomas/en.json.
// Los dibujos son SVG con atributos (nunca style=""): la CSP «style-src 'self'» lo bloquearía.
window.PilotaCentro = (() => {
  "use strict";

  const PESTANAS = [
    ["vivo", "En vivo", "M12 3a3 3 0 0 1 3 3v1h2a2 2 0 0 1 2 2v7a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4V9a2 2 0 0 1 2-2h2V6a3 3 0 0 1 3-3zM9.5 12h.01M14.5 12h.01"],
    ["comparar", "Comparar", "M4 20V10M10 20V4M16 20v-7M22 20H2"],
    ["movimientos", "Movimientos", "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"],
    ["ahora", "Cabina", "M4 14a8 8 0 0 1 16 0M12 14l4-4"],
    ["operar", "Dinero real", "M13 2 4 14h7l-1 8 9-12h-7z"],
    ["como", "Avanzado", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"],
  ];
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
    con_ordenes: "Todavía hay órdenes de Pilota abiertas en Binance: usa «Cerrar todo y volver a prueba».",
    sin_llave: "No encuentro la llave de Binance en este equipo. Conéctala de nuevo.",
  };

  function crear({ i18n, esc, numero, usdt, porcentaje, fechaHora }) {
    const { Tp, frase } = i18n;


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

    // ── Operar con dinero de verdad ──
    function requisito(q) {
      const detalle = {
        simulacion: q.cumple ? frase("Simulaste con {monto}.", { monto: usdt(q.n) }) : esc(Tp("Compara los perfiles en la pestaña «Comparar».")),
        prueba: frase("{dias} de {d} días y {ops} de {o} operaciones cerradas.", { dias: numero(q.dias, 0), d: numero(q.dias_pedidos, 0), ops: numero(q.operaciones, 0), o: numero(q.operaciones_pedidas, 0) }),
        llave: esc(!q.ok ? Tp("Conecta una llave de Binance aquí abajo.")
          : [q.lectura ? null : Tp("le falta permiso de lectura"), q.spot ? null : Tp("le falta permiso para operar spot"),
             q.retiro ? Tp("puede retirar: no se acepta") : null, q.ip ? null : Tp("no está limitada a tu IP")]
            .filter(Boolean).join(" · ") || Tp("Lee, opera spot, no puede retirar y está limitada a tu IP.")),
        minimos: q.cumple ? frase("Desde {n} se puede operar.", { n: usdt(q.minimo) }) : esc(Tp("Pilota los calcula sola al abrir: espera un momento.")),
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
        <p class="ayuda">Lo que pasa minuto a minuto lo ves en «Cabina», igual que en prueba. Las protecciones quedan puestas en Binance aunque apagues el equipo.</p>
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

    return { pestanas, panel, operar, ERRORES_REAL, PESTANAS: PESTANAS.map((p) => p[0]) };
  }

  return { crear };
})();
