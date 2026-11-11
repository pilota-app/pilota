// Pilota: la pantalla principal (bin/panel.py → panelEstado). Lo propio de la app, aparte de app.js para que los dos queden
// chicos. Dibuja la banda, el saldo con su línea del piso y su referencia en moneda local, los medidores de puntaje y
// exigencia por par, las posiciones, las propuestas con su cuenta atrás, el motor, el registro y la mascota.
// Nada de texto pegado: cada frase va completa, con sus marcadores, y su inglés en idiomas/en.json.
window.PilotaPanel = (() => {
  "use strict";
  // Lo que cuenta la mascota (bin/lib_panel.py: CUENTOS), con sus números. Explica la decisión de ahora, no opina.
  const CUENTOS = {
    frenado: "Hay un freno puesto ({freno}): no abro ninguna entrada nueva. Lo que esté abierto sigue con su protección automática.",
    pausado: "Estás en pausa: no abro nada hasta que me digas «Seguir». Sigues con {n} posiciones protegidas.",
    arranque: "Arranqué frenado en manual ({motivo}): de un estado del que no me fío no sale ninguna orden.",
    aviso: "Ojo con {aviso}: en esta cuenta no me frena, pero en real no abriría nada hasta que vuelva a su sitio.",
    cerrada: "Cerré {par} por {por}: dejó {neto}. Una operación es una operación, ni más ni menos.",
    esperando: "Te propuse {par} con puntaje {puntaje}: compro {monto} con stop en {stop}. Te quedan {queda} para decirme, y si no me respondes la dejo pasar.",
    abierta: "Tengo {n} posiciones abiertas y las estoy mirando. La de {par} va en {ganancia}.",
    llenas: "Tengo abiertas las {maximas} posiciones que caben, y la de {par} va en {ganancia}: hasta que cierre una, no abro nada más.",
    puesta: "Dejé una compra esperando en {entrada} para {par}: hasta que se llene, no hay nada abierto.",
    rechazada: "{par} puntúa {puntaje} y pasa la exigencia ({exigencia}), pero no me sale ningún monto con el que abrirla.",
    apagado: "{par} puntúa {puntaje} y pasa la exigencia ({exigencia}), pero el motor está apagado: nadie está mirando los cruces.",
    sobre_exigencia: "{par} puntúa {puntaje} y pasa la exigencia ({exigencia}): lo decido en la próxima revisión.",
    bajo_exigencia: "Estoy mirando: lo mejor de ahora es {par} con puntaje {puntaje} y la exigencia es {exigencia}, así que me quedo en USDT.",
    sin_oportunidad: "Estoy mirando y ninguna de las dos monedas da una oportunidad ahora mismo.",
    falta_algo: "Estoy mirando, pero todavía me falta algo para puntuar: te lo digo abajo, en cada paso.",
  };
  // El nombre del ánimo, para quien no ve la carita.
  const ANIMOS = { atento: "Atento", dudando: "Dudando", operando: "Operando", neutral: "Cerrando", frenado: "Frenado" };
  // Por qué la pantalla todavía no muestra un número (bin/lib_panel.py: MOTIVOS).
  const MOTIVOS = {
    sin_cuenta: "Arranqué frenado: hasta que revises el estado de la cuenta, sus números no son de fiar.",
    sin_medida: "Todavía no he medido ninguna oportunidad: mira «Tamaño de la operación», más abajo.",
    frenado: "Hay un freno puesto: no abro ninguna entrada nueva.",
    motor_apagado: "El motor está apagado: nadie está mirando los cruces. Pilota solo trabaja con el equipo encendido.",
    sin_1m: "Llevo {n} min sin velas de 1 minuto: en ese rato un stop no se habría aplicado.",
  };
  // Por qué un medidor no tiene puntaje.
  const SIN_PUNTAJE = {
    sin_oportunidad: "{par}: ninguna estrategia ve una oportunidad ahora mismo.",
  };
  // Qué quiere decir la banda que app.js deja fija arriba de todas las pantallas, en dos frases y sin letra chica.
  const AMBIENTES = {
    prueba: "**Prueba**: dinero ficticio con precios de verdad. Nada de este saldo existe en Binance, y pasar a real es un paso aparte.",
    real: "**Real**: es el dinero de tu cuenta de Binance. El puntaje, la exigencia, el tamaño y los frenos son los mismos que en prueba.",
  };
  // Lo que pidió la orden de una línea del registro (bin/lib_registro.py: CAMPOS_ORDEN, `lado` y `tipo`). Cada
  // combinación es una frase entera: ni «compra» ni «con límite» se muestran pegados a mano.
  const ORDENES = {
    "compra limite": "compró con límite en {precio}", "compra mercado": "compró a mercado en {precio}",
    "venta limite": "vendió con límite en {precio}", "venta mercado": "vendió a mercado en {precio}",
  };
  // Cómo quedó esa orden: puesta no es llenada, y una salida parcial cierra la mitad.
  const ESTADO_ORDEN = { puesta: "quedó puesta", llenada: "se llenó", cerrada: "quedó cerrada" };

  function crear({ i18n, esc, etiquetas, numero, usdt, porcentaje, duracion, fechaHora, fechaHoraMs }) {
    const { Tp, frase } = i18n;
    const E = etiquetas;
    const MAXIMO = 100;   // la escala del puntaje (bin/lib_puntaje.py: PUNTAJE_MAXIMO)
    // La cuenta atrás, como se lee un reloj: minutos y segundos, iguales en los dos idiomas.
    const reloj = (ms) => {
      const s = Math.max(0, Math.round(ms / 1000));
      return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    };
    const textoVence = (ms) => frase("Vence en {tiempo}: si no me respondes, la dejo pasar.", { tiempo: reloj(ms) });
    // El equivalente en la moneda de la persona: solo una referencia, y sin tasa no se muestra ninguno.
    const enLocal = (monto, l) => ((l && l.listo && typeof monto === "number" && isFinite(monto))
      ? `${numero(monto * l.tasa, 0)} ${l.moneda}` : "");

    // ── La mascota: la carita, lo que cuenta y la línea del día ──
    // Los cinco ánimos cambian la carita y el borde; lo que cuenta sale de la plantilla de su código, con los números
    // que manda el Python. La mascota no opina ni celebra: cuenta la decisión de ahora y, si hace falta, por qué.
    function mascota(p) {
      const m = p.mascota || {}, d = m.datos || {};
      const animo = ANIMOS[m.animo] ? m.animo : "atento";
      // El nombre del freno y el motivo del arranque van en minúscula, en medio de la frase (MOTIVO_CORTO en app.js).
      const dicho = frase(CUENTOS[m.cuento] || "Estoy mirando el mercado.", {
        freno: Tp(E.motivoCorto[d.freno] || d.freno || ""), motivo: Tp(E.motivoCorto[d.motivo] || d.motivo || ""),
        aviso: Tp(E.motivoCorto[d.aviso] || d.aviso || ""),
        par: d.par || "", por: Tp(E.cierre[d.por] || d.por || ""), neto: usdt(d.neto),
        puntaje: numero(d.puntaje, 0), exigencia: numero(d.exigencia, 0), n: numero(d.n, 0),
        maximas: numero(d.maximas, 0), monto: usdt(d.monto), stop: numero(d.stop),
        queda: duracion((d.queda_min || 0) * 60), ganancia: usdt(d.ganancia), entrada: numero(d.entrada) });
      return `<div class="mascota" data-animo="${esc(animo)}" role="status">
        <span class="mascota-cara" data-animo="${esc(animo)}" aria-hidden="true"></span>
        <div class="mascota-dice">
          <p class="mascota-animo">${ANIMOS[animo]}</p>
          <p class="mascota-texto">${dicho}</p>
          ${porque(m, d)}
          <p class="mascota-dia">${lineaDiaria(p)}</p></div></div>`;
    }
    // El motivo con nombre y número, en su propia frase entera: por qué no sale monto, o por qué te pregunto.
    function porque(m, d) {
      if (m.cuento === "rechazada" && d.motivo) {
        return `<p class="mascota-porque">${Tp(E.motivosTamano[d.motivo] || "Con esta oportunidad no me sale ningún monto.", { par: d.par || "", n: numero(d.n, 0) })}</p>`;
      }
      if (m.cuento === "esperando" && d.motivo) {
        return `<p class="mascota-porque">${Tp((E.pregunta || {})[d.motivo] || "Te pregunto antes de abrir esto.")}</p>`;
      }
      return "";
    }
    // La línea diaria: si hoy no se operó, el mejor puntaje del día contra la exigencia. Las propuestas que vencieron
    // sin respuesta se cuentan al lado: dejarlas pasar también es lo que hizo el día.
    function lineaDiaria(p) {
      const d = p.dia || {}, partes = [];
      if (d.opero) {
        partes.push(frase("Hoy abrí {entradas} y cerré {cerradas}.", {
          entradas: numero(d.entradas, 0), cerradas: numero(d.cerradas, 0) }));
      } else if (typeof d.mejor_puntaje !== "number") {
        partes.push(frase("Hoy no operé: todavía no tengo ningún puntaje del día, y la exigencia es {exigencia}.", {
          exigencia: numero(d.exigencia, 0) }));
      } else {
        partes.push(frase("Hoy no operé: mejor puntaje {n}, exigencia {exigencia}.", {
          n: numero(d.mejor_puntaje, 0), exigencia: numero(d.exigencia, 0) }));
      }
      if (d.vencidas > 0) {
        partes.push(frase("Dejé pasar {n} propuestas sin respuesta.", { n: numero(d.vencidas, 0) }));
      }
      return partes.join(" ");
    }

    // ── El saldo en USDT, con la línea del piso y su referencia en moneda local ──
    function saldo(p) {
      const s = p.saldo || {}, l = p.local || {};
      const local = enLocal(s.saldo, l);
      const parte = Math.round(Math.min(Math.max(s.sobre_piso || 0, 0), 1) * 100);
      return `<div class="saldo">
        <p class="saldo-monto" data-sin-traducir>${esc(usdt(s.saldo))}</p>
        ${local
          ? `<p class="saldo-local">${frase("≈ {monto} · referencia, la operación es en USDT", { monto: local })}</p>`
          : `<p class="saldo-local">Dime en Ajustes a cuánto está un USDT en tu moneda y te muestro la referencia al lado.</p>`}
        <div class="piso" role="img" aria-label="${esc(Tp("El saldo entre el piso y el capital de referencia"))}">
          <span class="piso-barra" style="width: ${parte}%"></span></div>
        <p class="saldo-linea">${s.toco_piso_absoluto
          ? frase("El saldo tocó el piso absoluto ({piso}): cierro a mercado lo que quede abierto y no abro nada más.", { piso: usdt(s.piso_absoluto) })
          : (s.toco_piso
            ? frase("El saldo tocó el piso ({piso}): no abro nada. Lo abierto sigue con su protección automática.", { piso: usdt(s.piso) })
            : frase("La línea del piso está en {piso}: el {parte} bajo tu capital de referencia ({referencia}).", {
              piso: usdt(s.piso), parte: porcentaje(s.parte, 0), referencia: usdt(s.referencia) }))}</p>
        <p class="saldo-linea">${frase("Hoy partí con {inicio} y el día se cierra si pierdo el {parte}.", {
          inicio: usdt((s.dia || {}).inicio), parte: porcentaje((s.dia || {}).limite, 0) })}</p>
        <p class="ayuda">${frase("**Piso**: el saldo en el que dejo de abrir cosas, el {parte} bajo tu capital de referencia. Más abajo está el piso absoluto ({absoluto}), el {parte_absoluto} bajo lo que aportaste: si el saldo lo toca, cierro a mercado lo que quede abierto.", {
          parte: porcentaje(s.parte, 0), absoluto: usdt(s.piso_absoluto),
          parte_absoluto: porcentaje(s.parte_absoluto, 0) })}</p></div>`;
    }

    // ── Los medidores: el puntaje de cada par contra la exigencia ──
    function medidor(m) {
      const parte = Math.round(Math.min(Math.max(m.parte || 0, 0), 1) * 100);
      const exigencia = Math.round(Math.min(Math.max((m.exigencia || 0) / MAXIMO, 0), 1) * 100);
      const detalle = typeof m.puntaje !== "number"
        ? frase(SIN_PUNTAJE[m.motivo] || "{par}: todavía no tengo puntaje de este par.", { par: m.par })
        : frase("{estrategia} en {temporalidad}: compro {monto} a {entrada}, con stop en {stop} y objetivo en {objetivo}.", {
          estrategia: Tp(E.estrategia[m.estrategia] || m.estrategia || ""),
          temporalidad: E.temporalidad[m.temporalidad] || m.temporalidad || "", monto: usdt(m.monto),
          entrada: numero(m.entrada), stop: numero(m.stop), objetivo: numero(m.objetivo) });
      // Sobre o bajo la exigencia, dicho con palabras y no solo con el color de la barra.
      const corte = typeof m.puntaje !== "number" ? "Sin puntaje todavía"
        : (m.pasa ? "Sobre la exigencia" : "Bajo la exigencia");
      // La barra es un dibujo: quien no la ve oye los dos números, el puntaje y la exigencia.
      const dibujo = typeof m.puntaje === "number"
        ? Tp("{par}: puntaje {n} de {maximo}, exigencia {exigencia}", {
          par: m.par, n: numero(m.puntaje, 0), maximo: numero(MAXIMO, 0), exigencia: numero(m.exigencia, 0) })
        : Tp("{par}: sin puntaje todavía, exigencia {exigencia}", { par: m.par, exigencia: numero(m.exigencia, 0) });
      return `<li class="medidor">
        <span class="medidor-par" data-sin-traducir>${esc(m.par)}</span>
        <span class="medidor-nota">${typeof m.puntaje === "number"
          ? frase("{n} de {maximo} · exigencia {exigencia}", { n: numero(m.puntaje, 0), maximo: numero(MAXIMO, 0), exigencia: numero(m.exigencia, 0) })
          : frase("sin puntaje · exigencia {exigencia}", { exigencia: numero(m.exigencia, 0) })}</span>
        <span class="serie-estado" data-estado="${m.pasa ? "listo" : "vacio"}">${corte}</span>
        <div class="medidor-barra" role="img" aria-label="${esc(dibujo)}" data-sin-traducir>
          <span class="medidor-valor${m.pasa ? " pasa" : ""}" style="width: ${parte}%"></span>
          <span class="medidor-exigencia" style="left: ${exigencia}%"></span></div>
        <span class="serie-detalle">${detalle}</span>
        ${(typeof m.puntaje === "number" && !m.puede && m.motivo)
          ? `<span class="serie-detalle freno">${Tp(E.motivosTamano[m.motivo] || "Con esta oportunidad no me sale ningún monto.", { par: m.par, n: 0 })}</span>`
          : ""}
        ${(typeof m.puntaje === "number" && m.puede && !m.pasa)
          ? `<span class="serie-detalle">${frase("No llega a la exigencia ({exigencia}): me quedo en USDT.", { exigencia: numero(m.exigencia, 0) })}</span>`
          : ""}</li>`;
    }

    // ── Las posiciones: lo que llevan ganado, su stop y su objetivo ──
    // Una abierta sin su protección automática no se lee igual que una protegida: el color del estado lo dice y el
    // detalle lo repite en palabras.
    function posicion(o) {
      const abierta = o.estado === "abierta";
      const donde = [o.par, E.temporalidad[o.temporalidad] || o.temporalidad].filter(Boolean).join(" · ");
      const estado = abierta ? (o.protegida ? "listo" : "incompleto") : "vacio";
      return `<li class="serie">
        <span class="serie-par" data-sin-traducir>${esc(donde)}</span>
        <span class="serie-estado" data-estado="${estado}">${E.posicion[o.estado] || o.estado}</span>
        ${typeof o.puntaje === "number"
          ? `<span class="serie-estado">${frase("Puntaje {n}", { n: numero(o.puntaje, 0) })}</span>` : ""}
        <span class="serie-detalle">${Tp(E.estrategia[o.estrategia] || o.estrategia || "")}</span>
        <span class="serie-detalle">${abierta
          ? frase("Compré {cantidad} a {entrada}: ahora vale {valor}.", {
            cantidad: numero(o.cantidad, 8), entrada: numero(o.precio), valor: usdt(o.valor) })
          : frase("Compra esperando en {entrada} por {monto}: hasta que se llene, no hay nada abierto.", {
            entrada: numero(o.precio), monto: usdt(o.monto) })}</span>
        ${(abierta && typeof o.ganancia === "number")
          ? `<span class="serie-detalle ${o.ganancia < 0 ? "freno" : "gana"}">${frase("Lleva {monto} ({parte}).", {
            monto: usdt(o.ganancia), parte: porcentaje(o.ganancia_relativa, 2) })}</span>`
          : (abierta ? `<span class="serie-detalle">Todavía no sé cuánto lleva: me faltan velas de 1 minuto de este par.</span>` : "")}
        <span class="serie-detalle">${frase("Stop en {stop} y objetivo en {objetivo}.", {
          stop: numero(o.stop), objetivo: numero(o.objetivo) })}</span>
        ${o.movido ? `<span class="serie-detalle">El stop móvil ya subió el stop: cada vez que se mueve, repongo la protección automática.</span>` : ""}
        ${abierta
          ? `<span class="serie-detalle${o.protegida ? "" : " freno"}">${o.protegida
            ? "Protegida: tiene su protección automática puesta."
            : "Sin protección automática: la cierro en la próxima revisión."}</span>`
          : `<span class="serie-detalle">${frase("Vence el {cuando}: si el precio no llega a ese nivel, la cancelo y no queda nada abierto.", {
            cuando: fechaHoraMs(o.vence_ms) })}</span>`}</li>`;
    }
    // Cuántas hay y cuántas caben: lo primero que se pregunta quien mira la lista.
    function cuentasPosiciones(p, posiciones) {
      const abiertas = posiciones.filter((o) => o.estado === "abierta");
      return frase("Tengo {abiertas} abiertas y {puestas} esperando, de {n} que caben a la vez: {protegidas} con su protección automática.", {
        abiertas: numero(abiertas.length, 0),
        puestas: numero(posiciones.length - abiertas.length, 0),
        n: numero((p.parametros || {}).posiciones, 0),
        protegidas: numero(abiertas.filter((o) => o.protegida).length, 0) });
    }

    // ── Las propuestas que esperan, con su cuenta atrás ──
    function propuesta(o, extra) {
      const esperando = extra.respondiendo === o.id;
      const donde = [o.par, E.temporalidad[o.temporalidad] || o.temporalidad].filter(Boolean).join(" · ");
      return `<li class="serie">
        <span class="serie-par" data-sin-traducir>${esc(donde)}</span>
        <span class="serie-estado" data-estado="listo">${frase("Puntaje {n}", { n: numero(o.puntaje, 0) })}</span>
        <span class="serie-detalle">${Tp(E.estrategia[o.estrategia] || o.estrategia || "")}</span>
        <span class="serie-detalle">${frase("Compro {monto} a {precio}, con stop en {stop} y objetivo en {objetivo}: arriesgo {arriesgado}.", {
          monto: usdt(o.monto), precio: numero(o.entrada), stop: numero(o.stop), objetivo: numero(o.objetivo),
          arriesgado: usdt(o.arriesgado) })}</span>
        ${o.motivo ? `<span class="serie-detalle">${Tp((E.pregunta || {})[o.motivo] || "Te pregunto antes de abrir esto.")}</span>` : ""}
        <span class="serie-detalle cuenta" data-vence="${Math.max(0, Number(o.queda_ms) || 0)}" data-desde="${Date.now()}">${textoVence(Number(o.queda_ms) || 0)}</span>
        <span class="serie-detalle">
          <button type="button" class="pz-boton pz-principal" data-propuesta="${esc(o.id)}" data-si="1"${esperando ? " disabled" : ""}>${esperando ? "Un momento…" : "Sí, ábrela"}</button>
          <button type="button" class="pz-boton" data-propuesta="${esc(o.id)}" data-si="0"${esperando ? " disabled" : ""}>No, me quedo en USDT</button></span></li>`;
    }

    // ── El motor: hace cuánto miró, si está mirando o dormido y qué pasó mientras nadie miraba ──
    // Cada cosa que pasó, con su singular, igual que en la pantalla del motor: lo que va dentro de «Dormiste 9 h: …».
    function cosasMotor(r) {
      return (E.cosasMotor || []).filter(([c]) => (r[c] || 0) > 0)
        .map(([c, uno, varios]) => Tp(r[c] === 1 ? uno : varios, { n: numero(r[c], 0) })).join(", ");
    }
    function resumenMotor(r) {
      const tiempo = duracion((r.dormido_ms || 0) / 1000), que = cosasMotor(r);
      if (!que) {
        return r.dormido ? frase("Dormiste {tiempo} y en ese rato no pasó nada.", { tiempo })
          : Tp("En la última revisión no pasó nada.");
      }
      return r.dormido ? frase("Dormiste {tiempo}: {que}.", { tiempo, que }) : frase("En la última revisión: {que}.", { que });
    }
    function motor(p) {
      const m = p.motor || {}, r = m.resumen || {};
      const estado = m.activo ? "listo" : (m.corriendo ? "incompleto" : "vacio");
      const etiqueta = m.activo ? "Motor mirando" : (m.corriendo ? "Motor dormido" : "Motor apagado");
      return `<div class="panel-motor">
        <p class="panel-motor-linea"><span class="serie-estado" data-estado="${estado}">${etiqueta}</span>
          <span class="serie-detalle">${typeof m.hace_min === "number"
            ? frase("Última revisión hace {tiempo}; reviso cada {ciclo}.", {
              tiempo: duracion(m.hace_min * 60), ciclo: duracion(m.ciclo_segundos) })
            : "Todavía no he revisado nada: el motor no ha dado ninguna vuelta."}</span>
          ${m.ultima ? `<span class="serie-detalle">${frase("La última fue el {cuando}.", { cuando: fechaHora(m.ultima) })}</span>` : ""}</p>
        ${r.hasta_ms ? `<p class="indicadores-linea">${resumenMotor(r)}</p>` : ""}
        <p class="indicadores-linea${m.corriendo ? "" : " freno"}">Pilota solo trabaja con el equipo encendido: con la app cerrada o el equipo dormido nadie mira los cruces, y un stop se aplica recién cuando vuelvo.</p></div>`;
    }

    // ── El registro: lo último que hice, con los campos de siempre ──
    // Lo que se puede decir de una línea: solo las claves que conocemos (del Python vienen números y códigos, nunca
    // texto de afuera), cada una en palabras. Lo que no conocemos no se muestra.
    function detalleRegistro(l) {
      const o = l.orden || {}, r = l.resultado || {}, partes = [];
      if (typeof l.puntaje === "number") {
        partes.push(frase("puntaje {n} de {maximo}", { n: numero(l.puntaje, 0), maximo: numero(MAXIMO, 0) }));
      }
      const pedido = ORDENES[`${o.lado || ""} ${o.tipo || ""}`];
      if (pedido && typeof o.precio === "number") partes.push(frase(pedido, { precio: numero(o.precio) }));
      if (typeof o.monto === "number") partes.push(frase("orden por {monto}", { monto: usdt(o.monto) }));
      if (typeof o.stop === "number") partes.push(frase("stop en {n}", { n: numero(o.stop) }));
      if (o.estado && ESTADO_ORDEN[o.estado]) partes.push(Tp(ESTADO_ORDEN[o.estado]));
      if (r.por) partes.push(frase("cerró por {que}", { que: Tp(E.cierre[r.por] || r.por) }));
      if (typeof r.neto === "number") partes.push(frase("dejó {n}", { n: usdt(r.neto) }));
      if (typeof r.saldo === "number") partes.push(frase("saldo {n}", { n: usdt(r.saldo) }));
      if (typeof r.minutos === "number") partes.push(frase("esperó {n} min", { n: numero(r.minutos, 0) }));
      if (r.motivo) partes.push(frase("motivo: {que}", { que: Tp(E.motivoCorto[r.motivo] || r.motivo) }));
      return partes.join(" · ");
    }
    function historial(p) {
      const h = p.historial || {};
      const lineas = Array.isArray(h.ultimas) ? h.ultimas : [];
      if (!lineas.length) return `<p class="suave">Todavía no hay nada anotado en el registro de esta cuenta.</p>`;
      return `<p class="indicadores-linea">${frase("{n} líneas en el registro, desde el {desde} ({dias} días). Ninguna se cambia ni se borra.", {
          n: numero(h.lineas, 0), desde: fechaHora(h.desde), dias: numero(h.dias, 0) })}</p>
        <p class="ayuda">Cada línea lleva siempre los mismos campos: la fecha, el par, el puntaje, la razón, lo que pidió la orden y cómo terminó.</p>
        <ul class="tramos" aria-label="Lo último que hice">${lineas.map((l) => {
          const detalle = detalleRegistro(l);
          return `<li class="tramo">
            <span class="tramo-nombre" data-sin-traducir>${esc(fechaHora(l.fecha))}</span>
            <span class="serie-estado">${E.razones[l.razon] || "Quedó anotado"}</span>
            ${l.par ? `<span class="serie-detalle" data-sin-traducir>${esc(l.par)}</span>` : ""}
            ${detalle ? `<span class="serie-detalle">${detalle}</span>` : ""}</li>`;
        }).join("")}</ul>`;
    }

    // ── La pantalla entera ──
    function html(p, extra = {}) {
      if (!p) return `<section id="panel" class="panel"><p class="suave">Abriendo Pilota…</p></section>`;
      const medidores = Array.isArray(p.medidores) ? p.medidores : [];
      const posiciones = Array.isArray(p.posiciones) ? p.posiciones : [];
      const esperan = Array.isArray(p.propuestas) ? p.propuestas : [];
      const motivos = Array.isArray(p.motivos) ? p.motivos : [];
      return `<section id="panel" class="panel">
        <p class="ayuda">${frase(AMBIENTES[p.ambiente === "real" ? "real" : "prueba"])}</p>
        ${mascota(p)}
        ${saldo(p)}
        <p class="indicadores-linea">${frase("Estás en modo {modo}, y la exigencia de ahora es {exigencia} de {maximo}.", {
          modo: Tp(E.modo[p.modo] || p.modo || ""), exigencia: numero(p.exigencia, 0), maximo: numero(MAXIMO, 0) })}</p>
        ${esperan.length ? `<h3>Lo que te estoy proponiendo</h3>
          <ul class="series" aria-label="Propuestas esperando tu respuesta">${esperan.map((o) => propuesta(o, extra)).join("")}</ul>
          <p class="indicadores-linea">${frase("Hoy vencieron {n} propuestas: una que nadie responde vence siempre, y eso también queda en el registro.", { n: numero(p.vencidas_hoy, 0) })}</p>`
          : `<p class="indicadores-linea">${frase("No tengo nada esperando tu respuesta. Hoy vencieron {n} propuestas.", { n: numero(p.vencidas_hoy, 0) })}</p>`}
        <h3>Cómo se ve cada moneda ahora</h3>
        <p class="ayuda">${frase("**Puntaje**: qué tan buena se ve ahora la mejor oportunidad de ese par, de 0 a 100. **Exigencia**: el puntaje mínimo para entrar ({exigencia} de {maximo}), la marca de la barra. Bajo esa marca me quedo en USDT.", {
          exigencia: numero(p.exigencia, 0), maximo: numero(MAXIMO, 0) })}</p>
        <ul class="medidores" aria-label="Puntaje y exigencia por par">${medidores.map(medidor).join("")}</ul>
        <h3>Lo que tengo abierto</h3>
        ${posiciones.length
          ? `<p class="indicadores-linea">${cuentasPosiciones(p, posiciones)}</p>
            <ul class="series" aria-label="Mis posiciones">${posiciones.map(posicion).join("")}</ul>`
          : `<p class="suave">${frase("No tengo nada abierto: todo el saldo está en USDT. Caben {n} posiciones a la vez.", { n: numero((p.parametros || {}).posiciones, 0) })}</p>`}
        ${motor(p)}
        ${motivos.map((m) => `<p class="indicadores-linea freno">${Tp(MOTIVOS[m.codigo] || E.motivosFrenos[m.codigo] || "Ahora no abro ninguna entrada nueva.", { n: numero(m.n, 0), par: m.par || "" })}</p>`).join("")}
        <h3>Lo último que hice</h3>
        ${historial(p)}</section>`;
    }

    // La cuenta atrás de cada propuesta, una vez por segundo: solo cambia ese texto, sin volver a pintar la pantalla.
    function latir(raiz) {
      const ahora = Date.now();
      let vivas = 0;
      for (const el of (raiz || document).querySelectorAll(".cuenta[data-vence]")) {
        const queda = Math.max(0, Number(el.dataset.vence) - (ahora - Number(el.dataset.desde)));
        if (queda > 0) vivas += 1;
        el.innerHTML = queda > 0 ? textoVence(queda) : Tp("Se acabó el tiempo: la dejé pasar y queda en el registro.");
      }
      return vivas;
    }

    return { html, latir };
  }

  return { crear };
})();
