// Pilota: la interfaz. La misma en Mac, Windows y Linux (host-tauri, con el WebView del sistema) y en el navegador (vista previa con demo.json).
// La app manda el estado con window.Pilota.estado(json); la interfaz pide cosas con host.enviar(accion, datos).
// Empezó con «pieza.py crear» (pieza «esqueleto» de Pieza): desde ahí es de la app.
// Las piezas de interfaz (host.js, i18n.js, tema.*, componentes.*, bienvenida.*) no se editan aquí: ver AGENTS.md → «Piezas».
(() => {
  "use strict";
  // ── Puente con la app: pieza «host-ui». host.plataforma es "mac" | "windows" | "linux" | "web" (vista previa: simular()). ──
  const host = PiezaHost.crearHost({ nombre: "pilota", global: "Pilota", simular: (accion, d, c) => simular(accion, d, c) });
  const NOMBRE = "Pilota";
  const REPO = "pilota-app/pilota";
  const ENLACES = { sitio: "https://pilota-app.github.io/pilota/", codigo: `https://github.com/${REPO}`, comunidad: `https://github.com/${REPO}/discussions`,
    aportar: `https://github.com/${REPO}/blob/main/CONTRIBUTING.md` };
  const DIAS = 90;   // lo primero que se baja para poder calcular (bin/lib_datos.py: DIAS_MINIMOS)
  // El monto de prueba sugerido en USDT: con él se dice si el capital alcanza. Elegirlo es parte del primer uso guiado (su propio paso del plan).
  const CAPITAL_PRUEBA = 200;
  // La escala del puntaje de una oportunidad (bin/lib_puntaje.py: PUNTAJE_MAXIMO).
  const PUNTAJE_MAXIMO = 100;
  // Los dos trabajos en segundo plano (bin/historial.py y bin/muestreo.py): las etapas del historial largo, en el mismo orden.
  const ETAPAS_HISTORIAL = ["1d", "4h", "1h"];
  const E = { config: {}, version: "", ias: [], ajustes: false, datos: null, descargando: false, iniciada: false,
    minimo: null, calculando: false, historial: null, muestreo: null, bajando: false, muestreando: false,
    indicadores: null, calculandoIndicadores: false, senales: null, calculandoSenales: false,
    backtest: null, corriendo: false, puntaje: null, puntuando: false, calibracion: null, calibrando: false,
    estado: null, reiniciando: false, tamano: null, frenos: null, pausando: false, desbloqueando: false,
    ejecutor: null, ejecutando: false, motor: null, revisandoMotor: false, encendiendoMotor: false,
    modos: null, decision: null, decidiendo: false, respondiendo: "", cambiandoModo: "",
    panel: null, guardandoLocal: false, pidiendoPanel: false };
  const raiz = document.getElementById("app");
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => "&#" + c.charCodeAt(0) + ";");

  // ── Idiomas: pieza «i18n». Las claves son la frase en español; el inglés, en idiomas/en.json (todo texto nuevo va ahí). ──
  // Regla: una frase sin valores se escribe en español tal cual (la traduce traducirDOM); una con valores va con frase(), que la
  // traduce, escapa los valores y la deja marcada data-sin-traducir.
  const faltantes = new Set();   // pruebas/interfaz.mjs revisa que no quede nada sin traducir
  const i18n = PiezaI18n.crear({ faltantes });
  const { Tp, frase } = i18n;
  let idiomaElegido = null;
  async function cargarIdioma(elegido) {
    // Lo recién elegido > ?idioma= (vista previa y pruebas) > lo guardado > el del sistema.
    if (elegido) idiomaElegido = elegido;
    await i18n.cargar(i18n.elegir({ elegido: idiomaElegido, config: E.config.idioma_ui }));
    document.documentElement.lang = i18n.idioma;
  }

  // ── Tema (sistema, claro u oscuro) y componentes (diálogos, avisos, Tu IA, actualizaciones, Acerca de) ──
  const tema = PiezaTema.crear({ guardar: (v) => { E.config.tema = v; host.enviar("config", { tema: v }); } });
  const ui = PiezaComponentes.crear({
    i18n, host, app: NOMBRE, repo: REPO, version: () => E.version, pintar, mantenerCampos: true,
    cerrar: () => { E.ajustes = false; pintar(); },   // Esc, el velo o ✕ sobre un diálogo de la app
    retener: (...a) => bv.retener(...a),               // mientras se elige el idioma, los avisos esperan
    elegirIA: (id) => { E.config.ia = id; host.enviar("config", { ia: id }); },
  });
  const toast = (frase_, o) => ui.aviso(frase_, o);

  // ── Conectar a tu IA (MCP): pieza «mcp». Solo lectura y apagada hasta que la persona conecta su IA en Ajustes. ──
  const mcpUI = PiezaMCP.crear({ i18n, host, pintar, app: NOMBRE, aviso: (t, o) => toast(t, o),
    ejemplo: "¿Qué decidió Pilota hoy y con qué puntaje?" });

  // ── Bienvenida: pieza «bienvenida». El idioma siempre primero y solo en la pantalla; después, los pasos de la app. ──
  const bv = PiezaBienvenida.crear({
    i18n, pintar, mostrarAviso: (...a) => toast(...a),
    guardarIdioma: (c) => { E.config.idioma_ui = c; host.enviar("config", { idioma_ui: c }); },
    cargarIdioma: (c) => cargarIdioma(c),
    terminar: () => { E.config.bienvenida = true; host.enviar("config", { bienvenida: true }); },
  });
  // La app: el primer uso guiado completo (riesgos, monto de prueba, camino con avance) es su propio paso del plan.
  bv.sumarPaso({ id: "hola", orden: 10, titulo: "Te damos la bienvenida", saltable: false,
    cuerpo: () => `<p><b data-sin-traducir>${esc(NOMBRE)}</b></p><p>La app: en una o dos frases, qué hace y para quién.</p>` });
  bv.sumarPaso({ id: "ia", orden: 20, titulo: "Elige tu IA", puede: () => !!E.config.ia,
    cuerpo: () => `<p>Usa la IA que ya tienes, con tu cuenta. La probamos con una pregunta corta.</p>${ui.filasIA({ ias: E.ias, elegida: E.config.ia })}` });

  // ── Lo que se ve ──
  const ETIQUETA_TEMPORALIDAD = { "1m": "1 m", "1h": "1 h", "4h": "4 h", "1d": "1 d" };
  const ETIQUETA_ESTADO = { listo: "Al día", incompleto: "Falta historial", vacio: "Sin datos" };
  const MOTIVOS = {
    sin_datos: "{par} {temporalidad}: sin velas todavía",
    faltan_velas: "{par} {temporalidad}: faltan {n} velas",
    huecos: "{par} {temporalidad}: la serie tiene {n} huecos",
    atrasado: "{par} {temporalidad}: la última vela no es la más reciente",
    sin_muestras: "{par}: todavía no hay ninguna muestra del libro",
    muestra_vieja: "{par}: la última muestra del libro es de hace {n} min",
    sin_tendencia_diaria: "{par} {temporalidad}: falta historial para saber si el día viene al alza",
    sin_contexto: "{par} {temporalidad}: falta historial para saber cómo viene BTC",
  };
  const ERRORES = {
    red: "No pude hablar con Binance. Revisa tu conexión e intenta de nuevo.",
    limite: "Binance pidió esperar: intenta de nuevo en unos minutos.",
    respuesta: "Binance respondió algo que no entendí. Intenta de nuevo.",
    monto: "Ese monto no me cuadra: tiene que ser en USDT y no más de lo que Pilota se cree.",
    pausa: "Eso es un sí o un no, y no me llegó ninguno de los dos.",
    modo: "Ese modo no existe: solo tengo manual, semiautomático y automático.",
    vencimiento: "Una propuesta puede esperar 5, 15 o 60 minutos, nada más.",
    sin_propuesta: "Esa propuesta ya no está esperando: o la respondiste o venció.",
    moneda: "Eso no me parece una moneda: son tres a ocho letras, como CLP, EUR o MXN.",
    tasa: "Esa tasa no me cuadra: dime con un número cuánto vale un USDT en tu moneda.",
  };
  const MOTIVOS_MINIMO = {
    sin_proteccion: "{par}: Binance no acepta protección automática en este par",
    sin_operar: "{par}: Binance tiene detenido este par",
  };
  const numero = (n, max = 2) => (typeof n === "number" && isFinite(n)
    ? n.toLocaleString(i18n.idioma, { maximumFractionDigits: max }) : "—");
  const usdt = (n) => `${numero(n)} USDT`;
  // `max` de decimales: la diferencia entre compra y venta de un par líquido es de milésimas de por ciento y se ve igual.
  const porcentaje = (n, max = 3) => (typeof n === "number" && isFinite(n) ? `${numero(n * 100, max)} %` : "—");
  const fecha = (ms) => (typeof ms === "number" && isFinite(ms)
    ? new Date(ms).toLocaleDateString(i18n.idioma, { day: "2-digit", month: "short", year: "numeric" }) : "—");
  const mes = (texto) => {
    const [a, m] = String(texto ?? "").split("-");
    const d = new Date(Date.UTC(Number(a), Number(m) - 1, 1));
    return isNaN(d.getTime()) ? "—" : d.toLocaleDateString(i18n.idioma, { month: "long", year: "numeric" });
  };
  // El tiempo que falta, en palabras y sin falsa precisión: lo que estima el trabajo son minutos, no segundos.
  const duracion = (segundos) => {
    const s = Math.max(0, Math.round(Number(segundos) || 0));
    if (s < 90) return Tp("menos de un minuto");
    if (s < 5400) return Tp("{n} min", { n: Math.round(s / 60) });
    return Tp("{n} h", { n: Math.round(s / 3600) });
  };
  const fechaHora = (texto) => {
    const d = new Date(String(texto ?? ""));
    return isNaN(d.getTime()) ? "—" : d.toLocaleString(i18n.idioma, { dateStyle: "medium", timeStyle: "short" });
  };
  // Lo mismo desde un momento en milisegundos (lo que guarda el Python cuando no escribe la fecha al lado).
  const fechaHoraMs = (ms) => (typeof ms === "number" && isFinite(ms)
    ? new Date(ms).toLocaleString(i18n.idioma, { dateStyle: "medium", timeStyle: "short" }) : "—");

  // Siempre arriba y del mismo color en todas las pantallas: con qué dinero se está jugando. El ambiente lo dice la app
  // (bin/panel.py); hasta que llega, la banda es la de prueba, que es con la que se parte.
  function banda() {
    const ambiente = (E.panel && E.panel.ambiente === "real") ? "real" : "prueba";
    return `<p class="banda banda-${ambiente}" role="status">${ETIQUETA_AMBIENTE[ambiente]}</p>`;
  }
  // La falta de historial de una serie, en palabras: los códigos vienen del Python (lib_datos, lib_indicadores) y se traducen
  // aquí; nunca se muestra texto que venga de Binance.
  function textoMotivo(m, etiqueta) {
    return frase(MOTIVOS[m && m.codigo] || "{par} {temporalidad}: falta historial",
      { par: m.par, temporalidad: ETIQUETA_TEMPORALIDAD[m.temporalidad] || m.temporalidad, n: m.n }, etiqueta);
  }
  function motivo(m) {
    return textoMotivo(m, "li");
  }
  function estadoDatos() {
    if (!E.datos) return `<p id="datos-estado" class="estado-datos">Revisando los datos…</p>`;
    if (E.datos.puede_operar) {
      return `<p id="datos-estado" class="estado-datos listo">${frase("Historial completo y continuo: {n} velas guardadas.", { n: E.datos.velas })}</p>`;
    }
    const motivos = Array.isArray(E.datos.motivos) ? E.datos.motivos : [];
    const resto = Math.max(0, motivos.length - 4);
    return `<div id="datos-estado" class="estado-datos falta"><p>Aún no puedo operar: falta historial.</p>
      <ul class="motivos">${motivos.slice(0, 4).map(motivo).join("")}${resto ? frase("y {n} series más", { n: resto }, "li") : ""}</ul></div>`;
  }
  function serie(s) {
    const detalle = s.velas
      ? frase("{n} velas · {desde} → {hasta}", { n: s.velas, desde: fecha(s.desde), hasta: fecha(s.hasta) })
      : `<span>Sin velas guardadas</span>`;
    return `<li class="serie">
      <span class="serie-par" data-sin-traducir>${esc(s.par)} · ${esc(ETIQUETA_TEMPORALIDAD[s.temporalidad] || s.temporalidad)}</span>
      <span class="serie-estado" data-estado="${esc(s.estado)}">${ETIQUETA_ESTADO[s.estado] || "Sin datos"}</span>
      <span class="serie-detalle">${detalle}</span></li>`;
  }
  function descarga() {
    const d = E.datos && E.datos.descarga;
    if (!d || !d.cuando) return `<p class="suave">Todavía no has descargado el historial.</p>`;
    return `<p class="suave">${frase("Última descarga: {cuando} · {n} velas nuevas", { cuando: fechaHora(d.cuando), n: d.nuevas || 0 })}</p>`;
  }
  // ── Capital mínimo viable: lo menos con lo que se puede operar de verdad (bin/minimo_viable.py) ──
  function parMinimo(p) {
    return `<li class="serie">
      <span class="serie-par" data-sin-traducir>${esc(p.par)}</span>
      <span class="serie-detalle">${frase("Desde {monto} por posición", { monto: usdt(p.posicion) })}</span>
      <span class="serie-detalle">${frase("{cantidad} {moneda} · Binance pide {nocional} por orden", { cantidad: numero(p.cantidad, 8), moneda: p.moneda, nocional: usdt(p.nocional_minimo) })}</span>
      ${p.motivo ? `<span class="serie-estado" data-estado="incompleto">${motivoMinimo(p)}</span>` : ""}</li>`;
  }
  function motivoMinimo(p) {
    return frase(MOTIVOS_MINIMO[p.motivo] || "{par}: Binance no acepta este par", { par: p.par });
  }
  // Las comisiones con las que se hace la cuenta (el capital mínimo viable y la familia costo): las de la API o las supuestas.
  function lineaComisiones(c) {
    const valores = { maker: porcentaje(c.maker), taker: porcentaje(c.taker), conversion: porcentaje(c.conversion) };
    return c.origen === "api"
      ? frase("Comisiones de tu cuenta: {maker} al entrar y {taker} al salir con el stop, más {conversion} de conversión USDT↔FDUSD.", valores)
      : frase("Comisiones supuestas: {maker} al entrar y {taker} al salir con el stop, más {conversion} de conversión USDT↔FDUSD. Las de verdad se leen de Binance cuando conectes tu llave.", valores);
  }
  function minimoViable() {
    const m = E.minimo;
    const etiqueta = E.calculando ? "Preguntando a Binance…" : (m && m.calculado ? "Calcular de nuevo" : "Calcular con los mínimos de Binance");
    const boton = `<div class="pz-pie"><button type="button" class="pz-boton" id="calcular-minimo"${E.calculando ? " disabled" : ""}>${etiqueta}</button></div>`;
    if (!m || !m.calculado) {
      return `<div id="minimo" class="minimo"><p class="suave">Todavía no lo he calculado: necesito los mínimos que Binance tiene ahora.</p>${boton}</div>`;
    }
    const pares = Array.isArray(m.pares) ? m.pares : [];
    return `<div id="minimo" class="minimo">
      <p class="minimo-monto" data-sin-traducir>${esc(usdt(m.capital_minimo))}</p>
      <p class="minimo-cabe ${m.alcanza ? "alcanza" : "falta"}">${m.alcanza
        ? frase("Con los {capital} del modo prueba alcanza.", { capital: usdt(m.capital) })
        : frase("Con los {capital} del modo prueba te faltan {falta}.", { capital: usdt(m.capital), falta: usdt(m.falta) })}</p>
      ${pares.length ? `<ul class="series" aria-label="Mínimo por par">${pares.map(parMinimo).join("")}</ul>` : ""}
      <p class="suave">${lineaComisiones(m.comisiones || {})}</p>
      <p class="suave">${frase("Calculado el {cuando}, con el stop supuesto a {caida} del precio de entrada.", { cuando: fechaHora(m.cuando), caida: porcentaje(m.caida_stop) })}</p>
      ${boton}</div>`;
  }
  // ── Los dos trabajos en segundo plano (pieza «trabajos»): los 3 años de velas y el muestreo del mercado ──
  // Los dos muestran lo mismo: el porcentaje, el tiempo que falta y en qué quedaron. El avance llega en los eventos de
  // progreso del trabajo (historialProgreso, muestreoProgreso) y también queda escrito en disco, así nada se pierde.
  function etapaHistorial(e) {
    // Una etapa con hoyos no está «al día» aunque esté bajada: con velas faltando en medio no se puede calcular (bin/historial.py).
    const lista = e.listo && !e.huecos;
    return `<li class="tramo">
      <span class="tramo-nombre" data-sin-traducir>${esc(ETIQUETA_TEMPORALIDAD[e.temporalidad] || e.temporalidad)}</span>
      <span class="serie-estado" data-estado="${lista ? "listo" : "incompleto"}">${lista ? "Al día" : "Falta historial"}</span>
      <span class="serie-detalle">${frase("{n} de {total} velas", { n: numero(e.velas, 0), total: numero(e.esperadas, 0) })}</span>
      ${e.huecos ? `<span class="serie-detalle">${frase("{n} huecos", { n: e.huecos })}</span>` : ""}
      ${e.desde ? `<span class="serie-detalle">${frase("desde el {desde}", { desde: fecha(e.desde) })}</span>` : ""}</li>`;
  }
  function lineaHistorial(h) {
    if (h.deteniendo) return "Deteniendo: termino la página que estoy bajando.";
    if (h.corriendo) {
      return frase("Etapa {n} de {total}: velas de {temporalidad} · falta {tiempo}", {
        n: Math.max(1, ETAPAS_HISTORIAL.indexOf(h.etapa) + 1), total: ETAPAS_HISTORIAL.length,
        temporalidad: ETIQUETA_TEMPORALIDAD[h.etapa] || h.etapa, tiempo: duracion(h.falta_segundos) });
    }
    if (h.estado === "error") return frase(ERRORES[h.error] || "No se pudo.");
    // La continuidad se revisa al terminar cada par: un hoyo que Binance no entregó se dice y se reintenta en la próxima vuelta.
    if (h.huecos) return frase("Están los 3 años, pero quedan {n} huecos en las velas: vuelve a intentar para rellenarlos.", { n: h.huecos });
    if (!h.faltan) return frase("Listo: {n} velas guardadas de los 3 años.", { n: numero(h.velas, 0) });
    if (h.estado === "detenido") return frase("Lo detuviste. Lo bajado queda guardado y falta {tiempo}.", { tiempo: duracion(h.falta_segundos) });
    if (h.estado === "interrumpido") return frase("Se cortó al cerrarse la app. Lo bajado queda guardado y falta {tiempo}.", { tiempo: duracion(h.falta_segundos) });
    return frase("Sin bajar todavía: son unos {tiempo} de descarga, y puedes detenerla cuando quieras.", { tiempo: duracion(h.falta_segundos) });
  }
  // El aviso al terminar la descarga de los 3 años: detenida a medias, bajada con hoyos o completa y continua.
  function finHistorial(h) {
    if (h.faltan) return "Detenido: lo que ya se bajó queda guardado.";
    if (h.huecos) return "Están los 3 años, pero quedaron huecos: puedes rellenarlos cuando quieras.";
    return "Listo: ya tienes los 3 años de velas.";
  }
  function botonHistorial(h) {
    if (h.corriendo) {
      return `<button type="button" class="pz-boton" id="historial-detener"${h.deteniendo ? " disabled" : ""}>${h.deteniendo ? "Deteniendo…" : "Detener"}</button>`;
    }
    const etiqueta = h.huecos ? "Rellenar los huecos"
      : (!h.faltan ? "Buscar lo que falte" : (h.velas ? "Seguir donde quedó" : "Bajar los 3 años"));
    return `<button type="button" class="pz-boton pz-principal" id="historial-bajar"${E.bajando ? " disabled" : ""}>${E.bajando ? "Bajando…" : etiqueta}</button>`;
  }
  function historial() {
    const h = E.historial;
    if (!h) return `<p class="suave">Revisando el historial largo…</p>`;
    return `<div id="historial" class="trabajo">
      <progress class="avance" max="100" value="${Number(h.pct) || 0}" aria-label="Avance de los 3 años"></progress>
      <p class="trabajo-pct">${frase("{pct} % · {velas} de {esperadas} velas",
        { pct: numero(h.pct, 1), velas: numero(h.velas, 0), esperadas: numero(h.esperadas, 0) })}</p>
      <p class="trabajo-linea">${lineaHistorial(h)}</p>
      <ul class="tramos" aria-label="Avance por temporalidad">${(h.etapas || []).map(etapaHistorial).join("")}</ul>
      <div class="pz-pie">${botonHistorial(h)}</div></div>`;
  }
  function parMuestreado(p) {
    return `<li class="tramo">
      <span class="tramo-nombre" data-sin-traducir>${esc(p.par)}</span>
      <span class="serie-detalle">${frase("compra {compra} · venta {venta}", { compra: numero(p.compra), venta: numero(p.venta) })}</span>
      <span class="serie-detalle">${frase("diferencia {spread}", { spread: porcentaje(p.spread_relativo, 4) })}</span></li>`;
  }
  function parMinutos(s) {
    return `<li class="tramo">
      <span class="tramo-nombre" data-sin-traducir>${esc(s.par)}</span>
      <span class="serie-estado" data-estado="${s.listo ? "listo" : "incompleto"}">${s.listo ? "Al día" : "Falta historial"}</span>
      <span class="serie-detalle">${frase("{n} de {total} velas de 1 m", { n: numero(s.velas, 0), total: numero(s.esperadas, 0) })}</span>
      ${s.huecos ? `<span class="serie-detalle">${frase("{n} huecos", { n: s.huecos })}</span>` : ""}</li>`;
  }
  function lineaMuestreo(m) {
    if (m.deteniendo) return "Deteniendo: termino el ciclo que estoy haciendo.";
    // Una vuelta que falla no termina el muestreo: se dice y se vuelve a intentar (bin/muestreo.py: FALLOS_SEGUIDOS).
    if (m.corriendo && m.fallos) {
      return frase("La última vuelta no resultó ({n} seguidas): lo intento de nuevo en {tiempo}", {
        n: m.fallos, tiempo: duracion(((m.proxima || 0) - Date.now()) / 1000) });
    }
    if (m.corriendo && m.faltan) {
      return frase("Poniendo al día las velas de 1 m · falta {tiempo}", { tiempo: duracion(m.falta_segundos) });
    }
    if (m.corriendo) {
      return frase("Muestreando cada {n} min: la próxima muestra, en {tiempo}",
        { n: Math.round((m.ciclo_segundos || 300) / 60), tiempo: duracion(((m.proxima || 0) - Date.now()) / 1000) });
    }
    if (m.estado === "error") return frase(ERRORES[m.error] || "No se pudo.");
    if (m.estado === "detenido") return "Lo detuviste: Pilota no está guardando muestras.";
    if (m.estado === "interrumpido") return "Se cortó al cerrarse la app: Pilota no está guardando muestras.";
    return "Apagado. Lo que no se guarde hoy no se puede recuperar después.";
  }
  // La última vuelta y lo que quedó sin muestras: Binance no da libro histórico, así que el hueco se dice en vez de taparse
  // (bin/muestreo.py: `cuando` y `sin_cobertura` quedan escritos en el plan).
  function vueltaMuestreo(m) {
    const huecos = Array.isArray(m.sin_cobertura) ? m.sin_cobertura.length : 0;
    const vuelta = m.cuando
      ? frase("Última vuelta: {cuando}", { cuando: fechaHora(m.cuando) })
      : `<span>Todavía no ha habido ninguna vuelta.</span>`;
    return vuelta + (huecos ? ` · ${frase("ventanas sin muestras: {n}", { n: numero(huecos, 0) })}` : "");
  }
  function muestreo() {
    const m = E.muestreo;
    if (!m) return `<p class="suave">Revisando el muestreo…</p>`;
    const pares = (m.ultima && Array.isArray(m.ultima.pares)) ? m.ultima.pares : [];
    const minutos = Array.isArray(m.minutos) ? m.minutos : [];
    return `<div id="muestreo" class="trabajo">
      <progress class="avance" max="100" value="${Number(m.pct) || 0}" aria-label="Avance de las velas de 1 m"></progress>
      <p class="trabajo-pct">${frase("{pct} % de las velas de 1 m · {velas} de {esperadas}",
        { pct: numero(m.pct, 1), velas: numero(m.velas, 0), esperadas: numero(m.esperadas, 0) })}</p>
      <p class="trabajo-linea">${lineaMuestreo(m)}</p>
      ${minutos.length ? `<ul class="tramos" aria-label="Velas de 1 m por par">${minutos.map(parMinutos).join("")}</ul>` : ""}
      ${pares.length ? `<ul class="tramos" aria-label="Última muestra">${pares.map(parMuestreado).join("")}</ul>` : ""}
      <p class="suave">${m.muestras
        ? frase("{n} muestras guardadas desde {mes}", { n: numero(m.muestras, 0), mes: mes(m.mes_desde) })
        : `<span>Todavía no hay ninguna muestra guardada.</span>`}</p>
      <p class="suave">${vueltaMuestreo(m)}</p>
      <div class="pz-pie">${botonMuestreo(m)}</div></div>`;
  }
  function botonMuestreo(m) {
    if (m.corriendo) {
      return `<button type="button" class="pz-boton" id="muestreo-apagar"${m.deteniendo ? " disabled" : ""}>${m.deteniendo ? "Deteniendo…" : "Detener"}</button>`;
    }
    return `<button type="button" class="pz-boton pz-principal" id="muestreo-encender"${E.muestreando ? " disabled" : ""}>${E.muestreando ? "Empezando…" : "Empezar a muestrear"}</button>`;
  }
  // ── Indicadores de las siete familias (bin/lib_indicadores.py y bin/lib_indicadores_mercado.py): el valor de ahora ──
  // Una serie corta, atrasada o con hoyos no da indicadores: en vez de un número falso, su fila dice qué historial falta.
  function ruptura(e, n) {
    if (e.rompio_maximo) return frase("rompió el techo de las últimas {n} velas: {nivel}", { n: numero(n, 0), nivel: numero(e.maximo) });
    if (e.rompio_minimo) return frase("rompió el piso de las últimas {n} velas: {nivel}", { n: numero(n, 0), nivel: numero(e.minimo) });
    return frase("entre el piso {minimo} y el techo {maximo} de las últimas {n} velas", { minimo: numero(e.minimo), maximo: numero(e.maximo), n: numero(n, 0) });
  }
  function serieIndicador(s, d) {
    const nombre = `<span class="serie-par" data-sin-traducir>${esc(s.par)} · ${esc(ETIQUETA_TEMPORALIDAD[s.temporalidad] || s.temporalidad)}</span>`;
    if (!s.listo) {
      return `<li class="serie">${nombre}
        <span class="serie-estado" data-estado="incompleto">Falta historial</span>
        <span class="serie-detalle">${textoMotivo({ codigo: s.motivo, par: s.par, temporalidad: s.temporalidad, n: s.cuantas })}</span></li>`;
    }
    const t = s.tendencia || {};
    const i = s.impulso || {};
    const v = s.volatilidad || {};
    const vol = s.volumen || {};
    return `<li class="serie">${nombre}
      <span class="serie-estado" data-estado="listo">Al día</span>
      <span class="serie-detalle">${frase("medias {m20} / {m50} / {m200}",
        { m20: numero(t.media_20), m50: numero(t.media_50), m200: numero(t.media_200) })}</span>
      <span class="serie-detalle">${frase("fuerza {adx} · RSI {rsi} · MACD {macd}",
        { adx: numero(t.adx, 1), rsi: numero(i.rsi, 1), macd: numero(i.macd) })}</span>
      <span class="serie-detalle">${frase("banda {baja} a {alta} · se mueve {atr} por vela · volumen {veces} veces lo normal",
        { baja: numero(v.banda_baja), alta: numero(v.banda_alta), atr: numero(v.atr), veces: numero(vol.relativo, 1) })}</span>
      <span class="serie-detalle">${ruptura(s.estructura || {}, (d && d.ruptura) || 0)}</span></li>`;
  }
  // El contexto de BTC: la misma serie de 1 d que mira el filtro de BTC, con sus dos parámetros a la vista.
  function contextoBTC(c) {
    if (!c) return "";
    const nombre = `<span data-sin-traducir>${esc(c.par)} · ${esc(ETIQUETA_TEMPORALIDAD[c.temporalidad] || c.temporalidad)}</span>`;
    if (!c.listo) {
      return `<p class="indicadores-linea">${nombre} — ${textoMotivo({ codigo: c.motivo, par: c.par, temporalidad: c.temporalidad, n: c.cuantas })}</p>`;
    }
    const datos = { cierre: numero(c.cierre), cambio: porcentaje(c.cambio, 2), distancia: porcentaje(Math.abs(c.distancia_media || 0), 1) };
    return `<p class="indicadores-linea">${nombre} — ${c.sobre_media
      ? frase("cerró en {cierre} ({cambio} el último día) y va {distancia} por encima de su media de 200 días.", datos)
      : frase("cerró en {cierre} ({cambio} el último día) y va {distancia} por debajo de su media de 200 días.", datos)}</p>`;
  }
  // El costo de ahora, por par operado: la comisión, la diferencia entre compra y venta de la última muestra y la conversión.
  function costo(c) {
    if (!c) return "";
    const filas = (Array.isArray(c.pares) ? c.pares : []).map((p) => `<li class="serie">
      <span class="serie-par" data-sin-traducir>${esc(p.par)}</span>
      ${p.listo
        ? `<span class="serie-estado" data-estado="listo">Al día</span>
           <span class="serie-detalle">${frase("entre compra y venta {spread} · entrar y salir cuesta {total}", { spread: porcentaje(p.spread_relativo, 4), total: porcentaje(p.total) })}</span>`
        : `<span class="serie-estado" data-estado="incompleto">Falta la muestra</span>
           <span class="serie-detalle">${textoMotivo({ codigo: p.motivo, par: p.par, temporalidad: "", n: p.cuantas })}</span>`}</li>`).join("");
    return `<p class="indicadores-linea">${lineaComisiones(c)}</p>
      <ul class="series" aria-label="Costo por par operado">${filas}</ul>`;
  }
  function indicadores() {
    const d = E.indicadores;
    if (!d) return `<p class="suave">Calculando los indicadores…</p>`;
    const series = Array.isArray(d.series) ? d.series : [];
    return `<div id="indicadores" class="indicadores">
      <p class="indicadores-resumen">${frase("{n} de {total} series con indicadores al día", { n: numero(d.listas, 0), total: numero(series.length, 0) })}</p>
      <p class="indicadores-linea">${(d.motivos || []).length
        ? frase("A una serie le hacen falta {n} velas cerradas y seguidas para calcularla: con velas faltando en medio, los indicadores dirían cualquier cosa.", { n: numero(d.ventana, 0) })
        : frase("Calculado el {cuando} con la última vela cerrada de cada serie.", { cuando: fechaHora(d.cuando) })}</p>
      ${series.length ? `<ul class="series" aria-label="Indicadores por par y temporalidad">${series.map((s) => serieIndicador(s, d)).join("")}</ul>` : ""}
      <h3>El contexto: BTC en 1 d</h3>
      ${contextoBTC(d.contexto)}
      <h3>El costo de ahora</h3>
      ${costo(d.costo)}
      <div class="pz-pie"><button type="button" class="pz-boton" id="indicadores-calcular"${E.calculandoIndicadores ? " disabled" : ""}>${E.calculandoIndicadores ? "Calculando…" : "Calcular de nuevo"}</button></div></div>`;
  }
  // ── Las tres estrategias y el filtro de BTC (bin/lib_estrategias.py): las señales crudas, todavía sin puntaje ──
  // Una señal dice par, temporalidad, nivel de entrada, stop y objetivo. Si BTC cae no se entra a nada: la señal se sigue
  // viendo (es lo que después va a medir el backtest), pero su fila dice que no se puede entrar.
  function detalleSenal(s) {
    const datos = { entrada: numero(s.entrada), stop: numero(s.stop), objetivo: numero(s.objetivo) };
    const linea = s.estrategia === "ruptura"
      ? frase("Ruptura con volumen y el día al alza: compra con límite al volver a {entrada}, stop en {stop} y objetivo en {objetivo}.", datos)
      : frase("Rebote en la banda de abajo con el mercado sin rumbo: compra con límite en {entrada}, stop en {stop} y objetivo en la media, {objetivo}.", datos);
    return `<span class="serie-detalle">${linea}</span>
      <span class="serie-detalle">${frase("arriesga {riesgo} para ganar {gana} · la orden límite espera {n} velas", {
        riesgo: porcentaje(s.distancia_stop, 2), gana: porcentaje(s.distancia_objetivo, 2), n: numero(s.vigencia_velas, 0) })}</span>`;
  }
  function serieSenal(s) {
    const nombre = `<span class="serie-par" data-sin-traducir>${esc(s.par)} · ${esc(ETIQUETA_TEMPORALIDAD[s.temporalidad] || s.temporalidad)}</span>`;
    if (!s.listo) {
      return `<li class="serie">${nombre}
        <span class="serie-estado" data-estado="incompleto">Falta historial</span>
        <span class="serie-detalle">${textoMotivo({ codigo: s.motivo, par: s.par, temporalidad: s.temporalidad, n: s.cuantas })}</span></li>`;
    }
    const suyas = Array.isArray(s.senales) ? s.senales : [];
    const puede = suyas.some((x) => x.permitida);
    // Sin la serie de 1 d no se sabe para dónde va el día: la ruptura no se mira y se dice cuál es la serie que falta.
    const sinDia = (s.al_alza === null || s.al_alza === undefined)
      ? `<span class="serie-detalle">${textoMotivo({ codigo: "sin_tendencia_diaria", par: s.par_diario, temporalidad: "1d", n: 0 })}</span>`
      : "";
    return `<li class="serie">${nombre}
      <span class="serie-estado" data-estado="${suyas.length ? (puede ? "listo" : "incompleto") : ""}">${
        suyas.length ? (puede ? "Se puede entrar" : "No se entra") : "Sin señal"}</span>
      ${suyas.length ? suyas.map(detalleSenal).join("")
        : `<span class="serie-detalle">Ninguna de las dos estrategias se gatilló con la última vela cerrada.</span>`}
      ${sinDia}</li>`;
  }
  function filtroBTC(f) {
    if (!f) return "";
    const datos = { cambio: porcentaje(f.cambio, 2), caida: porcentaje(f.caida, 2) };
    if (f.motivo === "sin_contexto") return `<p class="indicadores-linea freno">Sin el historial de BTC en 1 d no se entra a nada: con BTC a ciegas, ninguna oportunidad se mira.</p>`;
    if (f.motivo === "btc_cae") return `<p class="indicadores-linea freno">${frase("BTC cayó {cambio} en el último día cerrado, {caida} o más: hoy no se entra a nada.", datos)}</p>`;
    if (f.motivo === "btc_bajo_media") return `<p class="indicadores-linea freno">BTC cerró bajo su media de 200 días: no se entra a nada hasta que vuelva a estar encima.</p>`;
    return `<p class="indicadores-linea">${frase("BTC viene bien ({cambio} el último día y sobre su media de 200 días): el filtro deja entrar.", datos)}</p>`;
  }
  function enUSDT(u) {
    if (!u) return "";
    if (u.razon === "btc") return `<p class="indicadores-linea">Quedarse en USDT es la única opción mientras el filtro de BTC no deje entrar.</p>`;
    if (u.razon === "sin_oportunidad") return `<p class="indicadores-linea">Quedarse en USDT: con la última vela cerrada, ninguna de las dos estrategias se gatilló.</p>`;
    return `<p class="indicadores-linea">Quedarse en USDT también es una opción, y se compara con las demás: cuál conviene lo va a decir el puntaje, en su paso.</p>`;
  }
  function senales() {
    const d = E.senales;
    if (!d) return `<p class="suave">Mirando las estrategias…</p>`;
    const series = Array.isArray(d.series) ? d.series : [];
    return `<div id="senales" class="indicadores">
      <p class="indicadores-resumen">${frase("Señales para entrar ahora: {n}", { n: numero(d.entrables, 0) })}</p>
      ${filtroBTC(d.filtro)}
      ${series.length ? `<ul class="series" aria-label="Señales por par y temporalidad">${series.map(serieSenal).join("")}</ul>` : ""}
      ${enUSDT(d.usdt)}
      <p class="suave">${frase("Mirado el {cuando} con la última vela cerrada de cada serie. Una señal cruda todavía no es una orden: le falta el puntaje, el costo y el tamaño.", { cuando: fechaHora(d.cuando) })}</p>
      <div class="pz-pie"><button type="button" class="pz-boton" id="senales-calcular"${E.calculandoSenales ? " disabled" : ""}>${E.calculandoSenales ? "Mirando…" : "Mirar de nuevo"}</button></div></div>`;
  }
  // ── El backtest de las señales crudas (bin/backtest.py): qué habrían hecho estas reglas con el historial ──
  // Sin exigencia todavía: es el primer paso del orden de la calibración. Lo que se muestra son mediciones sobre lo que ya
  // pasó, con los costos de cada lado y el supuesto conservador marcado: nunca una promesa de ganancia.
  const ETIQUETA_ESTRATEGIA = { ruptura: "Ruptura", rebote: "Rebote", usdt: "Quedarse en USDT" };
  const PLANES = {
    normal: "La compuerta pasa: cada estrategia, par y temporalidad llega a los casos que pide.",
    ancho: "Plan B: por temporalidad no alcanzaba, así que las dos se cuentan juntas. La calibración tiene que dejar el modelo en «No validado».",
    unico: "Plan B: tampoco alcanzaba por par, así que queda un solo tramo por estrategia. La calibración tiene que dejar el modelo en «No validado».",
    insuficiente: "Ni juntando todo hay casos suficientes: falta historial antes de calibrar.",
  };
  function comparacion(nombre, d) {
    return `<li class="tramo"><span class="tramo-nombre">${nombre}</span>
      <span class="serie-detalle">${frase("rendimiento {rendimiento} · caída máxima {caida} · {n} operaciones", {
        rendimiento: porcentaje((d || {}).rendimiento, 1), caida: porcentaje((d || {}).caida_maxima, 1),
        n: numero((d || {}).operaciones || 0, 0) })}</span></li>`;
  }
  // Un tramo de la compuerta: los casos que de verdad hay, sin contar dos veces las operaciones que vivieron el mismo rato.
  function tramoCasos(t, minimo) {
    const donde = [t.par, ETIQUETA_TEMPORALIDAD[t.temporalidad] || t.temporalidad].filter(Boolean).join(" · ");
    return `<li class="tramo"><span class="tramo-nombre">${esc(ETIQUETA_ESTRATEGIA[t.estrategia] || t.estrategia)}</span>
      ${donde ? `<span class="serie-par" data-sin-traducir>${esc(donde)}</span>` : `<span class="serie-par">todo junto</span>`}
      <span class="serie-estado" data-estado="${t.alcanza ? "listo" : "incompleto"}">${frase("{n} casos", { n: numero(t.casos, 0) })}</span>
      ${t.alcanza ? "" : `<span class="serie-detalle">${frase("faltan {n} para los {minimo} que pide la compuerta", {
        n: numero(t.faltan, 0), minimo: numero(minimo, 0) })}</span>`}</li>`;
  }
  function serieBacktest(s) {
    const nombre = `<span class="serie-par" data-sin-traducir>${esc(s.par)} · ${esc(ETIQUETA_TEMPORALIDAD[s.temporalidad] || s.temporalidad)}</span>`;
    if (s.motivo) {
      return `<li class="serie">${nombre}
        <span class="serie-estado" data-estado="incompleto">Falta historial</span>
        <span class="serie-detalle">${textoMotivo({ codigo: s.motivo, par: s.par, temporalidad: s.temporalidad, n: s.faltan })}</span></li>`;
    }
    const r = s.resumen || {};
    return `<li class="serie">${nombre}
      <span class="serie-estado" data-estado="listo">${frase("{n} operaciones", { n: numero(r.operaciones, 0) })}</span>
      <span class="serie-detalle">${frase("{senales} señales · {llenadas} se llenaron · acierta {aciertos} · deja {neto} por operación", {
        senales: numero(r.senales, 0), llenadas: numero(r.llenadas, 0), aciertos: porcentaje(r.aciertos, 0), neto: porcentaje(r.neto_medio, 2) })}</span>
      ${s.empalmada ? `<span class="serie-detalle">${frase("{n} velas prestadas del par contra USDT (con los costos de FDUSD)", { n: numero(s.prestadas, 0) })}</span>` : ""}</li>`;
  }
  function sensibilidad(s) {
    const linea = s.factor === 0
      ? "si bastara tocar el nivel"
      : (s.principal ? "como se cuenta (hay que atravesar el nivel)" : "si costara mucho más llenarse");
    return `<li class="tramo"><span class="tramo-nombre">${linea}</span>
      <span class="serie-detalle">${frase("{llenadas} de {senales} señales se llenan · {n} operaciones · deja {neto} por operación", {
        llenadas: numero((s.resumen || {}).llenadas, 0), senales: numero((s.resumen || {}).senales, 0),
        n: numero((s.resumen || {}).operaciones, 0), neto: porcentaje((s.resumen || {}).neto_medio, 2) })}</span></li>`;
  }
  function lineaModelo(m) {
    if (!m) return "";
    return m.origen === "propio"
      ? `<p class="indicadores-linea">${frase("Diferencia entre compra y venta medida con tus propias muestras: {dias} días guardados.", { dias: numero(m.dias, 0) })}</p>`
      : `<p class="indicadores-linea">${frase("Diferencia entre compra y venta supuesta ({spread}), bastante peor que la de hoy: Binance no guarda el libro de antes. Con {faltan} días más de muestras propias se vuelve a calcular con lo medido.", { spread: porcentaje(m.supuesto, 3), faltan: numero(m.falta_dias, 0) })}</p>`;
  }
  function lineaAmbiguas(a) {
    if (!a || !a.velas) return `<p class="indicadores-linea">Ninguna vela tocó el stop y el objetivo a la vez.</p>`;
    const datos = { velas: numero(a.velas, 0), con: numero(a.con_1m, 0), acierto: porcentaje(a.acierto, 0) };
    return `<p class="indicadores-linea">${a.acierto === null
      ? frase("{velas} velas tocaron el stop y el objetivo a la vez: en todas se supuso el stop, lo malo. Todavía no hay velas de 1 m de esos días para revisarlo.", datos)
      : frase("{velas} velas tocaron el stop y el objetivo a la vez: en todas se supuso el stop, lo malo. De las {con} que sí tienen velas de 1 m, el supuesto acertó en {acierto}.", datos)}</p>`;
  }
  function backtest() {
    const d = E.backtest;
    const etiqueta = E.corriendo ? "Recorriendo el historial…" : (d && d.corrido ? "Correr de nuevo" : "Correr el backtest");
    const pie = `<div class="pz-pie"><button type="button" class="pz-boton" id="backtest-correr"${E.corriendo ? " disabled" : ""}>${etiqueta}</button></div>`;
    if (!d) return `<p class="suave">Cargando el backtest…</p>`;
    if (!d.corrido) {
      return `<div id="backtest" class="indicadores">
        <p class="indicadores-resumen">Todavía no he recorrido el historial.</p>
        ${lineaModelo(d.modelo)}
        <p class="indicadores-linea">${frase("La compuerta pide {minimo} casos por tramo antes de dejar calibrar.", { minimo: numero((d.compuerta || {}).casos_minimos, 0) })}</p>
        ${pie}</div>`;
    }
    const r = d.resumen || {};
    const c = d.compuerta || {};
    const series = Array.isArray(d.series) ? d.series : [];
    return `<div id="backtest" class="indicadores">
      <p class="indicadores-resumen">${frase("{n} operaciones de {senales} señales crudas, en {dias} días de historial", {
        n: numero(r.operaciones, 0), senales: numero(r.senales, 0), dias: numero((d.ventana || {}).dias, 0) })}</p>
      <p class="indicadores-linea">${frase("Acierta {aciertos} y deja {neto} por operación después de costos ({costo} se lleva entrar y salir).", {
        aciertos: porcentaje(r.aciertos, 0), neto: porcentaje(r.neto_medio, 2), costo: porcentaje(r.costo_medio, 2) })}</p>
      ${lineaModelo(d.modelo)}
      <ul class="tramos" aria-label="Comparación">
        ${comparacion("Estas señales, una tras otra", r)}
        ${comparacion("Quedarse en USDT", (d.referencias || {}).usdt)}
        ${comparacion("Comprar BTC y esperar", (d.referencias || {}).btc)}</ul>
      <p class="suave">La curva entra entera en cada operación, una después de otra: todavía no hay tamaño, reserva ni frenos (son sus propios pasos).</p>
      <h3>Los casos que de verdad hay</h3>
      <p class="indicadores-linea${c.plan_b ? " freno" : ""}">${PLANES[c.plan] || PLANES.insuficiente}</p>
      <ul class="tramos" aria-label="Casos por tramo">${(c.tramos || []).map((t) => tramoCasos(t, c.casos_minimos)).join("")}</ul>
      <h3>Serie por serie</h3>
      <ul class="series" aria-label="Backtest por par y temporalidad">${series.map(serieBacktest).join("")}</ul>
      <h3>Si una orden límite se llenara más fácil o más difícil</h3>
      <ul class="tramos" aria-label="Prueba de sensibilidad">${(d.sensibilidad || []).map(sensibilidad).join("")}</ul>
      ${lineaAmbiguas((d.supuestos || {}).ambiguas)}
      <p class="suave">${frase("Recorrido el {cuando} sin ninguna exigencia: así salieron las reglas, antes del puntaje. No es una promesa de ganancia.", { cuando: fechaHora(d.cuando) })}</p>
      ${pie}</div>`;
  }
  // ── El puntaje de 0 a 100 (bin/lib_puntaje.py): cada familia una nota, y las siete juntas el puntaje ──
  // Al lado del puntaje van la probabilidad de ganar que dicen las operaciones del historial que puntuaron como esta (las
  // de su tramo de puntaje) y la ganancia esperada después de costos, las dos con su rango. Quedarse en USDT también
  // puntúa: es la vara.
  const ETIQUETA_FAMILIA = { tendencia: "Tendencia", impulso: "Impulso", volatilidad: "Volatilidad",
    volumen: "Volumen", estructura: "Estructura", contexto: "Contexto", costo: "Costo" };
  function notaFamilia(f) {
    return `<li class="tramo"><span class="tramo-nombre">${ETIQUETA_FAMILIA[f.familia] || f.familia}</span>
      <span class="serie-detalle">${f.nota === null || f.nota === undefined
        ? `<span>sin número</span>`
        : frase("{n} de {maximo}", { n: numero(f.nota, 0), maximo: numero(PUNTAJE_MAXIMO, 0) })}</span></li>`;
  }
  // Sin una de las tres familias clave (tendencia, contexto y costo) no hay puntaje: se dice cuál falta en vez de
  // inventar el número. Sin una de las otras cuatro sí hay puntaje, con los pesos repartidos entre las que quedan.
  function sinPuntaje(o) {
    const familia = String(o.motivo || "").replace(/^sin_/, "");
    return frase("Sin {familia} no hay puntaje: una familia a ciegas haría entrar a algo que nadie miró entero.",
      { familia: ETIQUETA_FAMILIA[familia] || familia });
  }
  function sinUnaFamilia(o) {
    const familias = (o.faltan || []).map((f) => Tp(ETIQUETA_FAMILIA[f] || f)).join(", ");
    return `<span class="serie-detalle">${frase("Puntuado sin {familias}: sin ese número, su peso se reparte entre las otras familias.", { familias })}</span>`;
  }
  function probabilidad(o) {
    const e = o.evidencia || {};
    const g = o.ganancia || {};
    if (e.motivo === "sin_backtest") return `<span class="serie-detalle">Todavía no puedo decir con qué probabilidad gana: falta recorrer el historial.</span>`;
    if (e.motivo) return `<span class="serie-detalle">${frase("Todavía no puedo decir con qué probabilidad gana: hacen falta {minimo} operaciones parecidas y hay {n}.", { minimo: numero(e.casos_minimos, 0), n: numero(e.casos, 0) })}</span>`;
    return `<span class="serie-detalle">${frase("Gana {p} de las veces (entre {bajo} y {alto}, con {casos} casos del historial)", {
      p: porcentaje(g.probabilidad, 0), bajo: porcentaje(g.probabilidad_bajo, 0), alto: porcentaje(g.probabilidad_alto, 0),
      casos: numero(e.casos, 0) })}</span>
      <span class="serie-detalle">${frase("Ganancia esperada después de costos: {esperada} (entre {bajo} y {alto})", {
        esperada: porcentaje(g.esperada, 2), bajo: porcentaje(g.bajo, 2), alto: porcentaje(g.alto, 2) })}</span>
      ${e.origen && e.origen !== "normal" ? `<span class="serie-detalle freno">La probabilidad sale de un tramo ensanchado (plan B): todavía no está validada.</span>` : ""}`;
  }
  function opcionPuntaje(o) {
    const donde = [o.par, ETIQUETA_TEMPORALIDAD[o.temporalidad] || o.temporalidad].filter(Boolean).join(" · ");
    const g = o.ganancia || {};
    return `<li class="serie">
      <span class="serie-par" data-sin-traducir>${esc(donde)}</span>
      <span class="serie-estado" data-estado="${o.puntaje === null ? "incompleto" : "listo"}">${o.puntaje === null
        ? "Sin puntaje" : frase("{n} de {maximo}", { n: numero(o.puntaje, 0), maximo: numero(PUNTAJE_MAXIMO, 0) })}</span>
      <span class="serie-detalle">${ETIQUETA_ESTRATEGIA[o.estrategia] || o.estrategia}</span>
      ${o.puntaje === null ? `<span class="serie-detalle">${sinPuntaje(o)}</span>` : probabilidad(o)}
      ${o.renormalizado ? sinUnaFamilia(o) : ""}
      ${typeof g.gana === "number" ? `<span class="serie-detalle">${frase("Si llega al objetivo deja {gana} y si se va al stop cuesta {pierde}, con los costos de los dos lados.", {
        gana: porcentaje(g.gana, 2), pierde: porcentaje(Math.abs(g.pierde), 2) })}</span>` : ""}
      ${(o.familias || []).length ? `<ul class="tramos" aria-label="Notas por familia">${o.familias.map(notaFamilia).join("")}</ul>` : ""}</li>`;
  }
  function mejorOpcion(m) {
    if (!m) return `<p class="indicadores-resumen">Ninguna opción se puede puntuar todavía.</p>`;
    const donde = [m.par, ETIQUETA_TEMPORALIDAD[m.temporalidad] || m.temporalidad].filter(Boolean).join(" · ");
    return `<p class="indicadores-resumen">${m.estrategia === "usdt"
      ? frase("Lo que más puntúa ahora es quedarse en USDT: {n} de {maximo}", { n: numero(m.puntaje, 0), maximo: numero(PUNTAJE_MAXIMO, 0) })
      : frase("Lo que más puntúa ahora: {que} en {donde}, {n} de {maximo}", {
        que: Tp(ETIQUETA_ESTRATEGIA[m.estrategia] || m.estrategia), donde, n: numero(m.puntaje, 0), maximo: numero(PUNTAJE_MAXIMO, 0) })}</p>`;
  }
  // El supuesto de las velas que tocaron el stop y el objetivo sin velas de 1 m para desempatar: siempre marcado, porque la
  // probabilidad de ganar está calculada sobre operaciones que lo arrastran (bin/lib_puntaje.py: supuestos).
  function supuestoSin1m(s) {
    if (!s || !s.corrido) return `<p class="indicadores-linea">La probabilidad de ganar sale de las operaciones del backtest: hasta recorrer el historial, una oportunidad tiene puntaje pero no probabilidad.</p>`;
    const a = s.ambiguas || {};
    if (!a.velas) return `<p class="indicadores-linea">Ninguna operación del historial tocó el stop y el objetivo en la misma vela. Si pasara, se cuenta como stop: lo malo.</p>`;
    const datos = { velas: numero(a.velas, 0), con: numero(a.con_1m, 0), dias: numero(s.dias_1m, 0), acierto: porcentaje(s.acierto, 0) };
    return `<p class="indicadores-linea">${s.validado
      ? frase("{velas} operaciones tocaron el stop y el objetivo en la misma vela: en todas se cuenta el stop, lo malo. De las {con} que tienen velas de 1 m (se guardan {dias} días), el supuesto acertó en {acierto}.", datos)
      : frase("{velas} operaciones tocaron el stop y el objetivo en la misma vela: en todas se cuenta el stop, lo malo. Todavía no hay velas de 1 m de esos días para revisar el supuesto.", datos)}</p>`;
  }
  // Con qué modelo se está puntuando (bin/lib_puntaje.py: modelo). Mientras no haya calibración, las siete familias
  // pesan lo mismo y la exigencia —el corte para entrar, que es de su propio paso— es la alta: nadie probó todavía que
  // estos pesos separen lo bueno de lo malo.
  function modeloPuntaje(m) {
    if (!m) return "";
    const datos = { n: numero(m.exigencia, 0), maximo: numero(PUNTAJE_MAXIMO, 0) };
    if (m.estado === "validado") {
      return `<p class="indicadores-linea">${frase("El puntaje está calibrado y validado: la exigencia para entrar es {n} de {maximo}.", datos)}</p>`;
    }
    if (m.estado === "no_validado") {
      return `<p class="indicadores-linea freno">${frase("El puntaje está calibrado pero no validado: la exigencia para entrar es {n} de {maximo} y los montos quedan topados.", datos)}</p>`;
    }
    return `<p class="indicadores-linea">${frase("El puntaje está sin calibrar: las siete familias pesan lo mismo y, hasta calibrarlo con el historial, la exigencia para entrar es {n} de {maximo}.", datos)}</p>`;
  }
  function puntaje() {
    const d = E.puntaje;
    if (!d) return `<p class="suave">Puntuando las oportunidades…</p>`;
    const series = Array.isArray(d.series) ? d.series : [];
    const opciones = series.flatMap((s) => s.opciones || []);
    return `<div id="puntaje" class="indicadores">
      ${mejorOpcion(d.mejor)}
      ${modeloPuntaje(d.modelo)}
      <p class="indicadores-linea">${frase("Quedarse en USDT puntúa {n} de {maximo}: no gana ni pierde nada, así que una oportunidad recién conviene cuando puntúa más que eso.", {
        n: numero((d.usdt || {}).puntaje, 0), maximo: numero(PUNTAJE_MAXIMO, 0) })}</p>
      ${opciones.length
        ? `<ul class="series" aria-label="Oportunidades puntuadas">${opciones.map(opcionPuntaje).join("")}</ul>`
        : `<p class="indicadores-linea">Ninguna estrategia se gatilló con la última vela cerrada: no hay nada que puntuar.</p>`}
      ${supuestoSin1m(d.supuestos)}
      <p class="suave">${frase("Puntuado el {cuando}. Un puntaje no es una orden ni una promesa: la exigencia, el tamaño y los frenos vienen en los pasos siguientes.", { cuando: fechaHora(d.cuando) })}</p>
      <div class="pz-pie"><button type="button" class="pz-boton" id="puntaje-calcular"${E.puntuando ? " disabled" : ""}>${E.puntuando ? "Puntuando…" : "Puntuar de nuevo"}</button></div></div>`;
  }
  // ── La calibración del puntaje (bin/lib_calibracion.py): el año apartado, los pesos por ventanas y la prueba final ──
  // Lo que se muestra es con qué quedó el modelo —«Validado», o «No validado» con la exigencia alta y los montos
  // topados— y cómo se llegó ahí: el tramo que nadie miró hasta el final, las ventanas de ajustar y probar, las vueltas
  // que se dieron y el criterio con el que la prueba final aprobó (o no), revisión por revisión.
  const ETIQUETA_PLAN = { normal: "sin plan B", ancho: "plan B: las dos temporalidades juntas",
    unico: "plan B: un solo tramo por estrategia", insuficiente: "sin casos suficientes" };
  const ETIQUETA_CRITERIO = { casos: "Casos que no se pisan", neto: "Deja algo después de costos",
    usdt: "Le gana a quedarse en USDT", caida: "Caída máxima dentro del piso",
    plan: "La compuerta pasó sin plan B", nueva: "Primera prueba con este tramo" };
  const MOTIVOS_CALIBRACION = {
    sin_calibracion: "Todavía no he calibrado el puntaje.",
    sin_backtest: "Antes de calibrar hay que recorrer el historial: la compuerta de casos va primero.",
    falta_historia: "Falta historial: para apartar un año y ajustar por ventanas antes de él faltan {n} días.",
    pocos_casos: "En las ventanas de ajuste faltan {n} casos que no se pisen entre sí: con menos, el peso que gane va a ser el que tuvo suerte.",
    prueba_repetida: "La prueba final ya se hizo con este tramo y no se repite: para volver a probar faltan {n} días nuevos de historial.",
    plan_b: "La compuerta del backtest tuvo que ensanchar sus tramos: con plan B el modelo no queda validado.",
    no_deja_nada: "En el año apartado no dejó nada después de costos.",
    no_gana_a_usdt: "En el año apartado no le ganó a quedarse en USDT.",
    caida_grande: "La caída máxima del año apartado llega al piso de los frenos.",
    no_validado: "La prueba final no aprobó el criterio escrito de antemano.",
  };
  // El motivo por el que el modelo no quedó validado, en palabras. Los días o los casos que faltan vienen del estado
  // (el Python ya los contó): acá no se calcula nada.
  function lineaMotivoCalibracion(d) {
    if (!d.motivo) return "";
    const falta = (d.motivo === "falta_historia" || d.motivo === "prueba_repetida")
      ? (d.apartado || {}).faltan_dias
      : ((d.motivos || []).find((m) => m.codigo === d.motivo) || {}).n;
    return `<p class="indicadores-linea freno">${frase(MOTIVOS_CALIBRACION[d.motivo] || MOTIVOS_CALIBRACION.no_validado,
      { n: numero(falta || 0, 0) })}</p>`;
  }
  function pesoFamilia(f, peso) {
    return `<li class="tramo"><span class="tramo-nombre">${ETIQUETA_FAMILIA[f] || f}</span>
      <span class="serie-estado" data-estado="${peso ? "listo" : "incompleto"}">${frase("pesa {n}", { n: numero(peso, 2) })}</span>
      ${peso ? "" : `<span class="serie-detalle">Con el peso en cero esta familia no mueve el puntaje.</span>`}</li>`;
  }
  function vueltaCalibracion(v, elegida) {
    const p = v.prueba || {};
    const movidas = (v.cambios || []).map((c) => Tp(ETIQUETA_FAMILIA[c.familia] || c.familia)).join(", ");
    return `<li class="tramo"><span class="tramo-nombre">${frase("Vuelta {n}", { n: numero(v.n, 0) })}</span>
      <span class="serie-estado" data-estado="${v.n === elegida ? "listo" : ""}">${v.n === elegida ? "Con esta quedó" : "Probada"}</span>
      <span class="serie-detalle">${frase("exigencia {e} · en las ventanas de probar deja {neto} por operación con {casos} casos", {
        e: numero(v.exigencia, 0), neto: porcentaje(p.neto_medio, 2), casos: numero(p.casos, 0) })}</span>
      <span class="serie-detalle">${movidas
        ? frase("movió el peso de {familias}", { familias: movidas })
        : "no movió ningún peso"}</span></li>`;
  }
  // Cada revisión del criterio, también las que pasaron: una aprobación que no se puede revisar no es una aprobación.
  function revisionCriterio(x) {
    const valores = {
      casos: () => frase("{hay} de los {pide} que pide", { hay: numero(x.hay, 0), pide: numero(x.pide, 0) }),
      neto: () => frase("deja {hay} por operación", { hay: porcentaje(x.hay, 2) }),
      usdt: () => frase("rendimiento {hay}", { hay: porcentaje(x.hay, 1) }),
      caida: () => frase("cayó {hay} y el piso está en {pide}", { hay: porcentaje(x.hay, 1), pide: porcentaje(x.pide, 0) }),
      plan: () => esc(Tp(ETIQUETA_PLAN[x.hay] || x.hay)),
      nueva: () => esc(x.hay ? Tp("es la primera vez con este tramo") : Tp("este tramo ya se había usado")),
    };
    return `<li class="tramo"><span class="tramo-nombre">${ETIQUETA_CRITERIO[x.que] || x.que}</span>
      <span class="serie-estado" data-estado="${x.pasa ? "listo" : "incompleto"}">${x.pasa ? "Pasa" : "No pasa"}</span>
      <span class="serie-detalle">${(valores[x.que] || (() => ""))()}</span></li>`;
  }
  function calibracion() {
    const d = E.calibracion;
    const etiqueta = E.calibrando ? "Calibrando…" : (d && d.corrido ? "Calibrar de nuevo" : "Calibrar el puntaje");
    const pie = `<div class="pz-pie"><button type="button" class="pz-boton" id="calibracion-correr"${E.calibrando ? " disabled" : ""}>${etiqueta}</button></div>`;
    if (!d) return `<p class="suave">Cargando la calibración…</p>`;
    const p = d.parametros || {};
    if (!d.corrido) {
      return `<div id="calibracion" class="indicadores">
        <p class="indicadores-resumen">Todavía no he calibrado el puntaje.</p>
        <p class="indicadores-linea">${frase("Mientras no esté calibrado, las siete familias pesan lo mismo, la exigencia para entrar es {n} de {maximo} y el monto por posición queda topado en {tope}.", {
          n: numero(d.exigencia, 0), maximo: numero(PUNTAJE_MAXIMO, 0), tope: usdt(d.tope) })}</p>
        <p class="indicadores-linea">${frase("Al calibrar aparto los últimos {dias} días antes de mirar un solo peso, ajusto con ventanas de {ajustar} meses y pruebo con los {probar} siguientes, como máximo {vueltas} vueltas.", {
          dias: numero(p.dias_apartados, 0), ajustar: numero(p.meses_ajustar, 0), probar: numero(p.meses_probar, 0), vueltas: numero(p.vueltas_maximas, 0) })}</p>
        ${pie}</div>`;
    }
    const a = d.apartado || {};
    const ajuste = d.ajuste || {};
    const final = d.prueba_final || {};
    const ap = d.aprobacion || {};
    const validado = d.estado === "validado";
    return `<div id="calibracion" class="indicadores">
      <p class="indicadores-resumen">${validado
        ? frase("Modelo validado: la exigencia para entrar queda en {n} de {maximo}.", {
          n: numero(d.exigencia, 0), maximo: numero(PUNTAJE_MAXIMO, 0) })
        : frase("Modelo no validado: la exigencia queda en {n} de {maximo} y el monto por posición, topado en {tope}.", {
          n: numero(d.exigencia, 0), maximo: numero(PUNTAJE_MAXIMO, 0), tope: usdt(d.tope) })}</p>
      ${lineaMotivoCalibracion(d)}
      <p class="indicadores-linea">${a.desde === null
        ? frase("No alcancé a apartar ningún tramo: hacen falta {n} días de historial.", { n: numero(a.dias_minimos, 0) })
        : frase("Aparté {dias} días ({desde} a {hasta}) antes de mover un peso: nadie los miró hasta la prueba final.", {
          dias: numero(a.dias, 0), desde: fecha(a.desde), hasta: fecha(a.hasta) })}</p>
      <p class="indicadores-linea">${frase("{n} ventanas antes de ese tramo: {ajustar} meses para ajustar los pesos y los {probar} siguientes para probarlos, con {casos} casos de ajuste.", {
        n: numero((d.ventanas || []).length, 0), ajustar: numero(p.meses_ajustar, 0), probar: numero(p.meses_probar, 0),
        casos: numero(ajuste.casos, 0) })}</p>
      ${(ajuste.vueltas || []).length ? `<h3>Las vueltas que se dieron</h3>
        <p class="indicadores-linea">${frase("{n} de {maximas}: un peso se mueve solo si mejora de verdad, y la vuelta que gana la eligen las ventanas de probar.", {
          n: numero(ajuste.cuantas, 0), maximas: numero(ajuste.maximas, 0) })}</p>
        <ul class="tramos" aria-label="Vueltas de la calibración">${ajuste.vueltas.map((v) => vueltaCalibracion(v, ajuste.elegida)).join("")}</ul>` : ""}
      <h3>Los pesos con los que quedó</h3>
      <ul class="tramos" aria-label="Pesos por familia">${(d.familias || Object.keys(d.pesos || {})).map((f) => pesoFamilia(f, (d.pesos || {})[f])).join("")}</ul>
      <h3>La prueba final</h3>
      ${final.hecha
        ? `<p class="indicadores-linea">${frase("Una sola vez, con el tramo apartado ({desde} a {hasta}) y el criterio escrito antes de correrla: {n} operaciones sobre la exigencia {e}.", {
            desde: fecha((final.ventana || {}).desde), hasta: fecha((final.ventana || {}).hasta),
            n: numero((final.resumen || {}).operaciones, 0), e: numero(final.exigencia, 0) })}</p>
          <ul class="tramos" aria-label="Comparación de la prueba final">
            ${comparacion("El puntaje con su exigencia", final.resumen)}
            ${comparacion("Quedarse en USDT", (final.referencias || {}).usdt)}
            ${comparacion("Comprar BTC y esperar", (final.referencias || {}).btc)}</ul>
          <p class="suave">Le gana a quedarse en USDT o no aprueba. A comprar BTC y esperar se compara siempre, pero esa no es la vara: una posición larga en BTC tiene caídas que los frenos no dejarían pasar.</p>`
        : `<p class="indicadores-linea freno">La prueba final no se hizo: no se gasta dos veces con los mismos datos.</p>`}
      <ul class="tramos" aria-label="Criterio de aprobación">${(ap.revisiones || []).map(revisionCriterio).join("")}</ul>
      ${(d.rebacktest || {}).corrido ? `<h3>El backtest de nuevo, con puntaje y exigencia</h3>
        <p class="indicadores-linea">${frase("Antes del tramo apartado: {n} operaciones de {senales} señales que llegaron a la exigencia, acierta {aciertos} y deja {neto} por operación.", {
          n: numero(((d.rebacktest || {}).resumen || {}).operaciones, 0), senales: numero(((d.rebacktest || {}).resumen || {}).senales, 0),
          aciertos: porcentaje(((d.rebacktest || {}).resumen || {}).aciertos, 0), neto: porcentaje(((d.rebacktest || {}).resumen || {}).neto_medio, 2) })}</p>` : ""}
      <p class="suave">${frase("Calibrado el {cuando}. Los pesos y la exigencia son del puntaje: el tamaño y los frenos vienen en los pasos siguientes.", { cuando: fechaHora(d.cuando) })}</p>
      ${pie}</div>`;
  }
  // ── El estado firmado y el registro que no se borra ──
  const ETIQUETA_AMBIENTE = { prueba: "Prueba: dinero ficticio", real: "Real: dinero de verdad" };
  const ETIQUETA_MODO = { manual: "Manual", semiautomatico: "Semiautomático", automatico: "Automático" };
  // Por qué una cuenta arrancó frenada. Los códigos los pone el Python (lib_estado): acá se cuentan en palabras.
  const MOTIVOS_ARRANQUE = {
    sin_estado: "No encontré el archivo de estado, y el registro dice que esta cuenta ya vivió algo: arranqué frenado en manual.",
    huella_no_cuadra: "La huella del archivo de estado no cuadra con lo que dice adentro: arranqué frenado en manual.",
    fecha_futura: "El archivo de estado está fechado más adelante que ahora: arranqué frenado en manual.",
    formato_desconocido: "No pude leer el archivo de estado (quedó a medias o no tiene la forma que conozco): arranqué frenado en manual.",
    otro_ambiente: "El archivo de estado es de la otra cuenta, y prueba y real llevan todo separado: arranqué frenado en manual.",
  };
  // El mismo motivo, corto, para una línea del registro.
  const MOTIVO_CORTO = {
    sin_estado: "sin archivo de estado", huella_no_cuadra: "la huella no cuadra", fecha_futura: "fecha futura",
    formato_desconocido: "archivo ilegible", otro_ambiente: "archivo de la otra cuenta",
    // Los frenos (bin/lib_frenos.py), como los deja escritos su línea del registro.
    piso_absoluto: "el piso absoluto", piso: "el piso del capital de referencia", diario: "el freno del día",
    racha: "la racha de pérdidas", comision: "la comisión maker", fdusd: "el precio de FDUSD",
    esperando: "las 24 horas de espera",
  };
  // Por qué quedó anotada una línea (bin/lib_registro.py: RAZONES). Cada paso usa las suyas; el registro acepta solo
  // estos códigos, así que nunca hay una línea sin palabras.
  const RAZONES_REGISTRO = {
    arranque_frenado: "Arranqué frenado en manual", saldo_reiniciado: "Reiniciaste el saldo de prueba",
    aporte: "Depósito", retiro: "Retiro", referencia_reiniciada: "Reinicié el capital de referencia",
    cambio_modo: "Cambiaste de modo", desbloqueo: "Desbloqueaste un freno",
    propuesta: "Te propuse una operación", propuesta_vencida: "La propuesta venció",
    entrada_ruptura: "Entré por ruptura", entrada_rebote: "Entré por rebote",
    quedarse_en_usdt: "Me quedé en USDT", rechazo: "No abrí la operación",
    objetivo: "Cerró en el objetivo", stop: "Cerró en el stop", stop_movil: "Cerró con el stop móvil",
    cierre_manual: "La cerraste tú", proteccion_sin_confirmar: "La protección automática no se confirmó",
    freno_diario: "Freno del día", freno_racha: "Freno por racha de pérdidas", freno_piso: "Freno del piso",
    freno_piso_absoluto: "Freno del piso absoluto", freno_comision: "Freno por la comisión",
    freno_fdusd: "Freno por FDUSD", pausa: "Pusiste todo en pausa", reanudar: "Quitaste la pausa",
  };
  const ETIQUETA_CIERRE = { objetivo: "el objetivo", stop: "el stop", stop_movil: "el stop móvil", manual: "tu decisión" };
  // Lo que se puede decir de una línea: solo las claves que conocemos (del Python vienen números y códigos, nunca
  // texto), cada una en palabras. Lo que no conocemos no se muestra.
  function detalleRegistro(l) {
    const o = l.orden || {}, r = l.resultado || {}, partes = [];
    if (typeof l.puntaje === "number") partes.push(frase("puntaje {n} de {maximo}", { n: numero(l.puntaje, 0), maximo: numero(PUNTAJE_MAXIMO, 0) }));
    if (typeof o.monto === "number") partes.push(frase("orden por {monto}", { monto: usdt(o.monto) }));
    if (typeof o.stop === "number") partes.push(frase("stop en {n}", { n: numero(o.stop) }));
    if (r.por) partes.push(frase("cerró por {que}", { que: Tp(ETIQUETA_CIERRE[r.por] || r.por) }));
    if (typeof r.neto === "number") partes.push(frase("dejó {n}", { n: usdt(r.neto) }));
    if (typeof r.saldo === "number") partes.push(frase("saldo {n}", { n: usdt(r.saldo) }));
    if (r.motivo) partes.push(frase("motivo: {que}", { que: Tp(MOTIVO_CORTO[r.motivo] || r.motivo) }));
    return partes.join(" · ");
  }
  function filaRegistro(l) {
    const detalle = detalleRegistro(l);
    return `<li class="tramo"><span class="tramo-nombre" data-sin-traducir>${esc(fechaHora(l.fecha))}</span>
      <span class="serie-estado">${RAZONES_REGISTRO[l.razon] || "Quedó anotado"}</span>
      ${l.par ? `<span class="serie-detalle" data-sin-traducir>${esc(l.par)}</span>` : ""}
      ${detalle ? `<span class="serie-detalle">${detalle}</span>` : ""}</li>`;
  }
  // Las dos cuentas, siempre las dos: prueba y real llevan saldos, frenos y registro separados.
  function filaCuenta(c) {
    const a = c.arranque || {}, reg = c.registro || {}, leido = c.leido || {};
    const estado = c.frenado ? "incompleto" : (a.nuevo ? "vacio" : "listo");
    const etiqueta = c.frenado ? "Frenado en manual" : (a.nuevo ? "Sin estado todavía" : "Estado al día");
    const detalle = c.frenado
      ? (typeof leido.saldo === "number"
        ? frase("no me fío de sus números: el archivo decía saldo {saldo} y referencia {referencia}", {
          saldo: usdt(leido.saldo), referencia: usdt(leido.referencia) })
        : "no me fío de sus números: el archivo no decía ningún monto")
      : (a.nuevo
        ? "todavía no hay nada guardado de esta cuenta"
        : frase("saldo {saldo} · referencia {referencia} · {posiciones} posiciones · modo {modo}", {
          saldo: usdt(c.saldo), referencia: usdt(c.referencia), posiciones: numero((c.posiciones || []).length, 0),
          modo: Tp(ETIQUETA_MODO[c.modo] || c.modo) }));
    return `<li class="tramo"><span class="tramo-nombre">${ETIQUETA_AMBIENTE[c.ambiente] || c.ambiente}</span>
      <span class="serie-estado" data-estado="${estado}">${etiqueta}</span>
      <span class="serie-detalle${c.frenado ? " freno" : ""}">${detalle}</span>
      <span class="serie-detalle">${frase("registro: {n} líneas", { n: numero(reg.lineas, 0) })}</span></li>`;
  }
  function estadoFirmado() {
    const d = E.estado;
    if (!d) return `<p class="suave">Cargando el estado…</p>`;
    const cuentas = Array.isArray(d.cuentas) ? d.cuentas : [];
    const esta = cuentas.find((c) => c.ambiente === d.activo) || {};
    const a = esta.arranque || {}, reg = esta.registro || {}, p = d.parametros || {};
    const lineas = Array.isArray(reg.ultimas) ? reg.ultimas : [];
    const pie = `<div class="pz-pie"><button type="button" class="pz-boton" id="estado-reiniciar"${E.reiniciando ? " disabled" : ""}>${E.reiniciando ? "Reiniciando…" : "Reiniciar el saldo de prueba"}</button></div>`;
    return `<div id="estado" class="indicadores">
      ${d.frenado
        ? `<p class="indicadores-resumen freno">${frase(MOTIVOS_ARRANQUE[d.motivo] || MOTIVOS_ARRANQUE.formato_desconocido)}</p>
          <p class="indicadores-linea freno">No voy a abrir nada: en manual propongo y tú decides. El archivo de antes quedó tal cual, sin pisarlo, y el arranque quedó en el registro.</p>`
        : (a.nuevo
          ? `<p class="indicadores-resumen">Todavía no hay estado guardado de la cuenta de prueba.</p>
            <p class="indicadores-linea">${frase("Al elegir el monto de prueba lo dejo escrito con su huella y arranco en {modo}. Si después falta el archivo, la huella no cuadra o la fecha es futura, arranco frenado y te lo digo acá.", {
              modo: Tp(ETIQUETA_MODO[p.modo_frenado] || "Manual") })}</p>`
          : `<p class="indicadores-resumen">${frase("Estado al día y con su huella: {saldo} en la cuenta de prueba, en modo {modo}.", {
              saldo: usdt(esta.saldo), modo: Tp(ETIQUETA_MODO[esta.modo] || esta.modo) })}</p>
            <p class="indicadores-linea">${frase("Capital de referencia {referencia}: el saldo más alto que has alcanzado, que sube con las ganancias y nunca baja. Aportado {aportado} en {n} movimientos anotados uno por uno.", {
              referencia: usdt(esta.referencia), aportado: usdt(esta.aportado), n: numero((esta.aportes || []).length, 0) })}</p>`)}
      <ul class="tramos" aria-label="Las dos cuentas">${cuentas.map(filaCuenta).join("")}</ul>
      <h3>El registro que no se borra</h3>
      <p class="indicadores-linea">${reg.lineas
        ? frase("{n} líneas desde el {desde}, {dias} días. Cada una lleva siempre los mismos campos —fecha, par, puntaje, razón, orden y resultado— y ninguna se cambia después: lo que ya pasó se queda escrito.", {
          n: numero(reg.lineas, 0), desde: fechaHora(reg.desde), dias: numero(reg.dias, 0) })
        : "Todavía no hay ninguna línea. Cada decisión se agrega al final, con los mismos campos siempre, y no se borra nunca."}</p>
      ${lineas.length ? `<ul class="tramos" aria-label="Últimas líneas del registro">${lineas.map(filaRegistro).join("")}</ul>` : ""}
      ${reg.danadas ? `<p class="indicadores-linea freno">${frase("{n} líneas quedaron a medias y no las muestro. Tampoco las borro.", { n: numero(reg.danadas, 0) })}</p>` : ""}
      ${pie}</div>`;
  }
  // ── El tamaño de una operación (bin/lib_tamano.py): el orden fijo y el monto en USDT ──
  // Por qué una oportunidad no tiene monto. Los códigos los pone el Python: acá cada uno se cuenta en palabras.
  const MOTIVOS_TAMANO = {
    frenado: "Arranqué frenado en manual: de un estado del que no me fío no sale ningún monto.",
    sin_minimos: "Todavía no sé los mínimos que pide Binance: calcula el capital mínimo viable y vuelvo a medir.",
    sin_operar: MOTIVOS_MINIMO.sin_operar,
    sin_proteccion: MOTIVOS_MINIMO.sin_proteccion,
    sin_precio: "{par}: la señal no trae un precio de entrada que pueda usar.",
    sin_stop: "{par}: la señal no trae un stop bajo la entrada, y sin stop no hay monto.",
    posiciones_llenas: "Ya hay {n} posiciones abiertas: no abro una más.",
    sin_capital: "Todavía no hay capital en esta cuenta: elige el monto de prueba y calculo el tamaño.",
    sin_disponible: "No queda nada disponible para otra posición: la reserva en USDT no se toca.",
  };
  // Cuál de los tres límites cortó el monto (el último paso del orden).
  function limiteQueManda(t) {
    if (t.manda === "tope") {
      return frase("Lo corta el tope de {monto} por posición: el modelo todavía no está validado.", { monto: usdt(t.tope) });
    }
    if (t.manda === "disponible") {
      return frase("Lo corta lo disponible para esta posición: {monto}.", { monto: usdt(t.disponible) });
    }
    return frase("Lo corta el riesgo máximo: {monto} por operación.", { monto: usdt(t.riesgo_maximo) });
  }
  // El motivo de un rechazo, con el número que lo explica: «no se puede» sin un monto no sirve de nada.
  function motivoTamano(o) {
    const t = o.tamano || {};
    const m = t.minimo || {};
    if (o.motivo === "bajo_minimo") {
      return frase("Queda bajo el mínimo de Binance: con este stop la posición más chica es {monto} y para abrirla harían falta {capital} de capital.", {
        monto: usdt(m.posicion), capital: usdt(m.capital) });
    }
    return frase(MOTIVOS_TAMANO[o.motivo] || "No puedo calcular el monto de esta oportunidad.",
      { par: o.par, n: numero(t.abiertas, 0) });
  }
  function filaTamano(o) {
    const t = o.tamano || {};
    const donde = [o.par, ETIQUETA_TEMPORALIDAD[o.temporalidad] || o.temporalidad].filter(Boolean).join(" · ");
    return `<li class="serie">
      <span class="serie-par" data-sin-traducir>${esc(donde)}</span>
      ${o.puede
        ? `<span class="serie-estado" data-estado="listo" data-sin-traducir>${esc(usdt(t.monto))}</span>`
        : `<span class="serie-estado" data-estado="incompleto">Sin monto</span>`}
      <span class="serie-detalle">${ETIQUETA_ESTRATEGIA[o.estrategia] || o.estrategia}</span>
      ${o.puede
        ? `<span class="serie-detalle">${frase("Compraría {cantidad} {moneda} a {precio} con stop en {stop}: {monto} con sus costos.", {
            cantidad: numero(t.cantidad, 8), moneda: t.moneda, precio: numero(t.precio), stop: numero(t.stop), monto: usdt(t.monto) })}</span>
          <span class="serie-detalle">${frase("Si el stop se cruza pierdo {monto}, el {parte} del capital.", {
            monto: usdt(t.arriesgado), parte: porcentaje(t.arriesgado_relativo, 2) })}</span>
          <span class="serie-detalle">${limiteQueManda(t)}</span>`
        : `<span class="serie-detalle freno">${motivoTamano(o)}</span>`}
      ${o.puede && !o.permitida ? `<span class="serie-detalle freno">El monto está calculado, pero BTC no deja entrar ahora: no abriría nada.</span>` : ""}</li>`;
  }
  // Un paso del orden fijo: su nombre, en qué está y el número que lo explica. `suyo` es un valor que no se traduce
  // (un monto o un porcentaje), no una frase.
  function pasoTamano(nombre, estado, etiqueta, detalle, suyo = false) {
    return `<li class="tramo"><span class="tramo-nombre">${nombre}</span>
      <span class="serie-estado" data-estado="${estado}"${suyo ? " data-sin-traducir" : ""}>${suyo ? esc(etiqueta) : etiqueta}</span>
      <span class="serie-detalle">${detalle}</span></li>`;
  }
  function tamano() {
    const d = E.tamano;
    if (!d) return `<p class="suave">Midiendo el tamaño de cada operación…</p>`;
    const r = d.reparto || {}, modelo = d.modelo || {}, minimos = d.minimos || {};
    const ops = Array.isArray(d.oportunidades) ? d.oportunidades : [];
    const generales = (d.motivos || []).filter((m) => MOTIVOS_TAMANO[m.codigo]);
    return `<div id="tamano" class="indicadores">
      ${d.frenado
        ? `<p class="indicadores-resumen freno">Arranqué frenado en manual: de un estado del que no me fío no sale ningún monto.</p>`
        : (r.capital > 0
          ? `<p class="indicadores-resumen">${frase("Con {capital} de capital pongo hasta {posicion} por posición y arriesgo como máximo {riesgo} en cada operación.", {
              capital: usdt(r.capital), posicion: usdt(r.por_posicion), riesgo: usdt(r.riesgo_maximo) })}</p>`
          : `<p class="indicadores-resumen">Todavía no hay capital en esta cuenta: elige el monto de prueba y calculo el tamaño.</p>`)}
      <ul class="tramos" aria-label="El orden del tamaño">
        ${pasoTamano("Los mínimos de Binance", minimos.calculado ? "listo" : "incompleto",
          minimos.calculado ? "Al día" : "Faltan",
          minimos.calculado
            ? frase("la cantidad tiene que servir para la compra y para las dos patas de la protección: desde {monto} de capital.", { monto: usdt(minimos.capital_minimo) })
            : "Calcula el capital mínimo viable y vuelvo a medir: un mínimo inventado es una orden que Binance rechaza.")}
        ${pasoTamano("La reserva en USDT", "listo", porcentaje(r.reserva, 0),
          frase("{usdt} se quedan siempre en USDT y quedan {operable} para operar.", { usdt: usdt(r.en_usdt), operable: usdt(r.operable) }), true)}
        ${pasoTamano("Las posiciones a la vez", r.quedan > 0 ? "listo" : "incompleto",
          frase("{n} de {maximas}", { n: numero(r.abiertas, 0), maximas: numero(r.posiciones, 0) }),
          frase("{monto} por posición, y lo que ya está puesto ({comprometido}) no se reparte de nuevo.", {
            monto: usdt(r.por_posicion), comprometido: usdt(r.comprometido) }))}
        ${pasoTamano("El riesgo máximo", "listo", porcentaje(r.riesgo, 0),
          frase("no más de {monto} por operación, contando lo que cuesta salir por el stop.", { monto: usdt(r.riesgo_maximo) }), true)}
        ${modelo.topado ? pasoTamano("El tope del modelo sin validar", "incompleto", usdt(modelo.tope),
          "Mientras el modelo no esté validado, ningún monto por posición pasa de ahí.", true) : ""}
      </ul>
      ${ops.length
        ? `<h3>El monto de cada oportunidad</h3>
          <ul class="series" aria-label="Tamaño por oportunidad">${ops.map(filaTamano).join("")}</ul>`
        : `<p class="indicadores-linea">Ahora mismo no hay ninguna oportunidad que medir: cuando una estrategia se gatille, acá va su monto.</p>`}
      ${d.mejor
        ? `<p class="indicadores-linea">${frase("La que más puntúa y tiene monto: {que} en {donde}, {monto} con stop en {stop}.", {
            que: Tp(ETIQUETA_ESTRATEGIA[d.mejor.estrategia] || d.mejor.estrategia),
            donde: [d.mejor.par, ETIQUETA_TEMPORALIDAD[d.mejor.temporalidad] || d.mejor.temporalidad].filter(Boolean).join(" · "),
            monto: usdt((d.mejor.tamano || {}).monto), stop: numero((d.mejor.tamano || {}).stop) })}</p>`
        : (ops.length ? `<p class="indicadores-linea freno">Ninguna oportunidad de ahora tiene monto: no abriría nada.</p>` : "")}
      ${generales.map((m) => `<p class="indicadores-linea freno">${frase(MOTIVOS_TAMANO[m.codigo], { par: m.par, n: numero(m.n, 0) })}</p>`).join("")}
      <p class="suave">${(d.comisiones || {}).origen === "api"
        ? "Con las comisiones que dice la API de Binance."
        : "Con las comisiones supuestas: mientras no haya llave, las de verdad no se pueden leer."}</p>
      <p class="suave">Un monto no es una orden: el ejecutor rechaza toda orden que no pase antes por el tamaño y por los frenos.</p>
      </div>`;
  }
  // ── Los frenos y la máquina de estados (bin/lib_frenos.py): lo que Pilota no se puede saltar ──
  const ETIQUETA_ESTADO_FRENOS = { operando: "Operando", pausado: "En pausa", frenado: "Frenado",
    reduciendo: "Cerrando lo abierto" };
  const NOMBRE_FRENO = {
    piso_absoluto: "El piso absoluto", piso: "El piso del capital de referencia", diario: "El freno del día",
    racha: "La racha de pérdidas", comision: "La comisión maker", fdusd: "El precio de FDUSD",
  };
  // Por qué no se puede abrir una entrada. Los códigos los pone el Python (lib_frenos): acá cada uno en palabras.
  const MOTIVOS_FRENOS = {
    frenado: "Arranqué frenado en manual: de un estado del que no me fío no sale ninguna orden.",
    pausado: "Estás en pausa: no abro ninguna entrada hasta que me digas «Seguir».",
    posiciones_llenas: "Ya hay {n} posiciones abiertas, que son las que caben.",
    piso_absoluto: "El piso absoluto se tocó: cierro lo que queda abierto y no abro nada más.",
    piso: "El saldo tocó el piso del capital de referencia: no abro nada.",
    diario: "Perdí lo que acepto perder en un día: no abro nada más hasta que el día cambie.",
    comision: "La comisión maker pasó la que supuso el backtest: no abro nada.",
    fdusd: "FDUSD vale menos de lo que tiene que valer un dólar: no abro nada.",
    sin_medir: "Todavía no puedo medir uno de los frenos, y con un freno a ciegas no abro nada.",
  };
  // Lo que cada freno dice de sí mismo, con el número que lo explica: cuando pasa y cuando frena.
  function detalleFreno(f, c) {
    const piso = c.piso || {}, dia = c.dia || {}, racha = c.racha || {};
    if (f.codigo === "piso_absoluto") {
      return f.activo
        ? frase("El saldo ({valor}) tocó el piso absoluto ({limite}): cierro a mercado lo que esté abierto y no abro nada más.", { valor: usdt(f.valor), limite: usdt(f.limite) })
        : frase("Frena si el saldo baja de {limite}: el {parte} bajo lo que aportaste ({aportado}), que se cuenta depósito por depósito.", {
          limite: usdt(f.limite), parte: porcentaje(f.parte, 0), aportado: usdt(piso.aportado) });
    }
    if (f.codigo === "piso") {
      return f.activo
        ? frase("El saldo ({valor}) tocó el piso ({limite}): no abro nada. Lo que está abierto se queda con su protección automática.", { valor: usdt(f.valor), limite: usdt(f.limite) })
        : frase("Frena si el saldo baja de {limite}: el {parte} bajo el capital de referencia ({referencia}).", {
          limite: usdt(f.limite), parte: porcentaje(f.parte, 0), referencia: usdt(piso.referencia) });
    }
    if (f.codigo === "diario") {
      return f.activo
        ? frase("Hoy perdí el {caida} ({monto}): no abro nada más hasta que el día cambie, el {cuando}.", {
          caida: porcentaje(f.caida, 1), monto: usdt(Math.abs(dia.monto)), cuando: fechaHora(f.hasta) })
        : frase("Hoy partí con {inicio} y voy en {valor}: frena al perder el {parte} del día, bajo {limite}.", {
          inicio: usdt(dia.inicio), valor: usdt(f.valor), parte: porcentaje(f.parte, 0), limite: usdt(f.limite) });
    }
    if (f.codigo === "racha") {
      return f.activo
        ? frase("{n} pérdidas seguidas: vuelvo a manual. Te propongo y tú decides.", { n: numero(racha.n, 0) })
        : frase("{n} pérdidas seguidas: con {maxima} vuelvo a manual.", { n: numero(racha.n, 0), maxima: numero(racha.maxima, 0) });
    }
    if (f.codigo === "comision") {
      return f.activo
        ? frase("La comisión maker de ahora ({valor}) pasó la que supuso el backtest ({limite}): lo que ese backtest prometió ya no vale.", { valor: porcentaje(f.valor), limite: porcentaje(f.limite) })
        : frase("La maker de ahora es {valor} y el backtest supuso {limite}: frena si la sube.", {
          valor: porcentaje(f.valor), limite: porcentaje(f.limite) });
    }
    if (typeof f.valor !== "number") {
      return "Todavía no puedo medir cuánto vale FDUSD: necesito velas cerradas de la misma hora de los dos pares.";
    }
    return f.activo
      ? frase("FDUSD vale {valor} USDT, menos de {limite}: no abro nada y no liquido nada sin que me lo confirmes.", { valor: numero(f.valor, 4), limite: numero(f.limite, 3) })
      : frase("FDUSD vale {valor} USDT: frena bajo {limite}.", { valor: numero(f.valor, 4), limite: numero(f.limite, 3) });
  }
  function filaFreno(f, c) {
    const estado = f.activo ? "incompleto" : (f.aplica ? "listo" : "vacio");
    const etiqueta = f.activo ? "Frenado" : (f.aplica ? "Pasa" : (f.avisa ? "Avisa" : "No corre en prueba"));
    return `<li class="tramo"><span class="tramo-nombre">${NOMBRE_FRENO[f.codigo] || f.codigo}</span>
      <span class="serie-estado" data-estado="${estado}">${etiqueta}</span>
      <span class="serie-detalle${f.activo ? " freno" : ""}">${detalleFreno(f, c)}</span>
      ${!f.aplica ? `<span class="serie-detalle">En prueba no frena: no hay dinero de verdad que cuidar. Te lo digo igual.</span>` : ""}</li>`;
  }
  function frenos() {
    const d = E.frenos;
    if (!d) return `<p class="suave">Revisando los frenos…</p>`;
    const cuentas = Array.isArray(d.cuentas) ? d.cuentas : [];
    const c = cuentas.find((x) => x.ambiente === d.activo) || {};
    const p = d.parametros || {}, e = d.entradas || {}, des = c.desbloqueo || {}, reduce = d.reduce || {};
    const lista = Array.isArray(c.frenos) ? c.frenos : [];
    const pie = `<div class="pz-pie">
      <button type="button" class="pz-boton" id="frenos-pausar"${E.pausando ? " disabled" : ""}>${E.pausando ? "Un momento…" : (d.pausado ? "Seguir" : "Pausar")}</button>
      ${des.puede ? `<button type="button" class="pz-boton" id="frenos-desbloquear"${E.desbloqueando ? " disabled" : ""}>${des.listo ? "Desbloquear el piso" : "Pedir el desbloqueo"}</button>` : ""}</div>`;
    return `<div id="frenos" class="indicadores">
      <p class="indicadores-resumen${d.frenado ? " freno" : ""}">${frase("Ahora: {estado}, en modo {modo}.", {
        estado: Tp(ETIQUETA_ESTADO_FRENOS[d.estado] || d.estado), modo: Tp(ETIQUETA_MODO[d.modo] || d.modo) })}</p>
      ${e.puede
        ? `<p class="indicadores-linea">${frase("Puedo abrir hasta {n} posiciones más, si una oportunidad llega a la exigencia y el tamaño alcanza.", { n: numero(e.quedan, 0) })}</p>`
        : `<p class="indicadores-linea freno">${frase(MOTIVOS_FRENOS[e.motivo] || "No abro nada: hay un freno puesto.", { n: numero((c.posiciones || {}).abiertas, 0) })}</p>`}
      ${reduce.hay ? `<p class="indicadores-linea freno">${frase("Y no es solo no abrir: el piso absoluto cierra a mercado las {n} posiciones abiertas ({monto}).", {
        n: numero(reduce.posiciones, 0), monto: usdt(reduce.monto) })}</p>` : ""}
      ${d.pausado ? `<p class="indicadores-linea">${frase("Sigues con {n} posiciones protegidas: «Pausar» cancela las entradas y no toca ninguna protección automática.", { n: numero(d.protegidas, 0) })}</p>` : ""}
      <ul class="tramos" aria-label="Los frenos">${lista.map((f) => filaFreno(f, c)).join("")}</ul>
      <ul class="tramos" aria-label="Los frenos de siempre">
        ${pasoTamano("Sin apalancamiento", "listo", `${numero(p.apalancamiento, 0)}x`,
          "Pilota solo compra al contado y con lo que hay: una orden con apalancamiento no se pone nunca.", true)}
        ${pasoTamano("Las posiciones a la vez", (c.posiciones || {}).quedan > 0 ? "listo" : "incompleto",
          frase("{n} de {maximas}", { n: numero((c.posiciones || {}).abiertas, 0), maximas: numero(p.posiciones, 0) }),
          "Son las mismas dos del tamaño y del capital mínimo viable: una tercera no se abre.")}
      </ul>
      ${des.motivo === "esperando"
        ? `<p class="indicadores-linea">${frase("Pediste desbloquear el piso: se puede aplicar el {cuando}, 24 horas después. Hasta entonces no abro nada.", { cuando: fechaHora(des.hasta) })}</p>`
        : (des.motivo === "sin_desbloqueos"
          ? `<p class="indicadores-linea freno">${frase("Ya usaste los {n} desbloqueos del piso: este no se desbloquea más.", { n: numero(des.maximos, 0) })}</p>`
          : (des.motivo === "piso_absoluto"
            ? `<p class="indicadores-linea freno">El piso absoluto no se desbloquea.</p>` : ""))}
      ${(d.motivos || []).map((m) => `<p class="indicadores-linea freno">${frase("No pude medir FDUSD con {par}: sin ese número no abro nada.", { par: m.par })}</p>`).join("")}
      <p class="suave">Los frenos están en el código, fuera de la IA, y la cuenta de prueba y la real llevan los suyos por separado. El estado de los frenos vive en el archivo con huella: si no cuadra, arranco frenado en manual.</p>
      ${pie}</div>`;
  }
  // ── El ejecutor del modo prueba (bin/lib_ejecutor_prueba.py): dinero ficticio, precios de verdad ──
  const ETIQUETA_POSICION = { puesta: "Esperando", abierta: "Abierta" };
  // Por qué no se puso una orden o por qué todavía no se puede operar en prueba. Los códigos los pone el Python
  // (lib_ejecutor_prueba); los del tamaño y los frenos se cuentan como los cuentan ellos.
  const MOTIVOS_EJECUTOR = {
    sin_ambiente: "Esto es solo del modo prueba, y ahora no estás en prueba.",
    sin_opcion: "Ahora mismo no hay ninguna oportunidad con monto: no hay nada que poner.",
    no_permitida: "Esa oportunidad existe, pero BTC no deja entrar ahora: no abro nada.",
    repetida: "Ya tengo una orden o una posición por esa misma señal: no abro dos.",
    sin_cuenta: "Esta cuenta todavía no existe: elige el monto de prueba y empiezo.",
    sin_filtros: "Todavía no sé los mínimos que pide Binance: calcula el capital mínimo viable y vuelvo a mirar.",
    sin_niveles: "Esa señal no trae entrada, stop y objetivo en orden, y sin los tres no hay protección que poner.",
    tick: "Alguno de los tres precios no cae en el tick que pide Binance: la protección no cabría.",
    paso: "La cantidad no es un múltiplo del paso que pide Binance: la protección no cabría.",
    cantidad_minima: "La cantidad queda bajo la mínima que pide Binance: la protección no cabría.",
    nocional_compra: "La compra queda bajo el mínimo en USDT que pide Binance: no abro nada.",
    nocional_stop: "La pata del stop queda bajo el mínimo en USDT que pide Binance: no abro nada.",
    nocional_objetivo: "La pata del objetivo queda bajo el mínimo en USDT que pide Binance: no abro nada.",
    sin_1m: "{par}: sin velas de 1 minuto no puedo ver ningún cruce, así que no abro nada.",
    sin_tamano: "Esa orden no pasó por el tamaño, así que no la pongo.",
    monto_mayor: "Esa orden pide más de lo que dejó el tamaño: no la pongo.",
    lado: "Pilota solo compra: una venta no se pone nunca.",
    tipo: "Pilota solo entra con límite: una orden a mercado no se pone nunca.",
    apalancamiento: "Con apalancamiento no se pone ninguna orden.",
  };
  function motivoEjecutor(codigo, par, n) {
    return frase(MOTIVOS_EJECUTOR[codigo] || MOTIVOS_FRENOS[codigo] || MOTIVOS_TAMANO[codigo]
      || "No pude poner la orden.", { par: par || "", n: numero(n || 0, 0) });
  }
  // Una entrada puesta o una posición abierta, con su protección simulada y lo que lleva ganado.
  function filaPosicionPrueba(p) {
    const donde = [p.par, ETIQUETA_TEMPORALIDAD[p.temporalidad] || p.temporalidad].filter(Boolean).join(" · ");
    const abierta = p.estado === "abierta";
    return `<li class="serie">
      <span class="serie-par" data-sin-traducir>${esc(donde)}</span>
      <span class="serie-estado" data-estado="${abierta ? (p.protegida ? "listo" : "incompleto") : "vacio"}">${ETIQUETA_POSICION[p.estado] || p.estado}</span>
      <span class="serie-detalle">${ETIQUETA_ESTRATEGIA[p.estrategia] || p.estrategia}</span>
      ${abierta
        ? `<span class="serie-detalle">${frase("Compré {cantidad} a {precio}: {monto} comprometidos.", {
            cantidad: numero(p.cantidad, 8), precio: numero(p.precio), monto: usdt(p.monto) })}</span>
          <span class="serie-detalle">${p.objetivo > 0
            ? frase("Protección automática: stop en {stop} y objetivo en {objetivo}.", { stop: numero(p.stop), objetivo: numero(p.objetivo) })
            : frase("Protección automática: ya solo el stop móvil, en {stop}.", { stop: numero(p.stop) })}</span>
          ${typeof p.ganancia === "number"
            ? `<span class="serie-detalle">${frase("Ahora va en {precio}: {monto} ({parte}), antes de los costos de salir.", {
                precio: numero(p.precio_ahora), monto: usdt(p.ganancia), parte: porcentaje(p.ganancia_relativa, 2) })}</span>`
            : `<span class="serie-detalle">Todavía no tengo precio de ahora para decir cómo va.</span>`}
          ${p.movido ? `<span class="serie-detalle">${frase("El stop móvil ya subió desde {stop}: lo moví {n} veces, y cada vez cancelo la protección y pongo otra.", {
            stop: numero(p.stop_inicial), n: numero(p.reposiciones, 0) })}</span>` : ""}`
        : `<span class="serie-detalle">${frase("Compra con límite de {cantidad} en {precio} ({monto}), con stop en {stop} y objetivo en {objetivo}.", {
            cantidad: numero(p.cantidad, 8), precio: numero(p.precio), monto: usdt(p.monto),
            stop: numero(p.stop), objetivo: numero(p.objetivo) })}</span>
          <span class="serie-detalle">${frase("Vence el {cuando}: puesta no es llenada, y se llena solo cuando el precio llega al nivel y sigue en contra.", { cuando: fechaHoraMs(p.vence_ms) })}</span>`}
      <span class="serie-detalle">${p.mitad > 0
        ? frase("Va a salir en dos partes: {cantidad} en el objetivo y el resto con el stop móvil.", { cantidad: numero(p.mitad, 8) })
        : (abierta && !(p.objetivo > 0)
          ? "La mitad ya salió en el objetivo: lo que queda va con el stop móvil."
          : "Sale entera: la mitad no pasaría los mínimos de Binance.")}</span>
      ${abierta && !p.protegida ? `<span class="serie-detalle freno">Esta posición no tiene su protección automática puesta.</span>` : ""}</li>`;
  }
  // Las órdenes que Pilota tiene puestas, con su id propio: la entrada mientras no se llena y, llenada, las dos patas.
  function filaOrdenPrueba(o) {
    const QUE = { entrada: "La compra con límite", stop: "La pata del stop", objetivo: "La pata del objetivo" };
    return `<li class="tramo"><span class="tramo-nombre">${QUE[o.que] || o.que}</span>
      <span class="serie-estado" data-estado="vacio" data-sin-traducir>${esc(numero(o.precio))}</span>
      <span class="serie-detalle" data-sin-traducir>${esc(o.id || "")}</span>
      <span class="serie-detalle">${frase("por {cantidad}, puesta y esperando.", { cantidad: numero(o.cantidad, 8) })}</span></li>`;
  }
  function ejecutor() {
    const d = E.ejecutor;
    if (!d) return `<p class="suave">Mirando qué hay abierto en prueba…</p>`;
    const cob = d.cobertura || {}, p = d.parametros || {};
    const posiciones = Array.isArray(d.posiciones) ? d.posiciones : [];
    const ordenes = Array.isArray(d.ordenes) ? d.ordenes : [];
    const impedimentos = (d.motivos || []).filter((m) => m.codigo !== "sin_capital");
    const pie = `<div class="pz-pie">
      <button type="button" class="pz-boton" id="ejecutor-revisar"${E.ejecutando ? " disabled" : ""}>${E.ejecutando ? "Un momento…" : "Revisar los cruces"}</button></div>`;
    return `<div id="ejecutor" class="indicadores">
      <p class="indicadores-resumen${d.frenado ? " freno" : ""}">${d.frenado
        ? "Arranqué frenado en manual: de un estado del que no me fío no sale ninguna orden."
        : frase("Saldo de prueba: {saldo}. {abiertas} posiciones abiertas y {puestas} entradas esperando, con {monto} comprometidos.", {
            saldo: usdt(d.saldo), abiertas: numero(d.abiertas, 0), puestas: numero(d.puestas, 0),
            monto: usdt(d.comprometido) })}</p>
      ${posiciones.length
        ? `<ul class="series" aria-label="Lo que tengo en prueba">${posiciones.map(filaPosicionPrueba).join("")}</ul>`
        : `<p class="indicadores-linea">No tengo nada puesto ni abierto en prueba: cuando una oportunidad pase el tamaño y los frenos, acá va su orden.</p>`}
      ${ordenes.length ? `<h3>Las órdenes que tengo puestas</h3>
        <ul class="tramos" aria-label="Órdenes puestas">${ordenes.map(filaOrdenPrueba).join("")}</ul>` : ""}
      <p class="indicadores-linea">${cob.hasta_ms
        ? frase("Las velas de 1 minuto llegan hasta el {cuando}: {n} minutos sin mirar.", {
            cuando: fechaHora(cob.hasta), n: numero(cob.sin_cobertura_min, 0) })
        : "Todavía no tengo velas de 1 minuto guardadas: enciende el muestreo y con eso miro los cruces."}</p>
      ${impedimentos.map((m) => `<p class="indicadores-linea freno">${motivoEjecutor(m.codigo, m.par, m.n)}</p>`).join("")}
      <p class="suave">${frase("Los cruces se miran con las velas de 1 minuto, y una orden límite se llena solo cuando el precio sigue en contra: el mismo supuesto con el que se midió el backtest. Cada orden lleva el prefijo «{prefijo}» en su id, y lo que no lo lleve no es de Pilota: eso no se toca nunca.", { prefijo: p.prefijo || "pil" })}</p>
      <p class="suave freno">En prueba la protección existe solo con el motor encendido: no hay ninguna orden en Binance cuidando esto. Si Pilota no está corriendo, nadie mira los cruces.</p>
      ${pie}</div>`;
  }
  // ── El motor (bin/motor.py, bin/lib_reconciliar.py): la revisión cada 5 minutos y la reconciliación al despertar ──
  // Por qué el motor no está cuidando nada ahora mismo. Los códigos los pone el Python (lib_reconciliar.MOTIVOS).
  const MOTIVOS_MOTOR = {
    apagado: "El motor está apagado: nadie está mirando los cruces.",
    dormido: "La última revisión fue hace {n} min: mientras nadie mira, un stop no se aplica.",
    sin_1m: "Las velas de 1 minuto van {n} min atrasadas, y son las que dicen qué se cruzó.",
    frenado: "Hay un freno puesto: el motor revisa igual, pero no abre ninguna entrada nueva.",
    sin_conector: "El conector real todavía no existe: el motor solo reconcilia la cuenta de prueba.",
  };
  // Por qué una ventana quedó sin cobertura (lib_reconciliar: dormido, sin_1m, atrasada).
  const VENTANAS_MOTOR = {
    dormido: "nadie estaba mirando",
    sin_1m: "sin velas de 1 minuto",
    atrasada: "las velas de 1 minuto iban atrasadas",
  };
  // Lo que pasó en la ventana que nadie miró: «Dormiste 9 h: 1 stop, 2 propuestas vencidas».
  const COSAS_MOTOR = [
    ["stops", "{n} stop", "{n} stops"],
    ["objetivos", "{n} objetivo", "{n} objetivos"],
    ["llenadas", "{n} entrada llenada", "{n} entradas llenadas"],
    ["vencidas", "{n} propuesta vencida", "{n} propuestas vencidas"],
    ["cierres", "{n} cierre a mercado", "{n} cierres a mercado"],
    ["frenos", "{n} freno puesto", "{n} frenos puestos"],
    ["rechazos", "{n} orden rechazada", "{n} órdenes rechazadas"],
  ];
  function motivoMotor(m) {
    return frase(MOTIVOS_MOTOR[m && m.codigo] || "El motor no está cuidando nada ahora mismo.",
      { n: numero((m && m.n) || 0, 0) });
  }
  // Cada cosa que pasó, en texto plano y con su singular: lo que va dentro de «Dormiste 9 h: …».
  function cosasMotor(r) {
    return COSAS_MOTOR.filter(([c]) => (r[c] || 0) > 0)
      .map(([c, uno, varios]) => Tp(r[c] === 1 ? uno : varios, { n: numero(r[c], 0) })).join(", ");
  }
  function resumenMotor(r) {
    const tiempo = duracion((r.dormido_ms || 0) / 1000), que = cosasMotor(r);
    if (!que) {
      return r.dormido
        ? frase("Dormiste {tiempo} y en ese rato no pasó nada.", { tiempo })
        : `<span>En la última revisión no pasó nada.</span>`;
    }
    return r.dormido ? frase("Dormiste {tiempo}: {que}.", { tiempo, que }) : frase("En la última revisión: {que}.", { que });
  }
  // El mismo resumen para un aviso: ahí va texto plano, no el HTML que devuelve frase().
  function avisoMotor(r) {
    const tiempo = duracion((r.dormido_ms || 0) / 1000), que = cosasMotor(r);
    if (!que) {
      return r.dormido ? Tp("Dormiste {tiempo} y en ese rato no pasó nada.", { tiempo })
        : Tp("En la última revisión no pasó nada.");
    }
    return r.dormido ? Tp("Dormiste {tiempo}: {que}.", { tiempo, que }) : Tp("En la última revisión: {que}.", { que });
  }
  function lineaMotor(m) {
    if (m.deteniendo) return "Deteniendo: termino la revisión que estoy haciendo.";
    const hace = (typeof m.hace_ms === "number")
      ? frase("Última revisión hace {tiempo}", { tiempo: duracion(m.hace_ms / 1000) }) : "";
    if (m.corriendo) {
      const proxima = frase("la próxima, en {tiempo}", { tiempo: duracion(((m.proxima || 0) - Date.now()) / 1000) });
      return hace ? `${hace} · ${proxima}` : proxima;
    }
    if (m.estado === "error") return frase(ERRORES[m.error] || "No se pudo.");
    if (!hace) return "Todavía no he hecho ninguna revisión: Pilota solo trabaja con el equipo encendido.";
    return `${hace} · ${m.estado === "interrumpido"
      ? Tp("se cortó al cerrarse la app") : Tp("apagado: nadie está mirando los cruces")}`;
  }
  // Una ventana sin cobertura: el rato en que un stop no se habría aplicado. Queda escrita en vez de taparse.
  function ventanaMotor(v) {
    return `<li class="tramo">
      <span class="tramo-nombre">${frase("{n} min sin cubrir", { n: numero(v.min, 0) })}</span>
      <span class="serie-estado" data-estado="${v.abierto ? "incompleto" : "vacio"}">${v.abierto ? "Abierta" : "Cerrada"}</span>
      <span class="serie-detalle">${frase("desde el {cuando}", { cuando: fechaHora(v.desde) })}</span>
      <span class="serie-detalle">${Tp(VENTANAS_MOTOR[v.motivo] || "sin cobertura")}</span></li>`;
  }
  function botonMotor(m) {
    if (m.corriendo) {
      return `<button type="button" class="pz-boton" id="motor-apagar"${m.deteniendo ? " disabled" : ""}>${m.deteniendo ? "Deteniendo…" : "Detener"}</button>`;
    }
    return `<button type="button" class="pz-boton pz-principal" id="motor-encender"${E.encendiendoMotor ? " disabled" : ""}>${E.encendiendoMotor ? "Encendiendo…" : "Encender el motor"}</button>`;
  }
  function motor() {
    const m = E.motor;
    if (!m) return `<p class="suave">Mirando el motor…</p>`;
    const r = m.resumen || {}, cob = m.cobertura || {};
    const ventanas = (Array.isArray(m.sin_cobertura) ? m.sin_cobertura : []).slice(-3).reverse();
    return `<div id="motor" class="trabajo">
      <p class="indicadores-resumen${m.activo ? "" : " freno"}">${m.activo
        ? frase("Motor activo: reviso cada {n} min y tengo {protegidas} posiciones protegidas.", {
            n: Math.round((m.ciclo_segundos || 300) / 60), protegidas: numero(m.protegidas, 0) })
        : "Motor dormido: nadie está mirando los cruces ahora mismo."}</p>
      <p class="trabajo-linea">${lineaMotor(m)}</p>
      ${r.hasta_ms ? `<p class="indicadores-linea">${resumenMotor(r)}</p>` : ""}
      ${ventanas.length
        ? `<ul class="tramos" aria-label="Ventanas sin cobertura">${ventanas.map(ventanaMotor).join("")}</ul>` : ""}
      ${(m.motivos || []).map((x) => `<p class="indicadores-linea freno">${motivoMotor(x)}</p>`).join("")}
      <p class="suave">${cob.hasta_ms
        ? frase("Los cruces se miran con las velas de 1 minuto, y las que tengo llegan hasta el {cuando}. Las trae el muestreo: mientras no lleguen, la ventana queda abierta y la vuelvo a mirar en la próxima revisión.", { cuando: fechaHora(cob.hasta) })
        : `<span>Todavía no tengo velas de 1 minuto: enciende el muestreo y con ellas miro los cruces.</span>`}</p>
      <div class="pz-pie">${botonMotor(m)}
        <button type="button" class="pz-boton" id="motor-revisar"${E.revisandoMotor ? " disabled" : ""}>${E.revisandoMotor ? "Un momento…" : "Revisar ahora"}</button></div></div>`;
  }
  // ── Los tres modos y las propuestas que vencen (bin/propuestas.py, bin/lib_modos.py) ──
  // Qué hace cada modo, en palabras. El semiautomático se cuenta sin ninguna suma: el margen de «claramente alto» es
  // del código (lib_modos.MARGEN_CLARO), no una perilla de la persona.
  const QUE_HACE_MODO = {
    manual: "Te propongo cada operación —puntaje, razón, monto y stop— y espero tu «Sí».",
    semiautomatico: "Opero solo cuando el puntaje es claramente alto y el monto cabe en el que elegiste; si no, te pregunto.",
    automatico: "Opero solo, con el mismo puntaje, el mismo tamaño y los mismos frenos.",
  };
  // Por qué un modo está apagado. Los códigos los pone el Python (lib_modos, lib_frenos).
  const MOTIVOS_MODO = {
    sin_calibracion: "Hasta que el modelo esté calibrado, cada entrada la decides tú.",
    faltan_confirmaciones: "El automático se activa confirmando dos veces.",
    modo: "Ese modo no existe.",
    frenado: "Con un freno puesto solo queda el manual.",
  };
  // En qué quedó la última vuelta de decisión (lib_modos.DECISIONES).
  const TEXTO_DECISION = {
    propuesta: "Te propuse una operación y estoy esperando tu respuesta.",
    entrada: "Entré solo: la oportunidad pasó la exigencia, el tamaño y los frenos.",
    esperando: "Esa misma oportunidad ya está propuesta: no propongo dos veces lo mismo.",
    repetida: "Ya tengo una orden o una posición por esa misma señal.",
    sin_oportunidad: "Ahora mismo no hay ninguna oportunidad con monto.",
    bajo_exigencia: "La mejor oportunidad de ahora no llega a la exigencia: me quedo en USDT.",
    en_usdt: "Quedarse en USDT puntúa más que cualquier entrada de ahora.",
    frenado: "Hay un freno puesto: no abro ninguna entrada nueva.",
    rechazo: "No pude poner la orden.",
    sin_ambiente: "El conector real todavía no existe: esto es solo del modo prueba.",
  };
  // Por qué el semiautomático preguntó en vez de operar solo.
  const MOTIVOS_PREGUNTA = {
    no_claro: "El puntaje alcanza para entrar, pero no es claramente alto: mejor te pregunto.",
    monto_mayor: "Esta oportunidad pide más de lo que dejaste para que opere solo: mejor te pregunto.",
    sin_calibracion: "Sin calibración decides tú, aunque el modo diga otra cosa.",
  };
  function filaModo(m) {
    const estado = m.actual ? "listo" : (m.puede ? "vacio" : "incompleto");
    const etiqueta = m.actual ? "El tuyo" : (m.puede ? "Disponible" : "Apagado");
    return `<li class="tramo"><span class="tramo-nombre">${ETIQUETA_MODO[m.modo] || m.modo}</span>
      <span class="serie-estado" data-estado="${estado}">${etiqueta}</span>
      <span class="serie-detalle">${QUE_HACE_MODO[m.modo] || ""}</span>
      ${m.puede ? "" : `<span class="serie-detalle freno">${Tp(MOTIVOS_MODO[m.motivo] || MOTIVOS_FRENOS[m.motivo] || "Este modo no se puede usar ahora.")}</span>`}
      ${m.actual || !m.puede ? "" : `<span class="serie-detalle"><button type="button" class="pz-boton" data-modo="${esc(m.modo)}"${E.cambiandoModo ? " disabled" : ""}>${m.modo === "automatico" ? "Activar el automático" : "Usar este modo"}</button></span>`}</li>`;
  }
  // Una propuesta esperando: el puntaje, la razón, el monto en USDT, el stop y cuánto le queda antes de vencer.
  function filaPropuesta(p) {
    const donde = [p.par, ETIQUETA_TEMPORALIDAD[p.temporalidad] || p.temporalidad].filter(Boolean).join(" · ");
    const esperando = E.respondiendo === p.id;
    return `<li class="serie">
      <span class="serie-par" data-sin-traducir>${esc(donde)}</span>
      <span class="serie-estado" data-estado="listo">${frase("Puntaje {n}", { n: numero(p.puntaje, 0) })}</span>
      <span class="serie-detalle">${Tp(ETIQUETA_ESTRATEGIA[p.estrategia] || p.estrategia)}</span>
      <span class="serie-detalle">${frase("Compro {monto} a {precio}, con stop en {stop} y objetivo en {objetivo}: arriesgo {arriesgado}.", {
        monto: usdt(p.monto), precio: numero(p.entrada), stop: numero(p.stop), objetivo: numero(p.objetivo),
        arriesgado: usdt(p.arriesgado) })}</span>
      <span class="serie-detalle">${frase("Vence en {tiempo}: si no me respondes, la dejo pasar.", { tiempo: duracion(p.queda_ms / 1000) })}</span>
      ${p.motivo ? `<span class="serie-detalle">${Tp(MOTIVOS_PREGUNTA[p.motivo] || "Te pregunto antes de abrir esto.")}</span>` : ""}
      <span class="serie-detalle">
        <button type="button" class="pz-boton pz-principal" data-propuesta="${esc(p.id)}" data-si="1"${esperando ? " disabled" : ""}>${esperando ? "Un momento…" : "Sí, ábrela"}</button>
        <button type="button" class="pz-boton" data-propuesta="${esc(p.id)}" data-si="0"${esperando ? " disabled" : ""}>No, me quedo en USDT</button></span></li>`;
  }
  function modos() {
    const d = E.modos;
    if (!d) return `<p class="suave">Mirando en qué modo estoy…</p>`;
    const lista = Array.isArray(d.modos) ? d.modos : [];
    const esperan = (Array.isArray(d.propuestas) ? d.propuestas : []).filter((p) => p.espera);
    const dec = E.decision || null;
    const venc = (d.vencimientos || []).map((v) =>
      `<button type="button" data-vencimiento="${v}" aria-pressed="${d.vencimiento_min === v}">${Tp("{n} min", { n: numero(v, 0) })}</button>`).join("");
    const montos = (d.montos || []).map((m) =>
      `<button type="button" data-monto="${m}" aria-pressed="${d.monto === m}" data-sin-traducir>${esc(usdt(m))}</button>`).join("");
    return `<div id="modos" class="indicadores">
      <p class="indicadores-resumen${d.frenado ? " freno" : ""}">${frase("Ahora estás en modo {modo}: {que}", {
        modo: Tp(ETIQUETA_MODO[d.modo] || d.modo), que: Tp(QUE_HACE_MODO[d.modo] || "") })}</p>
      ${d.efectivo !== d.modo
        ? `<p class="indicadores-linea freno">${frase("Pero esta vuelta la decido como manual: {motivo}", {
            motivo: Tp(MOTIVOS_MODO[d.motivo_modo] || MOTIVOS_FRENOS[d.motivo_modo] || "hay algo que todavía no me deja operar sola.") })}</p>`
        : ""}
      <ul class="tramos" aria-label="Los tres modos">${lista.map(filaModo).join("")}</ul>
      ${esperan.length
        ? `<h3>Lo que te estoy proponiendo</h3>
          <ul class="series" aria-label="Propuestas esperando">${esperan.map(filaPropuesta).join("")}</ul>`
        : `<p class="indicadores-linea">${frase("No tengo nada propuesto. La mejor oportunidad de ahora puntúa {n} y la exigencia es {exigencia}.", {
            n: numero((d.mejor || {}).puntaje, 0), exigencia: numero(d.exigencia, 0) })}</p>`}
      ${dec ? `<p class="indicadores-linea">${Tp(TEXTO_DECISION[dec.decision] || "Todavía no he decidido nada.")}</p>` : ""}
      ${dec && dec.motivo && MOTIVOS_PREGUNTA[dec.motivo]
        ? `<p class="indicadores-linea">${Tp(MOTIVOS_PREGUNTA[dec.motivo])}</p>` : ""}
      <p class="indicadores-linea">${frase("Hoy vencieron {n} propuestas: una que nadie responde vence siempre, y eso también queda en el registro.", { n: numero(d.vencidas_hoy, 0) })}</p>
      <h3>Cuánto espera una propuesta</h3>
      <div class="pz-seg" role="group" aria-label="Cuánto espera una propuesta">${venc}</div>
      <h3>Hasta cuánto opero solo en semiautomático</h3>
      <div class="pz-seg" role="group" aria-label="Hasta cuánto opero solo">${montos}</div>
      ${(d.motivos || []).map((m) => `<p class="indicadores-linea freno">${Tp(MOTIVOS_MODO[m.codigo] || MOTIVOS_FRENOS[m.codigo] || TEXTO_DECISION[m.codigo] || "Ahora no abro ninguna entrada nueva.")}</p>`).join("")}
      <p class="suave">Tras cualquier freno vuelvo a manual, y mientras el modelo no esté calibrado el semiautomático y el automático quedan apagados: lo que el modelo promete todavía no está probado.</p>
      <div class="pz-pie">
        <button type="button" class="pz-boton" id="modos-decidir"${E.decidiendo ? " disabled" : ""}>${E.decidiendo ? "Mirando…" : "Mirar ahora"}</button></div></div>`;
  }
  // ── La pantalla principal (ui/panel.js): el saldo con su piso, los medidores, las posiciones y la mascota ──
  // Las etiquetas que ya existen acá se le pasan tal cual: una misma cosa no se nombra de dos formas.
  const panelUI = PilotaPanel.crear({
    i18n, esc, numero, usdt, porcentaje, duracion, fechaHora, fechaHoraMs,
    etiquetas: { ambiente: ETIQUETA_AMBIENTE, modo: ETIQUETA_MODO, temporalidad: ETIQUETA_TEMPORALIDAD,
      estrategia: ETIQUETA_ESTRATEGIA, posicion: ETIQUETA_POSICION, razones: RAZONES_REGISTRO, cierre: ETIQUETA_CIERRE,
      motivoCorto: MOTIVO_CORTO, motivosFrenos: MOTIVOS_FRENOS, motivosTamano: MOTIVOS_TAMANO,
      pregunta: MOTIVOS_PREGUNTA, cosasMotor: COSAS_MOTOR },
  });
  function principal() {
    const series = (E.datos && Array.isArray(E.datos.series)) ? E.datos.series : [];
    return `<header class="barra"><h1 data-sin-traducir>${esc(NOMBRE)}</h1>
      <button type="button" class="pz-boton" id="abrir-ajustes">Ajustes</button></header>
      ${banda()}
      <main class="contenido">
        ${panelUI.html(E.panel, { respondiendo: E.respondiendo })}
        <details class="por-dentro" id="por-dentro">
        <summary>Ver cómo lo pensé, paso a paso</summary>
        <h2>Cómo trabaja Pilota, paso a paso</h2>
        <p class="ayuda">Debajo está cada pieza por separado, con sus números: de dónde salen los datos, cómo se puntúa una oportunidad, cuánto se pone en cada operación y qué la frena. Nada de lo de arriba sale de otra parte.</p>
        <h2>Datos del mercado</h2>
        <p class="suave">${frase("Velas cerradas de Binance de los últimos {n} días. Pilota decide solo con velas cerradas y continuas.", { n: (E.datos && E.datos.dias) || DIAS })}</p>
        ${estadoDatos()}
        <div class="pz-pie"><button type="button" class="pz-boton pz-principal" id="descargar"${E.descargando ? " disabled" : ""}>${E.descargando ? "Descargando…" : "Descargar historial"}</button></div>
        ${series.length ? `<ul id="datos-series" class="series" aria-label="Datos por par y temporalidad">${series.map(serie).join("")}</ul>` : ""}
        ${descarga()}
        <h2>Capital mínimo viable</h2>
        <p class="ayuda">Lo menos que necesitas para operar sin romper los frenos: que la orden pase los mínimos de Binance, que el 40 % del capital se quede siempre en USDT, que quepan dos posiciones y que el riesgo de cada una no pase el 2 % del capital.</p>
        <p class="ayuda">${frase("**Protección automática**: las dos órdenes que cuidan una posición abierta, una con el objetivo y otra con el stop. Las dos tienen que pasar los mínimos de Binance, y la del stop es la más chica: es la que manda.")}</p>
        ${minimoViable()}
        <h2>Historial de 3 años</h2>
        <p class="ayuda">${frase("Los {dias} días de arriba son los que Pilota necesita para decidir. Los 3 años son para el backtest y la calibración: se bajan en segundo plano, por etapas, y puedes detenerlos y seguir después donde quedaste.", { dias: DIAS })}</p>
        ${historial()}
        <h2>Muestreo del mercado</h2>
        <p class="ayuda">${frase("Binance no guarda el libro de órdenes de antes: el mejor precio de compra y de venta de hoy solo lo vamos a tener si lo guardamos hoy. Cada {minutos} minutos Pilota guarda una muestra de los dos pares que opera y pone al día las velas de 1 m de los últimos {dias} días.", { minutos: Math.round(((E.muestreo && E.muestreo.ciclo_segundos) || 300) / 60), dias: (E.muestreo && E.muestreo.dias) || 30 })}</p>
        <p class="ayuda">Los precios de la muestra son del par contra FDUSD; los montos y el saldo, siempre en USDT.</p>
        ${muestreo()}
        <h2>Indicadores del mercado</h2>
        <p class="ayuda">Lo que mira Pilota en cada serie: para dónde va el precio (las medias de 20, 50 y 200 velas), cuánta fuerza tiene ese movimiento (ADX), si viene acelerando o cansado (RSI y MACD), cuánto se mueve y en qué parte de su banda está (Bollinger y ATR), si el volumen acompaña (volumen relativo y OBV) y si rompió el techo o el piso de las últimas velas. Aparte, cómo viene BTC y cuánto cuesta entrar y salir ahora mismo.</p>
        <p class="ayuda">${frase("**Media de 200 velas**: el precio promedio de las últimas 200 velas. Por eso una serie de 1 d necesita más de 200 días de historial: hasta que lleguen, su fila dice qué falta en vez de mostrar un número.")}</p>
        <p class="ayuda">Todo con velas cerradas y seguidas: la vela en curso todavía puede cambiar. El costo sale de la última muestra del libro, así que necesita el muestreo encendido.</p>
        ${indicadores()}
        <h2>Las tres estrategias</h2>
        <p class="ayuda">Pilota solo tiene tres salidas: entrar por una ruptura (el precio pasó el techo de las últimas velas con volumen y el día viene al alza, y se entra con límite cuando vuelve a ese nivel), entrar por un rebote (el precio pegó en la banda de abajo con el mercado sin rumbo, y se sale en la media) o quedarse en USDT.</p>
        <p class="ayuda">Y un freno sobre las dos entradas: si BTC cae, no se entra a nada, ni en BTC ni en ETH.</p>
        <p class="ayuda">${frase("**Señal cruda**: la oportunidad tal como la ve una estrategia, con su nivel de entrada, su stop y su objetivo. Todavía no es una orden: el puntaje, el costo de entrar y salir y el tamaño vienen en los pasos siguientes. Solo se compra, siempre con límite y sin apalancamiento.")}</p>
        ${senales()}
        <h2>Backtest de señales crudas</h2>
        <p class="ayuda">Qué habrían hecho estas reglas con el historial, todavía sin ninguna exigencia: cada señal pone su orden límite, se llena solo si el precio sigue en contra y se sigue vela por vela hasta el stop o el objetivo, descontando la comisión de cada lado, la conversión USDT↔FDUSD y la diferencia entre compra y venta.</p>
        <p class="ayuda">${frase("**Caso**: una operación que se puede contar aparte. Dos operaciones que vivieron el mismo rato son el mismo rato de mercado, así que cuentan una sola vez. Con menos casos de los que pide la compuerta, lo que salga es suerte y no sirve para calibrar.")}</p>
        <p class="ayuda">Donde el par contra FDUSD todavía no existía se usan las velas del par contra USDT con los costos de FDUSD, y se dice cuántas son prestadas.</p>
        ${backtest()}
        <h2>Puntaje de cada oportunidad</h2>
        <p class="ayuda">Cada una de las siete familias de indicadores se convierte en una nota de 0 a 100 y las siete juntas, con su peso, dan el puntaje de la oportunidad. Al lado van la probabilidad de ganar que dicen las operaciones del historial de ese mismo tramo y la ganancia esperada después de costos, las dos con su rango.</p>
        <p class="ayuda">${frase("**Puntaje**: qué tan buena se ve una oportunidad con lo que se sabe hoy, de 0 a 100. No es una orden ni una promesa: cuánto puntaje se le va a exigir para entrar (la exigencia), cuánto se arriesga y los frenos vienen en los pasos siguientes.")}</p>
        <p class="ayuda">Al empezar, las siete familias pesan lo mismo: los pesos los mueve la calibración, con datos de verdad. Y quedarse en USDT también puntúa, así que una oportunidad siempre se compara con no hacer nada.</p>
        ${puntaje()}
        <h2>Calibración del puntaje</h2>
        <p class="ayuda">Cuánto pesa cada familia y cuánto puntaje se le va a exigir a una oportunidad para entrar no se inventan: se ajustan con el historial y después se prueban con un tramo que nadie miró mientras se ajustaban.</p>
        <p class="ayuda">${frase("**Exigencia**: el puntaje mínimo para entrar. Mientras el modelo no esté validado, la exigencia es la alta ({n} de {maximo}) y el monto por posición queda topado: lo que el modelo promete todavía no está probado.", { n: numero((E.calibracion || {}).exigencia || 85, 0), maximo: numero(PUNTAJE_MAXIMO, 0) })}</p>
        <p class="ayuda">${frase("**Año apartado**: el último año del historial, que se deja afuera antes de ajustar un solo peso. Es el único que puede decir si esto sirve, y se gasta una sola vez: calibrar de nuevo sobre los mismos datos no vuelve a probar nada.")}</p>
        ${calibracion()}
        <h2>Registro y estado</h2>
        <p class="ayuda">Todo lo que Pilota decide queda escrito en un registro que solo crece: cada línea con los mismos campos (fecha, par, puntaje, razón, orden y resultado) y ninguna se cambia después. Y lo que Pilota sabe de sí misma —saldo, capital de referencia, modo y posiciones— vive en un archivo con huella.</p>
        <p class="ayuda">${frase("**Huella**: una marca que se saca del contenido del archivo. Si el archivo falta, la huella no cuadra o la fecha es futura, Pilota arranca frenada en modo manual y te lo dice: antes de confiar en un número hay que saber de dónde viene.")}</p>
        <p class="ayuda">La cuenta de prueba y la real llevan saldos, frenos y registro separados, y cada archivo de estado sirve solo para su cuenta.</p>
        ${estadoFirmado()}
        <h2>Tamaño de la operación</h2>
        <p class="ayuda">Cuánto se compra no se elige a ojo: primero los mínimos que pide Binance, después la reserva del 40 % que se queda siempre en USDT, después que quepan dos posiciones y, por último, que ninguna operación arriesgue más del 2 % del capital. El monto es el menor de todos esos límites.</p>
        <p class="ayuda">${frase("**Lo que se arriesga**: lo que se pierde si el precio llega al stop, con la comisión de salir incluida. Es eso lo que no pasa del 2 %, no el monto de la compra.")}</p>
        <p class="ayuda">Si con el stop de esa señal el monto queda bajo el mínimo de Binance, Pilota no abre nada y dice cuánto haría falta. Y mientras el modelo no esté validado, el monto por posición queda topado.</p>
        ${tamano()}
        <h2>Frenos</h2>
        <p class="ayuda">Los frenos no son un consejo: están en el código y Pilota no se los puede saltar. Sin apalancamiento, como máximo dos posiciones, un 5 % perdido cierra el día, cuatro pérdidas seguidas vuelven a manual, un 25 % bajo el capital de referencia no abre nada y, más abajo todavía, el piso absoluto sobre lo que aportaste cierra a mercado lo que quede abierto.</p>
        <p class="ayuda">${frase("**Capital de referencia**: el saldo más alto que has alcanzado. Sube con las ganancias y nunca baja con las pérdidas; lo único que lo mueve hacia abajo es un retiro. Los depósitos y los retiros van anotados uno por uno: un depósito no es una ganancia ni un retiro una pérdida.")}</p>
        <p class="ayuda">${frase("**Pausar**: cancela las entradas y no toca ninguna protección automática. Lo que esté abierto sigue protegido; cerrarlo es otra cosa y se pide aparte.")}</p>
        <p class="ayuda">Dos frenos miran el mercado y no tu cuenta: que la comisión maker no se pase de la que supuso el backtest y que FDUSD siga valiendo un dólar. En prueba no frenan, pero se avisan igual.</p>
        ${frenos()}
        <h2>Ejecutor de prueba</h2>
        <p class="ayuda">Con dinero ficticio y precios de verdad: Pilota pone una compra con límite en el nivel, mira minuto por minuto si el precio la llenó y, cuando se llena, le pone al tiro su protección automática. La mitad sale en el objetivo y el resto va con el stop móvil, que al moverse cancela la protección y pone otra.</p>
        <p class="ayuda">${frase("**Puesta y llenada**: una orden puesta es una orden esperando en el nivel; llenada es una compra que ya se hizo. Mientras está puesta no hay nada abierto, y si nadie la llena antes de que venza, se cancela.")}</p>
        <p class="ayuda">Antes de abrir cualquier cosa se revisa que la protección automática quepa de verdad: los tres precios en el tick de Binance, la cantidad en su paso y los tres lados sobre el mínimo en USDT. Si la mitad del objetivo no pasa ese mínimo, la posición sale entera. Cuándo entrar lo deciden el motor y los tres modos, en sus pasos.</p>
        ${ejecutor()}
        <h2>El motor y reconciliar</h2>
        <p class="ayuda">El motor es este computador: Pilota revisa cada 5 minutos y, al arrancar o al despertar, recorre las velas de 1 minuto que se perdió, aplica los stops y los objetivos que se cruzaron, repone la protección automática donde el stop móvil la movió, cancela la entrada que venció y cierra lo que quedó sin protección.</p>
        <p class="ayuda">${frase("**Ventana sin cobertura**: el rato en que nadie miró los cruces. En prueba la protección existe solo con el motor encendido, así que ese rato queda escrito en vez de taparse: es el rato en que un stop no se habría aplicado.")}</p>
        <p class="ayuda">Pilota solo trabaja con el equipo encendido. Si lo apagas o cierras la app, el motor se detiene, y al volver te dice cuánto durmió y qué pasó en ese rato.</p>
        ${motor()}
        <h2>Los tres modos</h2>
        <p class="ayuda">Quién dice «sí» a cada operación: en manual te propongo y espero; en semiautomático opero solo cuando el puntaje es claramente alto y el monto cabe en el que elegiste, y si no, te pregunto; en automático opero solo, y activarlo se confirma dos veces.</p>
        <p class="ayuda">${frase("**Propuesta**: una operación que te ofrezco con su puntaje, su razón, su monto en USDT y su stop, y que espera lo que elijas: 5, 15 o 60 minutos. Si nadie responde, vence. Siempre: no hay ningún camino donde el silencio opere.")}</p>
        <p class="ayuda">El modo lo eliges tú, pero no manda sobre nada más: el puntaje, la exigencia, el tamaño y los frenos son los mismos en los tres. Tras cualquier freno vuelvo a manual.</p>
        ${modos()}
        </details>
      </main>`;
  }
  function ajustes() {
    const idiomas = [["es", "Español"], ["en", "English"]].map(([c, n]) =>
      `<button type="button" data-idioma="${c}" aria-pressed="${i18n.idioma === c}" lang="${c}" data-sin-traducir>${n}</button>`).join("");
    const l = (E.panel && E.panel.local) || {};
    return `<h3>Idioma</h3><div class="pz-seg" role="group" aria-label="Idioma">${idiomas}</div>
      <h3>Moneda de referencia</h3>
      <p class="ayuda">Al lado del saldo y de cada monto te muestro cuánto es más o menos en tu moneda. Es solo para que te hagas una idea: la operación es en USDT siempre, el número lo pones tú y no sale de este computador.</p>
      <label class="pz-campo"><span>Tu moneda (CLP, EUR, MXN…)</span>
        <input id="local-moneda" type="text" maxlength="8" value="${esc(l.moneda || "CLP")}" autocomplete="off" spellcheck="false"></label>
      <label class="pz-campo"><span>Cuánto vale un USDT en tu moneda</span>
        <input id="local-tasa" type="number" min="0" step="1" value="${esc(l.tasa || "")}" inputmode="numeric" autocomplete="off"></label>
      <div class="pz-pie"><button type="button" class="pz-boton" id="local-guardar"${E.guardandoLocal ? " disabled" : ""}>${E.guardandoLocal ? "Guardando…" : "Guardar la referencia"}</button></div>
      <h3>Apariencia</h3>${tema.selectorHTML()}
      <h3>Tu IA</h3>${ui.filasIA({ ias: E.ias, elegida: E.config.ia })}
      ${mcpUI.html()}
      <h3>Actualizaciones</h3>${ui.filaActualizacion()}
      <h3>Acerca de</h3>${ui.acercaDe({ version: E.version, enlaces: ENLACES })}`;
  }
  function abrirAjustes() {
    E.ajustes = true;
    mcpUI.pedirEstado();   // qué IA hay en este computador y cuáles ya pueden consultar a Pilota
    pintar();
  }
  function pintar() {
    if (bv.soloIdioma) {   // primer uso: el idioma, solo (sin la app detrás ni avisos)
      raiz.innerHTML = `<div class="pantalla-idioma">${bv.html()}</div>`;
      bv.enfocar();
      return;
    }
    // Lo plegado que la persona abrió sigue abierto al volver a pintar (cada <details> con id).
    const abiertos = new Set([...raiz.querySelectorAll("details[id][open]")].map((d) => d.id));
    raiz.innerHTML = principal()
      + (bv.activa ? ui.envolver(bv.html(), { id: "t-bv", sinEsc: true }) : "")
      + (E.ajustes ? ui.dialogo({ id: "t-ajustes", titulo: "Ajustes", cuerpo: ajustes(),
        pie: '<button type="button" class="pz-boton pz-principal" data-pz-cerrar>Listo</button>' }) : "")
      + ui.capas();
    for (const id of abiertos) { const d = raiz.querySelector(`details#${CSS.escape(id)}`); if (d) d.open = true; }
    i18n.traducirDOM(raiz);
    ui.despuesDePintar();
  }

  // ── Lo que hace la persona ──
  document.addEventListener("click", async (ev) => {
    if (bv.manejarClic(ev) || ui.manejarClic(ev)) return;
    if (tema.manejarClic(ev)) return pintar();
    if (mcpUI.manejarClic(ev)) return;
    const b = ev.target.closest("button");
    if (!b) return;
    if (b.id === "abrir-ajustes") abrirAjustes();
    else if (b.id === "local-guardar") {
      // Lo que escribe la persona va en el archivo de entrada de la acción (nunca como argumento de un proceso).
      const moneda = (document.getElementById("local-moneda") || {}).value || "";
      const tasa = Number((document.getElementById("local-tasa") || {}).value);
      E.guardandoLocal = true;
      pintar();
      host.enviar("panelLocal", { moneda: moneda.trim().toUpperCase().slice(0, 8),
        tasa: isFinite(tasa) && tasa > 0 ? Math.round(tasa) : 0 });
    }
    else if (b.dataset.idioma) {
      E.config.idioma_ui = b.dataset.idioma;
      host.enviar("config", { idioma_ui: b.dataset.idioma });
      await cargarIdioma(b.dataset.idioma);
      pintar();
    } else if (b.id === "descargar") {
      E.descargando = true;
      pintar();
      host.enviar("velasDescargar", { dias: DIAS });
    } else if (b.id === "calcular-minimo") {
      E.calculando = true;
      pintar();
      host.enviar("minimoCalcular", { capital: CAPITAL_PRUEBA });
    } else if (b.id === "historial-bajar") {
      E.bajando = true;                      // «Bajar los 3 años» y «Seguir donde quedó» son lo mismo: el plan sabe dónde iba
      pintar();
      host.enviar("historialDescargar", {});
    } else if (b.id === "historial-detener") {
      host.enviar("historialDetener", {});
    } else if (b.id === "muestreo-encender") {
      E.muestreando = true;
      pintar();
      host.enviar("muestreoEncender", {});
    } else if (b.id === "muestreo-apagar") {
      host.enviar("muestreoApagar", {});
    } else if (b.id === "indicadores-calcular") {
      E.calculandoIndicadores = true;
      pintar();
      host.enviar("indicadoresEstado", {});
    } else if (b.id === "senales-calcular") {
      E.calculandoSenales = true;
      pintar();
      host.enviar("senalesEstado", {});
    } else if (b.id === "backtest-correr") {
      E.corriendo = true;             // recorrer 3 años de velas toma su rato: el botón lo dice mientras pasa
      pintar();
      host.enviar("backtestCorrer", {});
    } else if (b.id === "puntaje-calcular") {
      E.puntuando = true;
      pintar();
      host.enviar("puntajeEstado", {});
    } else if (b.id === "calibracion-correr") {
      E.calibrando = true;            // apartar, ajustar por ventanas y la prueba final: otra pasada por el historial
      pintar();
      host.enviar("calibracionCorrer", {});
    } else if (b.id === "estado-reiniciar") {
      // En prueba el saldo se reinicia con una sola confirmación y al tiro, y queda en el registro. La espera de 24 h
      // es solo para el desbloqueo del piso en real, en su paso.
      const si = await ui.confirmar({ titulo: "¿Reiniciar el saldo de prueba?",
        texto: "El saldo ficticio vuelve a {monto} y el capital de referencia parte de nuevo. Queda anotado en el registro, que no se borra.",
        valores: { monto: usdt(CAPITAL_PRUEBA) }, si: "Reiniciar", peligro: true });
      if (!si) return;
      E.reiniciando = true;
      pintar();
      host.enviar("estadoReiniciar", { saldo: CAPITAL_PRUEBA });
    } else if (b.id === "ejecutor-revisar") {
      // Mirar es aplicar: recorre las velas de 1 m que faltaban y deja los llenados, los cierres y el stop móvil donde van.
      E.ejecutando = true;
      pintar();
      host.enviar("ejecutorEstado", {});
    } else if (b.id === "motor-revisar") {
      // Una revisión ahora: reconcilia la ventana que nadie miró y deja aplicado lo que pasó en ella.
      E.revisandoMotor = true;
      pintar();
      host.enviar("motorRevisar", {});
    } else if (b.id === "motor-encender") {
      E.encendiendoMotor = true;
      pintar();
      host.enviar("motorEncender", {});
    } else if (b.id === "motor-apagar") {
      // Detener el motor no toca ninguna protección, pero en prueba la protección solo existe con el motor encendido:
      // desde aquí empieza una ventana sin cobertura.
      host.enviar("motorApagar", {});
    } else if (b.id === "frenos-pausar") {
      // «Pausar» cancela las entradas y nunca toca una protección automática: lo que está abierto sigue protegido.
      const pausado = !!(E.frenos && E.frenos.pausado);
      E.pausando = true;
      pintar();
      host.enviar("frenosPausar", { pausar: pausado ? 0 : 1 });
    } else if (b.id === "frenos-desbloquear") {
      const listo = !!(E.frenos && (((E.frenos.cuentas || []).find((c) => c.ambiente === E.frenos.activo) || {}).desbloqueo || {}).listo);
      const si = await ui.confirmar({ titulo: "¿Desbloquear el piso?",
        texto: listo
          ? "El capital de referencia pasa a ser tu saldo de ahora, así que el piso baja con él. Queda anotado en el registro, que no se borra."
          : "Pedirlo arranca una espera de 24 horas: recién después se puede aplicar, y son como máximo dos veces. Queda anotado en el registro, que no se borra.",
        si: listo ? "Desbloquear" : "Pedirlo", peligro: true });
      if (!si) return;
      E.desbloqueando = true;
      pintar();
      host.enviar("frenosDesbloquear", {});
    } else if (b.id === "modos-decidir") {
      // Una vuelta de decisión ahora: la misma que hace el motor cada 5 minutos.
      E.decidiendo = true;
      pintar();
      host.enviar("modosDecidir", {});
    } else if (b.dataset.modo) {
      // El automático se confirma dos veces: desde que se activa, nadie pregunta por cada operación.
      if (b.dataset.modo === "automatico") {
        const una = await ui.confirmar({ titulo: "¿Activar el modo automático?",
          texto: "Voy a abrir y cerrar operaciones sin preguntarte, con el mismo puntaje, el mismo tamaño y los mismos frenos. Te lo pregunto dos veces.",
          si: "Sí, sigo", peligro: true });
        if (!una) return;
        const dos = await ui.confirmar({ titulo: "¿Seguro?",
          texto: "Esta es la segunda: desde que lo actives no te pregunto por cada operación. Puedes volver a manual cuando quieras, y tras cualquier freno vuelvo solo.",
          si: "Activar el automático", peligro: true });
        if (!dos) return;
      }
      E.cambiandoModo = b.dataset.modo;
      pintar();
      host.enviar("modosElegir", { modo: b.dataset.modo, confirmaciones: b.dataset.modo === "automatico" ? 2 : 0 });
    } else if (b.dataset.propuesta) {
      // El «Sí» vuelve a calcular el tamaño y los frenos de ahora: la propuesta es una foto, no una orden guardada.
      E.respondiendo = b.dataset.propuesta;
      pintar();
      host.enviar("modosResponder", { id: b.dataset.propuesta, si: b.dataset.si === "1" ? 1 : 0 });
    } else if (b.dataset.vencimiento) {
      host.enviar("modosAjustar", { vencimiento: Number(b.dataset.vencimiento) });
    } else if (b.dataset.monto) {
      host.enviar("modosAjustar", { monto: Number(b.dataset.monto) });
    }
  });
  document.addEventListener("keydown", (ev) => { if (ui.manejarTecla(ev)) return; bv.manejarTecla(ev); });
  // La cuenta atrás de las propuestas, una vez por segundo: solo cambia ese texto (no se vuelve a pintar la pantalla).
  // Cuando se le acaba el tiempo a la última, se le pregunta a la app: la propuesta vence allá, no acá.
  setInterval(() => {
    if (!E.panel || !E.panel.esperando || bv.activa) return;
    if (panelUI.latir(raiz) === 0 && !E.pidiendoPanel) {
      E.pidiendoPanel = true;          // una sola vez: la respuesta trae lo que quedó después de vencer
      host.enviar("panelEstado", {});
    }
  }, 1000);

  // ── Lo que manda la app ──
  host.responder({
    async estado(e) {
      Object.assign(E, { config: e.config || {}, version: e.version || "" });
      await cargarIdioma();
      tema.aplicar(tema.elegir({ config: E.config.tema }));
      ui.actualizacionDisponible(e.actualizacion && e.actualizacion.hay ? e.actualizacion : null, { pintar: false });
      if (!E.iniciada) {
        E.iniciada = true;
        bv.abrir({ config: E.config, forzar: new URLSearchParams(location.search).has("bienvenida") });
        host.enviar("listaIA");
        host.enviar("velasEstado", { dias: DIAS });
        host.enviar("minimoEstado", { capital: CAPITAL_PRUEBA });
        host.enviar("historialEstado", {});
        host.enviar("muestreoEstado", {});
        host.enviar("indicadoresEstado", {});
        host.enviar("senalesEstado", {});
        host.enviar("backtestEstado", {});
        host.enviar("puntajeEstado", {});
        host.enviar("calibracionEstado", {});
        host.enviar("estadoArrancar", {});   // lo primero de todo: con qué estado arranca cada cuenta y si arranca frenada
        host.enviar("tamanoEstado", {});     // y con ese capital, cuánto se pondría en cada oportunidad de ahora
        host.enviar("frenosEstado", {});     // y si algún freno no deja abrir nada (mirarlos es aplicarlos)
        host.enviar("ejecutorEstado", {});   // y qué hay puesto o abierto en prueba (mirar también es aplicar)
        host.enviar("motorEstado", {});      // y hace cuánto fue la última revisión del motor, sin reconciliar nada
        host.enviar("modosEstado", {});      // y en qué modo quedó la cuenta y qué propuestas esperan un «Sí»
        host.enviar("panelEstado", {});      // y todo eso junto, como se ve en la pantalla principal
      }
      pintar();
    },
    // ── La pantalla principal: la banda, el saldo con su piso, los medidores, las posiciones y la mascota ──
    panelEstadoListo(r) {
      E.pidiendoPanel = false;
      if (r && r.ok && r.datos) E.panel = r.datos;
      pintar();
    },
    panelLocalListo(r) {
      E.guardandoLocal = false;
      if (r && r.ok && r.datos) {
        E.panel = r.datos;
        const l = r.datos.local || {};
        toast(l.listo
          ? Tp("Listo: te muestro la referencia en {moneda}, a {tasa} por USDT.", { moneda: l.moneda, tasa: numero(l.tasa, 0) })
          : Tp("Listo: dejo de mostrar la referencia en tu moneda."));
      } else {
        toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      }
      pintar();
    },
    velasEstadoListo(r) {
      if (r && r.ok && r.datos) E.datos = r.datos;
      pintar();
    },
    velasDescargaLista(r) {
      E.descargando = false;
      if (r && r.datos) E.datos = r.datos;
      if (r && r.ok) {
        host.enviar("indicadoresEstado", {});   // con velas nuevas, los indicadores que están en pantalla ya no valen
        host.enviar("senalesEstado", {});       // y tampoco las señales, que salen de esos indicadores
        host.enviar("puntajeEstado", {});       // ni el puntaje, que sale de las dos cosas
        toast(Tp("Listo: {n} velas nuevas.", { n: (r.datos && r.datos.descarga && r.datos.descarga.nuevas) || 0 }));
      } else {
        toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      }
      pintar();
    },
    minimoEstadoListo(r) {
      if (r && r.ok && r.datos) E.minimo = r.datos;
      pintar();
    },
    minimoCalculoListo(r) {
      E.calculando = false;
      if (r && r.datos) E.minimo = r.datos;
      if (r && r.ok) toast(Tp("Listo: puedes operar desde {monto}.", { monto: usdt(r.datos && r.datos.capital_minimo) }));
      else toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      pintar();
    },
    // ── Los dos trabajos en segundo plano: el avance llega en los eventos de progreso, el final en la respuesta ──
    historialEstadoListo(r) {
      if (r && r.ok && r.datos) E.historial = r.datos;
      pintar();
    },
    historialProgreso(e) {
      const avance = e && e.trabajo && e.trabajo.avance;
      if (!avance) return;                 // los otros eventos del trabajo no dicen nada de la descarga
      E.historial = avance;
      E.bajando = false;
      pintar();
    },
    historialListo(r) {
      E.bajando = false;
      if (r && r.datos) E.historial = r.datos;
      if (r && r.ok) {
        host.enviar("indicadoresEstado", {});   // con los 3 años, las series de 1 d recién alcanzan para la media de 200
        host.enviar("senalesEstado", {});       // y con ellas recién se sabe si el día viene al alza
        host.enviar("puntajeEstado", {});
        toast(Tp(finHistorial((r && r.datos) || {})));
      } else {
        toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      }
      pintar();
    },
    muestreoEstadoListo(r) {
      if (r && r.ok && r.datos) E.muestreo = r.datos;
      pintar();
    },
    muestreoProgreso(e) {
      const avance = e && e.trabajo && e.trabajo.avance;
      if (!avance) return;
      E.muestreo = avance;
      E.muestreando = false;
      pintar();
    },
    indicadoresEstadoListo(r) {
      E.calculandoIndicadores = false;
      if (r && r.ok && r.datos) E.indicadores = r.datos;
      pintar();
    },
    senalesEstadoListo(r) {
      E.calculandoSenales = false;
      if (r && r.ok && r.datos) E.senales = r.datos;
      pintar();
    },
    puntajeEstadoListo(r) {
      E.puntuando = false;
      if (r && r.ok && r.datos) E.puntaje = r.datos;
      pintar();
    },
    // Los tramos de puntaje se miden sobre el historial recorrido: de ahí sale con qué probabilidad gana una
    // oportunidad que puntúa como esta, así que recién después vale la pena volver a pedir el puntaje de ahora.
    puntajeTramosListos(r) {
      if (r && r.ok && r.datos) E.tramos = r.datos;
      host.enviar("puntajeEstado", {});
      pintar();
    },
    backtestEstadoListo(r) {
      if (r && r.ok && r.datos) E.backtest = r.datos;
      pintar();
    },
    backtestListo(r) {
      E.corriendo = false;
      if (r && r.datos) E.backtest = r.datos;
      if (r && r.ok) {
        host.enviar("puntajeMedir", {});    // la probabilidad de ganar sale de estas operaciones, por tramos de puntaje
        const c = (r.datos && r.datos.compuerta) || {};
        toast(c.plan_b
          ? Tp("Listo: {n} operaciones. No hay casos para todos los tramos: la compuerta tuvo que ensancharlos.", { n: numero((r.datos.resumen || {}).operaciones, 0) })
          : Tp("Listo: {n} operaciones recorridas.", { n: numero((r.datos.resumen || {}).operaciones, 0) }));
      } else {
        toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      }
      pintar();
    },
    calibracionEstadoListo(r) {
      if (r && r.ok && r.datos) E.calibracion = r.datos;
      pintar();
    },
    // Con la calibración hecha cambia con qué pesos y con qué exigencia se mira el puntaje: vale la pena volver a pedirlo.
    calibracionLista(r) {
      E.calibrando = false;
      if (r && r.datos) E.calibracion = r.datos;
      if (r && r.ok) {
        host.enviar("puntajeEstado", {});
        host.enviar("tamanoEstado", {});    // el tope del monto por posición sale del estado del modelo
        const d = r.datos || {};
        toast(d.estado === "validado"
          ? Tp("Listo: el modelo quedó validado y la exigencia es {n}.", { n: numero(d.exigencia, 0) })
          : Tp("Listo, pero el modelo quedó sin validar: la exigencia queda en {n} y los montos, topados.", { n: numero(d.exigencia, 0) }));
      } else {
        toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      }
      pintar();
    },
    // El estado firmado de las dos cuentas: si una arrancó frenada, viene con su motivo en código y acá se cuenta.
    estadoListo(r) {
      if (r && r.ok && r.datos) E.estado = r.datos;
      if (r && r.ok && r.datos && r.datos.frenado) {
        toast(Tp(MOTIVOS_ARRANQUE[r.datos.motivo] || MOTIVOS_ARRANQUE.formato_desconocido), { error: true });
      }
      pintar();
    },
    // El tamaño sale del capital de la cuenta, de los mínimos de Binance y del tope del modelo: cuando cambia cualquiera
    // de los tres (un reinicio del saldo, una calibración), vale la pena volver a pedirlo.
    tamanoEstadoListo(r) {
      if (r && r.ok && r.datos) E.tamano = r.datos;
      pintar();
    },
    // Los frenos salen del estado firmado de cada cuenta y de dos números del mercado: mirarlos es aplicarlos, así que
    // la respuesta ya viene con el modo en manual y lo nuevo anotado en el registro.
    frenosEstadoListo(r) {
      if (r && r.ok && r.datos) E.frenos = r.datos;
      pintar();
    },
    frenosListo(r) {
      E.pausando = false;
      E.desbloqueando = false;
      if (r && r.datos) E.frenos = r.datos;
      if (r && r.ok) {
        host.enviar("estadoArrancar", {});   // la pausa y el desbloqueo quedan en el estado firmado y en el registro
        host.enviar("panelEstado", {});      // y la mascota de arriba cuenta el freno que quedó puesto
        const d = r.datos || {};
        if (d.motivo_desbloqueo === "esperando") toast(Tp("Pedido: el desbloqueo del piso se puede aplicar en 24 horas."));
        else if (d.hecho) toast(Tp("Listo: el capital de referencia quedó en tu saldo de ahora, y el desbloqueo quedó en el registro."));
        else if (d.motivo_desbloqueo) toast(Tp("No hay nada que desbloquear."));
        else if (d.pausado) toast(Tp("En pausa: no abro ninguna entrada. Sigues con {n} posiciones protegidas.", { n: d.protegidas || 0 }));
        else toast(Tp("Listo: vuelvo a mirar oportunidades."));
      } else {
        toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      }
      pintar();
    },
    // El ejecutor de prueba: mirarlo es aplicarlo, así que la respuesta ya viene con lo que pasó en las velas de 1 m
    // que faltaban (llenados, cierres y el stop móvil donde quedó) y con el saldo ficticio al día.
    ejecutorEstadoListo(r) {
      E.ejecutando = false;
      const antes = E.ejecutor;
      if (r && r.ok && r.datos) E.ejecutor = r.datos;
      // Un cierre mueve el saldo, la racha y el registro: cuando eso pasa, el estado y los frenos ya no son los de antes.
      if (antes && E.ejecutor && E.ejecutor.operaciones !== antes.operaciones) {
        host.enviar("estadoArrancar", {});
        host.enviar("frenosEstado", {});
        host.enviar("panelEstado", {});
      }
      pintar();
    },
    // El motor: `motorEstado` solo dice en qué quedó (hace cuánto fue la última revisión, si está activo o dormido) y
    // `motorRevisar` reconcilia la ventana que nadie miró, así que después de él el estado y los frenos cambiaron.
    motorEstadoListo(r) {
      if (r && r.ok && r.datos) E.motor = r.datos;
      pintar();
    },
    motorRevisado(r) {
      E.revisandoMotor = false;
      if (r && r.datos) E.motor = r.datos;
      if (r && r.ok) {
        host.enviar("estadoArrancar", {});
        host.enviar("frenosEstado", {});
        host.enviar("ejecutorEstado", {});
        host.enviar("panelEstado", {});
        toast(avisoMotor((r.datos && r.datos.resumen) || {}));
      } else {
        toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      }
      pintar();
    },
    motorProgreso(e) {
      const avance = e && e.trabajo && e.trabajo.avance;
      if (!avance) return;
      E.motor = avance;
      E.encendiendoMotor = false;
      pintar();
    },
    motorListo(r) {
      E.encendiendoMotor = false;
      if (r && r.datos) E.motor = r.datos;
      if (r && r.ok) toast(Tp("Detuve el motor: mientras esté apagado nadie mira los cruces."));
      else toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      pintar();
    },
    // Los tres modos: `modosEstado` dice en cuál quedó la cuenta y qué propuestas esperan (y hace vencer la que se pasó
    // de su hora: mirar también es aplicar), y `modosDecidir` es una vuelta de decisión como la del motor.
    modosEstadoListo(r) {
      if (r && r.ok && r.datos) E.modos = r.datos;
      pintar();
    },
    modosDecidido(r) {
      E.decidiendo = false;
      if (r && r.datos) {
        E.modos = r.datos;
        E.decision = r.datos.decision || null;
      }
      if (r && r.ok) {
        const x = (r.datos && r.datos.decision) || {};
        if (x.decision === "propuesta") {
          toast(Tp("Te propuse una operación en {par}, con puntaje {n}: me dices.", { par: x.par || "", n: numero(x.puntaje, 0) }));
        } else if (x.decision === "entrada") {
          toast(Tp("Entré en {par} con puntaje {n}: {monto}.", { par: x.par || "", n: numero(x.puntaje, 0), monto: usdt(x.monto) }));
        } else {
          toast(Tp(TEXTO_DECISION[x.decision] || "No hice nada: ninguna oportunidad lo justificaba."));
        }
        host.enviar("estadoArrancar", {});
        host.enviar("frenosEstado", {});
        host.enviar("ejecutorEstado", {});   // si entró, hay una orden puesta que antes no estaba
        host.enviar("panelEstado", {});      // y la pantalla principal lo muestra todo junto
      } else {
        toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      }
      pintar();
    },
    modosRespondido(r) {
      E.respondiendo = "";
      if (r && r.datos) E.modos = r.datos;
      if (r && r.ok) {
        const d = r.datos || {};
        const c = d.motivo_respuesta || "";
        if (!d.si) toast(Tp("Listo: me quedo en USDT, y tu respuesta quedó en el registro."));
        else if (d.hecho) toast(Tp("Puse la compra con límite en el nivel, con su protección automática."));
        else {
          toast(Tp(MOTIVOS_EJECUTOR[c] || MOTIVOS_FRENOS[c] || MOTIVOS_MODO[c] || "No pude poner la orden.",
            { par: (d.respondida || {}).par || "", n: 0 }), { error: true });
        }
        host.enviar("estadoArrancar", {});
        host.enviar("frenosEstado", {});
        host.enviar("ejecutorEstado", {});
        host.enviar("panelEstado", {});
      } else {
        toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      }
      pintar();
    },
    modosElegido(r) {
      E.cambiandoModo = "";
      if (r && r.datos) E.modos = r.datos;
      if (r && r.ok && (r.datos || {}).hecho) {
        toast(Tp("Listo: quedaste en modo {modo}.", { modo: Tp(ETIQUETA_MODO[(r.datos || {}).modo] || "") }));
        host.enviar("estadoArrancar", {});   // el modo vive en el estado firmado y el cambio queda en el registro
        host.enviar("frenosEstado", {});
        host.enviar("panelEstado", {});
      } else {
        const motivo = (r && r.datos && r.datos.motivo_cambio) || (r && r.error) || "";
        toast(Tp(MOTIVOS_MODO[motivo] || MOTIVOS_FRENOS[motivo] || "No se pudo."), { error: true });
      }
      pintar();
    },
    modosAjustado(r) {
      if (r && r.datos) E.modos = r.datos;
      if (r && r.ok) {
        const d = r.datos || {};
        toast(Tp("Listo: una propuesta espera {n} min y opero sola hasta {monto}.", {
          n: numero(d.vencimiento_min, 0), monto: usdt(d.monto) }));
      } else {
        toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      }
      pintar();
    },
    estadoReinicioListo(r) {
      E.reiniciando = false;
      if (r && r.datos) E.estado = r.datos;
      if (r && r.ok) {
        host.enviar("tamanoEstado", {});
        host.enviar("frenosEstado", {});     // con el saldo y la referencia de nuevo, los frenos se miden de nuevo
        host.enviar("ejecutorEstado", {});   // y el ejecutor parte de cero: sin posiciones y sin órdenes puestas
        host.enviar("panelEstado", {});
        const esta = ((r.datos || {}).cuentas || []).find((c) => c.ambiente === (r.datos || {}).activo) || {};
        toast(Tp("Listo: el saldo de prueba quedó en {monto}, y el reinicio quedó en el registro.", { monto: usdt(esta.saldo) }));
      } else {
        toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      }
      pintar();
    },
    muestreoListo(r) {
      E.muestreando = false;
      if (r && r.datos) E.muestreo = r.datos;
      if (r && r.ok) toast(Tp("Dejé de muestrear: {n} muestras guardadas.", { n: (r.datos && r.datos.muestras) || 0 }));
      else toast(Tp(ERRORES[r && r.error] || "No se pudo."), { error: true });
      pintar();
    },
    mcpListo: (r) => mcpUI.recibir(r),   // la respuesta de mcpEstado y de mcpConectar
    iaLista(r) { E.ias = (r && r.ias) || []; pintar(); },
    iaProbada: (r) => ui.iaProbada(r),
    actualizacionRevisada: (r) => ui.actualizacionRevisada(r, { pintar: !bv.soloIdioma }),
    actualizacionProgreso: (a) => ui.actualizacionProgreso(a),
    // Los menús de la app (host-mac / host-escritorio): «Ajustes…» abre Ajustes (nunca en medio de la bienvenida); «guardar»
    // (al cerrar o salir) no tiene nada pendiente aquí.
    menu(m) { if (m && m.accion === "ajustes" && !bv.activa) abrirAjustes(); },
    _probar(f) { f(E); pintar(); },
    _pruebas: { ui, bv, i18n, faltantes, E },
  });

  // ── Vista previa en el navegador (datos ficticios de demo.json): c.responder("x", json) hace lo que la app ──
  let DEMO = null;
  const COMUNES = PiezaHost.simulacionesComunes();
  // Lo que se vería después de bajar lo que falta: todas las series al día.
  function completas(d) {
    const ventana = d.ventana || {};
    return { ...d, puede_operar: true, motivos: [], velas: (d.series || []).reduce((n, s) => n + s.esperadas, 0),
      descarga: { ...(d.descarga || {}), cuando: new Date().toISOString(), nuevas: 102, error: "" },
      series: (d.series || []).map((s) => ({ ...s, estado: "listo", motivo: "", cuantas: 0, faltan: 0, huecos: [],
        velas: s.esperadas, desde: s.desde ?? (ventana[s.temporalidad] || {}).desde, hasta: s.hasta ?? (ventana[s.temporalidad] || {}).hasta })) };
  }
  // Lo que hace minimo_viable.py con el capital que le pasan: decir si alcanza (el cálculo no se repite).
  function conCapital(m, d) {
    const capital = (d && typeof d.capital === "number") ? d.capital : 0;
    const minimo = (m && m.capital_minimo) || 0;
    return { ...m, capital, alcanza: !!minimo && capital >= minimo, falta: Math.max(0, minimo - capital) };
  }
  // Lo que hace lib_tamano con el capital de la cuenta activa: el reparto sale de su saldo (el monto de cada
  // oportunidad, igual: en la vista previa lo corta el tope del modelo sin validar).
  function tamanoDemo() {
    const d = DEMO.tamano;
    const esta = ((DEMO.estado || {}).cuentas || []).find((c) => c.ambiente === (DEMO.estado || {}).activo) || {};
    const capital = typeof esta.saldo === "number" ? esta.saldo : 0;
    const p = d.parametros || {};
    const operable = capital * (1 - p.reserva);
    const reparto = { ...d.reparto, capital, en_usdt: capital - operable, operable,
      por_posicion: operable / p.posiciones, libre: operable, disponible: operable / p.posiciones,
      riesgo_maximo: capital * p.riesgo };
    return { ...d, saldo: capital, referencia: esta.referencia ?? d.referencia, reparto,
      oportunidades: (d.oportunidades || []).map((o) => ({ ...o, tamano: { ...o.tamano, ...reparto } })) };
  }
  // Lo que hace lib_frenos.pausar: la pausa queda en el estado firmado de la cuenta activa y la máquina de estados
  // pasa a «pausado». Ninguna protección automática se toca, así que las posiciones protegidas no cambian.
  function conPausa(d, pausa) {
    const estado = pausa ? "pausado" : "operando";
    return { ...d, pausado: pausa, estado, motivo: pausa ? "pausado" : "",
      entradas: { ...d.entradas, puede: !pausa, motivo: pausa ? "pausado" : "" },
      cuentas: (d.cuentas || []).map((c) => (c.ambiente !== d.activo ? c
        : { ...c, pausado: pausa, estado, entradas: { ...c.entradas, puede: !pausa, motivo: pausa ? "pausado" : "" } })) };
  }
  // Lo que hace lib_modos.responder en la vista previa: el «Sí» pone la orden con el tamaño y los frenos de ahora, el
  // «No» se anota como quedarse en USDT, y en los dos casos la propuesta deja de esperar.
  function conRespuesta(m, d) {
    const si = !!d.si;
    const propuestas = (m.propuestas || []).map((p) => (p.id !== d.id ? p
      : { ...p, estado: si ? "aceptada" : "rechazada", espera: false, respondida_ms: Date.now() }));
    return { ...m, propuestas, esperando: propuestas.filter((p) => p.espera).length,
      puestas: si ? (m.puestas || 0) + 1 : m.puestas, hecho: true, motivo_respuesta: "", si,
      respondida: propuestas.find((p) => p.id === d.id) || null };
  }
  // Lo que hace lib_modos.elegir: un modo que no se puede usar vuelve con su motivo y nada cambia.
  function conModo(m, d) {
    const suyo = (m.modos || []).find((x) => x.modo === d.modo) || { puede: false, motivo: "modo" };
    if (!suyo.puede) return { ...m, hecho: false, motivo_cambio: suyo.motivo, pedido: d.modo };
    return { ...m, modo: d.modo, efectivo: d.modo, motivo_modo: "", hecho: true, motivo_cambio: "", pedido: d.modo,
      modos: (m.modos || []).map((x) => ({ ...x, actual: x.modo === d.modo })) };
  }
  function conAjuste(m, d) {
    return { ...m, hecho: true,
      vencimiento_min: typeof d.vencimiento === "number" ? d.vencimiento : m.vencimiento_min,
      monto: typeof d.monto === "number" ? d.monto : m.monto };
  }
  function mcpDemo() {
    return (DEMO.mcp = DEMO.mcp || { clientes: [], herramientas: [], actividad: [], escribir: false });
  }
  // Un trabajo en la vista previa: los pasos de demo.json, uno cada 500 ms, como irían llegando sus eventos de progreso. El
  // muestreo no «termina» (sigue hasta que lo detienes), así que solo el historial responde al final.
  function pasosDemo(c, clave, progreso, listo) {
    const pasos = DEMO[clave + "_pasos"] || [];
    pasos.forEach((paso, i) => c.luego(500 * (i + 1), () => {
      DEMO[clave] = paso;
      c.responder(progreso, { t: "estado", trabajo: { id: "20260210T140500-a1b2c3", tipo: clave, avance: paso } });
      if (listo && i === pasos.length - 1) c.responder(listo, { ok: true, datos: paso, error: "" });
    }));
  }
  function simular(accion, d, c) {
    if (!DEMO) return;
    switch (accion) {
      case "listo": return c.responder("estado", DEMO);
      case "config": Object.assign(DEMO.config, d); return;
      case "mcpEstado": return c.responder("mcpListo", { ok: true, ...mcpDemo() });
      case "mcpConectar": return c.luego(300, () => {
        const cliente = mcpDemo().clientes.find((x) => x.id === d.cliente);
        if (cliente) Object.assign(cliente, { conectado: d.orden === "conectar", al_dia: true });
        c.responder("mcpListo", { ok: true, ...mcpDemo(), orden: d.orden, cliente: d.cliente });
      });
      case "velasEstado": return c.responder("velasEstadoListo", { ok: true, datos: DEMO.velas });
      case "velasDescargar": return c.luego(400, () => {
        DEMO.velas = completas(DEMO.velas);
        c.responder("velasDescargaLista", { ok: true, datos: DEMO.velas, error: "" });
      });
      case "minimoEstado": return c.responder("minimoEstadoListo", { ok: true, datos: conCapital(DEMO.minimo, d) });
      case "minimoCalcular": return c.luego(400, () => {
        DEMO.minimo = DEMO.minimo_calculado;
        c.responder("minimoCalculoListo", { ok: true, datos: conCapital(DEMO.minimo, d), error: "" });
      });
      case "historialEstado": return c.responder("historialEstadoListo", { ok: true, datos: DEMO.historial });
      case "historialDescargar": return pasosDemo(c, "historial", "historialProgreso", "historialListo");
      case "historialDetener": return c.responder("historialEstadoListo",
        { ok: true, datos: { ...DEMO.historial, deteniendo: true } });
      case "muestreoEstado": return c.responder("muestreoEstadoListo", { ok: true, datos: DEMO.muestreo });
      case "muestreoEncender": return pasosDemo(c, "muestreo", "muestreoProgreso", "");
      case "muestreoApagar": return c.responder("muestreoEstadoListo",
        { ok: true, datos: (DEMO.muestreo = { ...DEMO.muestreo, estado: "detenido", corriendo: false, deteniendo: false }) });
      // Los indicadores salen de las velas guardadas: en la vista previa, a las series de 1 d todavía les faltan velas
      // (menos a BTCUSDT, la del contexto: es la que tiene más historia).
      case "indicadoresEstado": return c.responder("indicadoresEstadoListo", { ok: true, datos: DEMO.indicadores });
      // Las señales salen de esos mismos indicadores: en la vista previa, una ruptura en BTCFDUSD 4 h y un rebote en
      // ETHFDUSD 1 h; de la tendencia diaria de ETH todavía falta el historial (ETHUSDT 1 d), así que su ruptura no se mira.
      case "senalesEstado": return c.responder("senalesEstadoListo", { ok: true, datos: DEMO.senales });
      // El backtest recorre el historial guardado: en la vista previa parte sin correr y, al correrlo, da el reporte
      // completo (con un tramo que no llega a los casos que pide la compuerta, que es lo normal al empezar).
      case "backtestEstado": return c.responder("backtestEstadoListo", { ok: true, datos: DEMO.backtest });
      case "backtestCorrer": return c.luego(600, () => {
        DEMO.backtest = DEMO.backtest_corrido;
        DEMO.puntaje = DEMO.puntaje_corrido;   // con el historial recorrido, el puntaje ya tiene con qué estimar
        c.responder("backtestListo", { ok: true, datos: DEMO.backtest, error: "" });
      });
      // Medir los tramos de puntaje es otra pasada por el historial: hasta que pasa, una oportunidad trae la probabilidad
      // del tramo de la compuerta (ensanchado, plan B); con los tramos medidos ya se puede mirar por puntaje.
      case "puntajeMedir": return c.luego(400, () => c.responder("puntajeTramosListos",
        { ok: true, datos: DEMO.tramos_medidos, error: "" }));
      // El puntaje sale de los indicadores, las señales y el backtest guardado: en la vista previa, hasta recorrer el
      // historial cada oportunidad tiene puntaje pero todavía no probabilidad de ganar.
      case "puntajeEstado": return c.responder("puntajeEstadoListo", { ok: true, datos: DEMO.puntaje });
      // Calibrar aparta el último año, ajusta los pesos por ventanas y gasta la prueba final una sola vez: en la vista
      // previa parte sin calibrar y, al calibrar, queda «No validado» porque la compuerta del backtest usó el plan B.
      case "calibracionEstado": return c.responder("calibracionEstadoListo", { ok: true, datos: DEMO.calibracion });
      case "calibracionCorrer": return c.luego(600, () => {
        DEMO.calibracion = DEMO.calibracion_corrida;
        const d = DEMO.calibracion;
        // Con la calibración hecha, el puntaje se mira con esos pesos y con esa exigencia: en la app lo dice el estado
        // del modelo que escribe lib_calibracion, y acá se refleja igual.
        const modelo = { estado: d.estado, calibrado: d.calibrado, exigencia: d.exigencia, pesos: d.pesos,
          cuando: d.cuando, motivo: d.motivo };
        for (const clave of ["puntaje", "puntaje_corrido"]) {
          if (DEMO[clave]) DEMO[clave] = { ...DEMO[clave], modelo, exigencia: d.exigencia, pesos: d.pesos };
        }
        c.responder("calibracionLista", { ok: true, datos: d, error: "" });
      });
      // El estado firmado de las dos cuentas y el registro: en la vista previa la de prueba está al día y la real
      // todavía no existe (pasar a real es su propio paso). Al reiniciar, el saldo vuelve al monto de prueba y el
      // reinicio queda como una línea más del registro.
      case "estadoArrancar": return c.responder("estadoListo", { ok: true, datos: DEMO.estado });
      case "estadoReiniciar": return c.luego(300, () => {
        DEMO.estado = DEMO.estado_reiniciado;
        c.responder("estadoReinicioListo", { ok: true, datos: DEMO.estado, error: "" });
      });
      // El tamaño de cada oportunidad: en la vista previa, el capital de la cuenta de prueba alcanza, pero el modelo
      // todavía no está validado, así que el monto por posición lo corta el tope.
      case "tamanoEstado": return c.responder("tamanoEstadoListo", { ok: true, datos: tamanoDemo() });
      // Los frenos: en la vista previa ninguno está puesto (la cuenta de prueba va bien y los dos del mercado no
      // corren en prueba), así que se ve lo que cada uno vigila. «Pausar» cancela las entradas y nada más, y no hay
      // ningún piso tocado que desbloquear.
      case "frenosEstado": return c.responder("frenosEstadoListo", { ok: true, datos: DEMO.frenos });
      case "frenosPausar": return c.luego(300, () => c.responder("frenosListo",
        { ok: true, datos: (DEMO.frenos = conPausa(DEMO.frenos, !!d.pausar)), error: "" }));
      case "frenosDesbloquear": return c.luego(300, () => c.responder("frenosListo",
        { ok: true, datos: { ...DEMO.frenos, hecho: false, motivo_desbloqueo: "sin_freno" }, error: "" }));
      // El ejecutor de prueba: en la vista previa hay una entrada esperando en el nivel y una posición abierta con su
      // protección, y al revisar se llena la que esperaba (mirar es aplicar) y el stop móvil de la otra ya se movió.
      case "ejecutorEstado": return c.luego(300, () => {
        // La primera mirada muestra lo que hay; en la siguiente («Revisar los cruces») ya pasó lo que faltaba aplicar.
        if (DEMO.ejecutor_mirado && DEMO.ejecutor_revisado) DEMO.ejecutor = DEMO.ejecutor_revisado;
        DEMO.ejecutor_mirado = true;
        c.responder("ejecutorEstadoListo", { ok: true, datos: DEMO.ejecutor, error: "" });
      });
      // El motor: en la vista previa está apagado y la última revisión fue hace rato, así que al revisar se ve lo que
      // pasó mientras nadie miraba («Dormiste…»). Encenderlo deja la revisión al día, cada 5 minutos.
      case "motorEstado": return c.responder("motorEstadoListo", { ok: true, datos: DEMO.motor });
      case "motorRevisar": return c.luego(400, () => c.responder("motorRevisado",
        { ok: true, datos: (DEMO.motor = DEMO.motor_revisado || DEMO.motor), error: "" }));
      case "motorEncender": return pasosDemo(c, "motor", "motorProgreso", "");
      case "motorApagar": return c.responder("motorEstadoListo",
        { ok: true, datos: (DEMO.motor = { ...DEMO.motor, estado: "detenido", corriendo: false, deteniendo: false,
          activo: false, dormido: false }) });
      // Los tres modos: en la vista previa la cuenta está en manual (sin calibración los otros dos quedan apagados) y
      // hay una propuesta esperando. Al mirar ahora, la mejor oportunidad no llega a la exigencia: no propongo nada
      // nuevo y la que espera sigue esperando hasta que la respondas o venza.
      case "modosEstado": return c.responder("modosEstadoListo", { ok: true, datos: DEMO.modos });
      case "modosDecidir": return c.luego(400, () => c.responder("modosDecidido",
        { ok: true, datos: (DEMO.modos = { ...DEMO.modos, decision: DEMO.modos_decision || null }), error: "" }));
      case "modosResponder": return c.luego(300, () => c.responder("modosRespondido",
        { ok: true, datos: (DEMO.modos = conRespuesta(DEMO.modos, d)), error: "" }));
      case "modosElegir": return c.luego(200, () => c.responder("modosElegido",
        { ok: true, datos: (DEMO.modos = conModo(DEMO.modos, d)), error: "" }));
      case "modosAjustar": return c.responder("modosAjustado",
        { ok: true, datos: (DEMO.modos = conAjuste(DEMO.modos, d)), error: "" });
      // La pantalla principal: en la vista previa, la cuenta de prueba con una propuesta esperando (su cuenta atrás
      // corre sola), una entrada puesta, los dos medidores bajo la exigencia y el motor dormido. Guardar la moneda de
      // referencia solo cambia esa línea: la operación sigue siendo en USDT.
      case "panelEstado": return c.responder("panelEstadoListo", { ok: true, datos: DEMO.panel });
      case "panelLocal": return c.luego(200, () => {
        const tasa = typeof d.tasa === "number" ? d.tasa : 0;
        const local = { ...DEMO.panel.local, moneda: d.moneda || DEMO.panel.local.moneda, tasa, listo: tasa > 0 };
        DEMO.panel = { ...DEMO.panel, local };
        c.responder("panelLocalListo", { ok: true, datos: DEMO.panel, error: "" });
      });
      case "listaIA": return c.responder("iaLista", { ias: DEMO.ias, elegida: DEMO.config.ia });
      default: return COMUNES[accion] ? COMUNES[accion](d, c) : undefined;
    }
  }

  async function iniciar() {
    if (host.plataforma === "web") {
      try { DEMO = await (await fetch("demo.json")).json(); } catch { DEMO = { config: {} }; }
      // ?bienvenida: el primer uso, desde el idioma.
      if (new URLSearchParams(location.search).has("bienvenida")) DEMO.config.idioma_ui = "";
    }
    host.enviar("listo");
  }
  iniciar();
})();
