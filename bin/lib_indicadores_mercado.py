#!/usr/bin/env python3
"""lib_indicadores_mercado — las otras cinco familias del puntaje. Solo biblioteca estándar. No es una acción.

Con `bin/lib_indicadores.py` (tendencia e impulso) quedan completas las siete familias que después se van a pesar:

| Familia | Sus parámetros (dos o tres, nunca más) | De dónde sale |
|---|---|---|
| volatilidad | Bollinger (`BOLLINGER_VELAS` velas, `BOLLINGER_DESVIOS` desvíos) y ATR (`ATR_PERIODO`) | las velas guardadas |
| volumen | el volumen relativo (`VOLUMEN_VELAS` velas) y el OBV | las velas guardadas |
| estructura | el máximo roto y el mínimo roto (`RUPTURA_VELAS` velas) | las velas guardadas |
| contexto | BTC en 1 d: cuánto se movió el último día y su distancia a la media de 200 | la serie `BTCUSDT`-`1d` |
| costo | la comisión, la diferencia entre compra y venta y la conversión USDT↔FDUSD | `comisiones.json` y la última muestra |

Las dos capas son las del otro módulo: las cuentas de siempre, sobre listas de números (`bollinger`, `atr`, `volumen_relativo`,
`obv`, `obv_relativo`, `rupturas`, `cambios`), devuelven la serie completa con `None` donde el indicador todavía no existe (son
las que va a recorrer el backtest, vela por vela); las de la app (`valores`, `contexto`, `costo`, `estado`) dan el valor de
**ahora**, leyendo lo guardado. `estado()` es lo que responde la acción `indicadoresEstado`: las siete familias juntas.

Lo que no se negocia aquí:
- **Las mismas reglas de la ventana.** Solo velas cerradas, continuidad antes de calcular y la ventana fija de
  `lib_indicadores.VENTANA`: el estado de cada serie y su motivo son los del otro módulo. Aquí se suman familias, no se
  relajan requisitos.
- **El nivel que se rompe no se cuenta a sí mismo.** El techo y el piso son los de las `RUPTURA_VELAS` velas **anteriores**, y
  el volumen relativo compara con el promedio de las **anteriores**: si la vela entrara en su propio nivel o en su propio
  promedio, ninguna ruptura se vería y un volumen grande se diluiría solo.
- **El costo del momento no se inventa.** La diferencia entre compra y venta sale de la última muestra del libro
  (`mercado/muestreo.json`, el trabajo del muestreo): si no hay muestra, o es de hace más de `MUESTRA_VIGENTE_MIN` minutos, la
  familia costo queda con su motivo (`sin_muestras`, `muestra_vieja`) y sin números. Las comisiones son las que dejó escritas
  el conector real o, mientras no haya llave, las supuestas: `costo.origen` lo dice, igual que en el capital mínimo viable.
- **El contexto es BTC en 1 d, de `BTCUSDT`**: el par contra FDUSD recién empieza y no llega a los 200 días de media. Qué se
  hace con ese contexto —si BTC cae, no se entra a nada— es cosa de las estrategias, en su paso: aquí solo están los números.
- **Nada se redondea.** El redondeo vive en la pantalla (`numero()` y `porcentaje()` en `ui/app.js`): el puntaje y el backtest
  trabajan con todos los decimales.

Dónde queda: `<datos>/mercado/indicadores.json` (lo escribe `lib_indicadores.escribir_estado`, con la hora del cálculo).
"""
import math

import lib_datos
import lib_indicadores
import lib_trabajo
import minimo_viable

#: Bollinger: la media de 20 velas y dos desvíos estándar a cada lado (los de siempre).
BOLLINGER_VELAS, BOLLINGER_DESVIOS = 20, 2.0
ATR_PERIODO = 14
#: Con cuántas velas anteriores se compara el volumen de la última, y de cuántas sale el techo y el piso que se rompen.
VOLUMEN_VELAS = 20
RUPTURA_VELAS = 20
#: El contexto es BTC en 1 d, y sale del par contra USDT: es el que tiene años de historia (el de FDUSD recién empieza).
CONTEXTO_PAR, CONTEXTO_TEMPORALIDAD = "BTCUSDT", "1d"
#: Hasta cuándo sirve la última muestra del libro. El muestreo guarda una cada 5 minutos: con tres ciclos de margen, una
#: muestra más vieja que esto ya no es «el costo de ahora» y la familia costo se queda sin números.
MUESTRA_VIGENTE_MIN = 15
#: Una diferencia entre compra y venta mayor que esta no se cree (en estos pares es del orden de 1e-6): el archivo lo pudo
#: haber tocado cualquiera, y un costo falso haría pasar una operación que no conviene.
COSTO_MAXIMO = 0.05


# ── Las cuentas de siempre, sobre listas de números ──────────────────────────────────────────────────────────────────────────

def desviacion(valores, n):
    """El desvío estándar de cada ventana de `n` valores (el poblacional, el de Bollinger): `None` hasta que hay `n`."""
    medias = lib_indicadores.sma(valores, n)
    salida = [None] * len(valores)
    for i, m in enumerate(medias):
        if m is not None:
            salida[i] = math.sqrt(max(0.0, math.fsum((v - m) ** 2 for v in valores[i - n + 1:i + 1]) / n))
    return salida


def bollinger(cierres, n=BOLLINGER_VELAS, k=BOLLINGER_DESVIOS):
    """Las bandas de Bollinger: la media de `n` velas y `k` desvíos a cada lado. Además de las tres líneas devuelve las dos
    formas en que se usan: `ancho` (cuánto se abrió la banda, relativo a la media: el precio quieto la cierra) y `posicion`
    (dónde está el cierre entre las dos bandas: 0 en la de abajo, 1 en la de arriba). `posicion` **no se recorta**: fuera de
    la banda pasa de 0 a 1, y la calibración necesita ver cuánto. Con el precio plano no hay banda y las dos van en `None`."""
    medias, desvios = lib_indicadores.sma(cierres, n), desviacion(cierres, n)
    b = {k2: [None] * len(cierres) for k2 in ("media", "alta", "baja", "ancho", "posicion")}
    for i, (m, d) in enumerate(zip(medias, desvios)):
        if m is None:
            continue
        alta, baja = m + k * d, m - k * d
        b["media"][i], b["alta"][i], b["baja"][i] = m, alta, baja
        if alta > baja:
            b["ancho"][i] = (alta - baja) / m if m else None
            b["posicion"][i] = (cierres[i] - baja) / (alta - baja)
    return b


def rango_verdadero(altos, bajos, cierres):
    """El rango verdadero de cada vela: lo que se movió contando el salto desde el cierre anterior. `None` en la primera."""
    largo = len(cierres)
    if not (len(altos) == len(bajos) == largo):
        raise ValueError("las tres series tienen que tener el mismo largo")
    if not largo:
        return []
    return [None] + [max(altos[i] - bajos[i], abs(altos[i] - cierres[i - 1]), abs(bajos[i] - cierres[i - 1]))
                     for i in range(1, largo)]


def atr(altos, bajos, cierres, n=ATR_PERIODO):
    """El ATR de Wilder: cuánto se mueve esta serie, en el precio del par. Sembrado con la media simple de los primeros `n`
    rangos verdaderos y después suavizado, igual que el ADX y el RSI: el valor de hoy no depende de dónde empezó la serie."""
    if n <= 0:
        raise ValueError("el ATR necesita al menos una vela")
    rangos = rango_verdadero(altos, bajos, cierres)
    salida = [None] * len(cierres)
    if len(rangos) <= n:
        return salida
    actual = math.fsum(rangos[1:n + 1]) / n
    salida[n] = actual
    for i in range(n + 1, len(rangos)):
        actual = (actual * (n - 1) + rangos[i]) / n
        salida[i] = actual
    return salida


def volumen_relativo(volumenes, n=VOLUMEN_VELAS):
    """El volumen de cada vela comparado con el promedio de las `n` **anteriores** (la propia no entra: en una ruptura, una
    vela con mucho volumen se diluiría en su propio promedio). 1 es lo normal; 2, el doble de lo normal."""
    medias = lib_indicadores.sma(volumenes, n)
    return [None if (i == 0 or not medias[i - 1]) else volumenes[i] / medias[i - 1] for i in range(len(volumenes))]


def obv(cierres, volumenes):
    """El OBV: suma el volumen de las velas que cierran más arriba y resta el de las que cierran más abajo. Arranca en 0 en la
    primera vela de la ventana, así que lo que dice es cómo se mueve, no cuánto vale (para eso está `obv_relativo`)."""
    if len(cierres) != len(volumenes):
        raise ValueError("las dos series tienen que tener el mismo largo")
    salida = [0.0] * len(cierres)
    for i in range(1, len(cierres)):
        empuje = volumenes[i] if cierres[i] > cierres[i - 1] else (-volumenes[i] if cierres[i] < cierres[i - 1] else 0.0)
        salida[i] = salida[i - 1] + empuje
    return salida


def obv_relativo(cierres, volumenes, n=VOLUMEN_VELAS):
    """Qué parte del volumen de las últimas `n` velas empujó para un lado: de −1 (todo vendiendo) a 1 (todo comprando). Es el
    OBV sin su arranque arbitrario, el número que sí se puede comparar entre pares y entre temporalidades."""
    acumulado = obv(cierres, volumenes)
    salida = [None] * len(cierres)
    for i in range(n, len(cierres)):
        total = math.fsum(volumenes[i - n + 1:i + 1])
        if total:
            salida[i] = (acumulado[i] - acumulado[i - n]) / total
    return salida


def rupturas(altos, bajos, cierres, n=RUPTURA_VELAS):
    """Los máximos y mínimos rotos: el techo (`maximo`) y el piso (`minimo`) de las `n` velas **anteriores**, si el cierre los
    pasó y a qué distancia quedó de cada uno (relativa: positiva por encima). El nivel es el que usa la estrategia de ruptura
    para entrar con límite cuando el precio vuelve a él, así que es un precio, no una señal."""
    largo = len(cierres)
    if not (len(altos) == len(bajos) == largo):
        raise ValueError("las tres series tienen que tener el mismo largo")
    if n <= 0:
        raise ValueError("una ruptura necesita al menos una vela")
    r = {k: [None] * largo for k in ("maximo", "minimo", "rompio_maximo", "rompio_minimo",
                                     "distancia_maximo", "distancia_minimo")}
    for i in range(n, largo):
        techo, piso = max(altos[i - n:i]), min(bajos[i - n:i])
        r["maximo"][i], r["minimo"][i] = techo, piso
        r["rompio_maximo"][i], r["rompio_minimo"][i] = cierres[i] > techo, cierres[i] < piso
        if techo:
            r["distancia_maximo"][i] = (cierres[i] - techo) / techo
        if piso:
            r["distancia_minimo"][i] = (cierres[i] - piso) / piso
    return r


def cambios(cierres):
    """Cuánto se movió el precio en cada vela, sobre el cierre anterior: `None` en la primera. Es el parámetro con el que la
    familia contexto mira a BTC, y el que dice «BTC cayó» sin depender de la moneda del par."""
    if not cierres:
        return []
    return [None] + [((b - a) / a if a else None) for a, b in zip(cierres, cierres[1:])]


# ── Lo que usa la app: el valor de ahora ─────────────────────────────────────────────────────────────────────────────────────

def valores(velas):
    """Volatilidad, volumen y estructura al cierre de la última vela de `velas` (la más reciente al final, todas cerradas y
    seguidas), más cuánto se movió esa vela (`cambio`). Es la función que `lib_indicadores.de_serie` suma a cada serie, así
    las velas se recorren una sola vez. Lo que todavía no se puede calcular va en `None`: aquí no se inventa ningún número."""
    altos, bajos, cierres, volumenes = ([v[i] for v in velas] for i in (2, 3, 4, 5))
    b, rango, r = bollinger(cierres), atr(altos, bajos, cierres), rupturas(altos, bajos, cierres)
    cierre, medio = cierres[-1], rango[-1]
    return {"cambio": cambios(cierres)[-1],
            "volatilidad": {"banda_alta": b["alta"][-1], "banda_media": b["media"][-1], "banda_baja": b["baja"][-1],
                            "ancho": b["ancho"][-1], "posicion": b["posicion"][-1], "atr": medio,
                            "atr_relativo": (medio / cierre if medio is not None and cierre else None)},
            "volumen": {"volumen": volumenes[-1], "relativo": volumen_relativo(volumenes)[-1],
                        "obv": obv(cierres, volumenes)[-1], "obv_relativo": obv_relativo(cierres, volumenes)[-1]},
            "estructura": {k: r[k][-1] for k in r}}


def contexto(series):
    """La familia contexto: BTC en 1 d. Dos parámetros, los dos de la serie `CONTEXTO_PAR`-`CONTEXTO_TEMPORALIDAD` que ya
    calculó `lib_indicadores`: cuánto se movió el último día cerrado (`cambio`) y a qué distancia está de su media de 200 días
    (`distancia_media`, con `sobre_media` para leerla de un vistazo). Si esa serie no está al día, el contexto queda con su
    motivo: con BTC a ciegas no se mira ninguna oportunidad."""
    c = {"par": CONTEXTO_PAR, "temporalidad": CONTEXTO_TEMPORALIDAD, "listo": False, "motivo": "sin_datos",
         "cuantas": lib_indicadores.VENTANA, "vela": None, "cierre": None, "media_200": None, "distancia_media": None,
         "sobre_media": None, "cambio": None}
    s = next((x for x in series if x.get("par") == CONTEXTO_PAR and x.get("temporalidad") == CONTEXTO_TEMPORALIDAD), None)
    if s is None:
        return c
    c.update(motivo=s["motivo"], cuantas=s["cuantas"], vela=s["vela"])
    media, cierre, cambio = (s.get("tendencia") or {}).get("media_200"), s.get("cierre"), s.get("cambio")
    if s["listo"] and media and cierre is not None and cambio is not None:
        c.update(listo=True, motivo="", cuantas=0, cierre=cierre, media_200=media, cambio=cambio,
                 distancia_media=(cierre - media) / media, sobre_media=cierre > media)
    return c


def _numero(valor, positivo=False, maximo=None):
    """Un número de un archivo que pudo tocar cualquiera: `None` si no es un número que tenga sentido."""
    try:
        v = lib_datos.numero(valor, positivo=positivo)
    except (TypeError, ValueError, lib_datos.Respuesta):
        return None
    return v if maximo is None or v <= maximo else None


def ultima_muestra(plan=None):
    """La última muestra del libro que dejó el muestreo (`mercado/muestreo.json`): su hora y la muestra de cada par operado.
    Lo que no se entienda no existe: una muestra a medias no da costo."""
    ultima = (lib_trabajo.leer_plan("muestreo") if plan is None else plan).get("ultima") or {}
    ms = ultima.get("ms")
    if not isinstance(ms, int) or isinstance(ms, bool) or ms <= 0:
        return 0, {}
    pares = {p["par"]: p for p in (ultima.get("pares") or [])
             if isinstance(p, dict) and p.get("par") in lib_datos.PARES_OPERADOS}
    return ms, pares


def costo(ahora_ms=None, plan=None):
    """La familia costo, en tanto por uno y por par operado: la comisión (maker al entrar, taker al salir por el stop), la
    diferencia entre compra y venta de la última muestra del libro y la conversión USDT↔FDUSD. `total` las suma: lo que cuesta
    entrar y salir una vez, el mínimo que una oportunidad tiene que ganar para no perder plata (el mismo orden del capital
    mínimo viable). Sin muestra vigente no hay números, solo el motivo."""
    ahora = ahora_ms or lib_datos.ahora_local_ms()
    com = minimo_viable.comisiones()
    ms, muestras = ultima_muestra(plan)
    fijo = com["conversion"] + com["maker"] + com["taker"]
    pares, motivos = [], []
    for par in lib_datos.PARES_OPERADOS:
        p = {"par": par, "listo": False, "motivo": "sin_muestras", "cuantas": 0, "ms": None, "cuando": "",
             "compra": None, "venta": None, "spread": None, "spread_relativo": None, "total": None}
        m = muestras.get(par) or {}
        relativo = _numero(m.get("spread_relativo"), maximo=COSTO_MAXIMO)
        compra, venta = _numero(m.get("compra"), positivo=True), _numero(m.get("venta"), positivo=True)
        # Una muestra con fecha futura no es una muestra: el archivo está tocado y no se cree ninguno de sus números.
        if relativo is not None and compra and venta and ms <= ahora + 60_000:
            p.update(ms=ms, cuando=lib_datos.iso(ms), compra=compra, venta=venta, spread=_numero(m.get("spread")),
                     spread_relativo=relativo, cuantas=int(max(0, ahora - ms) // 60_000), motivo="")
            if ahora - ms > MUESTRA_VIGENTE_MIN * 60_000:
                p["motivo"] = "muestra_vieja"
            else:
                p.update(listo=True, total=fijo + relativo)
        if p["motivo"]:
            motivos.append({"codigo": p["motivo"], "par": par, "temporalidad": "", "n": p["cuantas"]})
        pares.append(p)
    return {"origen": com["origen"], "maker": com["maker"], "taker": com["taker"], "conversion": com["conversion"],
            "vigencia_min": MUESTRA_VIGENTE_MIN, "pares": pares, "motivos": motivos, "listo": not motivos}


def estado(ahora_ms=None):
    """Las siete familias juntas, en el mismo estado que ya lee la pantalla: las 12 series con tendencia, impulso,
    volatilidad, volumen y estructura, más el contexto de BTC y el costo del momento. `listo` pide las tres cosas: sin
    contexto o sin costo tampoco se puede mirar una oportunidad completa."""
    ahora = ahora_ms or lib_datos.ahora_local_ms()
    e = lib_indicadores.estado(ahora, extra=valores)
    e.update(bollinger=[BOLLINGER_VELAS, BOLLINGER_DESVIOS], atr=ATR_PERIODO, volumen=VOLUMEN_VELAS,
             ruptura=RUPTURA_VELAS, contexto=contexto(e["series"]), costo=costo(ahora))
    e["listo"] = bool(e["listo"] and e["contexto"]["listo"] and e["costo"]["listo"])
    return e
