#!/usr/bin/env python3
"""lib_puntaje — el puntaje de 0 a 100 de cada oportunidad. Solo biblioteca estándar. No es una acción.

Las siete familias de indicadores (`bin/lib_indicadores.py` y `bin/lib_indicadores_mercado.py`) ya dicen cómo está el
mercado; aquí cada una se convierte en una **nota de 0 a 100** y las notas se juntan, con su peso, en el **puntaje** de la
oportunidad. Al lado del puntaje van los dos números que importan de verdad para decidir: la **probabilidad de ganar** que
dicen las operaciones del historial que puntuaron como esta —las de su **tramo de puntaje**— y la **ganancia esperada
después de costos**, las dos con su rango de confianza y diciendo con cuántos casos están calculadas. Y como hay una cuarta salida posible, **quedarse en USDT también se puntúa**: una oportunidad recién conviene
cuando puntúa más que quedarse quieto.

| Familia | Sus parámetros (2 o 3, nunca más) |
|---|---|
| tendencia | el orden de las medias de 20, 50 y 200 velas (el cierre sobre la larga, la corta sobre la media) y la fuerza del ADX |
| impulso | el RSI, mejor en el medio de la escala (comprar sobrecomprado o en caída libre vale menos), y el MACD relativo al precio |
| volatilidad | cuánto se mueve la serie (ATR relativo) y cuánto se abrió la banda de Bollinger: quieta no llega al objetivo, loca se come el stop |
| volumen | el volumen contra lo normal de las velas anteriores y el OBV relativo (para qué lado empujó el volumen) |
| estructura | el nivel roto y a qué distancia quedó: perseguir un nivel ya roto vale menos. Con el piso roto, cero |
| contexto | BTC en 1 d: cuánto se movió el último día cerrado y su distancia a la media de 200 días |
| costo | la comisión de los dos lados, la diferencia entre compra y venta y la conversión USDT↔FDUSD, contra lo que la oportunidad promete |

Cada familia devuelve las tres cosas juntas (`tendencia(v)`, `impulso(v)`, …): su **nota** de 0 a 100 —acotada siempre, por
rampas y bandas recortadas en los extremos—, los **parámetros** que la formaron (nombre, el valor con que se puntuó y la
nota que le tocó a cada uno) y una **razón** corta (`subiendo_con_fuerza`, `nivel_ya_pasado`, `btc_cayendo`…, las de
`RAZONES`), que es la que la pantalla y la mascota cuentan en palabras en sus pasos. Sin uno de sus números la familia no
tiene nota y la razón dice cuál faltó (`sin_adx`, `sin_media_200`, `sin_spread`…).

Las siete notas se juntan en **un** puntaje de 0 a 100 con los pesos de partida (`PESOS_BASE`, todas lo mismo) y el
desglose viaja al lado: cada familia con su nota, sus parámetros, su razón, su peso y la `parte` que le tocó del puntaje
final. Y como el puntaje se mira contra una **exigencia** —el corte para entrar—, aquí va también el estado del modelo
(`modelo`): mientras no haya calibración queda en `sin_calibrar` con la exigencia alta (`EXIGENCIA_SIN_CALIBRAR`, 85), que
es lo que corresponde cuando los pesos son los de partida y nadie los probó contra el historial todavía.

Las dos capas son las de siempre:
- Las de siempre, sobre un diccionario plano de valores (`familias`, `puntaje_de`, y las notas de cada familia): no leen
  nada del disco y no saben de dónde salieron los números. `de_velas` las recorre vela por vela sobre una serie entera:
  es la capa que va a usar la calibración, en su paso, para dejar pasar solo las señales que llegan a la exigencia
  (`backtest.correr(filtrar=…)`).
- Las de la app (`valores_de`, `opcion`, `estado`): el puntaje de **ahora** de cada par operado, leyendo el estado de
  indicadores, las señales crudas, el último backtest y los tramos medidos, sin recorrer las velas de nuevo. Y `medir`,
  que sí recorre el historial entero una vez para dejar escritos esos tramos (la acción `puntajeMedir`).

Lo que no se negocia aquí:
- **Un puntaje no es una orden ni una promesa.** Dice qué tan buena se ve una oportunidad con lo que se sabe hoy. La
  exigencia (el corte), el tamaño y los frenos son de sus propios pasos.
- **Ningún número se inventa, y las familias clave no se saltan.** A una familia sin su parámetro no se le pone una nota
  media: queda sin nota. Si la que falta es una de las tres **clave** (`FAMILIAS_CLAVE`: para dónde va el precio, cómo
  viene BTC y qué se lleva el costo), la oportunidad **no se puntúa** —queda con su motivo (`sin_costo`,
  `sin_contexto`…)—, porque entrar sin mirar eso es entrar a ciegas. Si la que falta es una de las otras, el puntaje sale
  con las que sí tienen dato, **renormalizando los pesos** (cada peso contra la suma de los presentes, no un cero que
  castiga de gratis) y queda marcado: `renormalizado` y `faltan` dicen cuáles fueron.
- **La probabilidad sale de las operaciones que de verdad hubo, y del tramo de puntaje de esta oportunidad.** `medir`
  recorre el historial puntuando cada señal cruda antes de seguirla y reparte las operaciones en los cinco tramos de 20
  puntos de `TRAMOS_PUNTAJE` (`tramos_de_puntaje`): así la pregunta que se contesta es la que importa —si puntuar 80 gana
  más seguido que puntuar 40—. Mientras los tramos no estén medidos, o si el de esta oportunidad no llega a
  `CASOS_PROBABILIDAD` casos, se baja al tramo de la compuerta (estrategia, par y temporalidad) y queda dicho de dónde
  salió (`fuente`, `origen`, `tramo`). Sin ninguno de los dos no hay probabilidad (`sin_backtest`, `pocos_casos`): con
  cuatro operaciones, una tasa de acierto es una anécdota.
- **La tasa se mide con las operaciones y el rango con los casos.** Dos operaciones que vivieron el mismo rato de mercado
  no son dos pruebas (`backtest.sin_solapar`), así que el rango de confianza (Wilson, `CONFIANZA`) se calcula con los
  casos que no se pisan: es más ancho, y es el que corresponde.
- **La regla de las velas sin 1 m es una sola y queda marcada**: cuando una vela tocó el stop y el objetivo y no hay
  velas de 1 m para saber qué pasó primero, se supone el stop (`lib_resolucion.SUPUESTO_SIN_1M`, el mismo código que
  `backtest.SUPUESTO_AMBIGUO`). Las operaciones con que se miden los tramos salen de ahí (`seguir` cierra con
  `lib_resolucion.cerrar`), el supuesto se valida contra los `lib_datos.DIAS_MINUTOS` días que sí tienen velas de 1 m y
  el reporte dice en cuántas acertó y con qué etiqueta salió cada operación (`supuestos`): la probabilidad de ganar
  arrastra ese supuesto y eso no se esconde.
- **Lo que gana y lo que pierde no son estimaciones.** `ganancia` los saca con los precios de la señal y los costos de
  cada lado (`lib_costos.resultado`): el objetivo sale con una límite (maker) y el stop a mercado (taker, cruzando el
  libro). Lo único estimado es la probabilidad, y por eso la ganancia esperada va con su rango.
- **Los pesos son los de partida: todas las familias pesan lo mismo** (`PESOS_BASE`), escrito antes de ver un solo
  resultado. Los mueve la calibración, en su paso (`puntaje_de(..., pesos=…)`), y el reporte dice con cuáles quedó.
- **Sin calibración, el modelo está `sin_calibrar` y la exigencia es 85.** No es un detalle de pantalla: con los pesos de
  partida nadie probó todavía que este puntaje separe lo bueno de lo malo, así que el corte va alto. La exigencia que de
  verdad se use sale de la calibración, en su paso, y hasta entonces `modelo()` dice las dos cosas: en qué estado está y
  con qué exigencia se está mirando.
- **Quedarse en USDT se puntúa en la misma escala**, así que las dos opciones se comparan de frente: `mejor_de` las mira
  juntas y una oportunidad recién conviene cuando puntúa más que quedarse quieto.
- **Nada se redondea.** El redondeo vive en la pantalla (`numero()` y `porcentaje()` en `ui/app.js`).

Dónde queda: `<datos>/mercado/puntaje.json` (lo que devuelve `estado()`, con la hora del cálculo) y
`<datos>/mercado/tramos.json` (los tramos de puntaje medidos, lo que devuelve `medir()`).
"""
import math
import os

import backtest
import lib_costos
import lib_datos
import lib_estrategias
import lib_indicadores
import lib_indicadores_mercado
import lib_resolucion
import nucleo

#: Las siete familias, en el orden en que se muestran y se pesan.
FAMILIAS = ("tendencia", "impulso", "volatilidad", "volumen", "estructura", "contexto", "costo")
#: Las tres familias sin las que no hay puntaje: para dónde va el precio, cómo viene BTC y qué se lleva el costo. Las otras
#: cuatro, si les falta el dato, salen del promedio y los pesos se renormalizan; estas tres no se pueden suplir con nada.
FAMILIAS_CLAVE = ("tendencia", "contexto", "costo")
#: Cuánto pesa cada familia en el puntaje. Al empezar, todas lo mismo: no hay ningún resultado todavía que diga otra cosa.
PESOS_BASE = {f: 1.0 for f in FAMILIAS}
PUNTAJE_MAXIMO = 100.0
#: El estado del modelo mientras no haya calibración, y la exigencia con la que se mira el puntaje entonces: alta, porque
#: los pesos son los de partida y nadie probó todavía que separen lo bueno de lo malo (la idea: «No validado», 85).
MODELO_SIN_CALIBRAR = "sin_calibrar"
EXIGENCIA_SIN_CALIBRAR = 85.0
#: El puntaje de quedarse en USDT cuando sí se puede entrar a algo: la mitad justa de la escala. Quedarse quieto no gana ni
#: pierde, así que una oportunidad recién conviene cuando puntúa más que esto.
PUNTAJE_USDT = 50.0
#: La mitad de la escala: desde esta nota para arriba una familia cuenta como buena cuando hay que elegir su razón.
NOTA_MEDIA = 50.0
#: Tendencia: desde qué ADX se considera que hay tendencia y desde cuál es una tendencia fuerte.
ADX_SIN_FUERZA, ADX_CON_FUERZA = 15.0, 40.0
#: Impulso: el RSI vale 100 entre `RSI_BUENO_BAJO` y `RSI_BUENO_ALTO`, y baja a cero en los extremos (en caída libre y
#: sobrecomprado). El MACD se mira relativo al precio: este es el histograma que ya es mucho (0,2 % del precio).
RSI_VENDIDO, RSI_BUENO_BAJO, RSI_BUENO_ALTO, RSI_COMPRADO = 30.0, 45.0, 65.0, 85.0
MACD_FUERTE = 0.002
#: Volatilidad: una serie que se mueve menos que `ATR_QUIETO` por vela no llega al objetivo antes de que la orden venza, y
#: una que se mueve más que `ATR_LOCO` se come cualquier stop. Lo mismo con lo abierta que está la banda de Bollinger.
ATR_QUIETO, ATR_BUENO_BAJO, ATR_BUENO_ALTO, ATR_LOCO = 0.001, 0.003, 0.02, 0.05
ANCHO_QUIETO, ANCHO_BUENO_BAJO, ANCHO_BUENO_ALTO, ANCHO_LOCO = 0.005, 0.01, 0.06, 0.15
#: Volumen: desde cuánto el volumen acompaña (`VOLUMEN_NORMAL` es lo normal de las velas anteriores) y qué parte del
#: volumen empujando para un lado ya es mucho.
VOLUMEN_FLOJO, VOLUMEN_NORMAL, VOLUMEN_FUERTE = 0.7, 1.0, 2.5
OBV_FUERTE = 0.3
#: Estructura: a qué distancia de un nivel ya roto se considera que la oportunidad se pasó (perseguir el precio).
EXTENSION_MAXIMA = 0.02
#: Contexto: el mismo movimiento de BTC que mira el filtro (`lib_estrategias.CAIDA_BTC`) y la distancia a su media de 200
#: días que ya es mucho para un lado o para el otro.
DISTANCIA_BTC = 0.10
#: Costo: si entrar y salir se lleva esta parte de lo que la oportunidad promete, la nota de la familia es cero.
COSTO_PARTE_MAXIMA = 0.5
#: El rango de confianza de la probabilidad de ganar: el 95 % y su z.
CONFIANZA, Z_CONFIANZA = 0.95, 1.959963984540054
#: Menos casos que estos no son una probabilidad, son una anécdota (la compuerta pide `backtest.CASOS_MINIMOS` para
#: calibrar; esto es lo mínimo para atreverse a mostrar una tasa).
CASOS_PROBABILIDAD = 30
#: Los bordes de los tramos de puntaje con los que se estima la probabilidad de ganar: cinco tramos de 20 puntos,
#: escritos antes de ver un solo resultado. Un puntaje cae en el tramo que lo contiene y el 100 cae en el último
#: («80-100»), no afuera. Son anchos a propósito: tramos más finos tendrían menos casos que los que hacen falta.
TRAMOS_PUNTAJE = (0.0, 20.0, 40.0, 60.0, 80.0, 100.0)
#: La razón corta que puede dar cada familia: un código por situación, que la pantalla y la mascota cuentan en palabras en
#: sus pasos. Una familia sin su número no da ninguna de estas: dice qué parámetro le faltó (`sin_adx`, `sin_spread`…).
RAZONES = {"tendencia": ("subiendo_con_fuerza", "subiendo_sin_fuerza", "medias_mezcladas", "bajando"),
           "impulso": ("acelerando", "macd_en_contra", "viene_cansado", "sobrecomprado"),
           "volatilidad": ("se_mueve_lo_justo", "muy_quieto", "muy_movido"),
           "volumen": ("volumen_acompana", "volumen_flojo", "volumen_en_contra"),
           "estructura": ("techo_recien_roto", "nivel_ya_pasado", "cerca_del_piso", "en_medio_del_rango", "piso_roto"),
           "contexto": ("btc_bien", "btc_bajo_su_media", "btc_cayendo"),
           "costo": ("costo_bajo", "costo_se_lleva_mucho")}


def ruta_puntaje():
    return os.path.join(lib_datos.carpeta_mercado(), "puntaje.json")


def ruta_tramos():
    """Donde quedan los tramos de puntaje medidos (`medir`): el puntaje de ahora los lee sin recorrer nada."""
    return os.path.join(lib_datos.carpeta_mercado(), "tramos.json")


def parametros():
    """Con qué números se puntúa cada familia: los lee la pantalla y los va a mover la calibración, en su paso."""
    return {"adx_sin_fuerza": ADX_SIN_FUERZA, "adx_con_fuerza": ADX_CON_FUERZA,
            "rsi": [RSI_VENDIDO, RSI_BUENO_BAJO, RSI_BUENO_ALTO, RSI_COMPRADO], "macd_fuerte": MACD_FUERTE,
            "atr": [ATR_QUIETO, ATR_BUENO_BAJO, ATR_BUENO_ALTO, ATR_LOCO],
            "ancho": [ANCHO_QUIETO, ANCHO_BUENO_BAJO, ANCHO_BUENO_ALTO, ANCHO_LOCO],
            "volumen_flojo": VOLUMEN_FLOJO, "volumen_normal": VOLUMEN_NORMAL,
            "volumen_fuerte": VOLUMEN_FUERTE, "obv_fuerte": OBV_FUERTE,
            "extension_maxima": EXTENSION_MAXIMA, "caida_btc": lib_estrategias.CAIDA_BTC,
            "distancia_btc": DISTANCIA_BTC, "costo_parte_maxima": COSTO_PARTE_MAXIMA, "puntaje_usdt": PUNTAJE_USDT,
            "nota_media": NOTA_MEDIA, "casos_probabilidad": CASOS_PROBABILIDAD, "confianza": CONFIANZA,
            "tramos_puntaje": list(TRAMOS_PUNTAJE), "exigencia_sin_calibrar": EXIGENCIA_SIN_CALIBRAR}


def modelo(calibracion=None):
    """En qué estado está el modelo con que se puntúa y con qué exigencia se está mirando el puntaje.

    Mientras no haya calibración —y en este paso todavía no hay ninguna— el estado es `MODELO_SIN_CALIBRAR`, los pesos son
    los de partida (`PESOS_BASE`, todas las familias lo mismo) y la exigencia es `EXIGENCIA_SIN_CALIBRAR`: con pesos que
    nadie probó contra el historial, el corte va alto. `calibracion` es el gancho de su paso: de ahí salen después el
    estado («validado» o «No validado»), los pesos con que quedó y la exigencia que de verdad se usa."""
    c = calibracion or {}
    pesos = c.get("pesos") or {}
    if not c.get("calibrado") or not pesos:
        return {"estado": MODELO_SIN_CALIBRAR, "calibrado": False, "exigencia": EXIGENCIA_SIN_CALIBRAR,
                "pesos": dict(PESOS_BASE), "cuando": "", "motivo": "sin_calibracion"}
    exigencia = c.get("exigencia")
    return {"estado": c.get("estado") or MODELO_SIN_CALIBRAR, "calibrado": True,
            "exigencia": EXIGENCIA_SIN_CALIBRAR if exigencia is None else float(exigencia),
            "pesos": {f: float(pesos.get(f, 0.0) or 0.0) for f in FAMILIAS}, "cuando": c.get("cuando") or "",
            "motivo": c.get("motivo") or ""}


# ── Las cuentas de siempre: de un valor a una nota de 0 a 100 ───────────────────────────────────────────────────────────────

def rampa(valor, bajo, alto):
    """De 0 a 100 entre `bajo` y `alto`, recortada en los extremos. Con `alto` menor que `bajo` va al revés (así se
    escriben las notas en que menos es mejor, como el costo). `None` si el valor no existe: no se inventa una nota."""
    if valor is None or alto == bajo:
        return None
    return 100.0 * min(1.0, max(0.0, (float(valor) - bajo) / (alto - bajo)))


def banda(valor, bajo, bueno_bajo, bueno_alto, alto):
    """100 mientras el valor esté entre `bueno_bajo` y `bueno_alto`, y bajando hasta 0 en `bajo` y en `alto`: la forma de
    las notas en que lo que vale es estar en el medio (el RSI, lo que se mueve una serie)."""
    if valor is None:
        return None
    if valor < bueno_bajo:
        return rampa(valor, bajo, bueno_bajo)
    if valor > bueno_alto:
        return rampa(valor, alto, bueno_alto)
    return 100.0


def _p(nombre, valor, nota=None):
    """Un parámetro de una familia: con qué número se puntuó y qué nota le tocó. Hay dos sin nota propia, porque la de la
    familia no es un promedio de los suyos: los tres pedazos del costo (se suman) y el nivel roto de la estructura (manda
    sobre la distancia). Nunca más de tres por familia: con más parámetros, nadie sabe qué movió la nota."""
    return {"nombre": nombre, "valor": None if valor is None else float(valor), "nota": nota}


def _promedio(parametros):
    """La nota de una familia que es el promedio de sus parámetros. Si a uno le falta el número, la familia no tiene nota:
    una familia a medias es un número falso, y un número falso es peor que ninguno."""
    if not parametros or any(p["nota"] is None for p in parametros):
        return None
    return math.fsum(p["nota"] for p in parametros) / len(parametros)


def _familia(nombre, parametros, nota, razon):
    """Lo que devuelve cada familia: su nota de 0 a 100, los parámetros que la formaron y una razón corta. `razon` llega
    como función porque sin nota no hay razón que dar: lo que se dice entonces es qué número faltó (`sin_adx`,
    `sin_media_200`…), que es lo único honesto cuando el indicador no está."""
    if nota is None:
        faltan = [p["nombre"] for p in parametros if p["valor"] is None]
        return {"familia": nombre, "nota": None, "parametros": parametros,
                "razon": "sin_" + (faltan[0] if faltan else nombre)}
    return {"familia": nombre, "nota": nota, "parametros": parametros, "razon": razon()}


def tendencia(v):
    """Para dónde va el precio y con cuánta fuerza: el orden de las tres medias (cuántas de las tres condiciones se
    cumplen —el cierre sobre la de 200, la de 20 sobre la de 50, la de 50 sobre la de 200—, que valen lo mismo) y el ADX.
    Sin la media de 200 velas no hay nota: es la que dice si esto es una subida o un rebote dentro de una caída."""
    cierre, corta, media, larga = v.get("cierre"), v.get("media_20"), v.get("media_50"), v.get("media_200")
    cuantas = (None if None in (cierre, corta, media, larga)
               else sum(1 for x in (cierre > larga, corta > media, media > larga) if x))
    ps = [_p("medias", cuantas, None if cuantas is None else 100.0 * cuantas / 3.0),
          _p("adx", v.get("adx"), rampa(v.get("adx"), ADX_SIN_FUERZA, ADX_CON_FUERZA))]

    def razon():
        if cuantas == 3:
            return "subiendo_con_fuerza" if ps[1]["nota"] >= NOTA_MEDIA else "subiendo_sin_fuerza"
        return "bajando" if cuantas == 0 else "medias_mezcladas"
    return _familia("tendencia", ps, _promedio(ps), razon)


def impulso(v):
    """Si el movimiento viene acelerando o cansado: el RSI (mejor en el medio: comprar sobrecomprado o en caída libre vale
    menos) y el histograma del MACD medido contra el precio, para que BTC y ETH se puedan comparar."""
    cierre, histograma, rsi = v.get("cierre"), v.get("histograma"), v.get("rsi")
    relativo = None if (histograma is None or not cierre) else histograma / cierre
    ps = [_p("rsi", rsi, banda(rsi, RSI_VENDIDO, RSI_BUENO_BAJO, RSI_BUENO_ALTO, RSI_COMPRADO)),
          _p("macd", relativo, rampa(relativo, -MACD_FUERTE, MACD_FUERTE))]

    def razon():
        if rsi > RSI_BUENO_ALTO:
            return "sobrecomprado"
        if rsi < RSI_BUENO_BAJO:
            return "viene_cansado"
        return "acelerando" if relativo > 0 else "macd_en_contra"
    return _familia("impulso", ps, _promedio(ps), razon)


def volatilidad(v):
    """Cuánto se mueve esta serie: lo justo. Una serie quieta no alcanza el objetivo antes de que la orden límite venza y
    una serie loca se come cualquier stop, así que las dos notas son bandas, no rampas."""
    medio, ancho = v.get("atr_relativo"), v.get("ancho")
    ps = [_p("atr_relativo", medio, banda(medio, ATR_QUIETO, ATR_BUENO_BAJO, ATR_BUENO_ALTO, ATR_LOCO)),
          _p("ancho", ancho, banda(ancho, ANCHO_QUIETO, ANCHO_BUENO_BAJO, ANCHO_BUENO_ALTO, ANCHO_LOCO))]

    def razon():
        if medio > ATR_BUENO_ALTO or ancho > ANCHO_BUENO_ALTO:
            return "muy_movido"
        if medio < ATR_BUENO_BAJO or ancho < ANCHO_BUENO_BAJO:
            return "muy_quieto"
        return "se_mueve_lo_justo"
    return _familia("volatilidad", ps, _promedio(ps), razon)


def volumen(v):
    """Si el volumen acompaña: cuántas veces lo normal se movió en esta vela y para qué lado empujó el de las últimas
    (el OBV relativo, de −1 a 1)."""
    relativo, obv = v.get("volumen_relativo"), v.get("obv_relativo")
    ps = [_p("volumen_relativo", relativo, rampa(relativo, VOLUMEN_FLOJO, VOLUMEN_FUERTE)),
          _p("obv_relativo", obv, rampa(obv, -OBV_FUERTE, OBV_FUERTE))]

    def razon():
        if obv < 0:
            return "volumen_en_contra"
        return "volumen_acompana" if relativo >= VOLUMEN_NORMAL else "volumen_flojo"
    return _familia("volumen", ps, _promedio(ps), razon)


def estructura(v):
    """Dónde quedó el precio contra los niveles de las velas anteriores: qué nivel se rompió (`nivel_roto`: 1 el techo,
    −1 el piso, 0 ninguno) y a qué distancia quedó el precio de él. Esta familia no promedia: con el piso roto la nota es
    cero, no importa lo demás, porque la estructura se quebró para abajo. Con el techo roto, la nota es qué tan pegado al
    nivel está —perseguir un nivel que ya quedó `EXTENSION_MAXIMA` atrás vale cero— y sin ningún nivel roto, lo que vale
    es estar cerca del piso y no en medio del rango."""
    techo, piso = v.get("rompio_maximo"), v.get("rompio_minimo")
    arriba, abajo = v.get("distancia_maximo"), v.get("distancia_minimo")
    falta = techo is None or piso is None or arriba is None or abajo is None
    nivel = None if falta else (-1.0 if piso else (1.0 if techo else 0.0))
    distancia = None if falta else (arriba if techo else abajo)
    nota = None if falta else (0.0 if piso else rampa(distancia, EXTENSION_MAXIMA, 0.0))
    ps = [_p("nivel_roto", nivel), _p("distancia", distancia, nota)]

    def razon():
        if piso:
            return "piso_roto"
        if techo:
            return "techo_recien_roto" if nota >= NOTA_MEDIA else "nivel_ya_pasado"
        return "cerca_del_piso" if nota >= NOTA_MEDIA else "en_medio_del_rango"
    return _familia("estructura", ps, nota, razon)


def contexto(v):
    """Cómo viene BTC: los dos parámetros de la familia contexto. No reemplaza al filtro de BTC —ese no deja entrar a nada
    y vive en las estrategias—: aquí BTC cayendo baja el puntaje de todo, también el de ETH."""
    cambio, distancia = v.get("btc_cambio"), v.get("btc_distancia")
    ps = [_p("btc_cambio", cambio, rampa(cambio, -lib_estrategias.CAIDA_BTC, lib_estrategias.CAIDA_BTC)),
          _p("btc_distancia", distancia, rampa(distancia, -DISTANCIA_BTC, DISTANCIA_BTC))]

    def razon():
        if cambio < 0:
            return "btc_cayendo"
        return "btc_bien" if distancia >= 0 else "btc_bajo_su_media"
    return _familia("contexto", ps, _promedio(ps), razon)


def costo(v):
    """Qué parte de lo que la oportunidad promete se lleva entrar y salir. Sus tres parámetros son los tres costos que se
    pagan —la comisión de los dos lados, la diferencia entre compra y venta de la última muestra del libro y la conversión
    USDT↔FDUSD—, y la nota sale de los tres sumados contra la distancia al objetivo: si se llevan `COSTO_PARTE_MAXIMA` de
    lo que promete, la familia vale cero. Sin la muestra del libro no hay nota: el costo del momento no se inventa."""
    comision, spread, conversion = v.get("costo_comision"), v.get("costo_spread"), v.get("costo_conversion")
    objetivo = v.get("distancia_objetivo")
    ps = [_p("comision", comision), _p("spread", spread), _p("conversion", conversion)]
    hay = all(p["valor"] is not None for p in ps)
    parte = None if (not hay or not objetivo) else (comision + spread + conversion) / objetivo
    nota = rampa(parte, COSTO_PARTE_MAXIMA, 0.0)
    return _familia("costo", ps, nota, lambda: "costo_bajo" if nota >= NOTA_MEDIA else "costo_se_lleva_mucho")


NOTAS = {"tendencia": tendencia, "impulso": impulso, "volatilidad": volatilidad, "volumen": volumen,
         "estructura": estructura, "contexto": contexto, "costo": costo}


def familias(v):
    """Las siete familias de un diccionario de valores, cada una con su nota de 0 a 100 (o `None` si le falta algún
    parámetro), los parámetros que la formaron y su razón corta."""
    return {f: NOTAS[f](v or {}) for f in FAMILIAS}


def puntaje_de(v, pesos=None):
    """El puntaje de 0 a 100 de una oportunidad: las siete notas en un solo número, cada una con su peso, y el desglose
    por familia al lado (su nota, sus parámetros, su razón, su `peso` y la `parte` que le tocó del puntaje).

    Lo que se hace con una familia sin dato depende de cuál sea:
    - una de las tres **clave** (`FAMILIAS_CLAVE`) → no hay puntaje: `puntaje` en `None` y `motivo` con la primera que
      falta (`sin_costo`, `sin_contexto`, `sin_tendencia`). Entrar sin saber para dónde va el precio, cómo viene BTC o qué
      se lleva el costo es entrar a ciegas;
    - una de las otras cuatro → sale del promedio y los pesos se **renormalizan** entre las que sí tienen dato (cada peso
      contra la suma de los presentes). Queda marcado en `renormalizado` y en `faltan`: el puntaje es comparable con los
      demás, pero se mira con una familia menos y eso se dice.

    `pesos` es el gancho de la calibración (su paso): sin él, los de partida (`PESOS_BASE`, todas lo mismo)."""
    notas = familias(v)
    p = PESOS_BASE if pesos is None else pesos
    pesadas = [{**notas[f], "peso": float(p.get(f, 0.0) or 0.0)} for f in FAMILIAS]
    faltan = [d["familia"] for d in pesadas if d["nota"] is None]
    claves = [f for f in faltan if f in FAMILIAS_CLAVE]
    total = math.fsum(d["peso"] for d in pesadas if d["nota"] is not None)
    motivo = ("sin_" + claves[0]) if claves else ("sin_pesos" if total <= 0 else "")
    detalle = [{**d, "parte": 0.0 if (motivo or d["nota"] is None) else d["peso"] / total} for d in pesadas]
    if motivo:
        return {"puntaje": None, "familias": detalle, "faltan": faltan, "renormalizado": False, "motivo": motivo}
    return {"puntaje": math.fsum(d["nota"] * d["parte"] for d in detalle if d["nota"] is not None),
            "familias": detalle, "faltan": faltan, "renormalizado": bool(faltan), "motivo": ""}


# ── La probabilidad de ganar y la ganancia esperada después de costos ───────────────────────────────────────────────────────

def wilson(tasa, casos, z=Z_CONFIANZA):
    """El rango de confianza de una proporción, por el método de Wilson: el que no se sale de 0 a 1 ni con pocos casos
    (el de la fórmula de siempre, con 40 casos y una tasa alta, promete probabilidades sobre 1). Sin casos, sin rango."""
    if tasa is None or not casos or casos <= 0:
        return None, None
    p = min(1.0, max(0.0, float(tasa)))
    n = float(casos)
    divisor = 1.0 + z * z / n
    centro = (p + z * z / (2 * n)) / divisor
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / divisor
    return max(0.0, centro - margen), min(1.0, centro + margen)


def nombre_tramo(desde, hasta):
    """Cómo se llama un tramo de puntaje: sus dos bordes (`"60-80"`). Es el código con el que viaja; la pantalla lo
    cuenta en palabras en su paso."""
    return f"{int(desde)}-{int(hasta)}"


def bordes_de(puntaje):
    """En qué tramo de puntaje cae un puntaje: `(desde, hasta)`, o `None` si no hay puntaje. El borde de abajo entra y el
    de arriba no, salvo el último (un puntaje de 100 cae en `"80-100"`)."""
    if puntaje is None:
        return None
    p = min(PUNTAJE_MAXIMO, max(0.0, float(puntaje)))
    for desde, hasta in zip(TRAMOS_PUNTAJE, TRAMOS_PUNTAJE[1:]):
        if p < hasta or hasta >= PUNTAJE_MAXIMO:
            return desde, hasta
    return None


def _tramo_puntaje(desde, hasta, ops):
    """Un tramo de puntaje con sus números: cuántas operaciones cayeron ahí, cuántos **casos** son esas operaciones (las
    que no se pisan entre sí, `backtest.sin_solapar`), con qué frecuencia ganaron y su rango de confianza (Wilson, con
    los casos), y lo que dejaron después de costos —lo que dejó una ganadora, lo que costó una perdedora y la ganancia
    esperada del tramo, con el rango que le da el rango de la probabilidad—.

    Un tramo sin casos suficientes no se tapa: queda con `pocos` y `motivo` en `pocos_casos`, y la tasa igual se dice
    para que se vea cuántos casos hay. Un tramo vacío es un tramo con cero casos, no un tramo que no existe."""
    casos = backtest.sin_solapar(ops)
    d = {"tramo": nombre_tramo(desde, hasta), "desde": float(desde), "hasta": float(hasta), "operaciones": len(ops),
         "casos": casos, "ganadoras": 0, "perdedoras": 0,
         "ambiguas": sum(1 for o in ops if o.get("ambigua")), "aciertos": None, "bajo": None, "alto": None,
         "gana_medio": None, "pierde_medio": None, "neto_medio": None, "esperada": None, "esperada_bajo": None,
         "esperada_alto": None, "confianza": CONFIANZA, "casos_minimos": CASOS_PROBABILIDAD, "pocos": True,
         "motivo": "pocos_casos"}
    netos = [o["neto"] for o in ops]
    if not netos:
        return d
    ganan = [n for n in netos if n > 0]
    pierden = [n for n in netos if n <= 0]
    d.update(ganadoras=len(ganan), perdedoras=len(pierden), aciertos=len(ganan) / len(netos),
             neto_medio=math.fsum(netos) / len(netos),
             gana_medio=(math.fsum(ganan) / len(ganan)) if ganan else None,
             pierde_medio=(math.fsum(pierden) / len(pierden)) if pierden else None,
             pocos=casos < CASOS_PROBABILIDAD)
    d["bajo"], d["alto"] = wilson(d["aciertos"], d["casos"])
    d["esperada"] = d["neto_medio"]      # la esperada del tramo es lo que de verdad dejaron: nada de estimarla
    if d["gana_medio"] is not None and d["pierde_medio"] is not None:
        esperar = lambda q: q * d["gana_medio"] + (1 - q) * d["pierde_medio"]   # noqa: E731
        d["esperada_bajo"] = None if d["bajo"] is None else esperar(d["bajo"])
        d["esperada_alto"] = None if d["alto"] is None else esperar(d["alto"])
    d["motivo"] = "pocos_casos" if d["pocos"] else ""
    return d


def tramos_de_puntaje(operaciones):
    """Los cinco tramos de puntaje (`TRAMOS_PUNTAJE`) con las operaciones del backtest de señales crudas repartidas por
    el puntaje que tenían cuando se decidieron. Es la tabla con la que una oportunidad de ahora sabe con qué probabilidad
    gana: no «una ruptura de BTC en 4 h», sino «una oportunidad que puntuó como esta».

    Se cuentan solo las que **cerraron**, las que el filtro de BTC dejaba entrar —una señal que Pilota nunca habría
    tomado no es un caso— y las que tenían puntaje: una operación sin puntaje (le faltaba una familia clave) no dice nada
    de ningún tramo."""
    suyas = {nombre_tramo(a, b): [] for a, b in zip(TRAMOS_PUNTAJE, TRAMOS_PUNTAJE[1:])}
    for o in operaciones or []:
        if o.get("motivo") or not o.get("permitida") or o.get("neto") is None:
            continue
        bordes = bordes_de(o.get("puntaje"))
        if bordes is not None:
            suyas[nombre_tramo(*bordes)].append(o)
    return [_tramo_puntaje(a, b, suyas[nombre_tramo(a, b)]) for a, b in zip(TRAMOS_PUNTAJE, TRAMOS_PUNTAJE[1:])]


def de_tramo(tramos, puntaje):
    """El tramo de puntaje que le toca a una oportunidad, de una tabla ya medida (`medir`). `None` si no hay tabla medida
    o si la oportunidad no tiene puntaje: sin puntaje no hay tramo del que sacar nada."""
    bordes = bordes_de(puntaje)
    if not (tramos or {}).get("corrido") or bordes is None:
        return None
    nombre = nombre_tramo(*bordes)
    return next((t for t in tramos.get("tramos") or [] if t.get("tramo") == nombre), None)


def tramo_de(nivel, estrategia, par, temporalidad):
    """El tramo de un nivel de la compuerta que le corresponde a esta oportunidad: en el nivel «normal» es su estrategia,
    par y temporalidad; en los del plan B, el que las junta (ahí `par` y `temporalidad` van vacíos)."""
    quiere = {"estrategia": estrategia, "par": par, "temporalidad": temporalidad}
    claves = (nivel or {}).get("claves") or []
    for t in (nivel or {}).get("tramos") or []:
        if claves and all(t.get(k) == quiere.get(k) for k in claves):
            return t
    return None


def evidencia(reporte, estrategia, par, temporalidad, puntaje=None, tramos=None):
    """Con qué operaciones se estima la probabilidad de ganar de esta oportunidad, y de dónde salieron.

    Primero, **su tramo de puntaje** (`de_tramo`, de la tabla que mide `medir`): las operaciones del backtest de señales
    crudas que puntuaron como esta. Es la pregunta que de verdad importa —si puntuar 80 gana más seguido que puntuar
    40, ahí se ve— y por eso va antes que cualquier otra cosa.

    Si los tramos todavía no están medidos, o si el de esta oportunidad no llega a `CASOS_PROBABILIDAD` casos, se baja al
    tramo de la compuerta del backtest guardado: su estrategia, par y temporalidad primero y, si ese no alcanza, los
    ensanchados del plan B. De dónde salió queda dicho siempre: `fuente` (`puntaje` o `compuerta`), `origen` (el nivel de
    la compuerta) y `tramo` con sus bordes.

    La tasa sale de las operaciones que cerraron y el rango, de los casos que no se pisan entre sí: dos operaciones que
    vivieron el mismo rato de mercado no son dos pruebas. Y con menos casos que `CASOS_PROBABILIDAD` no hay probabilidad
    (`pocos`, `pocos_casos`): una tasa de cuatro operaciones es una anécdota, no un número para decidir."""
    d = {"fuente": "", "origen": "", "tramo": "", "desde": None, "hasta": None, "casos": 0, "operaciones": 0,
         "ganadoras": 0, "aciertos": None, "bajo": None, "alto": None, "confianza": CONFIANZA,
         "casos_minimos": CASOS_PROBABILIDAD, "pocos": True, "no_validado": True, "motivo": "sin_backtest"}
    t = de_tramo(tramos, puntaje)
    if t:
        d.update(tramo=t.get("tramo") or "", desde=t.get("desde"), hasta=t.get("hasta"),
                 casos=t.get("casos") or 0, operaciones=t.get("operaciones") or 0, motivo="pocos_casos")
        if not t.get("pocos", True) and t.get("operaciones"):
            return {**d, "fuente": "puntaje", "origen": "normal", "ganadoras": t.get("ganadoras") or 0,
                    "aciertos": t.get("aciertos"), "bajo": t.get("bajo"), "alto": t.get("alto"), "pocos": False,
                    "no_validado": bool((tramos or {}).get("no_validado", True)), "motivo": ""}
    if not (reporte or {}).get("corrido"):
        return d
    compuerta = reporte.get("compuerta") or {}
    d["motivo"] = "pocos_casos"
    for nivel in compuerta.get("niveles") or []:
        tr = tramo_de(nivel, estrategia, par, temporalidad)
        r = (tr or {}).get("resumen") or {}
        if not tr or tr.get("casos", 0) < CASOS_PROBABILIDAD or not r.get("operaciones"):
            continue
        bajo, alto = wilson(r.get("aciertos"), tr["casos"])
        d.update(fuente="compuerta", origen=nivel.get("nivel") or "", casos=tr["casos"], operaciones=r["operaciones"],
                 ganadoras=r.get("ganadoras") or 0, aciertos=r.get("aciertos"), bajo=bajo, alto=alto, pocos=False,
                 no_validado=bool(nivel.get("nivel") != "normal" or compuerta.get("no_validado")), motivo="")
        break
    return d


def ganancia(senal, spread, com, ev=None):
    """Lo que deja esta oportunidad, en tanto por uno del monto y **después de costos**: lo que gana si llega al objetivo
    (sale con una límite: maker), lo que cuesta si se va al stop (sale a mercado: taker, y además cruza el libro) y la
    ganancia esperada con la probabilidad de ganar de su tramo (`evidencia`), con el rango que le da el rango de esa
    probabilidad.

    Lo que gana y lo que pierde no son estimaciones: son cuentas con los precios de la señal (`lib_costos.resultado`). Lo
    único estimado es la probabilidad, y por eso la esperada va con su rango y nunca sola."""
    d = {"gana": None, "pierde": None, "esperada": None, "bajo": None, "alto": None, "probabilidad": None,
         "probabilidad_bajo": None, "probabilidad_alto": None, "confianza": CONFIANZA}
    entrada, stop, objetivo = (senal or {}).get("entrada"), (senal or {}).get("stop"), (senal or {}).get("objetivo")
    if not entrada or not stop or not objetivo or spread is None or not com:
        return d
    d["gana"] = lib_costos.resultado(entrada, objetivo, "objetivo", spread, com)["neto"]
    d["pierde"] = lib_costos.resultado(entrada, stop, "stop", spread, com)["neto"]
    p = (ev or {}).get("aciertos")
    if p is None:
        return d
    esperar = lambda q: q * d["gana"] + (1 - q) * d["pierde"]   # noqa: E731
    bajo, alto = (ev or {}).get("bajo"), (ev or {}).get("alto")
    d.update(probabilidad=p, probabilidad_bajo=bajo, probabilidad_alto=alto, esperada=esperar(p),
             bajo=None if bajo is None else esperar(bajo), alto=None if alto is None else esperar(alto))
    return d


# ── Una oportunidad puntuada, y la de quedarse en USDT ──────────────────────────────────────────────────────────────────────

def _contexto(c):
    """Los dos parámetros de la familia contexto, vengan del estado de indicadores (que ya trae `distancia_media`) o de
    una vela de `lib_estrategias.contexto_diario` (que trae el cierre y la media)."""
    c = c or {}
    cierre, media, distancia = c.get("cierre"), c.get("media_200"), c.get("distancia_media")
    if distancia is None and media and cierre is not None:
        distancia = (cierre - media) / media
    return {"btc_cambio": c.get("cambio"), "btc_distancia": distancia}


def _costo(c, com):
    """Los tres parámetros de la familia costo: la comisión de los dos lados y la conversión USDT↔FDUSD, leídas de la API
    antes del ciclo, y la diferencia entre compra y venta de la última muestra del libro de ese par. Lo que falta queda en
    `None` con su nombre —casi siempre el `spread`, que es el que pide una muestra al día—: el costo no se supone."""
    c, com = c or {}, com or {}
    maker, taker = com.get("maker"), com.get("taker")
    return {"comision": None if maker is None or taker is None else maker + taker,
            "spread": c.get("spread_relativo") if c.get("listo") else None, "conversion": com.get("conversion")}


def valores_de(serie, contexto_btc=None, costo=None, senal=None):
    """El diccionario plano con el que se puntúan las siete familias, armado desde una fila del estado de indicadores, el
    contexto de BTC, el costo del momento de ese par (`_costo`) y la señal que se está mirando: de la señal sale lo que
    promete la oportunidad, que es contra lo que se mide el costo."""
    s = serie or {}
    t, i = s.get("tendencia") or {}, s.get("impulso") or {}
    v, vol, e = s.get("volatilidad") or {}, s.get("volumen") or {}, s.get("estructura") or {}
    d = {"cierre": s.get("cierre"), "media_20": t.get("media_20"), "media_50": t.get("media_50"),
         "media_200": t.get("media_200"), "adx": t.get("adx"), "rsi": i.get("rsi"), "histograma": i.get("histograma"),
         "ancho": v.get("ancho"), "atr_relativo": v.get("atr_relativo"), "volumen_relativo": vol.get("relativo"),
         "obv_relativo": vol.get("obv_relativo"), "rompio_maximo": e.get("rompio_maximo"),
         "rompio_minimo": e.get("rompio_minimo"), "distancia_maximo": e.get("distancia_maximo"),
         "distancia_minimo": e.get("distancia_minimo"),
         "costo_comision": (costo or {}).get("comision"), "costo_spread": (costo or {}).get("spread"),
         "costo_conversion": (costo or {}).get("conversion"),
         "distancia_stop": (senal or {}).get("distancia_stop"),
         "distancia_objetivo": (senal or {}).get("distancia_objetivo")}
    d.update(_contexto(contexto_btc))
    return d


def opcion(senal, valores, reporte=None, spread=None, com=None, pesos=None, tramos=None):
    """Una oportunidad puntuada: la señal cruda tal como vino, con su puntaje por familias, la probabilidad de ganar del
    tramo de puntaje en que cae (o, mientras no estén medidos, la de su tramo en la compuerta del backtest) y la ganancia
    esperada después de costos con su rango. El puntaje se saca **antes** que la probabilidad, porque es el puntaje el que
    dice de qué tramo sale."""
    p = puntaje_de(valores, pesos)
    ev = evidencia(reporte, senal.get("estrategia"), senal.get("par"), senal.get("temporalidad"),
                   puntaje=p["puntaje"], tramos=tramos)
    return {"estrategia": senal.get("estrategia"), "par": senal.get("par") or "",
            "temporalidad": senal.get("temporalidad") or "", "razon": senal.get("razon") or "",
            "vela": senal.get("vela"), "entrada": senal.get("entrada"), "stop": senal.get("stop"),
            "objetivo": senal.get("objetivo"), "distancia_stop": senal.get("distancia_stop"),
            "distancia_objetivo": senal.get("distancia_objetivo"), "vence": senal.get("vence"),
            "permitida": bool(senal.get("permitida")), "filtro": senal.get("filtro") or "",
            "puntaje": p["puntaje"], "familias": p["familias"], "faltan": p["faltan"],
            "renormalizado": p["renormalizado"], "motivo": p["motivo"],
            "ganancia": ganancia(senal, spread, com, ev), "evidencia": ev}


def quedarse(filtro, opciones=()):
    """El puntaje de la cuarta salida: quedarse en USDT, **en la misma escala de 0 a 100** que las demás, para que las dos
    opciones se comparen de frente (`mejor_de`). Vale `PUNTAJE_USDT` —la mitad justa de la escala, porque quedarse quieto
    no gana ni pierde— y `PUNTAJE_MAXIMO` cuando no hay nada que mirar: si el filtro de BTC no deja entrar o ninguna
    estrategia se gatilló, quedarse no es una opción más, es la única.

    No tiene familias (no hay indicadores de no hacer nada), no tiene probabilidad de ganar (no es una apuesta) y su
    ganancia esperada es cero, exacta: por eso es la vara con la que se comparan las demás."""
    entrables = [o for o in opciones if o.get("permitida")]
    sola = not (filtro or {}).get("pasa") or not entrables
    razon = "btc" if not (filtro or {}).get("pasa") else ("hay_oportunidades" if entrables else "sin_oportunidad")
    return {"estrategia": "usdt", "par": "", "temporalidad": "", "razon": razon, "vela": None, "entrada": None,
            "stop": None, "objetivo": None, "distancia_stop": None, "distancia_objetivo": None, "vence": None,
            "permitida": True, "filtro": (filtro or {}).get("motivo") or "", "sola": sola,
            "puntaje": PUNTAJE_MAXIMO if sola else PUNTAJE_USDT, "familias": [], "faltan": [],
            "renormalizado": False, "motivo": "",
            "ganancia": {"gana": 0.0, "pierde": 0.0, "esperada": 0.0, "bajo": 0.0, "alto": 0.0, "probabilidad": None,
                         "probabilidad_bajo": None, "probabilidad_alto": None, "confianza": CONFIANZA},
            "evidencia": {"fuente": "", "origen": "usdt", "tramo": "", "desde": None, "hasta": None, "casos": 0,
                          "operaciones": 0, "ganadoras": 0, "aciertos": None, "bajo": None, "alto": None,
                          "confianza": CONFIANZA, "casos_minimos": CASOS_PROBABILIDAD, "pocos": False,
                          "no_validado": False, "motivo": ""}}


def mejor_de(opciones):
    """La opción que más puntúa de todas (quedarse en USDT incluida), mirando solo las que se pueden entrar y tienen
    puntaje. Es la que la pantalla muestra primero y la que la exigencia, en su paso, va a dejar pasar o no."""
    candidatas = [o for o in opciones if o.get("puntaje") is not None and o.get("permitida")]
    if not candidatas:
        return None
    return max(candidatas, key=lambda o: o["puntaje"])


# ── El supuesto de las velas sin 1 m, marcado ──────────────────────────────────────────────────────────────────────────────

def supuestos(reporte, tramos=None):
    """Los supuestos que arrastra la probabilidad de ganar, marcados en el reporte. El que más pesa es la regla de las
    velas sin velas de 1 m: cuando una vela tocó el stop y el objetivo y no se sabe qué pasó primero, se supone el stop
    (`lib_resolucion.SUPUESTO_SIN_1M`, el mismo código que `backtest.SUPUESTO_AMBIGUO`), lo malo, para que el resultado
    no cambie cuando la ventana de 1 m se corre.

    Ese supuesto no se deja suelto: se valida contra los `lib_datos.DIAS_MINUTOS` días que sí tienen velas de 1 m y aquí
    se dice en cuántas acertó (`acierto`) y cuántas se pudieron revisar (`validado`). Cuando los tramos de puntaje están
    medidos, la validación que manda es la suya (es con esas operaciones que se estimó la probabilidad) y se dice con qué
    etiqueta salió cada una (`etiquetas`). También queda dicho que todo esto viene de un backtest **sin exigencia** y con
    el spread que diga su modelo: no es la prueba final, esa es cosa de la calibración, en su paso."""
    s = (reporte or {}).get("supuestos") or {}
    t = tramos or {}
    medidos = bool(t.get("corrido"))
    propios = (t.get("supuestos") or {}) if medidos else {}
    a = propios.get("ambiguas") or s.get("ambiguas") or {}
    return {"corrido": bool((reporte or {}).get("corrido")), "cuando": (reporte or {}).get("cuando") or "",
            "sin_1m": lib_resolucion.SUPUESTO_SIN_1M, "dias_1m": lib_datos.DIAS_MINUTOS, "ambiguas": a,
            "regla": lib_resolucion.parametros(), "etiquetas": propios.get("etiquetas") or {},
            "medidos": medidos, "medidos_cuando": t.get("cuando") or "",
            "validado": bool(a.get("validado", a.get("con_1m"))), "acierto": a.get("acierto"),
            "spread": propios.get("spread") or s.get("spread") or "",
            "empalme": bool(propios.get("empalme") or s.get("empalme")),
            "sin_exigencia": bool(s.get("sin_exigencia", True)),
            "no_validado": bool(((reporte or {}).get("compuerta") or {}).get("no_validado", True))}


# ── La capa que recorre las velas: la que va a usar la calibración ─────────────────────────────────────────────────────────

def de_velas(par, temporalidad, velas, al_alza=None, filtro=None, contexto_btc=None, spread=None, com=None,
             pesos=None):
    """El puntaje de las señales crudas de cada vela de una serie: una lista del mismo largo que `velas`, con las señales
    de esa vela ya puntuadas (`puntaje`, `familias`) o una lista vacía. Es la capa que va a recorrer la calibración, en su
    paso, para dejar pasar por `backtest.correr(filtrar=…)` solo las que llegan a la exigencia, y por eso los indicadores
    se calculan enteros una vez y después se mira vela por vela.

    `al_alza(ms)` y `filtro(ms)` son los de `lib_estrategias` (la tendencia diaria del par y el filtro de BTC) y
    `contexto_btc(ms)` es el de `lib_estrategias.contexto_en`: sin él, la familia contexto no tiene nota y ninguna señal
    queda puntuada, igual que en las estrategias. `spread` y `com` son los del backtest (el modelo de costos), no los de
    la última muestra: aquí se está mirando el pasado."""
    altos, bajos, cierres, volumenes = ([v[i] for v in velas] for i in (2, 3, 4, 5))
    medias = [lib_indicadores.sma(cierres, n) for n in lib_indicadores.MEDIAS]
    fuerza = lib_indicadores.adx(altos, bajos, cierres)["adx"]
    rsis = lib_indicadores.rsi(cierres)
    histogramas = lib_indicadores.macd(cierres)["histograma"]
    banda_ = lib_indicadores_mercado.bollinger(cierres)
    medio = lib_indicadores_mercado.atr(altos, bajos, cierres)
    niveles = lib_indicadores_mercado.rupturas(altos, bajos, cierres)
    relativos = lib_indicadores_mercado.volumen_relativo(volumenes)
    obvs = lib_indicadores_mercado.obv_relativo(cierres, volumenes)
    crudas = lib_estrategias.de_velas(par, temporalidad, velas, al_alza=al_alza, filtro=filtro)
    com = com or lib_costos.comisiones()
    spread = lib_costos.SPREAD_SUPUESTO if spread is None else spread
    comision = com["maker"] + com["taker"]
    paso = lib_datos.PASO_MS[temporalidad]
    salida = []
    for i, suyas in enumerate(crudas):
        if not suyas:
            salida.append([])
            continue
        c = contexto_btc(velas[i][0] + paso) if contexto_btc else None
        base = {"cierre": cierres[i], "media_20": medias[0][i], "media_50": medias[1][i], "media_200": medias[2][i],
                "adx": fuerza[i], "rsi": rsis[i], "histograma": histogramas[i], "ancho": banda_["ancho"][i],
                "atr_relativo": None if (medio[i] is None or not cierres[i]) else medio[i] / cierres[i],
                "volumen_relativo": relativos[i], "obv_relativo": obvs[i],
                "rompio_maximo": niveles["rompio_maximo"][i], "rompio_minimo": niveles["rompio_minimo"][i],
                "distancia_maximo": niveles["distancia_maximo"][i], "distancia_minimo": niveles["distancia_minimo"][i],
                "costo_comision": comision, "costo_spread": spread, "costo_conversion": com["conversion"],
                **_contexto(c)}
        puntuadas = []
        for s in suyas:
            p = puntaje_de({**base, "distancia_stop": s["distancia_stop"],
                            "distancia_objetivo": s["distancia_objetivo"]}, pesos)
            puntuadas.append({**s, "puntaje": p["puntaje"], "familias": p["familias"],
                              "renormalizado": p["renormalizado"], "motivo": p["motivo"]})
        salida.append(puntuadas)
    return salida


# ── La medición de los tramos: qué dio cada tramo de puntaje en el historial ───────────────────────────────────────────────

def seguir(velas, i, s, spread, com, factor=lib_costos.PENETRACION_SPREADS, minutos=None):
    """Qué le habría pasado a una señal **ya puntuada** de la vela `i`: si su orden límite se llenó mientras estuvo viva
    y, llenada, si terminó en el stop o en el objetivo, con el resultado después de costos (`lib_costos.resultado`) y el
    puntaje con que se decidió pegado a la operación.

    Es el recorrido del backtest (`backtest.seguir`), con dos cosas que este paso necesita: el `puntaje` y su `tramo`
    viajan con la operación —sin eso no hay tramos que medir— y la salida la decide `lib_resolucion.cerrar`, así la regla
    de las velas sin 1 m está en un solo lugar y la `etiqueta` con que se resolvió viaja también. La señal se decide con
    la vela cerrada, así que la orden se puede llenar recién en la **siguiente** y vive las `vigencia_velas` que dice."""
    nivel, stop, objetivo = s["entrada"], s["stop"], s["objetivo"]
    bordes = bordes_de(s.get("puntaje"))
    o = {"estrategia": s["estrategia"], "par": s["par"], "temporalidad": s["temporalidad"], "senal_ms": s["vela"],
         "puntaje": s.get("puntaje"), "tramo": nombre_tramo(*bordes) if bordes else "",
         "permitida": bool(s["permitida"]), "filtro": s["filtro"], "nivel": nivel,
         "limite": nivel * (1 - lib_costos.margen_llenado(spread, factor)), "stop": stop, "objetivo": objetivo,
         "llenada": False, "entrada_ms": None, "salida_ms": None, "velas": 0, "por": "", "bruto": None, "neto": None,
         "costos": None, "ambigua": False, "etiqueta": lib_resolucion.CLARA, "motivo": "sin_llenar"}
    vigencia = int(s.get("vigencia_velas") or lib_estrategias.VIGENCIA_VELAS)
    entrada = next((j for j in range(i + 1, min(len(velas), i + 1 + vigencia))
                    if lib_costos.llena(nivel, velas[j][3], spread, factor)), None)
    if entrada is None:
        return o
    o.update(llenada=True, entrada_ms=velas[entrada][0], motivo="sin_cerrar")
    r = lib_resolucion.cerrar(velas, entrada, stop, objetivo, s["temporalidad"], minutos, backtest.VELAS_MAXIMAS)
    if r["motivo"]:
        return o
    cuenta = lib_costos.resultado(nivel, r["precio"], r["por"], spread, com)
    o.update(motivo="", ambigua=r["ambigua"], etiqueta=r["etiqueta"], salida_ms=r["salida_ms"], velas=r["velas"],
             por=cuenta["por"], bruto=cuenta["bruto"], neto=cuenta["neto"], costos=cuenta["costos"])
    return o


def _etiquetas(ops):
    """Con qué etiqueta de la regla de las velas sin 1 m salió cada operación que cerró: cuántas no necesitaron ningún
    supuesto y cuántas lo necesitaron. La probabilidad por tramos se calculó con todas ellas y eso se dice."""
    cuenta = {lib_resolucion.CLARA: 0, lib_resolucion.CON_1M: 0, lib_resolucion.SIN_1M: 0}
    for o in ops or []:
        if not o.get("motivo") and o.get("etiqueta") in cuenta:
            cuenta[o["etiqueta"]] += 1
    return cuenta


def _supuestos_medidos(ops, empalmes, origen_spread, minutos=None):
    """Con qué supuestos salieron estos tramos: la regla de las velas sin 1 m con su validación contra los días que sí
    las tienen (`lib_resolucion.validar`), la etiqueta con que salió cada operación, de dónde salió el spread, si hubo
    empalme y que esto se midió **sin exigencia**, sobre las señales crudas."""
    return {"sin_1m": lib_resolucion.SUPUESTO_SIN_1M, "regla": lib_resolucion.parametros(),
            "ambiguas": lib_resolucion.validar(ops, minutos), "etiquetas": _etiquetas(ops),
            "spread": origen_spread, "empalme": any(e["empalmada"] for e in empalmes or []), "sin_exigencia": True}


def _parametros_medicion(penetracion):
    return {"tramos": list(TRAMOS_PUNTAJE), "casos_minimos": CASOS_PROBABILIDAD, "confianza": CONFIANZA,
            "penetracion": penetracion, "calentamiento": lib_indicadores.VELAS_CALENTAMIENTO,
            "velas_maximas": backtest.VELAS_MAXIMAS, "supuesto_sin_1m": lib_resolucion.SUPUESTO_SIN_1M}


def medir(ahora_ms=None, factor=None, pesos=None, calibracion=None, minutos=None):
    """La probabilidad de ganar y la ganancia esperada después de costos **por tramos de puntaje**, medidas sobre los
    resultados del backtest de señales crudas.

    Es el mismo recorrido del historial que `backtest.correr` —las cuatro series de entrada empalmadas, el mismo modelo
    de spread, el mismo no llenado condicionado y los mismos costos de cada lado— con una diferencia: cada señal se
    **puntúa** antes de seguirla (`de_velas`) y cada salida se resuelve con `lib_resolucion`, así que al final las
    operaciones se pueden repartir por el puntaje que tenían (`tramos_de_puntaje`).

    Es una pasada aparte y lenta a propósito (la acción `puntajeMedir`): recorre años de velas y calcula los indicadores
    de cada serie. Lo que deja escrito (`escribir_tramos`) es lo que el puntaje de ahora lee sin recorrer nada.

    El recorrido va **siempre con el supuesto** de las velas sin 1 m, nunca con las velas de 1 m que haya: un resultado
    que cambiara porque la ventana de 1 m se corrió no sería un resultado. `minutos` es con qué **validar** ese supuesto
    (`{par: velas}`; sin él, las guardadas). `pesos` y `calibracion` son los ganchos de la calibración, en su paso: con
    otros pesos, los tramos se vuelven a medir."""
    ahora = ahora_ms or lib_datos.ahora_local_ms()
    com, costos = lib_costos.comisiones(), lib_costos.modelo()
    principal = lib_costos.PENETRACION_SPREADS if factor is None else float(factor)
    m = modelo(calibracion)
    p = m["pesos"] if pesos is None else pesos
    motivos, empalmes, filas, todas = [], [], [], []
    btc = lib_datos.leer_serie(lib_indicadores_mercado.CONTEXTO_PAR, lib_estrategias.TEMPORALIDAD_DIARIA)
    hay_btc = len(btc) >= backtest.VELAS_MINIMAS
    filtro = lib_estrategias.filtro_en(btc) if hay_btc else None
    contexto_btc = lib_estrategias.contexto_en(btc) if hay_btc else None
    if not hay_btc:   # sin el contexto de BTC no se entra a nada y ninguna señal queda puntuada: no hay nada que medir
        motivos.append({"codigo": "sin_contexto", "par": lib_indicadores_mercado.CONTEXTO_PAR,
                        "temporalidad": lib_estrategias.TEMPORALIDAD_DIARIA, "n": backtest.VELAS_MINIMAS - len(btc)})
    for par in lib_datos.PARES_OPERADOS:
        diario = lib_estrategias.PAR_DIARIO[par]
        velas_dia = lib_datos.leer_serie(diario, lib_estrategias.TEMPORALIDAD_DIARIA)
        al_alza = lib_estrategias.al_alza_en(velas_dia) if len(velas_dia) >= backtest.VELAS_MINIMAS else None
        if al_alza is None:
            motivos.append({"codigo": "sin_tendencia_diaria", "par": diario,
                            "temporalidad": lib_estrategias.TEMPORALIDAD_DIARIA,
                            "n": backtest.VELAS_MINIMAS - len(velas_dia)})
        for temporalidad in lib_estrategias.TEMPORALIDADES_SENAL:
            velas, empalme = backtest.empalmar(par, temporalidad)
            empalmes.append(empalme)
            fila = {"par": par, "temporalidad": temporalidad, "velas": empalme["velas"], "motivo": empalme["motivo"],
                    "faltan": empalme["faltan"], "empalmada": empalme["empalmada"], "prestadas": empalme["prestadas"],
                    "senales": 0, "puntuadas": 0, "operaciones": 0}
            if empalme["motivo"]:
                motivos.append({"codigo": empalme["motivo"], "par": par, "temporalidad": temporalidad,
                                "n": empalme["faltan"]})
                filas.append(fila)
                continue
            spread = lib_costos.spread_de(costos, par)
            puntuadas = de_velas(par, temporalidad, velas, al_alza=al_alza, filtro=filtro, contexto_btc=contexto_btc,
                                 spread=spread, com=com, pesos=p)
            # El calentamiento no da operaciones, igual que en el backtest: ahí el ATR y el ADX todavía arrastran.
            suyas = [(i, s) for i, fila_i in enumerate(puntuadas) for s in fila_i
                     if i >= lib_indicadores.VELAS_CALENTAMIENTO]
            ops = [seguir(velas, i, s, spread, com, principal) for i, s in suyas]
            fila.update(senales=len(suyas), puntuadas=sum(1 for _, s in suyas if s.get("puntaje") is not None),
                        operaciones=sum(1 for o in ops if not o["motivo"]))
            todas.extend(ops)
            filas.append(fila)
    cerradas = [o for o in todas if not o["motivo"] and o["permitida"]]
    return {"formato": 1, "corrido": True, "cuando": lib_datos.iso(ahora), "modelo": m, "comisiones": com,
            "pesos": {f: float(p.get(f, 0.0) or 0.0) for f in FAMILIAS},
            "parametros": _parametros_medicion(principal), "ventana": backtest.ventana_de(empalmes), "series": filas,
            "tramos": tramos_de_puntaje(todas), "resumen": backtest.resumen(todas), "operaciones": len(cerradas),
            "sin_puntaje": sum(1 for o in cerradas if o.get("puntaje") is None),
            "supuestos": _supuestos_medidos(todas, empalmes, costos["origen"], minutos),
            "no_validado": not m["calibrado"], "motivos": motivos, "listo": not motivos}


def sin_medir():
    """Lo que se ve antes de medir ninguno: los cinco tramos en cero, con sus bordes y sin ningún número inventado."""
    return {"formato": 1, "corrido": False, "cuando": "", "modelo": modelo(), "comisiones": lib_costos.comisiones(),
            "pesos": dict(PESOS_BASE), "parametros": _parametros_medicion(lib_costos.PENETRACION_SPREADS),
            "ventana": backtest.ventana_de([]), "series": [], "tramos": tramos_de_puntaje([]),
            "resumen": backtest.resumen([]), "operaciones": 0, "sin_puntaje": 0,
            "supuestos": _supuestos_medidos([], [], "", {}), "no_validado": True, "motivos": [], "listo": False}


def tramos_guardados():
    """Los últimos tramos medidos o, si no se midió ninguno, los cinco en cero. Sin red y sin recorrer nada."""
    d = nucleo.leer_json(ruta_tramos(), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    if isinstance(d, dict) and d.get("formato") == 1 and d.get("corrido") and isinstance(d.get("tramos"), list):
        return d
    return sin_medir()


def escribir_tramos(d):
    """Deja escritos los tramos medidos: los leen el puntaje de ahora y la calibración sin volver a recorrer nada."""
    nucleo.escribir_json(ruta_tramos(), d)
    return d


# ── Lo que usa la app: el puntaje de ahora ─────────────────────────────────────────────────────────────────────────────────

def _comisiones(c):
    """Las comisiones de la familia costo, en la forma que pide `lib_costos.resultado`."""
    return {"maker": (c or {}).get("maker"), "taker": (c or {}).get("taker"),
            "conversion": (c or {}).get("conversion"), "origen": (c or {}).get("origen") or ""}


def estado(ahora_ms=None, indicadores=None, senales=None, reporte=None, pesos=None, calibracion=None, tramos=None):
    """El puntaje de ahora de los dos pares que se operan: cada señal cruda con su puntaje por familias, su probabilidad
    de ganar y su ganancia esperada después de costos, más el puntaje de quedarse en USDT (la misma escala: se comparan de
    frente), cuál es la mejor opción de todas y en qué estado está el modelo con que se puntúa.

    `indicadores`, `senales`, `reporte` y `tramos` se pueden pasar ya calculados (el motor, en su paso, los tiene a mano)
    para no recorrer las velas dos veces ni volver a leer nada del disco. `listo` pide lo mismo que las señales —las
    cuatro series, el contexto de BTC y la tendencia diaria— y además el costo del momento de cada par, un backtest
    corrido y los tramos de puntaje medidos: sin ellos hay puntaje, pero no hay probabilidad ni ganancia esperada, y eso
    se dice (`sin_backtest`, `sin_tramos`).

    Los pesos salen del modelo (`modelo`): sin calibración son los de partida y la exigencia queda alta. `pesos` sigue
    siendo el gancho directo de la calibración mientras prueba combinaciones, en su paso."""
    ahora = ahora_ms or lib_datos.ahora_local_ms()
    e = lib_indicadores_mercado.estado(ahora) if indicadores is None else indicadores
    s = lib_estrategias.estado(ahora, indicadores=e) if senales is None else senales
    bt = backtest.guardado() if reporte is None else reporte
    tr = tramos_guardados() if tramos is None else tramos
    m = modelo(calibracion)
    p = m["pesos"] if pesos is None else pesos
    filas = {(x.get("par"), x.get("temporalidad")): x for x in (e.get("series") or [])}
    costos = {x.get("par"): x for x in ((e.get("costo") or {}).get("pares") or [])}
    com = _comisiones(e.get("costo"))
    motivos = list(s.get("motivos") or [])
    series, opciones = [], []
    for fila in s.get("series") or []:
        par, temporalidad = fila.get("par"), fila.get("temporalidad")
        c = costos.get(par) or {}
        costo_ahora = _costo(c, com)
        spread = c.get("spread_relativo") if c.get("listo") else None
        suyas = []
        for senal in fila.get("senales") or []:
            valores = valores_de(filas.get((par, temporalidad)), e.get("contexto"), costo_ahora, senal)
            suyas.append(opcion(senal, valores, bt, spread, com, p, tr))
        series.append({"par": par, "temporalidad": temporalidad, "listo": bool(fila.get("listo")),
                       "motivo": fila.get("motivo") or "", "cuantas": fila.get("cuantas") or 0,
                       "vela": fila.get("vela"), "cierre": fila.get("cierre"), "opciones": suyas})
        opciones.extend(suyas)
    for par in lib_datos.PARES_OPERADOS:
        c = costos.get(par) or {}
        if not c.get("listo"):
            motivos.append({"codigo": c.get("motivo") or "sin_muestras", "par": par, "temporalidad": "",
                            "n": c.get("cuantas") or 0})
    if not bt.get("corrido"):
        motivos.append({"codigo": "sin_backtest", "par": "", "temporalidad": "", "n": 0})
    if not tr.get("corrido"):
        motivos.append({"codigo": "sin_tramos", "par": "", "temporalidad": "", "n": 0})
    en_usdt = quedarse(s.get("filtro") or {}, opciones)
    return {"formato": 1, "cuando": lib_datos.iso(ahora), "familias": list(FAMILIAS),
            "claves": list(FAMILIAS_CLAVE), "modelo": m, "exigencia": m["exigencia"],
            "pesos": {f: float(p.get(f, 0.0) or 0.0) for f in FAMILIAS},
            "parametros": parametros(), "maximo": PUNTAJE_MAXIMO, "confianza": CONFIANZA,
            "casos_minimos": CASOS_PROBABILIDAD, "filtro": s.get("filtro") or {}, "comisiones": com,
            "series": series, "opciones": opciones, "usdt": en_usdt,
            "mejor": mejor_de([*opciones, en_usdt]), "supuestos": supuestos(bt, tr),
            "tramos": tr.get("tramos") or [],
            "medicion": {"corrido": bool(tr.get("corrido")), "cuando": tr.get("cuando") or "",
                         "operaciones": tr.get("operaciones") or 0, "sin_puntaje": tr.get("sin_puntaje") or 0,
                         "no_validado": bool(tr.get("no_validado", True))},
            "motivos": motivos, "listo": not motivos}


def escribir_estado(e):
    """Deja escrito el último puntaje: lo leen la calibración, el motor y la pantalla sin volver a calcular nada."""
    nucleo.escribir_json(ruta_puntaje(), e)
    return e
