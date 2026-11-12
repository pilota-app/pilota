# Cambios · Changelog

Lo que cambia para quien usa Pilota, en palabras simples. Las descargas de cada versión están en
[Releases](https://github.com/pilota-app/pilota/releases).
*What changes for people using Pilota, in plain words. Downloads for each version are in Releases.*

## Sin publicar · Unreleased
<!-- Una línea por cambio que se nota, en lenguaje de persona («Ahora puedes…»), en español · *e inglés*. Al publicar una
versión (subir «version» en app.json), estas líneas pasan a «## X.Y.Z». -->
- Pilota ahora se ordena en cinco pestañas: Ahora, Simular, Operar, Historial y Cómo pienso. *Pilota is now organized in five
  tabs: Now, Simulate, Trade, History and How I think.*
- Nuevo: «Simular». Eliges un monto y un período y ves qué habría hecho Pilota con él, con las reglas de hoy, al lado de quedarte
  en USDT y de comprar BTC y esperar. Después lo pruebas en vivo con ese monto ficticio. *New: "Simulate". Choose an amount and a
  period and see what Pilota would have done with it, with today's rules, next to staying in USDT and buying BTC and holding.
  Then try it live with that play money.*
- Nuevo: «Operar». Conectas tu llave de Binance (se guarda en el llavero del Mac, nunca en un archivo) y, cuando cumples los cinco
  requisitos, enciendes el dinero real. Una llave que puede retirar no se acepta nunca. *New: "Trade". Connect your Binance key
  (stored in the Mac keychain, never in a file) and, once you meet the five requirements, turn on real money. A key that can
  withdraw is never accepted.*
- Arreglado: los avisos y algunos textos se traducían dos veces, y el registro podía mostrar un código en vez de un motivo.
  *Fixed: notices and some texts were translated twice, and the log could show a code instead of a reason.*
- La pantalla principal ahora es una cabina: el robot te cuenta qué hizo, una cadena de seis luces muestra cómo va cada parte
  de Pilota (mercado, puntaje, tamaño, frenos, tu sí y motor), el saldo se ve como un medidor entre el piso y tu capital, cada
  moneda tiene su dial de puntaje y cada propuesta muestra su stop, su entrada y su objetivo en una línea de colores. El detalle
  técnico sigue ahí, plegado en «Ver cómo lo pensé, paso a paso».
  *The main screen is now a cockpit: the robot tells you what it did, a chain of six lights shows how each part of Pilota is
  doing (market, score, size, brakes, your yes and engine), the balance is a gauge between the floor and your capital, each coin
  has its score dial and each proposal shows its stop, entry and target on a colored line. The technical detail is still there,
  folded under "See how I thought it through, step by step".*
- Arreglado: la barra del piso y los medidores de puntaje se veían siempre llenos o vacíos. *Fixed: the floor bar and the score
  meters always looked full or empty.*
- Arreglado: en inglés, la fila «Sin apalancamiento» mostraba código en vez de «1x». *Fixed: in English, the "No leverage" row
  showed code instead of "1x".*
- Ahora puedes descargar los últimos 90 días de velas cerradas de Binance (BTC y ETH, en 1 h, 4 h y 1 d) y ver, par por par, si
  el historial está completo. Mientras falte historia, Pilota lo dice en vez de operar.
  *You can now download the last 90 days of closed Binance candles (BTC and ETH, in 1 h, 4 h and 1 d) and see, pair by pair,
  whether the history is complete. While history is missing, Pilota says so instead of trading.*
- Ahora puedes ver el capital mínimo viable: lo menos con lo que Pilota puede operar, con los mínimos que Binance pide hoy,
  la reserva del 40 % en USDT, dos posiciones y la protección automática en los dos lados.
  *You can now see the minimum workable capital: the least Pilota can trade with, using the minimums Binance asks for today,
  the 40 % USDT reserve, two positions and automatic protection on both sides.*
- Ahora puedes bajar 3 años de historial en segundo plano, con su porcentaje y el tiempo que falta: lo detienes cuando quieras y
  después sigues donde quedaste, sin volver a bajar nada.
  *You can now download three years of history in the background, with its percentage and the time left: stop it whenever you
  want and later pick up where you left off, without downloading anything twice.*
- Al terminar cada par, Pilota revisa que no falte ninguna vela en medio y vuelve a pedir solo lo que falte. Si Binance no la
  entrega, te dice cuántos huecos quedaron y puedes rellenarlos después.
  *As each pair finishes, Pilota checks that no candle is missing in between and asks again only for what's missing. If Binance
  doesn't hand it over, it tells you how many gaps are left and you can fill them in later.*
- Ahora Pilota puede guardar cada 5 minutos el mejor precio de compra y de venta y los últimos trades, y mantener al día las
  velas de 1 minuto de los últimos 30 días, par por par. Binance no guarda el libro de antes: lo que no se guarde hoy no se
  recupera después, así que si una vuelta no resulta, Pilota lo dice, deja escrito el rato que quedó sin muestras y lo intenta
  de nuevo en vez de dejar de muestrear. En pantalla ves cuándo fue la última vuelta, cuándo viene la próxima y cuántas ventanas
  quedaron sin muestras.
  *Pilota can now save the best bid and ask and the latest trades every 5 minutes, and keep the 1-minute candles of the last 30
  days up to date, pair by pair. Binance doesn't keep the past order book: whatever isn't saved today can't be recovered later,
  so if a round doesn't work out, Pilota says so, writes down the stretch left without samples and tries again instead of
  stopping the sampling. On screen you see when the latest round was, when the next one is due and how many stretches were left
  without samples.*
- Ahora puedes ver, par por par y temporalidad por temporalidad, los indicadores con los que Pilota mira el mercado: las medias
  de 20, 50 y 200 velas, la fuerza de la tendencia (ADX) y el impulso (RSI y MACD). Siempre con velas cerradas y seguidas: si a
  una serie le falta historial, esa fila dice qué falta en vez de mostrar un número.
  *You can now see, pair by pair and timeframe by timeframe, the indicators Pilota uses to read the market: the 20, 50 and 200
  candle averages, the strength of the trend (ADX) and momentum (RSI and MACD). Always with closed candles in a row: if a series
  is missing history, that row says what's missing instead of showing a number.*
- Ahora cada serie muestra además cuánto se mueve el precio y en qué parte de su banda está (Bollinger y ATR), si el volumen
  acompaña y si rompió el techo o el piso de las últimas velas. Aparte ves cómo viene BTC en 1 d —el contexto con el que se
  mira todo lo demás— y cuánto cuesta entrar y salir ahora mismo: la comisión, la diferencia entre compra y venta de la última
  muestra del libro y la conversión USDT↔FDUSD. Si la muestra es vieja o no hay ninguna, Pilota lo dice en vez de inventar un
  costo.
  *Each series now also shows how much the price moves and where in its band it sits (Bollinger and ATR), whether volume is
  backing it up and whether it broke the ceiling or the floor of the last candles. Separately you see how BTC is doing in 1 d
  —the context everything else is read against— and what it costs to get in and out right now: the fee, the gap between bid and
  ask in the latest order book sample and the USDT↔FDUSD conversion. If the sample is old or there is none, Pilota says so
  instead of making a cost up.*
- Ahora puedes ver lo que ve Pilota con sus tres estrategias: entrar por una ruptura (el precio pasó el techo de las últimas
  velas con volumen y el día viene al alza), entrar por un rebote en la banda de abajo con el mercado sin rumbo, o quedarse en
  USDT. Cada señal dice par, temporalidad, nivel de entrada, stop y objetivo, y cuánto arriesga para cuánto gana. Si BTC cae,
  Pilota no entra a nada y te dice por qué; si falta el historial de 1 d con el que mide el día, lo dice en vez de suponerlo.
  *You can now see what Pilota sees with its three strategies: get in on a breakout (the price went past the ceiling of the
  last candles with volume and the day is heading up), get in on a bounce off the lower band with the market going nowhere, or
  stay in USDT. Each signal says the pair, the timeframe, the entry level, the stop and the target, and how much it risks for
  how much it makes. If BTC is falling, Pilota enters nothing and tells you why; if the 1 d history it measures the day with is
  missing, it says so instead of assuming it.*
- Ahora puedes correr el backtest de esas señales sobre todo el historial y ver qué habrían dado, sin inventar nada: cada
  señal pone su orden límite y solo se llena si el precio sigue en contra, el stop paga lo que cuesta salir a mercado y se
  descuentan la comisión de cada lado y la conversión USDT↔FDUSD. El resultado se compara con quedarse en USDT y con comprar
  BTC y esperar, te muestra qué pasaría si una orden límite se llenara más fácil o más difícil, marca las velas que se
  pidieron prestadas al par contra USDT y te dice si hay casos suficientes para calibrar: si no hay, lo dice en vez de darte
  un número bonito.
  *You can now run the backtest of those signals over the whole history and see what they would have given, without making
  anything up: each signal places its limit order and only fills if the price keeps going against it, the stop pays what
  getting out at market costs, and the fee on each side plus the USDT↔FDUSD conversion are taken off. The result is compared
  with staying in USDT and with buying BTC and waiting, it shows you what would happen if a limit order filled more easily or
  less easily, it marks the candles borrowed from the pair against USDT and it tells you whether there are enough cases to
  calibrate: if there aren't, it says so instead of handing you a pretty number.*
- Ahora cada oportunidad trae su puntaje de 0 a 100: las siete familias de indicadores se convierten en una nota cada una y
  las siete juntas dan el puntaje, así que puedes ver por qué una oportunidad puntúa alto o bajo. Al lado va con qué
  probabilidad gana —sacada de las operaciones del historial parecidas, con su rango y diciendo con cuántos casos— y cuánto
  deja o cuesta después de costos. Quedarse en USDT también puntúa, así que una oportunidad siempre se compara con no hacer
  nada, de frente y en la misma escala. Si a una familia le falta su número, Pilota puntúa con las demás y lo dice; y si
  la que falta es para dónde va el precio, cómo viene BTC o cuánto cuesta entrar y salir, no hay puntaje: eso no se
  supone. Mientras no haya calibración, Pilota avisa que el puntaje está sin calibrar y le exige 85 para entrar.
  *Each opportunity now comes with its score from 0 to 100: the seven families of indicators each turn into a mark and the
  seven together give the score, so you can see why an opportunity scores high or low. Next to it is how likely it is to win
  —taken from similar operations in the history, with its range and saying how many cases it's based on— and how much it
  leaves or costs after costs. Staying in USDT scores too, so an opportunity is always compared with doing nothing, head to
  head and on the same scale. If a family is missing its number, Pilota scores with the rest and says so; and if the missing
  one is where the price is heading, how BTC is doing or what it costs to get in and out, there is no score: that is not
  assumed. While there is no calibration, Pilota warns that the score is uncalibrated and demands 85 to enter.*
- Ahora la probabilidad de ganar no sale de «una ruptura de BTC en 4 h», sino de las oportunidades del historial que
  puntuaron como la de ahora: después de recorrer el historial, Pilota reparte esas operaciones en cinco tramos de puntaje
  y te dice, para el tramo de cada oportunidad, con qué frecuencia ganó, cuánto dejó después de costos —comisión de los
  dos lados, diferencia entre compra y venta y conversión USDT↔FDUSD—, el rango de las dos cosas y con cuántos casos está
  calculado. Si en ese tramo hay pocos casos, lo dice en vez de darte una probabilidad que no se sostiene.
  *The odds of winning no longer come from "a BTC breakout on 4 h", but from the opportunities in the history that scored
  like the one you have now: after walking through the history, Pilota splits those operations into five score buckets and
  tells you, for each opportunity's bucket, how often it won, how much it left after costs —the fee on both sides, the gap
  between bid and ask and the USDT↔FDUSD conversion—, the range of both and how many cases it's based on. If that bucket
  has too few cases, it says so instead of handing you odds that don't hold up.*
- Ahora puedes calibrar el puntaje: Pilota aparta el último año del historial antes de mover un solo peso, ajusta cuánto pesa
  cada familia con ventanas de 12 meses probando con los 3 siguientes (como máximo 3 vueltas, y te dice cuántas dio y con cuál
  quedó), vuelve a correr el backtest con el puntaje y la exigencia puestos y recién entonces hace la prueba final, una sola
  vez, con ese año apartado y contra un criterio escrito de antemano que puedes revisar entero. Si aprueba, el modelo queda
  «Validado» con su exigencia; si no aprueba —o si al backtest le faltaron casos y tuvo que ensanchar sus tramos—, queda «No
  validado»: la exigencia se va a 85 y el monto por posición queda topado. La prueba final no se gasta dos veces: para volver
  a probar hace falta historial nuevo que el modelo no haya visto, y Pilota te dice cuánto falta.
  *You can now calibrate the score: Pilota sets the last year of the history aside before moving a single weight, fits how much
  each family weighs with 12-month windows tested on the 3 that follow (at most 3 rounds, and it tells you how many it ran and
  which one it kept), runs the backtest again with the score and the demand in place and only then runs the final test, once,
  on that set-aside year and against a criterion written beforehand that you can review in full. If it passes, the model ends
  up "Validated" with its demand; if it doesn't —or if the backtest ran short of cases and had to widen its buckets— it ends up
  "Not validated": the demand goes to 85 and the amount per position stays capped. The final test isn't spent twice: testing
  again needs new history the model hasn't seen, and Pilota tells you how much is missing.*
- Ahora todo lo que Pilota decide queda en un registro que solo crece: cada línea con los mismos campos —fecha, par, puntaje,
  razón, orden y resultado— y ninguna se cambia ni se borra después. Y lo que Pilota sabe de sí misma —saldo, capital de
  referencia, modo y posiciones— vive en un archivo con huella, uno para la cuenta de prueba y otro para la real, con todo
  separado. Si ese archivo falta, su huella no cuadra o está fechado en el futuro, Pilota arranca frenada en modo manual, te
  dice por qué, no se cree ninguno de sus números y deja el archivo tal cual en vez de pisarlo. El saldo de prueba lo
  reinicias con una sola confirmación y al tiro, y el reinicio queda en el registro.
  *Everything Pilota decides now goes into a log that only grows: each line with the same fields —date, pair, score, reason,
  order and result— and none changed or erased afterwards. And what Pilota knows about itself —balance, reference capital,
  mode and positions— lives in a file with a fingerprint, one for the test account and one for the live account, with
  everything kept separate. If that file is missing, its fingerprint doesn't match or it's dated in the future, Pilota starts
  braked in manual mode, tells you why, doesn't trust any of its numbers and leaves the file exactly as it was instead of
  overwriting it. You reset the test balance with a single confirmation and right away, and the reset goes into the log.*
- Ahora Pilota te dice cuánto pondría en cada oportunidad, en USDT, y por qué ese monto y no otro: primero los mínimos que
  pide Binance con ese stop (la cantidad tiene que servir para la compra y para las dos patas de la protección), después la
  reserva del 40 % que se queda siempre en USDT, después que quepan dos posiciones y, por último, que la operación no
  arriesgue más del 2 % de tu capital, contando lo que cuesta salir. El monto es el menor de esos límites y la pantalla dice
  cuál fue el que cortó. Si con ese stop el monto queda bajo el mínimo de Binance, no abre nada y te dice cuál sería la
  posición más chica y desde cuánto capital sí se podría. Y mientras el modelo no esté validado, el monto por posición queda
  topado en 15 USDT.
  *Pilota now tells you how much it would put into each opportunity, in USDT, and why that amount and not another: first the
  minimums Binance asks for with that stop (the quantity has to work for the buy and for both legs of the protection), then
  the 40 % reserve that always stays in USDT, then that two positions fit and, last, that the operation doesn't risk more
  than 2 % of your capital, counting what getting out costs. The amount is the smallest of those limits and the screen says
  which one cut it. If with that stop the amount comes out under Binance's minimum, it opens nothing and tells you what the
  smallest position would be and from how much capital it would work. And while the model isn't validated, the amount per
  position stays capped at 15 USDT.*
- Ahora puedes ver los frenos y lo que vigila cada uno, con su número: sin apalancamiento, dos posiciones como máximo, un 5 %
  perdido cierra el día (y te dice a qué hora se levanta), cuatro pérdidas seguidas vuelven a manual, un 25 % bajo el capital
  de referencia no abre nada y, más abajo todavía, el piso absoluto sobre lo que aportaste cierra a mercado lo que quede
  abierto. Dos frenos más miran el mercado —que la comisión no se pase de la que supuso el backtest y que FDUSD siga valiendo
  un dólar—: en prueba no frenan, pero te los avisa igual. «Pausar» cancela las entradas y no toca ninguna protección
  automática: lo que esté abierto sigue protegido y te dice con cuántas posiciones te quedas. Y el piso lo puedes desbloquear
  a mano: en real, pidiéndolo y esperando 24 horas, como máximo dos veces y siempre anotado en el registro.
  *You can now see the brakes and what each one watches, with its number: no leverage, two positions at most, 5 % lost closes
  the day (and it tells you what time it lifts), four losses in a row go back to manual, 25 % below the reference capital
  opens nothing and, lower still, the absolute floor on what you paid in closes whatever is open at market. Two more brakes
  watch the market —that the fee doesn't go above the one the backtest assumed and that FDUSD is still worth a dollar—: in
  test mode they don't brake, but you're told anyway. Pausing cancels entries and doesn't touch any automatic protection:
  whatever is open stays protected and it tells you how many positions you keep. And you can unlock the floor by hand: in
  live mode, by asking and waiting 24 hours, twice at most and always written into the log.*
- Ahora Pilota opera en modo prueba con dinero ficticio: pone la entrada, le arma su protección automática y va mirando las
  velas de 1 minuto para saber si se llenó, si tocó el stop o si llegó al objetivo, con los mismos precios, mínimos y costos
  de Binance. Antes de poner nada revisa que la protección quepa en los tres niveles y en los dos lados —si no cabe, no abre
  la posición— y ninguna orden pasa sin haber pasado por el monto y por los frenos. Si la mitad que saldría en el objetivo
  queda bajo el mínimo de Binance, la posición sale entera; cuando el stop sube, cancela la protección y pone otra, y te dice
  cuántas veces. Las órdenes de Pilota quedan marcadas como suyas: lo que no lleva su marca no lo cancela ni lo cierra nunca.
  Como en prueba la protección solo existe con el computador encendido, la pantalla te dice hasta cuándo llegan las velas que
  la cuidan y cuánto rato quedó sin cubrir.
  *Pilota now trades in test mode with fake money: it places the entry, sets up its automatic protection and watches the
  1-minute candles to tell whether it filled, hit the stop or reached the target, with Binance's real prices, minimums and
  costs. Before placing anything it checks that the protection fits at all three levels and on both sides —if it doesn't fit,
  the position isn't opened— and no order goes through without having passed the amount and the brakes. If the half that
  would exit at the target falls below Binance's minimum, the position exits whole; when the stop moves up, it cancels the
  protection and places another, and tells you how many times. Pilota's orders are marked as its own: anything without that
  mark is never cancelled or closed. Since in test mode the protection only exists while the computer is on, the screen tells
  you how far the candles that watch it reach and how long went uncovered.*
- Ahora Pilota revisa cada 5 minutos y, al arrancar o al despertar, recorre las velas de 1 minuto que se perdió: aplica los
  stops y los objetivos que se cruzaron, repone la protección automática donde el stop móvil la movió, cancela la entrada
  que venció y cierra lo que quedó sin protección. En pantalla ves hace cuánto fue la última revisión, si está activo o
  dormido y un resumen de lo que pasó mientras nadie miraba («Dormiste 9 h: 1 stop, 2 propuestas vencidas»). El rato sin
  cubrir queda escrito en vez de taparse, y mientras las velas que faltan no lleguen, esa ventana sigue abierta: es el rato
  en que un stop no se habría aplicado. Pilota solo trabaja con el equipo encendido.
  *Pilota now checks every 5 minutes and, when it starts or wakes up, walks through the 1-minute candles it missed: it
  applies the stops and targets that were crossed, puts back the automatic protection wherever the trailing stop moved it,
  cancels the entry that expired and closes whatever was left unprotected. On screen you see how long ago the last check
  was, whether it's running or asleep and a summary of what happened while nobody was watching ("You slept 9 h: 1 stop, 2
  expired proposals"). The uncovered time is written down instead of covered up, and while the missing candles haven't
  arrived that stretch stays open: it's the time when a stop wouldn't have been applied. Pilota only works while the
  computer is on.*
- Ahora eliges quién dice «sí» a cada operación. En manual, Pilota te propone con todo lo que hace falta para decidir
  —puntaje, razón, monto en USDT y stop— y espera tu respuesta los 5, 15 o 60 minutos que elijas: si nadie responde, la
  propuesta vence, y eso queda en el registro. En semiautomático opera sola cuando el puntaje es claramente alto y el
  monto cabe en el que dejaste (15 USDT por defecto, visible y editable); si no, te pregunta. El automático opera solo y
  se activa confirmando dos veces. Mientras el modelo no esté calibrado, el semiautomático y el automático quedan
  apagados y te digo por qué, y tras cualquier freno vuelvo a manual.
  *You now choose who says "yes" to each trade. On manual, Pilota proposes with everything you need to decide —score,
  reason, amount in USDT and stop— and waits for your answer for the 5, 15 or 60 minutes you choose: if nobody answers,
  the proposal expires, and that goes into the log. On semi-automatic it trades on its own when the score is clearly
  high and the amount fits the one you left (15 USDT by default, visible and editable); otherwise it asks you.
  Automatic trades on its own and is turned on by confirming twice. While the model isn't calibrated, semi-automatic and
  automatic stay off and I tell you why, and after any brake I go back to manual.*
- Ahora, al abrir Pilota, una banda de color se queda pegada arriba diciendo con qué dinero se juega («Prueba: dinero
  ficticio» o «Real: dinero de verdad»), y debajo ves tu saldo en USDT con la línea del piso dibujada —hasta dónde puede
  bajar antes de que Pilota deje de abrir cosas— y, si le dices a cuánto está un USDT en tu moneda, cuánto es más o menos
  en ella, siempre como referencia. Y un medidor por moneda con el puntaje de su mejor oportunidad junto a la exigencia,
  que te dice con palabras si está sobre o bajo ella. Cada término lleva su ayuda corta al lado.
  *When you open Pilota, a coloured band now stays pinned at the top telling you which money is in play ("Test mode: play
  money" or "Live mode: real money"), and below it you see your balance in USDT with the floor line drawn —how far it can
  fall before Pilota stops opening anything— and, if you tell it what one USDT is worth in your currency, roughly how much
  that is, always as a reference. Plus one gauge per coin with its best opportunity's score next to the threshold, which
  tells you in words whether it's above or below it. Each term comes with its short help next to it.*
- En la misma pantalla ves ahora lo que tienes abierto —cuántas posiciones de las que caben, lo que lleva ganada cada una,
  su stop, su objetivo y si tiene puesta su protección automática—, lo que te está proponiendo Pilota con el tiempo que
  queda para responder corriendo en pantalla y cuántas propuestas vencieron hoy, hace cuánto fue la última revisión del
  motor con lo que pasó mientras nadie miraba, y lo último que hizo con los campos de siempre: fecha, par, puntaje,
  razón, la orden que se pidió y cómo terminó. Y el aviso de siempre a la vista: Pilota solo trabaja con el equipo
  encendido.
  *That same screen now shows what you have open —how many positions out of those that fit, what each one is at, its
  stop, its target and whether its automatic protection is in place—, what Pilota is proposing to you with the time left
  to answer counting down on screen and how many proposals expired today, how long ago the engine's last check was along
  with what happened while nobody was watching, and the last thing it did with the usual fields: date, pair, score,
  reason, the order it asked for and how it ended. Plus the usual warning in plain sight: Pilota only works with the
  computer on.*
- Y arriba de todo eso, una mascota robot te cuenta en una frase qué está haciendo y por qué, con los números de
  verdad: el freno que tiene puesto, el aviso del mercado que en prueba no la frena, lo que acaba de cerrar (sin
  celebrarlo), lo que te está proponiendo con su monto y su stop, lo que tiene abierto, o por qué no entra —no llega a
  la exigencia, la pasa y no le sale ningún monto, o la pasa y el motor está apagado—. Cambia de carita según el caso.
  Y cuando el día pasa sin operar, lo dice derecho: «Hoy no operé: mejor puntaje 62, exigencia 72», más las propuestas
  que dejó pasar sin respuesta.
  *And above all that, a robot pet now tells you in one sentence what it's doing and why, with the real numbers: the
  brake it has on, the market warning that doesn't brake it in test mode, what it just closed (without celebrating it),
  what it's proposing to you with its amount and its stop, what it has open, or why it isn't getting in —it doesn't
  reach the threshold, it passes and no amount comes out, or it passes and the engine is off—. Its face changes to
  match. And when the day goes by without trading, it says so plainly: "I didn't trade today: best score 62, threshold
  72", plus the proposals it let go without an answer.*
- En Ajustes puedes conectar la IA que ya usas para preguntarle por tus datos de Pilota. Por defecto solo puede leer.
  *In Settings you can connect the AI you already use to ask it about your Pilota data. By default it can only read.*
