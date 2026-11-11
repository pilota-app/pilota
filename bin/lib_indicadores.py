#!/usr/bin/env python3
"""lib_indicadores — tendencia e impulso sobre las velas guardadas. Solo biblioteca estándar. No es una acción.

Las dos primeras familias del puntaje: **tendencia** (medias de 20, 50 y 200 velas y ADX) e **impulso** (RSI y MACD). Dos o
tres parámetros por familia y nada más: cada parámetro que se suma hay que calibrarlo después con datos de verdad. Las otras
cinco (volatilidad, volumen, estructura, contexto y costo) están en `bin/lib_indicadores_mercado.py`: entran por `extra` en
`de_serie` y `estado`, así las velas se recorren una sola vez, y es ese módulo el que arma el estado completo de la acción.

Las cuentas están separadas en dos capas:
- Las de siempre, sobre listas de números (`sma`, `ema`, `rsi`, `macd`, `adx`): devuelven la serie completa, con `None` en las
  velas en que el indicador todavía no existe. Son las que usan el backtest y la calibración, vela por vela.
- Las de la app (`valores`, `de_serie`, `estado`): el valor de **ahora** de cada par y temporalidad, leyendo lo guardado.

Lo que no se negocia aquí:
- **Solo velas cerradas.** La vela en curso no entra nunca: sus valores todavía pueden cambiar y moverían el indicador.
- **Continuidad antes de calcular.** Una serie con hoyos, corta o atrasada no se calcula: queda con su motivo (`sin_datos`,
  `huecos`, `atrasado`, `faltan_velas`, los mismos códigos de `lib_datos`) y la pantalla lo dice. Una media o un RSI sobre una
  serie con velas faltando en medio es un número falso, y un número falso es peor que ninguno.
- **La ventana es fija** (`VENTANA` velas: la media más larga más el calentamiento). RSI, ADX y MACD son suavizados que
  arrastran todo lo anterior, así que con una ventana fija el valor de hoy es siempre el mismo, no importa cuánta historia
  esté guardada ni si acaba de llegar el historial largo.
- **Nada se redondea.** El redondeo vive en la pantalla (`numero()` en `ui/app.js`): el puntaje y el backtest trabajan con
  todos los decimales.

Dónde queda: `<datos>/mercado/indicadores.json` (lo que devuelve `estado()`, con la hora del cálculo).
"""
import math
import os

import lib_datos
import nucleo

#: Las medias simples de la familia tendencia, de la más corta a la más larga.
MEDIAS = (20, 50, 200)
RSI_PERIODO = 14
MACD_RAPIDA, MACD_LENTA, MACD_SENAL = 12, 26, 9
ADX_PERIODO = 14
#: Velas de calentamiento antes de la media más larga: lo que necesitan los suavizados para que el valor de hoy no dependa de
#: dónde empezó la serie (con 200 velas, lo que arrastran de antes queda muy por debajo de lo que se muestra).
VELAS_CALENTAMIENTO = 200
#: La ventana con la que se calcula, siempre la misma: las últimas `VENTANA` velas cerradas y seguidas.
VENTANA = max(MEDIAS) + VELAS_CALENTAMIENTO


def ruta_indicadores():
    return os.path.join(lib_datos.carpeta_mercado(), "indicadores.json")


# ── Las cuentas de siempre, sobre listas de números ──────────────────────────────────────────────────────────────────────────

def sma(valores, n):
    """La media simple de cada punto: `None` hasta que hay `n` valores. La suma se recalcula entera en cada paso (una resta
    arrastrada pierde decimales en series largas, y estas medias son la base de todo lo demás)."""
    if n <= 0:
        raise ValueError("una media necesita al menos una vela")
    return [math.fsum(valores[i - n + 1:i + 1]) / n if i >= n - 1 else None for i in range(len(valores))]


def ema(valores, n):
    """La media exponencial, sembrada con la media simple de las primeras `n`: el valor queda definido desde la vela `n` y no
    depende de cuánta historia se le pase antes del calentamiento."""
    if n <= 0:
        raise ValueError("una media necesita al menos una vela")
    salida = [None] * len(valores)
    if len(valores) < n:
        return salida
    peso = 2.0 / (n + 1)
    actual = math.fsum(valores[:n]) / n
    salida[n - 1] = actual
    for i in range(n, len(valores)):
        actual = valores[i] * peso + actual * (1 - peso)
        salida[i] = actual
    return salida


def _rsi_de(sube, baja):
    """0 a 100. Sin bajadas, 100 (todo sube); sin ningún movimiento, 50: un precio plano no es ni fuerza ni debilidad."""
    if baja == 0:
        return 100.0 if sube else 50.0
    return 100.0 - 100.0 / (1 + sube / baja)


def rsi(cierres, n=RSI_PERIODO):
    """El RSI de Wilder: cuánto de lo que se movió el precio fue para arriba. Suavizado de Wilder (el original), no exponencial."""
    salida = [None] * len(cierres)
    if len(cierres) <= n:
        return salida
    subidas = [max(0.0, b - a) for a, b in zip(cierres, cierres[1:])]
    bajadas = [max(0.0, a - b) for a, b in zip(cierres, cierres[1:])]
    sube, baja = math.fsum(subidas[:n]) / n, math.fsum(bajadas[:n]) / n
    salida[n] = _rsi_de(sube, baja)
    for i in range(n, len(subidas)):
        sube = (sube * (n - 1) + subidas[i]) / n
        baja = (baja * (n - 1) + bajadas[i]) / n
        salida[i + 1] = _rsi_de(sube, baja)
    return salida


def macd(cierres, rapida=MACD_RAPIDA, lenta=MACD_LENTA, senal=MACD_SENAL):
    """MACD: la diferencia entre la media exponencial corta y la larga, su señal (la media exponencial de esa diferencia) y el
    histograma (diferencia menos señal). Devuelve las tres series, alineadas con las velas."""
    rapidas, lentas = ema(cierres, rapida), ema(cierres, lenta)
    linea = [None if (a is None or b is None) else a - b for a, b in zip(rapidas, lentas)]
    desde = next((i for i, v in enumerate(linea) if v is not None), len(linea))
    suavizada = [None] * desde + ema(linea[desde:], senal)
    return {"macd": linea, "senal": suavizada,
            "histograma": [None if (a is None or b is None) else a - b for a, b in zip(linea, suavizada)]}


def adx(altos, bajos, cierres, n=ADX_PERIODO):
    """El ADX de Wilder: cuánta fuerza tiene la tendencia (0 a 100), sin decir para qué lado. `di_mas` y `di_menos` sí lo dicen.
    Devuelve las tres series, alineadas con las velas (el ADX recién existe en la vela 2n−1: se suaviza dos veces)."""
    largo = len(cierres)
    if not (len(altos) == len(bajos) == largo):
        raise ValueError("las tres series tienen que tener el mismo largo")
    vacias = {"adx": [None] * largo, "di_mas": [None] * largo, "di_menos": [None] * largo}
    if n <= 0:
        raise ValueError("el ADX necesita al menos una vela")
    if largo < 2 * n:
        return vacias
    rango, dm_mas, dm_menos = [], [], []     # desde la vela 1: cada uno mira también la vela anterior
    for i in range(1, largo):
        sube, baja = altos[i] - altos[i - 1], bajos[i - 1] - bajos[i]
        rango.append(max(altos[i] - bajos[i], abs(altos[i] - cierres[i - 1]), abs(bajos[i] - cierres[i - 1])))
        dm_mas.append(sube if sube > baja and sube > 0 else 0.0)
        dm_menos.append(baja if baja > sube and baja > 0 else 0.0)
    di_mas, di_menos, dx = [None] * largo, [None] * largo, [None] * largo
    suma_rango, suma_mas, suma_menos = (math.fsum(x[:n]) for x in (rango, dm_mas, dm_menos))
    for i in range(n, largo):
        if i > n:                            # el suavizado de Wilder: se saca un promedio y se suma la vela nueva
            j = i - 1
            suma_rango = suma_rango - suma_rango / n + rango[j]
            suma_mas = suma_mas - suma_mas / n + dm_mas[j]
            suma_menos = suma_menos - suma_menos / n + dm_menos[j]
        mas = 100.0 * suma_mas / suma_rango if suma_rango else 0.0
        menos = 100.0 * suma_menos / suma_rango if suma_rango else 0.0
        di_mas[i], di_menos[i] = mas, menos
        dx[i] = 100.0 * abs(mas - menos) / (mas + menos) if mas + menos else 0.0
    fuerza = [None] * largo
    fuerza[2 * n - 1] = math.fsum(dx[n:2 * n]) / n
    for i in range(2 * n, largo):
        fuerza[i] = (fuerza[i - 1] * (n - 1) + dx[i]) / n
    return {"adx": fuerza, "di_mas": di_mas, "di_menos": di_menos}


# ── Lo que usa la app: el valor de ahora de cada serie ───────────────────────────────────────────────────────────────────────

def valores(velas):
    """Tendencia e impulso al cierre de la última vela de `velas` (la más reciente va al final, todas cerradas y seguidas).
    Lo que todavía no se puede calcular va en `None`: aquí no se inventa ningún número."""
    cierres, altos, bajos = [v[4] for v in velas], [v[2] for v in velas], [v[3] for v in velas]
    fuerza, impulso = adx(altos, bajos, cierres), macd(cierres)
    tendencia = {f"media_{n}": sma(cierres, n)[-1] for n in MEDIAS}
    tendencia.update(adx=fuerza["adx"][-1], di_mas=fuerza["di_mas"][-1], di_menos=fuerza["di_menos"][-1])
    return {"cierre": cierres[-1], "tendencia": tendencia,
            "impulso": {"rsi": rsi(cierres)[-1], "macd": impulso["macd"][-1],
                        "senal": impulso["senal"][-1], "histograma": impulso["histograma"][-1]}}


def velas_cerradas(par, temporalidad, ahora_ms=None):
    """La ventana con la que se calcula: las últimas `VENTANA` velas guardadas que ya cerraron."""
    paso = lib_datos.PASO_MS[temporalidad]
    fin = ((ahora_ms or lib_datos.ahora_local_ms()) // paso) * paso   # la apertura de la vela en curso: el borde de lo cerrado
    return [v for v in lib_datos.leer_serie(par, temporalidad) if v[0] < fin][-VENTANA:]


def de_serie(par, temporalidad, ahora_ms=None, extra=None):
    """Los indicadores de ahora de una serie, o el motivo por el que no se calculan. Los códigos son los de `lib_datos`: la
    pantalla ya sabe traducirlos y nunca muestra texto que venga de Binance.

    `extra(velas)` es por dónde entran las otras familias (`lib_indicadores_mercado.valores`): lo que devuelve se suma a la
    serie y las velas se recorren una sola vez. Solo se llama cuando la serie está completa: una familia más no relaja la
    continuidad."""
    paso = lib_datos.PASO_MS[temporalidad]
    ultima = ((ahora_ms or lib_datos.ahora_local_ms()) // paso) * paso - paso
    velas = velas_cerradas(par, temporalidad, ahora_ms)
    hoyos = lib_datos.huecos(velas, temporalidad)
    e = {"par": par, "temporalidad": temporalidad, "velas": len(velas), "necesarias": VENTANA,
         "desde": velas[0][0] if velas else None, "vela": velas[-1][0] if velas else None, "ultima_cerrada": ultima,
         "listo": False, "motivo": "", "cuantas": 0}
    if not velas:
        e["motivo"], e["cuantas"] = "sin_datos", VENTANA
    elif hoyos:
        e["motivo"], e["cuantas"] = "huecos", len(hoyos)
    elif velas[-1][0] < ultima:
        e["motivo"], e["cuantas"] = "atrasado", (ultima - velas[-1][0]) // paso
    elif len(velas) < VENTANA:
        e["motivo"], e["cuantas"] = "faltan_velas", VENTANA - len(velas)
    else:
        e.update(valores(velas), listo=True)
        if extra is not None:
            e.update(extra(velas))
    return e


def estado(ahora_ms=None, extra=None):
    """Los indicadores de las 12 series (los 4 pares en 1 h, 4 h y 1 d). La de 1 m queda fuera a propósito: es la que mira los
    cruces de stop y objetivo, no la que decide."""
    ahora = ahora_ms or lib_datos.ahora_local_ms()
    series = [de_serie(p, t, ahora, extra) for p in lib_datos.PARES for t in lib_datos.TEMPORALIDADES]
    motivos = [{"codigo": s["motivo"], "par": s["par"], "temporalidad": s["temporalidad"], "n": s["cuantas"]}
               for s in series if s["motivo"]]
    return {"formato": 1, "cuando": lib_datos.iso(ahora), "ventana": VENTANA, "medias": list(MEDIAS),
            "rsi": RSI_PERIODO, "macd": [MACD_RAPIDA, MACD_LENTA, MACD_SENAL], "adx": ADX_PERIODO,
            "series": series, "motivos": motivos, "listas": sum(1 for s in series if s["listo"]),
            "listo": not motivos}


def escribir_estado(e):
    """Deja escrito el último cálculo: lo leen el puntaje, el motor y la pantalla sin volver a recorrer las velas."""
    nucleo.escribir_json(ruta_indicadores(), e)
    return e
