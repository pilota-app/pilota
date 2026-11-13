# Pilota — guía para trabajar en el proyecto

> Para personas y para cualquier IA de programación (Claude Code, Codex, Gemini/Antigravity…). `CLAUDE.md` y `GEMINI.md` solo
> importan este archivo: la guía es una sola.

<!-- La app: en un párrafo, qué es Pilota, para quién y qué hace con la IA de la persona (si la usa). Sin promesas que la app
no cumpla todavía. Borra este comentario al escribirlo. -->

**Principios que no se negocian**

<!-- La app: de 4 a 7 principios propios, numerados y en negrita al comienzo, cada uno con su porqué. Los que comparte toda la
familia (ajústalos a la app): los datos son de la persona y viven en su computador; la IA es la de la persona, con su cuenta, sin
herramientas ni memoria, y ve lo mínimo; todo lo que viene de afuera se valida y se escapa; gratis y abierto (AGPL-3.0), sin
cuentas ni publicidad; nada personal en el código (Ana Pérez, Matías Soto). Borra este comentario al escribirlos. -->

## Mapa del repo

| Ruta | Qué es |
|---|---|
| `bin/` | Python **solo biblioteca estándar**: lo que corren las apps. El último argumento siempre es el JSON de salida; lo que escribe la persona llega en un JSON de entrada, nunca como argumento. |
| `ui/` | La interfaz única (`index.html` con CSP, `app.js`, `panel.js` —la pantalla principal—, `app.css`), las piezas de interfaz (ver «Piezas») e `idiomas/en.json`. |
| `escritorio/` | App de escritorio (Rust + Tauri, pieza «host-tauri»): lo propio en `src/main.rs` (y los módulos que sume la app); `src/pieza/` es de la pieza. `Cargo.toml`, `tauri.conf.json`, `Info.plist` y `pruebas/arranque.sh` los genera Pieza. |
| `docs/` | La página pública (GitHub Pages). |
| `pruebas/` | `correr.sh` (todo lo que revisa GitHub en cada cambio) y las pruebas. |
| `herramientas/` | `revisar_privacidad.sh` (antes de cada commit), `empaquetar.sh` (arma la app de Mac). |
| `app.json`, `piezas.json`, `acciones.json` | **Pieza** (ver «Piezas»): `app.json` describe la app (id, nombre, versión, datos, plataformas, config y sus acciones); `piezas.json` y `acciones.json` los escribe `pieza.py`. |
| `CHANGELOG.md` | Lo que cambia para quien usa la app, en palabras simples (ver «Lo que rodea a un cambio»). |
| `bin/lib_datos.py` | Los datos de mercado: el cliente de la API pública de Binance (lista blanca, límites y reintentos), las velas guardadas y la revisión de continuidad. No es una acción. |
| `bin/velas.py` | La acción de las velas: `estado` (qué hay y qué falta, sin tocar la red) y `descargar` (baja las velas cerradas que falten). |
| `bin/minimo_viable.py` | El capital mínimo viable: `estado` (el último cálculo guardado, sin red) y `calcular` (pide a Binance los filtros vigentes de los pares que se operan y saca desde cuánto se puede operar). |
| `bin/lib_trabajo.py` | El puente con la pieza «trabajos» para los dos trabajos largos: el proyecto, el plan en disco, el estado real (vivo, interrumpido), «Detener» y los errores de Binance como código. No es una acción. |
| `bin/historial.py` | El trabajo de los 3 años: `estado`, `descargar` (empezar y «Seguir donde quedó» son lo mismo) y `detener`. |
| `bin/muestreo.py` | El trabajo del muestreo: `estado`, `encender` (cada 5 min: el libro, los últimos trades y las velas de 1 m) y `apagar`. |
| `bin/lib_indicadores.py` | Tendencia e impulso: las cuentas de siempre sobre listas de números (`sma`, `ema`, `rsi`, `macd`, `adx`) y el valor de ahora de cada serie (`valores`, `de_serie`, `estado`, con el gancho `extra`). No es una acción. |
| `bin/lib_indicadores_mercado.py` | Las otras cinco familias: volatilidad (`bollinger`, `atr`), volumen (`volumen_relativo`, `obv`), estructura (`rupturas`), contexto (`contexto`: BTC en 1 d) y costo (`costo`: comisión, spread y conversión). Arma el estado completo (`estado`). No es una acción. |
| `bin/indicadores.py` | La acción de los indicadores: `estado` (las siete familias sobre lo guardado, sin tocar la red, y lo deja escrito). |
| `bin/lib_estrategias.py` | Las tres estrategias (`ruptura`, `rebote` y quedarse en USDT) y el filtro de BTC (`filtro_btc`): las señales crudas vela por vela (`de_velas`, con `al_alza_en` y `filtro_en`) y las de ahora (`de_indicadores`, `estado`). No es una acción. |
| `bin/senales.py` | La acción de las señales: `estado` (las tres estrategias sobre los indicadores de lo guardado, sin tocar la red, y lo deja escrito). |
| `bin/lib_costos.py` | Lo que cuesta entrar y salir (comisión por lado, conversión USDT↔FDUSD y la diferencia entre compra y venta: `resultado`) y el modelo de spread y de no llenado del backtest (`modelo`, `spread_de`, `margen_llenado`, `llena`). No es una acción. |
| `bin/backtest.py` | El backtest de las señales crudas: el empalme con el par de USDT (`empalmar`), el recorrido (`senales_de`, `seguir`, `recorrer`), la compuerta de casos (`sin_solapar`, `compuerta`), el reporte (`resumen`, `curva`, `comprar_y_esperar`) y las acciones `estado` y `correr`. |
| `bin/lib_puntaje.py` | El puntaje de 0 a 100: la nota de cada familia con sus parámetros y su razón corta (`rampa`, `banda`, `tendencia`, `impulso`, `volatilidad`, `volumen`, `estructura`, `contexto`, `costo`, `RAZONES`, `familias`), las siete juntas en un puntaje con su desglose y los pesos renormalizados cuando falta una familia que no es clave (`puntaje_de`, `PESOS_BASE`, `FAMILIAS_CLAVE`), el estado del modelo con su exigencia (`modelo`, `MODELO_SIN_CALIBRAR`, `EXIGENCIA_SIN_CALIBRAR`), la probabilidad de ganar con su rango (`wilson`, `evidencia`) y la ganancia esperada después de costos (`ganancia`), los tramos de puntaje medidos sobre el historial (`TRAMOS_PUNTAJE`, `bordes_de`, `tramos_de_puntaje`, `de_tramo`, `seguir`, `medir`, `tramos_guardados`), el puntaje de quedarse en USDT en la misma escala (`quedarse`, `mejor_de`), el supuesto de las velas sin 1 m marcado (`supuestos`) y las dos capas (`de_velas`, `estado`). No es una acción. |
| `bin/lib_resolucion.py` | La regla de las velas sin 1 m, en un solo lugar: qué tocó cada vela (`toco`, `trozo_de`, `en_minutos`), la vela que tocó los dos niveles resuelta con el supuesto conservador o con las velas de 1 m, con su etiqueta (`de_ambigua`, `resolver`, `SUPUESTO_SIN_1M`, `CLARA`, `CON_1M`, `SIN_1M`), la operación completa (`cerrar`, `comparar`) y la validación contra los días que sí tienen 1 m (`validar`, `parametros`). No es una acción. |
| `bin/puntaje.py` | Las dos acciones del puntaje: `estado` (puntúa las señales crudas de ahora sobre lo guardado, sin tocar la red, y lo deja escrito) y `medir` (recorre el historial puntuando cada señal antes de seguirla y deja los tramos de puntaje con su probabilidad y su ganancia esperada). |
| `bin/lib_calibracion.py` | La calibración del puntaje: el año que se aparta antes de mirar un peso (`apartar`, `DIAS_APARTADOS`, `DIAS_PRUEBA_NUEVA`), las ventanas de ajustar y probar (`ventanas_de`, `pools`), el historial recorrido una sola vez con las notas pegadas a cada operación (`recorrido`, `notas_de`, `puntaje_con`, `clave_de`), los pesos y la exigencia por vueltas contadas (`ajustar`, `mejor_exigencia`, `medir_puntuadas`, `PESOS_CANDIDATOS`, `EXIGENCIAS`, `VUELTAS_MAXIMAS`), el backtest de nuevo por el gancho de siempre (`gancho`, `correr_con`), la prueba final con el criterio escrito antes (`criterio`, `aprobar`, `CRITERIO_*`), el estado del modelo con su tope de monto (`calibrar`, `modelo`, `VALIDADO`, `NO_VALIDADO`, `TOPE_NO_VALIDADO`) y lo guardado (`guardada`, `escribir`, `sin_calibrar`). No es una acción. |
| `bin/calibrar.py` | Las dos acciones de la calibración: `estado` (la última calibración guardada, sin calibrar ni recorrer nada) y `correr` (la pasada lenta: apartar, ajustar por ventanas, el re-backtest con exigencia y la prueba final, y lo deja escrito). |
| `bin/lib_registro.py` | El registro que no se borra: los campos fijos de cada línea y sus reglas (`CAMPOS`, `RAZONES`, `CAMPOS_ORDEN`, `CAMPOS_RESULTADO`, `CODIGO`, `linea`, `revisar`), dónde vive (`carpeta`, `ruta`, `anios`), agregar al final (`anotar`) y leer (`leer`, `ultimas`, `primera`, `cuantas`, `resumen`). No es una acción. |
| `bin/lib_estado.py` | El estado firmado, separado para prueba y real: la huella (`huella`), el cuerpo con sus campos (`CAMPOS`, `cuerpo_de`) y cómo se mueve (`nuevo`, `con_saldo`, `con_aporte`, `con_modo`, `sanear`, `legible`), guardar y cargar con el arranque frenado (`guardar`, `cargar`, `MOTIVOS_FRENADO`, `MODOS`, `MODO_FRENADO`) y lo que hace la app (`activo`, `arrancar`, `reiniciar`, `estado`, `parametros`). No es una acción. |
| `bin/estado.py` | Las dos acciones del estado: `arrancar` (lo primero al abrir la app: las dos cuentas con su arranque, y el frenado queda en el registro) y `reiniciar` (el saldo de prueba de nuevo en el monto elegido). |
| `bin/lib_tamano.py` | El tamaño de una operación en el orden fijo: el mínimo de Binance con ese stop (`cantidad_minima`, `minimo_de`, `bajar_al_paso`), la reserva y las dos posiciones (`reparto`, `parte_del_capital`), el riesgo del 2 % y el monto con su límite que manda y el tope del modelo sin validar (`tamano`, `RECHAZOS`, `LIMITES`, `comisiones`, `costo_de`), y el tamaño de ahora de cada oportunidad puntuada (`filtros_de`, `posiciones_de`, `de_opcion`, `mejor_de`, `estado`, `escribir`, `guardado`). No es una acción. |
| `bin/tamano.py` | La acción del tamaño: `estado` (cuánto se compraría ahora en cada oportunidad, sobre lo guardado y sin tocar la red, y lo deja escrito). |
| `bin/lib_frenos.py` | Los frenos y la máquina de estados: los ocho frenos con sus números (`FRENOS`, `EFECTOS`, `SOLO_REAL`, `APALANCAMIENTO`, `POSICIONES`, `PERDIDA_DIARIA`, `RACHA_MAXIMA`, `PISO`, `PISO_ABSOLUTO`, `FDUSD_MINIMO`), el día del mercado (`fecha_de`, `fin_del_dia_ms`, `al_dia`, `dia_de`), los dos pisos (`piso_de`), los dos frenos de mercado (`comision_de`, `fdusd_de`, `mercado_de`), los de una cuenta con el estado en que la dejan (`de_cuenta`, `ESTADOS`, `desbloqueo_de`), la puerta del ejecutor (`permite_entrada`, `revisar_orden`, `RECHAZOS`), lo que mueven un cierre y un aporte (`con_cierre`, `con_aporte`) y lo que hace la app (`aplicar`, `revisar`, `pausar`, `desbloquear`, `aportar`, `estado`, `parametros`, `escribir`, `guardado`). No es una acción. |
| `bin/frenos.py` | Las tres acciones de los frenos: `estado` (los revisa, los aplica y los deja escritos: mirarlos es aplicarlos), `pausar` (cancela las entradas sin tocar ninguna protección) y `desbloquear` (el desbloqueo del piso, con su espera de 24 h en real). |
| `bin/lib_ejecutor_prueba.py` | El ejecutor del modo prueba, con el mismo contrato que va a tener el conector real (ver esa sección): los ids deterministas con prefijo propio y lo ajeno que no se toca (`PREFIJO`, `id_de`, `es_nuestro`, `nuestras`, `ajenas`), la revisión de que la protección automática cabe en los filtros de Binance de cada lado (`cabe`, `mitad_de`, `_pata`), poner la entrada solo con lo que dijeron el tamaño y los frenos (`entrar`, `RECHAZOS`), los cruces sobre las velas de 1 m con su protección simulada, el stop móvil que la repone y las propuestas que vencen (`seguir`, `revisar`, `cerrar`, `neto_de`), el rato sin velas que cuiden (`cobertura_de`, `GRACIA_COBERTURA_MS`) y lo que hace la app (`estado`, `parametros`, `escribir`, `guardado`). No es una acción. |
| `bin/operar_prueba.py` | La acción del ejecutor de prueba: `estado` (recorre las velas de 1 m que faltaban, deja aplicado lo que pasó —llenados, vencimientos, stops, objetivos y el stop móvil— y lo deja escrito: mirar es aplicar). |
| `bin/lib_reconciliar.py` | El motor y la reconciliación: el plan con la última revisión y las ventanas sin cobertura (`armar`, `ventanas_de`, `ruta_motor`), el rato que nadie miró (`ventana`, `GRACIA_MS`), lo que pasó en ese rato según el registro (`lineas_de`, `cuentas_de`, `CLAVES`), lo huérfano que se cierra (`huerfanas_de`, `cerrar_huerfano`), la ventana sin cobertura escrita (`anotar_ventana`), una revisión completa con su gancho para los modos (`reconciliar`, `decidir`) y lo que lee la pantalla (`vista`, `estado`, `parametros`, `MOTIVOS`). No es una acción. |
| `bin/motor.py` | Las cuatro acciones del motor: `estado` (hace cuánto fue la última revisión, sin reconciliar), `revisar` (una revisión ahora: reconcilia la ventana que nadie miró y los modos deciden), `encender` (el trabajo cada 5 min) y `apagar`. |
| `bin/lib_modos.py` | Los tres modos y las propuestas que vencen: los ajustes de la persona y las propuestas en disco (`ajustes`, `VENCIMIENTOS`, `MONTOS`, `guardado`, `guardar`), una propuesta con su id determinista y su hora de vencimiento (`id_de`, `propuesta_de`, `opcion_de`, `proponer`, `vigentes`, `caducar`, `vencidas_hoy`), qué modo se puede usar (`permitido`, `SIN_CALIBRACION`, `CONFIRMACIONES`, `claramente_alto`, `MARGEN_CLARO`), la vuelta de decisión que engancha el motor (`decidir`, `DECISIONES`) y lo que hace la persona (`responder`, `elegir`, `ajustar`, `estado`, `parametros`). No es una acción. |
| `bin/propuestas.py` | Las cinco acciones de los modos: `estado` (en qué modo quedó, qué propuestas esperan y cuántas vencieron hoy; mirar también es aplicar), `decidir` (una vuelta de decisión ahora, la misma del motor), `responder` (el «Sí» o el «No» a una propuesta), `modo` (el modo, con las dos confirmaciones del automático) y `ajustar` (cuánto espera una propuesta y hasta cuánto opera solo el semiautomático). |
| `bin/lib_panel.py` | La pantalla principal en un solo lugar: el saldo con su línea del piso (`saldo_de`), los medidores de puntaje y exigencia por par (`medidor_de`), las posiciones como se ven (`posicion_de`), la línea diaria (`dia_de`), lo que cuenta la mascota (`mascota_de`, `ANIMOS`, `CUENTOS`), la moneda de referencia que escribe la persona (`local`, `guardar_local`, `MONEDA_LOCAL`) y todo junto (`estado`, `MOTIVOS`, `parametros`). No decide ni opera nada. No es una acción. |
| `bin/panel.py` | Las dos acciones de la pantalla principal: `estado` (todo lo que se ve al abrir, sin tocar la red) y `local` (la moneda de referencia y a cuánto está un USDT en ella). |
| `ui/panel.js` | La pantalla principal dibujada (`PilotaPanel.crear`): la mascota y su línea diaria, el saldo con su piso y su referencia local, los medidores, las posiciones, las propuestas con su cuenta atrás (`latir`), el motor y el registro. Las etiquetas que ya existen se las pasa `ui/app.js`. |
| `bin/lib_perfiles.py` | Los perfiles (`PERFILES`; se ofrecen los de `ORDEN`: holding y rotación; `RETIRADOS` los de señales; `SUGERIDO`): qué temporalidades mira cada uno, la ganancia/riesgo mínima, el riesgo por operación y cuántas posiciones (`acepta`, `relacion`, `tamano`), y las velas de 5 m armadas con las de 1 m (`agrupar`, `serie`). No es una acción. |
| `bin/lib_piloto.py` | El robot en vivo, solo en prueba: empezar con un perfil y un monto (`empezar`, `detener`), la vuelta que engancha el motor (`decidir`: con perfil opera el perfil, sin perfil o en real deciden los tres modos), las señales de la última vela cerrada (`senales_de_ahora`), el holding por partes y lo que lee la pantalla (`estado`, `movimientos`). No es una acción. |
| `bin/vivo.py` | Las acciones del robot en vivo: `estado`, `empezar` (perfil y monto), `detener`, `grafico` (velas, marcas de compra y venta y líneas de lo abierto) y el trabajo `encender` (el flujo de Binance al segundo: guarda cada vela de 1 m al cerrar y revisa en ese mismo instante). |
| `bin/lib_flujo.py` | El flujo de Binance en vivo por WebSocket, solo biblioteca estándar: un solo destino (`HOST`, `PUERTO`, `ruta_de`), el saludo revisado, marcos con tope, ping/pong, silencio que corta (`SILENCIO_MAXIMO`) y cada mensaje revisado (`vela_de`). Solo lectura. No es una acción. |
| `bin/lib_radar.py` | Qué está esperando el robot: por par y temporalidad del perfil, el gatillo de cada estrategia (a qué precio tendría que cerrar la vela), cuánto falta (`distancia`, `cerca`), la operación posible (entrada, stop, objetivo y `rr`, y si el perfil la acepta) y la historia de esa misma jugada (`estadisticas`, `agrupar`, `al_dia`: ganadas de cuántas y lo que dejó en promedio). Lo escribe el flujo en vivo en `mercado/radar.json`. No decide nada. No es una acción. |
| `bin/lib_universo.py` | Las ocho monedas del robot en prueba contra USDT (`lib_datos.UNIVERSO`: BTC, ETH, BNB, SOL, XRP, ADA, TRX y DOGE): sus mínimos de Binance (`filtros`, una vez al día en `mercado/universo.json`), sus velas (`preparar`: 3 años de 1 d, 4 h y 1 h y 3 días de 1 m) y sus costos (`comisiones_de`: contra USDT no hay conversión). Lo corre el flujo en vivo en segundo plano. No es una acción. |
| `bin/lib_rotacion.py` | La rotación: la fuerza de cada moneda (`fuerza`: lo que subió en 30 días dividido por cuánto se movió), el ranking, a cuáles pasarse (`elegir`, con margen para no cambiar por nada) y la misma regla sobre el pasado (`simular`). Pura: no lee el disco. No es una acción. |
| `bin/lib_holding.py` | Las formas de holdear: comprar por partes y guardar, con una variante cada una (`reparto`, `partes`, `descuento`, `rebalanceo`, `cosecha`). `paso` es un día y lo usan igual la comparación (`simular`) y el robot en vivo (`lib_piloto._vuelta_holding_v`). Puro. No es una acción. |
| `bin/simular.py` | Las acciones de «Comparar»: `estado`, `correr` (todos los perfiles con un monto y un período) y `mapa` (el mapa de inicios, `simularMapa`). |
| `bin/lib_tendencia.py` | Seguir la tendencia y ajustar el tamaño por volatilidad (`en_tendencia`, `volatilidad`, `tamano`, `pesos_tendencia`, `pesos_rotacion`) y su recorrido por el pasado día por día (`simular`). **No lo usa ningún perfil**: no pasó la prueba con datos reales (ver «Los perfiles y el robot en vivo»). Queda para probarlo de nuevo con datos nuevos. Puro. No es una acción. |
| `bin/lib_candado.py` | Una sola cosa a la vez entre procesos: un solo trabajo de cada tipo (`unico`, `YaCorriendo`), una revisión a la vez (`candado`) y el trabajo que quedó sin app (`huerfano`). No es una acción. |
| `ui/grafico.js` | El gráfico de velas en vivo en un `<canvas>` (`PilotaGrafico.crear`): 1 m, 5 m, 1 h y 4 h, Bollinger, medias, volumen y RSI con un botón, las flechas de compra y venta, las líneas de entrada, stop y objetivo, el precio que se mueve cada segundo y el destello de color de cada operación. |
| `bin/lib_simulacion.py` | «Si hubiera puesto X»: el historial como una cartera con tamaño y frenos (`cartera`, con `perfil` y sus `movimientos`), comprar BTC y esperar, el holding por partes (`holding`), las señales sobre 5 m (`ops_rapidas`), la rotación (`rotacion`) y los perfiles que se ofrecen lado a lado (`comparar`). No es una acción (la corre `bin/simular.py`). |
| `ui/vivo.js` | Las pestañas «En vivo», «Comparar» (con la película de movimientos) y «Movimientos» (`PilotaVivo.crear`). Los movimientos se cuentan en frases completas desde los códigos del registro. |
| `ui/centro.js` | Las pestañas de arriba y «Dinero real» (requisitos, llave de Binance e interruptor). |
<!-- La app: suma una fila por cada carpeta o archivo propio importante (qué es y qué hay adentro), sin repetir lo de arriba. -->

## Los datos de mercado

Todo lo que Pilota calcula sale de velas **cerradas** de Binance. Los pares son los dos que se operan (`BTCFDUSD`, `ETHFDUSD`) y
los dos que dan más historia y el filtro de BTC (`BTCUSDT`, `ETHUSDT`), cada uno en `1h`, `4h` y `1d`: 12 series.

A eso se suma, solo de los dos pares que se operan, la serie de **1 m** de los últimos 30 días (`lib_datos.MINUTO`): es la que va a
ver los cruces de stop y objetivo en el modo prueba y la que se recorre al despertar. Es una ventana que se corre: lo anterior se
suelta (`bajar_tramo(..., recortar_desde=…)`).

| Dónde (en los datos de la app, nunca en la carpeta de la persona) | Qué |
|---|---|
| `mercado/velas/<PAR>-<TEMPORALIDAD>.json` | `{"formato": 1, "par", "temporalidad", "paso_ms", "guardado", "velas": [[apertura_ms, abre, alto, bajo, cierra, volumen], …]}`, ordenadas, sin repetidas y sin la vela en curso. `<TEMPORALIDAD>` es `1h`, `4h`, `1d` y, solo en `BTCFDUSD` y `ETHFDUSD`, `1m`. |
| `mercado/estado.json` | Lo que devuelve `lib_datos.estado()`: cada serie con sus velas, sus huecos y su motivo, y `puede_operar`. Mientras falte historia, este archivo es la explicación de por qué Pilota no opera. |
| `mercado/minimo.json` | Lo que devuelve `minimo_viable.medir()`: los filtros vigentes de `BTCFDUSD` y `ETHFDUSD`, el mínimo por posición y el capital mínimo viable, con la hora del cálculo. |
| `mercado/indicadores.json` | Lo que devuelve `lib_indicadores_mercado.estado()`: cada serie con su última vela cerrada y sus cinco familias (tendencia, impulso, volatilidad, volumen, estructura) o el motivo por el que no se calcula, más `contexto` (BTC en 1 d) y `costo` (comisión, spread y conversión), con la hora del cálculo. |
| `mercado/senales.json` | Lo que devuelve `lib_estrategias.estado()`: las cuatro series de entrada (los dos pares operados en 1 h y 4 h) con las señales crudas de cada una o su motivo, el filtro de BTC, la opción de quedarse en USDT y los parámetros con los que se miró, con la hora del cálculo. |
| `mercado/backtest.json` | Lo que devuelve `backtest.correr()`: el modelo de costos, la ventana recorrida, las cuatro series de entrada con sus números, los empalmes, el resumen, la compuerta de casos con su plan, el reporte contra quedarse en USDT y contra comprar y esperar, la prueba de sensibilidad, los supuestos marcados y las últimas operaciones de ejemplo. Antes del primero, `corrido` es falso y no hay ningún número. |
| `mercado/puntaje.json` | Lo que devuelve `lib_puntaje.estado()`: las cuatro series de entrada con sus oportunidades puntuadas (las siete notas con su peso, la parte que le tocó a cada una, sus parámetros y su razón, el puntaje, la probabilidad de ganar de su tramo con su rango y de dónde salió, y la ganancia esperada después de costos), el puntaje de quedarse en USDT, cuál es la mejor opción, el estado del modelo con su exigencia (`modelo`, `exigencia`), los tramos de puntaje medidos (`tramos`, `medicion`) y los supuestos marcados (el de las velas sin 1 m, el spread y el empalme), con la hora del cálculo. |
| `mercado/tramos.json` | Lo que devuelve `lib_puntaje.medir()`: los cinco tramos de puntaje (`TRAMOS_PUNTAJE`) con sus operaciones, sus casos, con qué frecuencia ganaron y su rango (Wilson), lo que dejó cada tramo después de costos con el rango de su esperada, el resumen del recorrido, las cuatro series con cuántas señales se puntuaron y los supuestos marcados (la regla de las velas sin 1 m con su validación y la etiqueta de cada operación). Antes de la primera medición, `corrido` es falso y los cinco tramos están en cero. |
| `mercado/calibracion.json` | Lo que devuelve `lib_calibracion.calibrar()`: el estado del modelo (`estado`, `calibrado`, `exigencia`, `pesos`, `tope`, `topado`, `motivo`), el tramo apartado y las ventanas con las que se ajustó, las vueltas que se dieron con sus cambios (`ajuste`), el backtest de nuevo con puntaje y exigencia (`rebacktest`), la prueba final con su ventana (`prueba_final`, `hecha`), la aprobación revisión por revisión contra el criterio escrito antes (`aprobacion`), el reporte contra quedarse en USDT y contra comprar BTC y esperar (`referencias`), los supuestos marcados y los parámetros. Antes de la primera calibración, `corrido` es falso, el estado es `sin_calibrar` y la exigencia es 85. |
| `mercado/tamano.json` | Lo que devuelve `lib_tamano.estado()`: el reparto del capital de la cuenta activa (la reserva, las dos posiciones, lo comprometido y el riesgo máximo), el estado del modelo con su tope, los mínimos de Binance que se usaron, y cada oportunidad puntuada con su monto en USDT, su cantidad, lo que se arriesga, cuál de los tres límites mandó (`manda`) y, si no hay orden, su motivo en código. |
| `mercado/comisiones.json` | `{"maker", "taker"}`: las comisiones que lea de la API el conector real (su propio paso). Mientras no exista, la cuenta usa las supuestas de `minimo_viable.COMISIONES_SUPUESTAS` y lo dice en pantalla (`comisiones.origen`). |
| `mercado/historial.json` | El plan de los 3 años (`historial.armar()`): las 12 series con `inicio`, `fin`, `siguiente` (desde dónde seguir), sus velas, sus pedidos, sus `huecos` (si quedó `continua`), y en qué quedó el trabajo. |
| `mercado/muestreo.json` | El plan del muestreo (`muestreo.armar()`): cómo van las velas de 1 m de cada par, cuántas muestras se llevan, la última, cuándo viene la próxima, cuántas vueltas seguidas salieron mal (`fallos`) y las ventanas que quedaron sin muestras (`sin_cobertura`: `{"desde", "hasta", "ciclos", "error", "abierto"}`, las últimas `muestreo.HUECOS_GUARDADOS`). |
| `mercado/muestras/<AAAA-MM>.jsonl` | Una línea por muestra: `{"ms", "par", "compra", "compra_cantidad", "venta", "venta_cantidad", "spread", "spread_relativo", "trades": [[ms, precio, cantidad, compra], …]}`. Se agrega al final y **no se reescribe nunca**. |

Reglas que no se cambian sin pensarlo dos veces (`bin/lib_datos.py`):
- **Solo velas cerradas.** La vela en curso no se guarda: sus valores todavía pueden cambiar.
- **La red solo va a `api.binance.com` por https**, solo a las rutas de `RUTAS`, sin redirecciones y sin los proxies del entorno.
  Mientras Pilota no tenga la pieza «Red», el candado vive en `pedir_api`. La única otra salida es el flujo público de velas en
  vivo (`bin/lib_flujo.py`): `stream.binance.com:9443` por TLS, solo la ruta de velas de los pares conocidos (`lib_flujo.PARES`: los dos contra FDUSD y
  las ocho contra USDT), solo lectura.
- **Los límites de la API se respetan**: ante 429 o 418 se espera lo que pide Binance (`Retry-After`, tope `ESPERA_MAXIMA`) y se
  reintenta hasta `INTENTOS` veces; igual ante un 5xx o un corte de red.
- **Continuidad antes de calcular**: `huecos()` revisa paso por paso (hora por hora en `1h`). Una serie con hoyos, corta o
  atrasada deja `puede_operar` en falso con su motivo (`sin_datos`, `faltan_velas`, `huecos`, `atrasado`); la interfaz traduce
  esos códigos, nunca muestra texto que venga de Binance.
- **Lo que se guarda no se redondea para mostrarlo.** `Binance.libro()` devuelve `spread_relativo` entero: en un par líquido es
  del orden de 1e-6 y redondearlo lo borra (3,16e-06 en vez de 3,157886426614667e-06). Es la base del modelo de spread y de no
  llenado del backtest; el redondeo vive en la pantalla (`porcentaje()` en `ui/app.js`).
- Las pruebas **no salen a la red**: `pruebas/test_app.py` reemplaza la API por `ApiFalsa` (velas inventadas) y el `dormir` del
  cliente, así se prueba la espera sin esperar.

## El capital mínimo viable

Antes de operar, Pilota dice desde cuánto se puede operar de verdad (`bin/minimo_viable.py`). La cuenta sigue el mismo orden que
el tamaño de una operación y se hace con los filtros que Binance tiene en ese momento (`/api/v3/exchangeInfo`):

1. **Los mínimos de Binance** (tick, paso de cantidad, cantidad mínima y nocional mínimo): la cantidad tiene que servir para la
   compra y para **las dos patas de la protección automática**. La pata del stop vale menos USDT, así que es la que manda.
2. **La reserva**: el 40 % del capital se queda en USDT. 3. **Dos posiciones** a la vez. 4. **Riesgo máximo del 2 %** por operación.

`capital mínimo = posición mínima ÷ min((1 − reserva) ÷ posiciones, riesgo ÷ caída del stop)`, redondeado para arriba.

Reglas que no se cambian sin pensarlo dos veces:
- **El precio es el de la última vela de 1 h cerrada**, igual que el resto de Pilota.
- **Los supuestos se marcan.** El stop se supone a `CAIDA_STOP` del precio (más abajo que cualquier estrategia: un stop más abajo
  pide más cantidad). Mientras no haya llave, las comisiones son las supuestas y `comisiones.origen` dice `"supuesto"`; la
  pantalla lo muestra. Ningún número de Binance se enseña tal cual: el par y su moneda se revisan contra los que conocemos.
- **Si Binance no dice un mínimo, no se inventa**: `filtros_de()` falla y la pantalla dice que no se pudo calcular.

## Los indicadores de las siete familias

Las siete familias que después va a pesar el puntaje, con dos o tres parámetros cada una (cada parámetro que se suma hay que
calibrarlo con datos de verdad):

| Familia | Sus parámetros | Dónde |
|---|---|---|
| tendencia | medias simples de 20, 50 y 200 velas y el ADX de Wilder (con sus dos direcciones) | `lib_indicadores.py` |
| impulso | el RSI de Wilder y el MACD 12/26/9 con su señal y su histograma | `lib_indicadores.py` |
| volatilidad | Bollinger (20 velas, 2 desvíos: las tres líneas, el `ancho` y la `posicion` del cierre) y el ATR de Wilder (14) | `lib_indicadores_mercado.py` |
| volumen | el volumen relativo (contra las 20 velas anteriores) y el OBV (con `obv_relativo`, de −1 a 1) | `lib_indicadores_mercado.py` |
| estructura | el techo y el piso de las 20 velas anteriores: si se rompieron y a qué distancia quedaron | `lib_indicadores_mercado.py` |
| contexto | BTC en 1 d (de `BTCUSDT`): cuánto se movió el último día y su distancia a la media de 200 | `lib_indicadores_mercado.py` |
| costo | la comisión (maker al entrar, taker al salir por el stop), la diferencia entre compra y venta y la conversión USDT↔FDUSD | `lib_indicadores_mercado.py` |

Las cuentas van en dos capas: las de siempre, sobre listas de números (`sma`, `ema`, `rsi`, `macd`, `adx`, `bollinger`, `atr`,
`volumen_relativo`, `obv`, `obv_relativo`, `rupturas`, `cambios`), devuelven la serie completa con `None` donde el indicador
todavía no existe (son las que va a recorrer el backtest, vela por vela); las de la app (`valores`, `de_serie`, `contexto`,
`costo`, `estado`) dan el valor de **ahora** de cada par y temporalidad leyendo lo guardado. Las cinco familias nuevas entran a
cada serie por el gancho `extra` de `de_serie`, así las velas se recorren una sola vez, y `lib_indicadores_mercado.estado()` es
lo que responde la acción `indicadoresEstado` (`bin/indicadores.py`), que no toca la red: las 12 series con sus cinco familias,
más `contexto` y `costo` aparte (no son de una serie sola). `listo` pide las tres cosas; `motivos` sigue siendo el de las
series, y el contexto y el costo llevan el suyo.

Reglas que no se cambian sin pensarlo dos veces:
- **Solo velas cerradas**, igual que el resto de Pilota: la vela en curso no entra nunca (`velas_cerradas` corta en el borde
  de lo cerrado), porque sus valores todavía pueden cambiar y moverían el indicador.
- **Continuidad antes de calcular.** Una serie vacía, con hoyos, atrasada o corta no se calcula: queda con su motivo
  (`sin_datos`, `huecos`, `atrasado`, `faltan_velas`, los mismos códigos de `lib_datos`, que la pantalla ya traduce) y sin
  ningún valor. Una media o un RSI con velas faltando en medio es un número falso, y un número falso es peor que ninguno.
- **La ventana es fija**: las últimas `VENTANA` velas (la media más larga más `VELAS_CALENTAMIENTO`). El RSI, el ADX y el MACD
  son suavizados que arrastran todo lo anterior, así que con una ventana fija el valor de hoy es siempre el mismo, no importa
  cuánta historia esté guardada ni si acaba de llegar el historial largo. Por eso una serie de `1d` recién da indicadores con
  más de 200 días: hasta entonces su fila dice qué falta.
- **Nada se redondea aquí.** El redondeo vive en la pantalla (`numero()` y `porcentaje()` en `ui/app.js`): el puntaje y el
  backtest trabajan con todos los decimales.
- La serie de **1 m queda fuera** a propósito: es la que mira los cruces de stop y objetivo, no la que decide.
- **El nivel que se rompe no se cuenta a sí mismo.** El techo y el piso son los de las `RUPTURA_VELAS` velas **anteriores**, y
  el volumen relativo compara con el promedio de las **anteriores**: si la vela entrara en su propio nivel o en su propio
  promedio, ninguna ruptura se vería y un volumen grande se diluiría solo.
- **El costo del momento no se inventa.** La diferencia entre compra y venta sale de la última muestra del libro que dejó el
  muestreo (`mercado/muestreo.json`, `ultima`): sin muestra, con una muestra de hace más de `MUESTRA_VIGENTE_MIN` minutos o con
  una que no se entienda (el archivo lo pudo tocar cualquiera), la familia costo queda con su motivo (`sin_muestras`,
  `muestra_vieja`) y sin números. Las comisiones son las de la API si el conector real ya las dejó escritas y, si no, las
  supuestas: `costo.origen` lo dice, igual que en el capital mínimo viable.
- **El contexto es BTC en 1 d y sale de `BTCUSDT`**: el par contra FDUSD recién empieza y no llega a los 200 días de media.
  Qué se hace con ese contexto —si BTC cae, no se entra a nada— es cosa de las estrategias, en su paso: aquí solo están los
  números.

## Las tres estrategias y el filtro de BTC

Sobre los indicadores, las tres salidas posibles de cada vuelta (`bin/lib_estrategias.py`). Son solo tres a propósito: cada
estrategia hay que calibrarla y probarla con datos de verdad.

| Estrategia | Cuándo mira | Cómo entra | Cómo sale |
|---|---|---|---|
| `ruptura` (tendencia) | el cierre pasó el techo de las `RUPTURA_VELAS` velas anteriores, con el volumen sobre `VOLUMEN_RUPTURA` veces lo normal y el día al alza | límite **en el nivel roto**: se espera a que el precio vuelva a él, no se persigue | objetivo a `OBJETIVO_RUPTURA` del nivel, stop a `STOP_ATR_RUPTURA` ATR |
| `rebote` (rango) | el cierre pegado a la banda de abajo de Bollinger (`POSICION_REBOTE`) con el ADX bajo (`ADX_RANGO`) | límite en la banda de abajo (o en el cierre, si ya quedó más abajo) | objetivo en la media de la banda, stop a `STOP_ATR_REBOTE` ATR |
| `usdt` | siempre | no entra | — |

La acción `senalesEstado` (`bin/senales.py`) responde `lib_estrategias.estado()`: las cuatro series de entrada (los dos pares
que se operan en 1 h y 4 h) con sus señales crudas, el filtro de BTC y la opción de quedarse en USDT. Las dos capas son las
de los indicadores: `de_velas` (y `al_alza_en`, `filtro_en`, `tendencia_diaria`, `contexto_diario`) recorre las velas una por
una y es la que va a usar el backtest; `de_indicadores` y `estado` dan las señales de **ahora** a partir del estado de
indicadores, así las velas se recorren una sola vez.

Reglas que no se cambian sin pensarlo dos veces:
- **Una señal cruda no es una orden.** Dice par, temporalidad, nivel de entrada, stop y objetivo, con la distancia a cada
  uno, y nada más. El puntaje, la exigencia, el costo de entrar y salir y el tamaño son de sus propios pasos.
- **Si BTC cae, no se entra a nada** (`filtro_btc`, sobre la familia contexto: la caída del último día cerrado y la media de
  200 días), y sin contexto tampoco (`sin_contexto`): con BTC a ciegas ninguna oportunidad se mira. El filtro **no borra**
  la señal —el backtest necesita verla— le pone `permitida` en falso y su motivo.
- **Solo se compra** (`lado` siempre `"compra"`) y siempre con **límite** (`orden`): la entrada es post-only contra FDUSD,
  del lado maker. Sin apalancamiento y sin vender en corto.
- **La tendencia diaria no se supone.** Sale de la serie de 1 d del par contra USDT (`PAR_DIARIO`), que es el que tiene años
  de historia —el de FDUSD recién empieza y no llega a la media de 200 días, la misma razón de la familia contexto—. Si esa
  serie no está, la ruptura de ese par no se mira y queda el motivo `sin_tendencia_diaria`.
- **1 d no es temporalidad de entrada** (`TEMPORALIDADES_SENAL`): es la que dice para dónde va el día.
- **Nunca se mira el futuro.** `al_alza_en` y `filtro_en` responden con la última vela de 1 d **cerrada** antes de ese
  momento: en el backtest, decidir con una vela que todavía no cerró es inventar ganancias.
- **Ningún número se inventa.** Si a una vela le falta un parámetro (el ATR, la banda, el volumen relativo) o el stop
  quedaría bajo cero o el objetivo bajo la entrada, esa vela no da señal.
- **Los números de las reglas son los de partida**, escritos antes de ver un solo resultado (`parametros()`): los mueve la
  calibración, en su paso, y el reporte dice con cuáles quedó. La mitad con objetivo y la mitad con stop móvil de la
  estrategia de tendencia es cosa del ejecutor, también en su paso: aquí está el objetivo y el stop de la señal.

## El backtest de señales crudas

El primer paso del orden de la calibración, y por eso va **sin exigencia**: qué daban estas reglas con el historial, antes de
que exista el puntaje (`bin/backtest.py`, con los costos en `bin/lib_costos.py`). Las acciones son `backtestEstado` (lo último
que se corrió, sin recorrer nada) y `backtestCorrer`.

| Qué | Cómo |
|---|---|
| costos por lado | entrar es maker (límite post-only contra FDUSD) y salir por el objetivo también; el stop sale a mercado (taker) y además cruza el libro. La conversión USDT↔FDUSD se paga una vez por lado (`lib_costos.resultado`) |
| spread | mientras no haya `lib_costos.DIAS_MODELO` días con muestras propias, el supuesto conservador `SPREAD_SUPUESTO` (muy peor que el de hoy); con datos propios, el percentil `PERCENTIL_SPREAD` de lo medido. `modelo.origen` dice cuál |
| no llenado condicionado | una compra límite se llena cuando el precio **sigue en contra**: el mínimo de la vela tiene que atravesar el nivel por `PENETRACION_SPREADS` spreads. La prueba de sensibilidad (`SENSIBILIDAD`) repite el recorrido entero con los tres factores |
| empalme | donde el par contra FDUSD todavía no existía se usan las velas del par del mismo activo contra USDT con los costos de FDUSD (`empalmar`), y queda marcado (`empalmada`, `prestadas`, `corte`) |
| compuerta | los casos por estrategia, par y temporalidad, **sin contar dos veces los que se solapan** (`sin_solapar`), contra `CASOS_MINIMOS` |
| reporte | contra quedarse en USDT y contra comprar y esperar: rendimiento, caída máxima y operaciones |

Reglas que no se cambian sin pensarlo dos veces:
- **Nunca se mira el futuro.** La señal se decide con la vela cerrada y su orden se puede llenar recién en la vela
  **siguiente**; la tendencia diaria y el filtro de BTC salen de la última vela de 1 d cerrada antes de ese momento
  (`lib_estrategias.al_alza_en`, `filtro_en`).
- **Los costos se equivocan para el lado caro.** Un backtest con costos optimistas promete plata que no existe: spread
  supuesto, stop que cruza el libro y límite que solo cuenta si el precio la atraviesa.
- **Con el stop y el objetivo en la misma vela se supone el stop** (`SUPUESTO_AMBIGUO`): de hace años no hay velas de 1 m, y
  un resultado que cambiara cuando la ventana de 1 m se corre no sería un resultado. El supuesto se **valida** contra los 30
  días que sí tienen esas velas (`validar_ambiguas`) y el reporte lo deja marcado con cuántas veces acertó.
- **El plan B está escrito antes de ver un resultado.** Si un tramo no llega a `CASOS_MINIMOS`: se juntan las temporalidades
  (`ancho`), después los pares (`unico`) y, si todavía no alcanza, se dice (`insuficiente`). Haber usado el plan B no se tapa:
  `compuerta.plan_b` y `no_validado` quedan en el reporte y la calibración, en su paso, tiene que dejar el modelo en «No
  validado» con la exigencia alta.
- **Un caso no es una señal.** La compuerta cuenta solo las operaciones que cerraron y que el filtro de BTC dejaba entrar, y
  de esas, las que no se pisan entre sí: dos operaciones que vivieron el mismo rato son el mismo rato de mercado.
- **Continuidad antes de recorrer**, igual que en todo lo demás: una serie vacía, corta (menos de `VELAS_MINIMAS`) o con
  hoyos no se recorre y queda con su motivo. Las primeras `lib_indicadores.VELAS_CALENTAMIENTO` velas tampoco dan
  operaciones: ahí el ATR y el ADX todavía arrastran de dónde empezó la serie.
- **No es una cartera.** Las operaciones se solapan y la curva con la que se compara entra entera en cada una: el tamaño, la
  reserva y los frenos son sus propios pasos, y la pantalla lo dice.
- **La exigencia entra por un gancho.** `correr(filtrar=…)` es por donde la calibración, en su paso, va a dejar pasar solo
  las señales que llegan a la exigencia: el recorrido no se escribe dos veces.
- **Cada tramo de la compuerta lleva su `resumen`** (`tramos_de`): de ahí saca el puntaje la probabilidad de ganar de una
  oportunidad de ese mismo tramo.

## El puntaje de 0 a 100

Cada familia de indicadores se convierte en una **nota de 0 a 100** y las siete juntas, con su peso, dan el **puntaje** de
la oportunidad (`bin/lib_puntaje.py`, acciones `puntajeEstado` y `puntajeMedir` en `bin/puntaje.py`). Al lado del puntaje
van los dos números con los que se decide de verdad: la **probabilidad de ganar** del tramo de puntaje en que cae y la
**ganancia esperada después de costos**, las dos con su rango de confianza y diciendo con cuántos casos están calculadas.
Y quedarse en USDT también puntúa: es la vara.

| Familia | Sus parámetros (2 o 3, nunca más) | Forma | Razones |
|---|---|---|---|
| tendencia | `medias` (cuántas de las tres condiciones de 20/50/200 se cumplen) y `adx` | rampa `ADX_SIN_FUERZA`→`ADX_CON_FUERZA` | `subiendo_con_fuerza`, `subiendo_sin_fuerza`, `medias_mezcladas`, `bajando` |
| impulso | `rsi` y `macd` (el histograma contra el precio) | banda del RSI, rampa `±MACD_FUERTE` | `acelerando`, `macd_en_contra`, `viene_cansado`, `sobrecomprado` |
| volatilidad | `atr_relativo` y `ancho` (lo abierta que está la banda de Bollinger) | bandas: quieta no llega al objetivo, loca se come el stop | `se_mueve_lo_justo`, `muy_quieto`, `muy_movido` |
| volumen | `volumen_relativo` (contra lo normal) y `obv_relativo` | rampas `VOLUMEN_FLOJO`→`VOLUMEN_FUERTE` y `±OBV_FUERTE` | `volumen_acompana`, `volumen_flojo`, `volumen_en_contra` |
| estructura | `nivel_roto` (1 el techo, −1 el piso, 0 ninguno) y `distancia` | rampa inversa hasta `EXTENSION_MAXIMA`; con el piso roto, 0 | `techo_recien_roto`, `nivel_ya_pasado`, `cerca_del_piso`, `en_medio_del_rango`, `piso_roto` |
| contexto | `btc_cambio` (su último día en 1 d) y `btc_distancia` (a su media de 200) | rampas `±CAIDA_BTC` y `±DISTANCIA_BTC` | `btc_bien`, `btc_bajo_su_media`, `btc_cayendo` |
| costo | `comision` (los dos lados), `spread` y `conversion`, contra lo que promete | rampa inversa hasta `COSTO_PARTE_MAXIMA` | `costo_bajo`, `costo_se_lleva_mucho` |

Cada familia (`tendencia(v)`, `impulso(v)`, …) devuelve las tres cosas juntas: su **nota** de 0 a 100, los **parámetros**
que la formaron (`nombre`, `valor` y la `nota` de cada uno) y una **razón** corta (`RAZONES`), la que la pantalla y la
mascota cuentan en palabras en sus pasos. Sin uno de sus números, la familia no tiene nota y su razón dice cuál faltó
(`sin_adx`, `sin_media_200`, `sin_spread`…).

`puntaje_de` junta las siete en **un** puntaje de 0 a 100 con sus pesos (`PESOS_BASE`: al empezar, todas lo mismo) y deja
el desglose al lado: cada familia con su nota, sus parámetros, su razón, su `peso` y la `parte` que le tocó del puntaje
final (las partes suman 1). Y `modelo()` dice con qué se está puntuando: mientras no exista calibración, el estado es
`sin_calibrar`, los pesos son los de partida y la exigencia es `EXIGENCIA_SIN_CALIBRAR` (85).

Las dos capas son las de siempre: las de siempre trabajan sobre un diccionario plano de valores (`familias`, `puntaje_de`)
y `de_velas` las recorre vela por vela sobre una serie entera —es la que va a usar la calibración para
`backtest.correr(filtrar=…)`—; las de la app (`valores_de`, `opcion`, `estado`) dan el puntaje de **ahora** leyendo el
estado de indicadores, las señales crudas y el último backtest guardado.

Reglas que no se cambian sin pensarlo dos veces:
- **Un puntaje no es una orden ni una promesa.** La exigencia (el corte), el tamaño y los frenos son de sus propios pasos.
- **Ningún número se inventa, y las familias clave no se saltan.** A una familia sin su parámetro no se le pone una nota
  media: queda sin nota, diciendo qué número le faltó (`sin_spread`, `sin_media_200`). Si la que falta es una de las tres
  **clave** (`FAMILIAS_CLAVE`: `tendencia`, `contexto` y `costo` —para dónde va el precio, cómo viene BTC y qué se lleva
  el costo), la oportunidad **no se puntúa**: queda con su motivo (`sin_costo`, `sin_contexto`…) y sin puntaje. Si la que
  falta es una de las otras cuatro, el puntaje sale con las que sí tienen dato, **renormalizando los pesos** (cada peso
  contra la suma de los presentes, no un cero que castiga de gratis) y queda marcado (`renormalizado`, `faltan`).
- **Sin calibración, el modelo está `sin_calibrar` y la exigencia es 85.** Con los pesos de partida nadie probó todavía
  que este puntaje separe lo bueno de lo malo, así que el corte va alto. El estado, los pesos y la exigencia de verdad
  salen de la calibración, en su paso (`estado(..., calibracion=…)`), y hasta entonces `modelo()` dice las dos cosas.
- **La probabilidad sale de las operaciones que de verdad hubo, y del tramo de puntaje de la oportunidad.** `medir`
  recorre el historial puntuando cada señal cruda **antes** de seguirla (`de_velas` + `seguir`, que cierra con
  `lib_resolucion.cerrar`) y reparte las operaciones en los cinco tramos de 20 puntos de `TRAMOS_PUNTAJE`
  (`tramos_de_puntaje`): así la pregunta que se contesta es «con qué frecuencia gana algo que puntúa como esto». Cada
  tramo lleva sus operaciones, sus **casos** (los que no se pisan, `backtest.sin_solapar`), su tasa con su rango (Wilson)
  y lo que dejó después de costos con el rango de su esperada. Es la acción `puntajeMedir` (pasada lenta, aparte) y queda
  en `mercado/tramos.json`.
- **Si el tramo de puntaje no alcanza, se baja al de la compuerta, y queda dicho de dónde salió.** Sin tramos medidos o
  con menos de `CASOS_PROBABILIDAD` casos en el suyo, `evidencia` usa el tramo de esa estrategia, par y temporalidad del
  backtest guardado (bajando por los niveles de la compuerta). `fuente` (`puntaje` o `compuerta`), `origen` (el nivel) y
  `tramo` (los bordes) lo dicen siempre; sin ninguno de los dos no hay probabilidad (`sin_backtest`, `pocos_casos`,
  `pocos`) y, si hubo que ensanchar, tampoco está validado (`no_validado`).
- **La tasa se mide con las operaciones y el rango con los casos** que no se pisan (`wilson`, `CONFIANZA`): dos
  operaciones que vivieron el mismo rato de mercado no son dos pruebas, así que el rango es más ancho y es el que va.
- **La regla de las velas sin 1 m se dice siempre.** Una vela que tocó el stop y el objetivo se cuenta como stop
  (`lib_resolucion.SUPUESTO_SIN_1M`, el mismo código que `backtest.SUPUESTO_AMBIGUO`); el supuesto se valida contra los
  `lib_datos.DIAS_MINUTOS` días que sí tienen velas de 1 m y el reporte dice en cuántas acertó (`supuestos`): la
  probabilidad arrastra ese supuesto y no se esconde.
- **Lo que gana y lo que pierde no son estimaciones**: salen de los precios de la señal con los costos de cada lado
  (`lib_costos.resultado`, objetivo maker y stop taker cruzando el libro). Lo único estimado es la probabilidad, y por eso
  la ganancia esperada nunca va sin su rango.
- **Quedarse en USDT vale `PUNTAJE_USDT`** —la mitad justa de la escala: no gana ni pierde— y `PUNTAJE_MAXIMO` cuando no
  hay nada que mirar (el filtro de BTC frenado o ninguna estrategia gatillada). No tiene probabilidad: no es una apuesta.
  Está en la **misma escala** que las demás a propósito: `mejor_de` las compara de frente, mirando solo las que se pueden
  entrar y tienen puntaje, así que una oportunidad recién conviene cuando puntúa más que quedarse quieto.
- **Los pesos son los de partida: todas las familias pesan lo mismo** (`PESOS_BASE`), escrito antes de ver un resultado.
  Los mueve la calibración, en su paso (`puntaje_de(..., pesos=…)`), y el reporte dice con cuáles quedó.

## La regla de las velas sin 1 m

Una operación cierra en la primera vela que tocó su stop o su objetivo. La vela que tocó **los dos** no dice qué se cruzó
primero, y de hace años no hay velas de 1 m (Pilota guarda los últimos `lib_datos.DIAS_MINUTOS` días). La regla, en un solo
lugar (`bin/lib_resolucion.py`), con su etiqueta pegada al resultado:

| Qué hay | Qué pasa | Etiqueta |
|---|---|---|
| la vela tocó un solo nivel | cierra ahí: no hay nada que suponer | `CLARA` |
| tocó los dos y están sus velas de 1 m **completas** | se mira minuto por minuto qué se cruzó primero (`en_minutos`) | `CON_1M` |
| tocó los dos y no están (o el minuto tampoco lo dice) | **el stop antes que el objetivo** (`SUPUESTO_SIN_1M`) | `SIN_1M` |

Las dos capas son las de siempre: `toco`, `trozo_de`, `en_minutos`, `de_ambigua`, `resolver`, `cerrar` y `comparar` no leen
nada del disco (las usan el backtest, la calibración y el ejecutor de prueba, en sus pasos), y `validar`, si no se le pasan
las velas de 1 m, las lee de lo guardado.

Reglas que no se cambian sin pensarlo dos veces:
- **El supuesto se equivoca para el lado caro**: suponer el objetivo sería prometer plata que nadie vio.
- **El resultado no puede cambiar porque la ventana de 1 m se corra.** Los 30 días de 1 m se mueven, así que el recorrido
  del historial va siempre con el supuesto (`cerrar(..., minutos=None)`) y las velas de 1 m se usan para **validarlo**. Donde
  sí se resuelve con 1 m de verdad es en el modo prueba y al reconciliar, en sus pasos: ahí las velas están.
- **Media ventana no resuelve nada.** Si falta un solo minuto de la vela, `trozo_de` no devuelve nada y manda el supuesto:
  el cruce pudo pasar justo en el minuto que falta. Y del minuto no se baja más: si el mismo minuto tocó los dos niveles,
  queda `sin_resolver` y no cuenta ni como acierto ni como error.
- **La validación resuelve las mismas velas de las dos formas** (`validar`): cuántas fueron ambiguas (`velas`), cuántas se
  pudieron revisar (`con_1m`, `sin_1m`), qué dijo el minuto (`stop_primero`, `objetivo_primero`, `sin_resolver`) y en
  cuántas el supuesto dijo lo mismo (`iguales`, `distintas`, `acierto`). Con menos de `VELAS_VALIDACION` velas revisadas el
  acierto se informa igual, pero `validado` queda en falso: tres velas no validan nada.
- **La etiqueta se dice siempre**, también cuando la vela fue clara: un resultado sin su etiqueta no se puede comparar con
  otro. Son códigos; la pantalla los traduce, en su paso.

## La calibración del puntaje

El cuarto y el quinto paso del orden de la calibración (los tres primeros son el backtest de señales crudas, la compuerta de
casos y los tramos de puntaje): cuánto pesa cada familia y cuánta **exigencia** se le pide a una oportunidad para entrar no se
inventan (`bin/lib_calibracion.py`, acciones `calibracionEstado` y `calibracionCorrer` en `bin/calibrar.py`). El orden importa y
es siempre este:

| Paso | Qué hace |
|---|---|
| 1. apartar | Los últimos `DIAS_APARTADOS` (365) días quedan afuera **antes** de mirar un solo peso (`apartar`). Sin historial para el año apartado y las ventanas de antes, no se calibra nada (`falta_historia`). |
| 2. recorrer | Una sola pasada por el historial (`recorrido`), la misma del backtest (empalme, modelo de spread, no llenado condicionado y costos por lado), puntuando cada señal cruda **antes** de seguirla. Las siete **notas** viajan con cada operación, así que probar otros pesos no vuelve a mirar una vela (`puntaje_con`). |
| 3. ajustar | `MESES_AJUSTAR` (12) meses para ajustar y los `MESES_PROBAR` (3) siguientes para probar, corriéndose de 3 en 3 meses y siempre antes del corte (`ventanas_de`, `pools`); de las que salgan, las últimas `VENTANAS_MAXIMAS`. Un peso se mueve solo si de verdad mejora, y se dan como máximo `VUELTAS_MAXIMAS` (3) vueltas: el reporte dice cuántas (`ajuste.cuantas`) y con cuál quedó (`elegida`). |
| 4. re-backtest | El backtest de nuevo con el puntaje y la exigencia puestos, por el gancho de siempre (`correr_con`, `backtest.correr(filtrar=…)`): el recorrido no se escribe dos veces. |
| 5. prueba final | **Una sola vez**, con el año apartado y el criterio escrito antes (`aprobar`, `criterio`). |

Reglas que no se cambian sin pensarlo dos veces:
- **El año apartado no se mira hasta la prueba final.** Los pesos y la exigencia salen de las ventanas de antes del corte, y una
  operación cuenta en la ventana en que se **decidió** (`senal_ms`), aunque haya cerrado después.
- **La prueba final se gasta una sola vez.** Queda escrita con su ventana (`prueba_final.ventana`) y no se repite: para volver a
  probar hace falta un tramo intacto de al menos `DIAS_PRUEBA_NUEVA` (90) días **después** del que ya se usó (`apartar` recibe
  esa ventana, no la prueba entera). Si no lo hay, el modelo queda «No validado» con el motivo `prueba_repetida`.
- **Si no aprueba, el modelo queda «No validado»**: exigencia `EXIGENCIA_NO_VALIDADO` (85) y los montos por posición topados en
  `TOPE_NO_VALIDADO` (15 USDT), que es lo que va a leer el tamaño de la operación en su paso (`modelo()`). Los pesos ajustados se
  quedan y el reporte dice con cuáles, pero nada de lo que prometen está probado.
- **El plan B de la compuerta manda.** Si el backtest de señales crudas tuvo que ensanchar sus tramos, el modelo no puede quedar
  validado, pase lo que pase en la prueba final. Y sin ese backtest corrido no se calibra nada (`sin_backtest`): la compuerta de
  casos va antes.
- **El criterio está escrito antes de ver un resultado** (`criterio`, `CRITERIO_*`) y se revisa entero, también las revisiones
  que pasaron (`aprobacion.revisiones`): `CRITERIO_CASOS` casos que no se pisen, que deje algo después de costos, que le gane a
  quedarse en USDT y que su caída máxima no llegue al piso de los frenos (`CRITERIO_CAIDA`, −25 %).
- **Ganarle a comprar BTC y esperar no es el criterio.** El reporte lo compara siempre (`referencias.btc`), pero una posición
  larga en BTC tiene caídas que los frenos de Pilota no dejarían pasar: la vara es quedarse en USDT.
- **Con qué se elige es la ganancia media por operación después de costos** (`medir_puntuadas`, `objetivo`), no el rendimiento
  compuesto, que premia operar mucho. Y sin `CASOS_VENTANA` casos no hay objetivo: no es que sea peor, es que no se midió.
- **Nunca se mira el futuro**, igual que en el backtest: la señal se decide con la vela cerrada, su límite se puede llenar recién
  en la siguiente y la vela que tocó el stop y el objetivo se cuenta como stop (`lib_resolucion.SUPUESTO_SIN_1M`), con el
  supuesto marcado en el reporte (`supuestos`).
- **Nada de esto toca la red ni se guarda a medias**: `calibracionEstado` lee lo guardado (`guardada`) y `calibracionCorrer` deja
  el reporte entero escrito (`escribir`), con su motivo cuando no se pudo calibrar.

## El registro que no se borra y el estado firmado

Dos archivos, dos reglas: lo que pasó **se queda escrito** y lo que Pilota cree de sí misma **se puede comprobar**
(`bin/lib_registro.py`, `bin/lib_estado.py`, acciones `estadoArrancar` y `estadoReiniciar` en `bin/estado.py`). Todo está
**separado para prueba y para real**: dos registros, dos estados, dos juegos de frenos.

| Dónde (en los datos de la app) | Qué |
|---|---|
| `registro/<ambiente>/<AAAA>.jsonl` | Una línea por decisión, con los campos fijos (`lib_registro.CAMPOS`): `{"ms", "fecha", "par", "puntaje", "razon", "orden", "resultado"}`. Se agrega al final (`O_APPEND`, 0600) y **no se reescribe nunca**. Un archivo por año: el mismo corte con el que se exporta el CSV, en su paso. |
| `estado/<ambiente>.json` | `{"formato": 1, "huella": "<sha256>", "estado": {…}}`. El cuerpo: `modo`, `saldo`, `referencia`, `aportado`, `aportes`, `posiciones`, `operaciones`, `racha`, `dia`, `desbloqueos`, `reinicios` y `cuando_ms`. |

Reglas que no se cambian sin pensarlo dos veces:
- **Nada de texto libre en el registro.** La `razon` es uno de los códigos de `RAZONES` (cada paso suma los suyos y la pantalla
  los traduce) y `orden` y `resultado` solo aceptan las claves conocidas con números, booleanos o códigos cortos (`CODIGO`). Así
  un error de Binance no puede llegar a la pantalla convertido en texto. Lo que se lee del archivo vuelve a pasar por `revisar`:
  una fecha editada a mano se recalcula desde el `ms` y una línea que quedó a medias se salta y se cuenta (`danadas`), nunca se
  borra.
- **Si el archivo de estado falta, la huella no cuadra o la fecha es futura, se arranca frenado en modo manual** (`cargar`):
  `frenado` en verdadero, el motivo en código (`MOTIVOS_FRENADO`) y **los números en cero**: de un archivo del que no se puede
  fiar nadie no sale un tamaño de operación. Lo que decía el archivo viaja aparte (`leido`), solo para mostrarlo.
- **El archivo sospechoso no se pisa.** `cargar` no escribe nada y `arrancar` solo agrega la línea `arranque_frenado` al
  registro: la evidencia se guarda y la persona decide.
- **La primera vez no es un freno.** Sin archivo y sin registro no hay nada que perder (`arranque.motivo` = `primera_vez`); el
  estado nace cuando la persona elige el monto de prueba. Que una cuenta ya haya vivido algo lo dice el registro
  (`lib_registro.cuantas`), que es lo único que no se puede perder.
- **El ambiente va dentro de la huella.** Un estado de prueba copiado sobre el de real no cuadra: son dos cuentas distintas.
- **El capital de referencia es el saldo más alto alcanzado** (`con_saldo`): sube con las ganancias y nunca baja con las
  pérdidas. Lo único que lo mueve hacia abajo es un retiro, y los depósitos y retiros van **explícitos** en su libro
  (`con_aporte`, `aportes`, `aportado`): un depósito no es una ganancia ni un retiro una pérdida, que es justo lo que mira el
  piso de los frenos en su paso.
- **El saldo de prueba se reinicia con una sola confirmación y al tiro** (`reiniciar`), y queda en el registro. La espera de 24 h
  es solo para el desbloqueo del piso en real, en su paso. El saldo real no se reinicia nunca: lo dice Binance al reconciliar.
- **Los días que lleva una cuenta los cuenta el registro, no el estado** (`resumen.dias`): el estado se puede perder.
- **Los frenos y los tres modos son sus propios pasos.** Acá los contadores (`racha`, `dia`, `desbloqueos`) nacen en cero y el
  modo solo se revisa contra `MODOS`; el de partida y el de después de cualquier freno es `MODO_FRENADO` (manual).
- **Con qué dinero se juega lo dice `activo()`** y hoy siempre es prueba: pasar a real es su propio paso y hasta que esté
  cerrado el interruptor no existe.

## El tamaño de una operación

Cuánto se compra sale de un orden **fijo**, el mismo con el que se calcula el capital mínimo viable al revés
(`bin/lib_tamano.py`, acción `tamanoEstado` en `bin/tamano.py`, archivo `mercado/tamano.json`):

| Paso | Qué pone | Dónde |
|---|---|---|
| 1. el mínimo de Binance | la cantidad tiene que servir para la compra y para **las dos patas** de la protección automática con **ese** stop; la del stop vale menos USDT, así que es la que manda | `cantidad_minima`, `minimo_de` |
| 2. la reserva | el 40 % del capital se queda en USDT y no se opera nunca | `reparto` |
| 3. las dos posiciones | lo que queda se reparte entre las dos, y lo que ya está puesto en una abierta no se reparte de nuevo | `reparto`, `posiciones_de` |
| 4. el riesgo | como máximo el 2 % del capital por operación, contando lo que cuesta salir por el stop | `tamano` |

`monto = min(riesgo ÷ distancia al stop, lo disponible para esa posición, el tope)`, y `manda` dice cuál de los tres
cortó. El **tope** existe mientras el modelo esté «Aún sin validar» (`lib_calibracion.TOPE_NO_VALIDADO`, 15 USDT):
`topado` y `manda` lo dejan dicho en pantalla.

Reglas que no se cambian sin pensarlo dos veces:
- **Si queda bajo el mínimo de Binance, no hay orden.** `puede` en falso, el motivo en código (`bajo_minimo`) y, al
  lado, la posición más chica que sí se podría y desde cuánto capital (`minimo.posicion`, `minimo.capital`): un «no se
  puede» sin un número no sirve de nada. Una orden que Binance rechaza es una posición sin protección.
- **Ningún mínimo se inventa.** Sin el cálculo del capital mínimo viable no hay filtros y no hay tamaño
  (`sin_minimos`), y un par detenido o sin protección automática tampoco (`sin_operar`, `sin_proteccion`).
- **De un estado del que no se puede fiar nadie no sale un tamaño**: si la cuenta arrancó frenada, sus números vienen
  en cero (`lib_estado.cargar`) y acá queda `frenado`. Los otros rechazos se revisan en el mismo orden en que se
  cuentan: `sin_precio`, `sin_stop`, `posiciones_llenas`, `sin_capital`, `sin_disponible`.
- **Los costos se equivocan para el lado caro.** La conversión USDT↔FDUSD, la comisión maker de la entrada y la taker
  del stop se descuentan del monto **y** se cuentan dentro del 2 %: lo que se arriesga de verdad (`arriesgado`) nunca
  pasa el freno. Con comisiones supuestas se dice (`comisiones.origen`), igual que en el capital mínimo viable.
- **Se redondea para el lado que no se pasa**: el precio y el stop bajan al tick y la cantidad baja al paso
  (`bajar_al_paso`). Redondear para arriba sería pasarse del límite que acaba de calcularse.
- **El puntaje no entra en la cuenta.** El tamaño no premia una oportunidad linda: la exigencia, los tres modos y los
  frenos son sus propios pasos, y el ejecutor rechaza toda orden que no pase antes por el tamaño y por los frenos.
- **Los tres números del orden son los mismos de `minimo_viable`** (`RESERVA`, `POSICIONES`, `RIESGO`): se importan de
  ahí, no se copian, y que no se separen lo revisa una prueba.

## Los frenos y la máquina de estados

Los frenos están **en el código y fuera de la IA** (`bin/lib_frenos.py`, acciones `frenosEstado`, `frenosPausar` y
`frenosDesbloquear` en `bin/frenos.py`, archivo `mercado/frenos.json`). No son un consejo: son la respuesta a «¿puedo abrir
algo?», y una orden que no pasó antes por el tamaño tampoco pasa por acá.

| Freno | Cuándo | Qué hace |
|---|---|---|
| sin apalancamiento | siempre | solo se compra al contado y con lo que hay (`APALANCAMIENTO`, revisado en `revisar_orden`) |
| máximo 2 posiciones | `POSICIONES` abiertas | no abre una más (el mismo número del tamaño y del capital mínimo viable) |
| piso absoluto | el saldo cae `PISO_ABSOLUTO` (35 %) bajo el **capital aportado** | bloquea **y reduce la exposición a la fuerza**: `reduce` pide cerrar a mercado |
| piso | el saldo cae `PISO` (25 %) bajo el **capital de referencia** | bloquea; lo abierto se queda con su protección automática |
| diario | se pierde `PERDIDA_DIARIA` (5 %) en el día | bloquea hasta el cambio de día (`dia.hasta_ms`) |
| racha | `RACHA_MAXIMA` (4) pérdidas seguidas | vuelve a manual, no bloquea: Pilota propone y la persona decide |
| comisión | la maker de ahora pasa la que supuso el backtest | bloquea y avisa |
| FDUSD | FDUSD vale menos de `FDUSD_MINIMO` (0,995) | bloquea y avisa; **no liquida nada** sin confirmación |

Cuatro estados (`ESTADOS`), y manda el más grave: `operando` → `pausado` (con «Pausar») → `frenado` (un freno que bloquea) →
`reduciendo` (el piso absoluto). Tras **cualquier** freno el modo vuelve a manual.

Reglas que no se cambian sin pensarlo dos veces:
- **El estado de los frenos vive en el archivo con huella** (`bin/lib_estado.py`): `racha`, `dia`, `desbloqueos`,
  `desbloqueo`, `pausado` y `frenos` (los que ya quedaron anotados). Si ese archivo falta, su huella no cuadra o su fecha es
  futura, la cuenta ya viene frenada en manual y con los números en cero, y **`aplicar` no escribe nada**: el archivo
  sospechoso no se pisa y una cuenta que todavía no existe no se inventa.
- **Mirar los frenos es aplicarlos.** `frenosEstado` corre `revisar`: deja el modo en manual y anota cada freno nuevo en el
  registro, **una sola vez** (para eso está `frenos` en el estado). No hay un «solo mirar» que deje a Pilota operando con un
  freno puesto. Lo mismo va a correr el motor cada 5 minutos y al reconciliar, en su paso.
- **El día es el día UTC** (`fecha_de`), el mismo corte de Binance y del registro; la pantalla lo muestra en hora local
  («se levanta a las 21:00»). La hora del computador se usa para mostrar, nunca para decidir.
- **Un depósito no es una ganancia ni un retiro una pérdida**, ni para los pisos ni para el día: los aportes van explícitos
  en el libro propio (`con_aporte`, `aportar`, `dia.aportado`) y el capital de referencia se mueve con ellos.
- **«Pausar» nunca toca una protección automática**: cancela las entradas y nada más, y la pantalla dice con cuántas
  posiciones protegidas se queda (`protegidas`).
- **El piso se desbloquea a mano**: en real, con 24 h de espera y como máximo `DESBLOQUEOS_MAXIMOS` (2) veces; volver a
  pedirlo no reinicia la espera. Aplicarlo es un **reinicio documentado** del capital de referencia (pasa a ser el saldo de
  ahora) y queda en el registro. En prueba es al tiro —ahí la espera no cuida nada— y el **piso absoluto no se desbloquea**.
- **Los dos frenos de mercado no corren en prueba, pero se avisan** (`SOLO_REAL`, `avisa`): ahí no hay dinero de verdad que
  cuidar y sí hay algo que mostrar. FDUSD se mide con las velas cerradas que ya hay, implícito en los dos pares del mismo
  activo (`fdusd_de`: el mismo BTC vale lo mismo en los dos), y manda el valor más bajo. **Lo que no se puede medir no se
  inventa**: queda en `motivos` y, en real, eso solo ya no deja abrir nada (`sin_medir`).
- **Prueba y real llevan frenos separados**, como el saldo y el registro.

## El ejecutor de prueba

El modo prueba se ejecuta en `bin/lib_ejecutor_prueba.py` (acción `ejecutorEstado` en `bin/operar_prueba.py`, archivo
`mercado/ejecutor.json`). Es el **mismo contrato** que va a tener el conector real —`entrar`, `revisar`, `cerrar`,
`estado`— con una sola diferencia: acá no hay dinero. Todo lo demás es de verdad (precios, velas de 1 m, mínimos de
Binance, tamaño y frenos), así que lo que en real no se puede hacer acá tampoco. El saldo ficticio, las posiciones y sus
órdenes viven en el estado firmado de la cuenta de prueba (`lib_estado`, campo `posiciones`); lo que pasó, en el registro
que no se borra.

Reglas que no se cambian sin pensarlo dos veces:
- **Toda orden pasa antes por el tamaño y por los frenos.** `entrar` no decide cuánto ni si se puede: eso ya lo dijeron
  `lib_tamano.tamano` y `lib_frenos.revisar_orden`, y una orden que no venga de ahí se rechaza con su motivo en código
  (`RECHAZOS`). El ejecutor no es el lugar donde se discute un freno.
- **Una posición sin protección no se abre.** Antes de poner la entrada se revisa que la protección automática **cabe**
  (`cabe`): el tick de los tres niveles, el paso de la cantidad y la cantidad y el nocional mínimos **de cada lado** (la
  compra, el stop y el objetivo). Una orden que Binance rechazaría es una posición desnuda.
- **La mitad que no alcanza el mínimo no se parte**: la ruptura sale mitad en el objetivo y mitad con el stop móvil, pero
  si esa mitad queda bajo el mínimo de Binance la posición sale **entera** (`ESTRATEGIAS_PARCIALES`, `entera`).
- **Los cruces se miran con velas de 1 m**, no con el libro (`seguir` + `lib_resolucion.resolver`): el minuto que tocó el
  stop y el objetivo a la vez se cuenta como stop, y una límite se llena solo cuando el precio siguió en contra
  (`lib_costos.llena`).
- **El stop móvil cancela y repone la protección** —es lo que pide Binance—, con su cuenta a la vista (`reposiciones`).
- **Los ids son deterministas y llevan el prefijo propio** (`PREFIJO` = `pil`, `id_de`): lo que no lo lleva es de otro y
  Pilota no lo toca nunca (`es_nuestro`, `ajenas`).
- **El dinero se mueve una sola vez, al cerrar**: entrar compromete el monto y no toca el saldo; el saldo se mueve con lo
  que dejó la operación (`lib_frenos.con_cierre`, costos de los dos lados con `lib_costos.resultado`).
- **Mirar es aplicar**, como en los frenos: `ejecutorEstado` corre `revisar`, que recorre las velas de 1 m que faltaban y
  deja aplicado lo que pasó. **En prueba la protección existe solo con el motor encendido**: el rato sin velas que la
  cuiden se dice (`cobertura`, `GRACIA_COBERTURA_MS`), nunca se tapa. De una cuenta cuyo archivo no es de fiar no se toca
  nada.
- **El saldo de prueba se reinicia donde se reiniciaba** (`lib_estado.reiniciar`: una sola confirmación, al tiro y queda
  en el registro). Acá no hay otra puerta para eso.

## El motor y reconciliar

El **motor** es el equipo donde corre Pilota: si está apagado, nadie mira los cruces. Cada 5 minutos hace una **revisión**
(`bin/lib_reconciliar.py`, acción `motorRevisar` o el trabajo `motorEncender`, plan `mercado/motor.json`), y al arrancar o
al despertar esa misma revisión **reconcilia** la ventana que nadie miró: los frenos aplicados (`lib_frenos.revisar`), las
velas de 1 m perdidas recorridas con sus stops, objetivos y stop móvil (`lib_ejecutor_prueba.revisar`), lo huérfano
cerrado, la ventana sin cobertura escrita y el resumen de vuelta («Dormiste 9 h: 1 stop, 2 propuestas vencidas»).

Reglas que no se cambian sin pensarlo dos veces:
- **El motor reconcilia con lo que hay, no con lo que supone.** En prueba, con las velas de 1 m que están en disco (las
  trae el muestreo) y con el estado firmado; en real va a reconciliar contra lo que diga **Binance** —órdenes abiertas,
  saldos y llenados—, nunca contra lo guardado, y eso es cosa del conector real, en su paso (`SIN_CONECTOR`).
- **Las velas que todavía no llegaron no cierran la ventana.** Si el muestreo no alcanzó a bajar los minutos que
  faltaban, la ventana queda **abierta** (`anotar_ventana`, `sin_cobertura`) y la revisión siguiente la vuelve a mirar: el
  rato en que un stop no se habría aplicado se dice, nunca se tapa. Dormir más que la gracia también queda escrito.
- **Mirar no es revisar.** `motorEstado` solo dice en qué quedó (hace cuánto fue la última revisión, si está activo o
  dormido, cuándo viene la próxima) y no reconcilia nada; reconciliar es `motorRevisar` y el trabajo.
- **Revisar dos veces no cambia nada dos veces**: cada posición lleva hasta dónde la recorrieron (`revisado_ms`) y los
  ids de las órdenes son deterministas, así que no se duplica ni un llenado ni una línea del registro.
- **Lo huérfano se cierra, no se espera** (`cerrar_huerfano`): la entrada que ya venció se cancela aunque no hubiera
  velas que la cancelaran, y la posición abierta sin protección se cierra a mercado. Lo que no lleva el prefijo propio no
  es de Pilota y no se toca.
- **El resumen sale del registro que no se borra** (`cuentas_de` sobre `lib_registro.ultimas`): lo que no quedó escrito
  no pasó. Si la ventana trae más líneas que el tope, el resumen lo dice (`topado`) en vez de dar un número que no es.
- **Cuándo entrar no se decide acá.** La revisión deja el mundo al día y le pasa el contexto al gancho `decidir`: los
  tres modos y las propuestas que vencen son su propio paso.

## Los tres modos y las propuestas que vencen

Quién dice «sí» a cada operación es lo único que eligen los modos (`bin/lib_modos.py`, acciones `modosEstado`,
`modosDecidir`, `modosResponder`, `modosElegir` y `modosAjustar` en `bin/propuestas.py`, archivo `mercado/modos.json`).
El modo vive en el estado firmado de la cuenta (`lib_estado`, campo `modo`), con los frenos; los ajustes de la persona
(cuánto espera una propuesta y hasta cuánto opera solo el semiautomático) y las propuestas, en `mercado/modos.json`.

| Modo | Qué hace |
|---|---|
| manual | **propone** y espera: puntaje, razón, monto en USDT y stop, con su vencimiento (`VENCIMIENTOS`: 5, 15 o 60 min) |
| semiautomático | opera solo cuando el puntaje es **claramente alto** (`MARGEN_CLARO` sobre la exigencia) y el monto cabe en el elegido (`MONTO`, 15 USDT); si no, pregunta |
| automático | opera solo, y activarlo pide **dos** confirmaciones (`CONFIRMACIONES`) |

Reglas que no se cambian sin pensarlo dos veces:
- **Si nadie responde, la propuesta vence. Siempre** (`caducar`, razón `propuesta_vencida` en el registro). No existe un
  camino donde el silencio opere: quien quiera que Pilota opere sola hasta un monto usa el semiautomático, que es ese
  monto escrito y a la vista.
- **Mirar es aplicar**, como en los frenos y en el ejecutor: `modosEstado` hace vencer la propuesta que se pasó de su
  hora y la deja en el registro, **una sola vez** (el estado de la propuesta es lo que evita la segunda línea).
- **Sin calibración, el semiautomático y el automático no se pueden elegir** (`permitido`, `SIN_CALIBRACION`): quedan
  apagados con el motivo a la vista, nunca escondidos. Y si el estado firmado dice un modo que ya no corresponde, la
  vuelta se decide **como manual** (`efectivo`): el estado no se pisa desde acá.
- **Tras cualquier freno se vuelve a manual.** Eso lo hace `lib_frenos.aplicar`; acá se respeta en los dos sentidos: con
  un freno puesto no se puede elegir otro modo, y un freno que bloquea no deja ni proponer (`decidir` → `frenado`).
- **«Claramente alto» no se muestra como una suma.** El margen es del código; en pantalla va en palabras («solo opera
  solo cuando el puntaje es claramente alto; si no, pregunta»).
- **La propuesta es una foto, no una orden guardada.** Al responder «Sí», el tamaño y los frenos se calculan de cero
  (`opcion_de` + `lib_ejecutor_prueba.entrar` sin tamaño inyectado), y una propuesta nunca vive más que su propia señal.
  Si al responder hay un freno, la orden no se pone y la propuesta sigue esperando mientras le quede hora.
- **Decir «No» es quedarse en USDT** (`RAZON_NO`): el registro no inventa una razón nueva para lo mismo.
- **Acá no se discute ningún freno ni ningún monto**: la exigencia la dice el modelo, el monto el tamaño y el permiso
  los frenos. Los modos solo eligen quién confirma, y el ejecutor rechaza igual lo que no pasó por los dos.
- **La misma señal no se propone ni se entra dos veces** (`id_de`, determinista con el par, la vela y la estrategia, más
  `lib_ejecutor_prueba.repetida`): revisar de nuevo no abre dos posiciones por una señal.
- **Es el gancho del motor** (`lib_reconciliar.reconciliar(decidir=…)`, que `bin/motor.py` conecta en `revisar` y en el
  trabajo): la revisión deja el mundo al día y recién entonces se decide, con los frenos ya aplicados.

## Los perfiles y el robot en vivo

Lo que ve la persona primero es el robot (`ui/vivo.js`, pestaña «En vivo»): elige un perfil y un monto ficticio, y el motor
opera solo con precios reales de Binance (`bin/lib_piloto.py`). «Comparar» corre los perfiles que se ofrecen sobre el pasado
con el mismo monto (`lib_simulacion.comparar`), y «Movimientos» cuenta todo lo que hizo, en palabras.

**Se ofrecen la familia holding y la rotación** (`lib_perfiles.ORDEN`), agrupados en la pantalla («Comprar y guardar» y
«Experimento»):

| Perfil | Qué hace |
|---|---|
| holding (el sugerido) | compra BTC 60 % y ETH 40 % (contra FDUSD) en 12 partes, una por semana, y mantiene |
| holding_ocho | lo mismo con las 8 monedas en partes iguales |
| compra_semanal | 52 compras semanales de BTC y ETH, cada una un 1 % bajo el cierre; si al día siguiente no llega, compra igual |
| rebalanceo | la mitad en BTC y ETH y la mitad en USDT; vende el sobrante sobre 60 % y compra lo que falta bajo 40 % |
| cosecha | vende un cuarto cuando una moneda vale 30 % sobre su costo y lo recompra si cae 15 % desde esa venta |
| indice_eeuu | 60 % S&P 500 (SPYB) y 40 % Nasdaq 100 (QQQB) en 12 partes semanales, y mantiene |
| indice_semanal | lo mismo en 52 compras semanales, cada una un 1 % más abajo |
| acciones_ocho | Apple, Microsoft, Nvidia, Amazon, Google, Meta, Tesla y Broadcom en partes iguales |
| semanal_rotacion (mezcla) | 50 % compra_semanal y 50 % rotacion |
| nucleo_satelite (mezcla) | 70 % holding_usdt (BTC y ETH contra USDT, no se ofrece solo) y 30 % rotacion |
| cripto_acciones (mezcla) | 50 % compra_semanal y 50 % indice_semanal |
| rotacion (experimento) | una vez al día tiene las 2 monedas más fuertes de las 8 contra USDT (`lib_rotacion`); puede caer tanto como BTC |

**Las acciones** son los bStocks de Binance (`lib_datos.ACCIONES`, contra USDT): acciones de EE. UU. tokenizadas y respaldadas
1:1 por la acción en un custodio. Se leen con la misma API pública y el mismo flujo que las monedas (`lib_datos.ACTIVOS`).
Llegaron a Binance en junio de 2026: «Comparar» las mide desde que existen y lo dice (`recorte` = `acciones`, con
`lib_simulacion.inicio_posible`), y el mapa de inicios no tiene casillas antes. Que la cuenta de la persona pueda comprarlas
con dinero real depende de su país: el conector real todavía no las conoce.

**Las mezclas** (`tipo` = `mezcla`, `componentes`) reparten el monto entre perfiles. Cada parte tiene su propio libro en
`piloto.json` (`mezcla[perfil]`) y decide sola (`lib_piloto._vuelta_mezcla`); en el pasado se suman sus curvas día por día
(`lib_simulacion.mezcla`). La pantalla muestra cuánto vale cada parte («Mi plan»).

**El mapa de inicios** (`lib_simulacion.mapa`, acción `simularMapa`): si hubieras empezado cada 6 meses desde junio de 2018,
cuánto tendrías hoy con cada perfil y con comprar BTC de una. Los holding se corren de nuevo desde cada inicio; la rotación
y BTC se corren una vez y se miden desde cada inicio (sus reglas no dependen del día en que partiste, salvo la primera
compra). Sirve para ver qué perfil aguanta un mal comienzo, no para elegir el momento: eso solo se sabe mirando atrás.

Las variantes de holding (`variante` en `lib_perfiles`) se deciden una vez por día, al cerrar la vela diaria, con
`lib_holding.paso`: el mismo paso que mide la comparación. En vivo compran y venden con el precio de 1 m de ahora y la orden
más abajo se llena con el mínimo del día que acaba de cerrar. Cada compra queda como `compra_holding` y cada venta como
`venta_holding` (con `por`: `semana`, `limite`, `cierre`, `rebalanceo`, `cosecha` o `recompra`). La pantalla dice su plan
(«Mi plan»: cuántas compras lleva, qué orden dejó y a qué precio vendería o recompraría) con las reglas que manda
`lib_piloto.estado` (`reglas`).

**Por qué no hay perfiles de señales** (medido en nov 2026 con velas diarias reales de Binance, eligiendo con 2018-06 → 2023-11 y probando una
sola vez con 2023-11 → 2026-11, el tramo que nadie miró al elegir):
- Los cuatro perfiles de señales (conservador, equilibrado, trader y scalper) perdieron o quedaron en cero contra quedarse en
  USDT en 3 años. Quedan **retirados** (`RETIRADOS`): no se ofrecen y uno que estaba andando se detiene solo (`vivo.retirar`).
  Su máquina sigue porque es la de los tres modos del dinero real.
- Seguir la tendencia, la rotación con tamaño por volatilidad, comprar las bajas dentro de una subida y no vender nunca con
  pérdida: la mejor variante de cada idea en el tramo de elegir quedó muy por debajo de comprar BTC y esperar en el tramo de
  prueba (de −28 % a +32 %, contra +96 % de BTC). No se suman.
- La rotación simple fue la única que aguantó los dos tramos, y sin ventaja clara: según cuándo reparte da entre +55 % y +96 %
  en el tramo de prueba. Por eso va como experimento y la pantalla lo dice.
- Para volver a probar una idea hace falta un tramo nuevo que nadie haya mirado: el de 2023-11 → 2026-11 ya se usó.
- **103 fórmulas en muchas ventanas** (nov 2026, solo cripto): reglas de tendencia, rotación, volatilidad, mezclas, compra
  semanal y rebalanceo, medidas en ventanas de 1 a 4 años que empiezan cada mes. Se eligieron las 5 mejores solo con las
  ventanas que terminan antes de 2023-11 y se miraron una vez en las que empiezan después. Ninguna le gana a BTC en todas
  las ventanas. Las de «BTC (o BTC y ETH) solo sobre su media de 50 días» le ganan en 5 o 6 de cada 10 ventanas de prueba,
  con una peor ventana de 1 año de −7 % a −17 % contra −45 % de BTC: pierden un poco en las subidas fuertes (inicios de
  2024) y ganan en las caídas (inicios de 2025). Son 103 intentos y el tramo de prueba es un solo mercado: es una pista, no
  una ventaja probada. Las acciones no se midieron: tienen pocos meses de historia.
- **Cripto y acciones van aparte** en la pantalla (`lib_perfiles.mercado_de`: `cripto`, `acciones` o `mixto`, que sale en los
  dos lados): las criptos operan siempre, caen más y tienen años de historia; las acciones siguen el horario de EE. UU. y en
  Binance tienen meses. El mapa de inicios solo se muestra en cripto.

Reglas que no se cambian sin pensarlo dos veces:
- **Las mismas reglas en el pasado y en vivo.** `lib_perfiles` es el único lugar de los números, y lo usan `lib_simulacion` y
  `lib_piloto`. Un perfil solo puede achicar el riesgo (`lib_tamano.RIESGO` es el techo, lo revisa un `assert`).
- **Solo en prueba.** Con el ambiente real activo, `lib_piloto.decidir` no hace nada propio y deciden los tres modos. Empezar
  reinicia el saldo de prueba (`lib_estado.reiniciar`, queda en el registro con `perfil_empezado`).
- **La orden pasa por lo de siempre**: el tamaño del perfil, `lib_frenos` y `lib_ejecutor_prueba.entrar`, que no abre nada sin
  su protección. El robot no tiene un camino propio para poner una orden.
- **Cada vela se mira una sola vez** (`vistas` en `piloto.json`) y **una vela atrasada no es una señal de ahora**
  (`sin_datos`). Por eso el muestreo deja al día también las velas de 1 h, 4 h y 1 d (`muestreo.velas_al_dia`).
- **Las compras del holding viven en `estado/piloto.json`**, no en el estado firmado: es dinero ficticio y no tiene órdenes.
  Cada compra queda en el registro (`compra_holding`).
- **Pilota prepara sola lo que falta al abrir** (`prepararSola` en `ui/app.js`): el flujo en vivo (siempre, también en la vista
  previa), los mínimos, el muestreo y el historial. Cada cosa se pide una vez por sesión; en la vista previa solo el flujo,
  salvo con `?auto`.
- **Reacciona al cerrar la vela, no antes.** El flujo (`vivo.py encender`) muestra la vela en curso cada segundo, pero se decide
  con velas cerradas, igual que en el pasado: la revisión corre en el segundo en que cierra cada minuto. En prueba, un stop o
  un objetivo se aplica al cerrar el minuto con el precio del nivel; en real la protección vive en Binance y salta al instante.
- **El radar explica, no decide** (`lib_radar`): usa las mismas reglas y números de `lib_estrategias` para decir a qué precio
  compraría, cuánto falta y por qué la otra jugada no aplica. La probabilidad que muestra es la **historia** de esa jugada
  (las operaciones que de verdad habría hecho en el pasado), siempre con cuántas fueron y dicha como pasado, no como promesa.
  Cada entrada guarda esa historia en `piloto.json` (`jugadas`) para mostrarla junto a la compra.
- **Cada perfil opera sus monedas** (`lib_perfiles`: `pares`, `pares_de`), todas contra USDT y solo en prueba. El dinero real
  sigue en BTC y ETH contra FDUSD (`lib_datos.PARES_OPERADOS`) hasta que estas monedas pasen su prueba en vivo: el conector
  real no las conoce. Las de las ocho se preparan solas en segundo plano (`vivo.preparar_universo`), sus velas largas se piden
  en el minuto en que cierran (`vivo.largas_al_dia`) y sus velas de 1 m se guardan cuando ya tienen historia y nunca más de
  `lib_datos.DIAS_MINUTOS` días.
- **La rotación decide una vez al día** (`lib_piloto._vuelta_rotacion`): al cerrar la vela diaria ordena las ocho por fuerza,
  tiene las `posiciones` mejores que estén sobre su promedio y cambia una solo cuando sale de los `posiciones + margen`
  primeros. Compra y vende a mercado con la comisión taker y la diferencia de puntas, y solo con un precio de 1 m fresco
  (`PRECIO_FRESCO_MS`). Si BTC cae o hay un freno, vende todo y espera en USDT. Cada cambio queda en el registro
  (`rotacion_compra`, `rotacion_venta`).
- **El gráfico no decide nada**: muestra las velas guardadas más la que se está formando, las marcas del registro y las líneas
  de lo abierto. Sus indicadores se calculan en la pantalla con las mismas fórmulas de `lib_indicadores*`.

## La pantalla principal

Lo que se ve al abrir Pilota se arma en un solo lugar (`bin/lib_panel.py`, acciones `panelEstado` y `panelLocal` en
`bin/panel.py`) y se dibuja en `ui/panel.js`, aparte de `ui/app.js` para que los dos queden chicos.

| Qué se ve | De dónde sale |
|---|---|
| la banda de prueba o real | `lib_estado.activo` (`ambiente`, `ficticio`): arriba de todo y de otro color en cada ambiente |
| el saldo con la línea del piso | `lib_frenos.piso_de` y `dia_de` sobre el estado firmado (`sobre_piso` es la barra, de 0 a 1) |
| la referencia en moneda local | `panel/local.json`: la moneda y la tasa **las escribe la persona** (no hay ningún servicio de cambio) |
| los medidores por par | el último tamaño escrito (`lib_tamano.guardado`): de cada par, la oportunidad que más puntúa contra la exigencia |
| las posiciones y las propuestas | `lib_ejecutor_prueba.guardado` y `lib_modos.estado` (de ahí sale `queda_ms`, la cuenta atrás) |
| el motor y el registro | `lib_reconciliar.estado` y el `registro` de la cuenta activa (las últimas `LINEAS`) |
| la mascota y la línea diaria | `mascota_de` y `dia_de`: ánimo (`ANIMOS`) y código (`CUENTOS`) con sus números |

Reglas de esta pantalla:
- **No decide, no opera y no toca la red**: junta lo que ya está escrito. Lo único que se mueve al mirar es lo que ya se
  movía al abrir las otras pantallas (una propuesta pasada de hora vence en `lib_modos.estado`: mirar es aplicar).
- **Un número que no está no se inventa.** Sin tamaño escrito, el medidor va sin puntaje y con su motivo; sin velas de
  1 m, una posición va sin ganancia; sin tasa, no hay ninguna equivalencia en moneda local.
- **La moneda local es una referencia y se dice**: el monto va con la nota «referencia, la operación es en USDT», nunca
  en vez de los USDT.
- **La banda queda pegada arriba** (`.banda` es `sticky`, z-index 3: bajo los diálogos) y debajo dice en dos frases con
  qué dinero se juega. Cada término lleva su ayuda corta al lado de lo que explica (el piso, el puntaje, la exigencia), y
  «OCO» se muestra siempre como «protección automática».
- **«Puntaje» es la oportunidad y «exigencia» el corte**, en todo el texto: cada medidor dice con palabras si está
  «Sobre la exigencia» o «Bajo la exigencia», no solo con el color de su barra.
- **La mascota no opina: cuenta.** Manda el freno puesto, después el aviso del mercado (`aviso`: la comisión o FDUSD
  pasados, que en prueba no frenan y se dicen igual), después lo que recién cerró (`neutral`, sin celebrar, hasta
  `RECIEN_MS`), después lo que espera tu respuesta, después lo abierto (`llenas` cuando están las que caben) y al final
  lo que está mirando: `bajo_exigencia` si no llega, `rechazada` si pasa y no sale monto (con el motivo del tamaño en su
  propia frase), `apagado` si pasa y el motor no está mirando, y `sobre_exigencia` si pasa y lo decide en la próxima
  revisión. Los cinco ánimos cambian la carita y el borde; el ánimo también va en palabras, para quien no la ve.
- **El registro se lee después de mirar los modos**: mirar es aplicar, así que la propuesta que venció al mirar ya
  cuenta en la línea diaria (`dia.vencidas`) y en «Lo último que hice» de esta misma vuelta.
- **Las palabras viven en la pantalla**, como siempre: el Python manda códigos y números (`ANIMOS`, `CUENTOS`,
  `MOTIVOS`) y `ui/panel.js` los cuenta en frases completas, con su inglés en `ui/idiomas/en.json`.
- **La cuenta atrás es del navegador** (`latir`, una vez por segundo, solo ese texto): la propuesta vence en el Python,
  no en la pantalla. El número de propuestas vencidas hoy (`vencidas_hoy`) se muestra igual haya o no una esperando.
- **Una posición dice si está protegida**: una abierta sin su protección automática se lee distinto (el estado en
  `incompleto` y su línea en `freno`), y una puesta dice hasta cuándo espera (`vence_ms`): puesta no es llenada.
- **El motor dice hace cuánto miró y qué se perdió** (`hace_min`, `resumen`, con las mismas palabras de su pantalla), y
  el aviso de que **Pilota solo trabaja con el equipo encendido** está siempre a la vista, no solo cuando está apagado.
- **Una línea del registro se muestra con sus campos fijos** (`lib_registro.CAMPOS`): fecha, par, puntaje, razón, lo que
  pidió la orden (`ORDENES`, `ESTADO_ORDEN`) y cómo terminó. Del Python vienen números y códigos; una clave que la
  pantalla no conoce no se muestra.

Dónde queda: `<datos>/panel/local.json` (moneda y tasa de referencia). Todo lo demás se lee de los archivos de su paso.

## Los trabajos en segundo plano

Lo que tarda minutos o no termina nunca corre como **trabajo** (pieza «trabajos», con `bin/lib_trabajo.py` en medio).
Pilota tiene tres:

| Trabajo | Qué hace | Acciones |
|---|---|---|
| `historial` (`bin/historial.py`) | Los **3 años** de las 12 series, por etapas (`1d`, `4h`, `1h`: de lo más barato a lo más caro). | `historialEstado`, `historialDescargar`, `historialDetener` |
| `muestreo` (`bin/muestreo.py`) | Cada **5 minutos**: el mejor precio de compra y de venta y los últimos trades de los dos pares que se operan, más las velas de 1 m de los últimos 30 días al día. | `muestreoEstado`, `muestreoEncender`, `muestreoApagar` |
| `motor` (`bin/motor.py`) | Cada **5 minutos**: la revisión que reconcilia (frenos, velas de 1 m perdidas, lo huérfano y la ventana sin cobertura). | `motorEstado`, `motorRevisar`, `motorEncender`, `motorApagar` |
| `vivo` (`bin/vivo.py`) | **Siempre conectado**: el flujo de Binance al segundo. Cada segundo publica la vela en curso y, al cerrar cada minuto, guarda la vela y hace la revisión completa en ese instante. | `vivoEncender` (progreso `vivoProgreso`) |

Reglas que no se cambian sin pensarlo dos veces:
- **Uno solo de cada tipo** (`lib_candado.unico`): si ya hay un motor, un muestreo o un flujo corriendo, el segundo contesta
  `ya_corriendo` y no parte. Y **una revisión a la vez**: `lib_reconciliar.reconciliar` toma su candado, así el motor y el flujo
  pueden convivir sin pisar el estado firmado. **Si la app se cierra de golpe, el trabajo termina solo** (`huerfano`).
- **Se guarda en cada página.** `lib_datos.bajar_tramo` guarda las velas y el plan en cada pedido que trae algo nuevo, y revisa
  «Detener» **antes** de cada pedido. Así «Detener» y «Seguir donde quedó» no pierden ni repiten nada, y cerrar la app tampoco.
- **«Empezar» y «Seguir donde quedó» son la misma acción**: el plan en disco (`siguiente` de cada serie) dice desde dónde va.
  Si el plan se perdió, se vuelve a recorrer sin perder ninguna vela (lo guardado se reconoce con `lib_datos.fin_continuo`).
- **El avance se mide en pedidos a Binance**, no en velas: cada pedido trae hasta 1000 velas y tarda más o menos lo mismo, y hay
  pares con menos historia que la ventana (FDUSD), que nunca llegarían al 100 % contando velas. El tiempo que falta sale de los
  segundos por pedido **medidos** en la vuelta (hasta entonces, `SEGUNDOS_POR_PEDIDO`).
- **La historia que no existe no se inventa ni se pide dos veces**: si Binance no tiene velas de un tramo, ese tramo queda
  recorrido y el plan guarda desde cuándo hay (`desde`). El empalme con el par de USDT es cosa del backtest, en su paso.
- **Continuidad al terminar cada par.** Antes de dar una serie por terminada, el historial largo la revisa paso por paso con
  lo que hay en disco (`historial.revisar`, sobre `lib_datos.huecos`) y vuelve a pedir **solo** los tramos que falten: un
  pedido por hoyo, nunca la serie de nuevo. Un hoyo que sobrevive queda anotado (`huecos`, `continua`), la pantalla lo dice y
  la vuelta siguiente lo reintenta: una serie con hoyos da medias y rupturas falsas, así que `terminada()` pide las dos cosas
  (recorrida y continua).
- **Las muestras del mercado no se recuperan después.** Binance no da libro histórico: lo que no se guarde hoy no existe. Por eso
  se guardan desde el primer día, una línea por muestra, y nunca se reescriben.
- **Una vuelta mala no termina el muestreo.** Un tropezón de red o un límite de Binance se anota en el plan (`fallos`, `error`),
  la pantalla lo dice y en 5 minutos se vuelve a intentar; recién con `muestreo.FALLOS_SEGUIDOS` vueltas malas seguidas el
  trabajo termina en `error`. Una vuelta buena borra la cuenta. (El historial largo es al revés: ahí un error corta, porque
  «Seguir donde quedó» retoma sin perder nada.)
- **El hueco queda escrito.** Cada vuelta que no alcanzó a muestrear anota su ventana sin libro (`sin_cobertura`): las vueltas
  malas seguidas son un solo hueco y la primera vuelta buena lo cierra. Si lo que falló fue el historial de 1 m, no hay hueco
  que anotar (esas velas se vuelven a pedir donde quedaron), y lo que se guardó antes de cortarse el ciclo se cuenta igual:
  ya está en disco.
- **La pantalla no manda ids de trabajo**: «Detener» busca solo el último trabajo de ese tipo (`lib_trabajo.ultimo`). Un trabajo
  que dice «corriendo» y dejó de latir quedó `interrumpido`: la pantalla ofrece «Seguir donde quedó».
- El avance llega a la interfaz por el **evento de progreso** del trabajo (`historialProgreso`, `muestreoProgreso`,
  `motorProgreso`, con el resumen en `trabajo.avance`) y además queda escrito en el plan: las dos cosas dicen lo mismo.
- **Los trabajos se ven igual** en la pantalla (`historial()`, `muestreo()` y `motor()` en `ui/app.js`): en qué quedó
  (`lineaHistorial`, `lineaMuestreo`, `lineaMotor`) y un solo botón que cambia de nombre según el estado. Los dos que bajan
  cosas tienen además la barra con el porcentaje, el tramo o la etapa y el tiempo que falta
  (`duracion(falta_segundos)`), y su botón cambia de nombre según el estado («Bajar los 3 años», «Seguir donde quedó»,
  «Rellenar los huecos», «Detener»). Del muestreo se muestran además la última vuelta (`cuando`) y las ventanas que
  quedaron sin muestras (`sin_cobertura`); del motor, hace cuánto fue la última revisión, el resumen de la ventana que
  nadie miró (`resumenMotor`) y las ventanas sin cobertura.

<!-- La app: aquí van las secciones propias de la app («Cómo funciona», el formato de sus archivos, el puente con sus acciones,
lo que hace cada app nativa…). Escribe lo que una persona o una IA necesita para cambiar algo sin romperlo; nada más. -->

## Piezas (de [Pieza](https://github.com/pieza-app/pieza))
Pilota usa piezas de Pieza, la base de la familia de apps: código probado que se copia a la app (modelo «copiar y adueñarse»).

| Pieza | Versión | Archivos | Qué usa Pilota |
|---|---|---|---|
| `actualizaciones` | 0.5.2 | `escritorio/src/pieza/actualizaciones.rs` | <!-- La app: qué usa de «Actualizaciones» --> |
| `bienvenida` | 0.4.1 | `ui/bienvenida.css`, `ui/bienvenida.js` | <!-- La app: qué usa de «Bienvenida» --> |
| `componentes` | 0.3.1 | `ui/componentes.css`, `ui/componentes.js` | <!-- La app: qué usa de «Componentes» --> |
| `contrato` | 0.1.3 | `pruebas/contrato.py` | <!-- La app: qué usa de «Contrato del puente» --> |
| `empaquetado` | 0.2.2 | `herramientas/python.lock` | <!-- La app: qué usa de «Empaquetado» --> |
| `esqueleto` | 0.2.1 |  | <!-- La app: qué usa de «Esqueleto de una app nueva» --> |
| `github` | 0.3.1 |  | <!-- La app: qué usa de «Repo listo para la comunidad» --> |
| `host-tauri` | 0.1.3 | `escritorio/iconos/128x128.png`, `escritorio/iconos/128x128@2x.png`, `escritorio/iconos/32x32.png`, `escritorio/iconos/icon.icns`, `escritorio/iconos/icon.ico`, `escritorio/iconos/icono.png`, `escritorio/src/pieza/enchufe.rs`, `escritorio/src/pieza/host.rs`, `escritorio/src/pieza/mod.rs`, `escritorio/src/pieza/procesador.rs`, `escritorio/src/pieza/protocolo.rs`, `escritorio/src/pieza/sistema.rs`, `escritorio/src/pieza/vigilante.rs` | <!-- La app: qué usa de «App de Mac, Windows y Linux» --> |
| `host-ui` | 0.3.0 | `ui/host.js` | <!-- La app: qué usa de «Puente de la interfaz» --> |
| `i18n` | 0.3.1 | `ui/i18n.js` | <!-- La app: qué usa de «Idiomas» --> |
| `ia` | 0.7.2 | `bin/ia.py` | <!-- La app: qué usa de «Tu IA» --> |
| `mcp` | 0.1.0 | `bin/mcp.py`, `bin/mcp_conectar.py`, `bin/mcp_servidor.py`, `ui/mcp.js` | Las herramientas de solo lectura (`bin/mcp_herramientas.py`) y la sección «Conectar a tu IA» de Ajustes (`PiezaMCP`: `mcpEstado`, `mcpConectar` → `mcpListo`). `mcpReparar` queda fuera (`app.json` → `sin_acciones`). |
| `nucleo` | 0.7.1 | `bin/nucleo.py` | <!-- La app: qué usa de «Núcleo» --> |
| `pagina` | 0.1.3 | `docs/pagina-comunes.json`, `docs/pagina.css`, `docs/pagina.js`, `docs/sello-en.svg`, `docs/sello.svg`, `docs/tema.css`, `herramientas/pagina_capturas.mjs` | <!-- La app: qué usa de «Página pública» --> |
| `tema` | 0.3.0 | `ui/tema.css`, `ui/tema.js` | <!-- La app: qué usa de «Temas: claro, oscuro y vidrio» --> |
| `trabajos` | 0.2.2 | `bin/trabajos.py`, `escritorio/src/pieza/progreso.rs` | Los dos trabajos en segundo plano (ver esa sección): `Trabajo.nuevo`, `latir`, `etapa`, `detenido`, `terminar`, `del_proyecto`, `estado_real` y `detener`, con `bin/lib_trabajo.py` en medio. El avance viaja en el evento `{"t": "estado", "trabajo": {…, "avance"}}`. |
| `universos` | 0.1.0 | `bin/universo_formato.py`, `ui/universos.js`, `ui/universos/bosque.json`, `ui/universos/espacio.json`, `ui/universos/neon.json` | <!-- La app: qué usa de «Universos» --> |

- **No edites a mano los archivos de una pieza.** Se actualizan con «Pieza al día» (`.github/workflows/pieza-al-dia.yml`, una vez por
  semana abre un PR o un issue) o con `python3 <pieza>/herramientas/pieza.py actualizar .`. Si hay que cambiar algo, el cambio va
  primero a Pieza (`pieza.py diferencias . <pieza>` lo muestra) y vuelve desde allá; `pieza.py estado .` dice si algo quedó distinto.
- Lo que **generan** las piezas desde `app.json` (el empaquetado, los workflows, las plantillas de GitHub) se vuelve a generar con
  `pieza.py generar .` después de cambiar `app.json`; si lo cambias a mano, desde ahí es de la app y Pieza ya no lo toca.
- `app.json` y `acciones.json` van dentro de las apps (los empaqueta `herramientas/empaquetar.sh` y `extraResources`). Después de
  cambiar una acción de `app.json`: `python3 <pieza>/herramientas/pieza.py acciones .`.
- `.gitignore` es una lista blanca: un archivo o carpeta nueva de la raíz se agrega ahí.
- Al agregar o actualizar una pieza, pon al día esta tabla (`pieza.py estado .` dice las versiones).

## Reglas al cambiar cosas
- Código, comentarios, commits y textos en **español** (de Chile neutro). Todo texto nuevo visible va con su traducción en
  `ui/idiomas/en.json` en el mismo cambio, como frase completa con marcadores (`T("Llevas {n}…", {n})`), nunca pedazos pegados.
- Contenido de la persona con `esc()` y `data-sin-traducir`. Lo que escribe la persona **nunca** va como argumento de un proceso.
- Archivos de piezas: no se editan aquí (ver «Piezas»). Colores con los tokens de «tema» y botones y diálogos de «componentes».
- Antes de cerrar un cambio: `bash pruebas/correr.sh` y mirar la interfaz (`cd ui && python3 -m http.server 8765`, `?idioma=en`,
  `?bienvenida`), también a 390 px y en claro y oscuro.
- Una prueba falla, nunca se cuelga ni depende del reloj: lo que la interfaz muestra solo mientras un trabajo avanza se revisa
  sobre lo anotado (`anotarAvance` en `pruebas/interfaz.mjs`), no mirando justo en ese instante, y un ciclo que corta «Detener»
  lleva además un tope de vueltas en la prueba.
- Seguridad (detalle en `SECURITY.md`): CSP sin scripts ni manejadores en línea; todo dato externo validado y escapado; la IA sin
  herramientas ni MCP. Workflows: actions fijadas por SHA con su versión en un comentario, `permissions` mínimos,
  `persist-credentials: false`, nunca `pull_request_target` ni `${{ github.event.* }}` dentro de `run:`.
- Privacidad: `bash herramientas/revisar_privacidad.sh` antes de cada commit (usa `.terminos-privados`, local y nunca versionado).
  Jamás subas datos reales, ni siquiera "para probar".
- Commits con autor `@users.noreply.github.com`. El repo es público: cada commit se ve al tiro.
- Swift solo compila en un Mac (o en el job `mac` de GitHub): imita código que ya compila y anota qué revisar en el Mac.
<!-- La app: suma las reglas propias (el formato de sus archivos, lo que nunca se cambia sin compatibilidad…). -->

## Lo que rodea a un cambio
Un cambio está listo cuando la app **y lo que la cuenta** dicen lo mismo. Antes de empezar, anota qué tipo de cambio es; al terminar,
revisa cada fila ("no aplica" se decide, no se supone):

| Si el cambio… | Deja al día |
|---|---|
| agrega o cambia una función | la página (`docs/`: funciones, «cómo funciona», comparación, preguntas frecuentes), el README y la guía si la hay |
| cambia lo que se ve | capturas de la página y del README (datos ficticios, español e inglés, normal y celular) e imagen para compartir si sale esa vista |
| cambia un flujo o un paso | instrucciones paso a paso, preguntas frecuentes, textos de la bienvenida e instalación si la toca |
| quita algo | bórralo de la página, el README y las guías: nada que prometa lo que ya no hace |
| cambia el formato de datos o el puente | la documentación del formato, `ejemplos/` si existe y esta guía |
| cambia carpetas, reglas o pruebas | esta guía (`AGENTS.md`) y `CONTRIBUTING.md` |
| actualiza o agrega una pieza | `piezas.json` (lo escribe `pieza.py`), la tabla «Piezas» de esta guía y `app.json` si pide config |
| resuelve un issue | ciérralo con «Resuelto en …» dando crédito y abre issues para lo que quedó pendiente |
| lo nota quien usa Pilota | `CHANGELOG.md`: una línea en «Sin publicar», en lenguaje de persona («Ahora puedes…»), en español e inglés |

Todo texto nuevo de la página y del README va en los dos idiomas, sin nada inventado. Antes de cerrar, busca con `grep` en `docs/` y el
README el nombre o el texto viejo de lo que cambió. Al publicar una versión (se sube `version` en `app.json`), las líneas de «Sin
publicar» pasan a su número. Los issues que abrimos para una tarea traen una sección «Qué actualizar alrededor» con las filas de
esta tabla que le tocan.

## Revisar aportes
Todo entra por pull request y lo junta quien mantiene el proyecto, solo con su aprobación. Leer todo el diff antes de correr nada
(alerta roja: workflows, scripts de instalación o empaquetado, la CSP, `innerHTML` sin `esc()`, red nueva, dependencias nuevas,
binarios, cómo se arma el comando o el pedido de la IA). Agentes: `.claude/agents/pilota-revisor.md` y `pilota-privacidad.md`.
Detalle en `CONTRIBUTING.md`.
