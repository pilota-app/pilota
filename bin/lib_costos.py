#!/usr/bin/env python3
"""lib_costos — lo que cuesta entrar y salir, y el modelo de spread y de no llenado. Solo biblioteca estándar. No es una
acción.

Es lo que el backtest (`bin/backtest.py`) le resta a cada operación antes de decir si ganó. Tres cosas, y ninguna se puede
saltar:

| Qué | Cómo se cuenta |
|---|---|
| comisiones por lado | entrar es **maker** (límite post-only contra FDUSD), salir por el objetivo también; salir por el stop es **taker** |
| conversión USDT↔FDUSD | su comisión y su diferencia, una vez al entrar y una al salir (el saldo vive en USDT) |
| diferencia entre compra y venta | solo la paga el que cruza el libro: el stop sale a mercado y le pega al otro lado |

Y el **no llenado condicionado**: una orden límite no se llena porque el precio la tocó, se llena cuando el precio **sigue en
contra**. Una compra en `nivel` se cuenta llenada recién cuando el mínimo de la vela bajó de `nivel` por un margen de
`PENETRACION_SPREADS` diferencias de compra y venta. Con el factor en 0 basta tocarla (lo optimista) y con el factor alto hay
que atravesarla: esa es la **prueba de sensibilidad** (`SENSIBILIDAD`), que el reporte muestra entera para que se vea cuánto
del resultado es la regla y cuánto el mercado.

Lo que no se negocia aquí:
- **El costo supuesto es el malo, no el promedio.** Binance no da libro histórico: hasta que Pilota junte el suyo, el spread
  es `SPREAD_SUPUESTO`, bastante peor que el que se mide hoy en un par líquido (del orden de 1e-6). Un backtest que supone un
  costo optimista promete plata que no existe.
- **El modelo propio recién manda con `DIAS_MODELO` días de muestras propias**, y lo que se toma de ellas es el percentil
  `PERCENTIL_SPREAD`, no la media: el costo que importa es el de los ratos malos. `origen` dice cuál de los dos se usó y el
  reporte lo marca.
- **Los días son días con muestras**, no el rato entre la primera y la última: un día sin muestrear no es un día de datos.
- **Nada se redondea** y lo que no se entienda no existe: una línea de muestras a medias no entra (el archivo lo pudo tocar
  cualquiera, y un costo falso hace pasar una operación que no conviene).
- **Las comisiones son las de la API si el conector real ya las dejó escritas** y, si no, las supuestas
  (`minimo_viable.comisiones()`): `origen` lo dice, igual que en el capital mínimo viable.
"""
import json
import math
import os

import lib_datos
import minimo_viable

#: La diferencia entre compra y venta que se supone mientras no haya muestras propias: unos 5 puntos base, muy por encima de
#: la que se mide hoy en estos pares (del orden de 1e-6). Es a propósito: el backtest se equivoca para el lado caro.
SPREAD_SUPUESTO = 0.0005
#: Cuántos días con muestras propias hacen falta para dejar el supuesto y usar lo medido (la idea completa: 60).
DIAS_MODELO = 60
#: Qué parte de los spreads propios queda por debajo del que se usa: el percentil 90, no el promedio.
PERCENTIL_SPREAD = 0.90
#: Cuántas diferencias de compra y venta tiene que atravesar el precio para contar una límite como llenada.
PENETRACION_SPREADS = 1.0
#: La prueba de sensibilidad: los factores de penetración con los que se repite el recorrido completo. El del medio es el que
#: manda; el 0 es «tocarla basta» (lo optimista) y el alto, «hay que atravesarla» (lo pesimista).
SENSIBILIDAD = (0.0, PENETRACION_SPREADS, 3.0 * PENETRACION_SPREADS)
#: Un spread mayor que esto no se cree (en estos pares es del orden de 1e-6): el archivo lo pudo tocar cualquiera.
SPREAD_MAXIMO = 0.05
#: Tope de líneas de muestras que se leen de una vez: el muestreo guarda dos por ciclo y los archivos crecen para siempre.
MUESTRAS_MAXIMAS = 500_000
#: Qué lado paga comisión de cuál al salir: el objetivo es una límite (maker) y el stop sale a mercado (taker).
COMISION_SALIDA = {"objetivo": "maker", "stop": "taker"}


# ── El modelo de spread: el supuesto conservador y, con datos propios, lo medido ─────────────────────────────────────────────

def percentil(valores, p):
    """El valor bajo el que queda la fracción `p` de los datos, el del dato más cercano y sin interpolar: así el número que
    sale es uno que de verdad pasó. `None` sin datos: un percentil de nada no se inventa."""
    if not valores:
        return None
    orden = sorted(valores)
    return orden[min(len(orden) - 1, max(0, math.ceil(p * len(orden)) - 1))]


def _spread(valor):
    """Un spread relativo de un archivo que pudo tocar cualquiera: `None` si no es un número que tenga sentido."""
    try:
        v = lib_datos.numero(valor, positivo=False)
    except (TypeError, ValueError, lib_datos.Respuesta):
        return None
    return v if v <= SPREAD_MAXIMO else None


def muestras_propias(maximo=MUESTRAS_MAXIMAS):
    """Los spreads que ya guardó el muestreo (`mercado/muestras/<AAAA-MM>.jsonl`), por par operado, y cuántos días
    distintos cubren. Una línea que no se entiende se salta: el resto del archivo sigue sirviendo."""
    pares = {p: [] for p in lib_datos.PARES_OPERADOS}
    dias, cuantas = set(), 0
    for mes in lib_datos.meses_con_muestras():
        if cuantas >= maximo:
            break
        try:
            with open(os.path.join(lib_datos.carpeta_muestras(), mes + ".jsonl"), encoding="utf-8") as f:
                for linea in f:
                    if cuantas >= maximo:
                        break
                    try:
                        m = json.loads(linea)
                    except ValueError:
                        continue
                    if not isinstance(m, dict) or m.get("par") not in pares:
                        continue
                    ms, relativo = m.get("ms"), _spread(m.get("spread_relativo"))
                    if not isinstance(ms, int) or isinstance(ms, bool) or ms <= 0 or relativo is None:
                        continue
                    pares[m["par"]].append(relativo)
                    dias.add(ms // lib_datos.DIA_MS)
                    cuantas += 1
        except OSError:
            continue
    return {"pares": pares, "muestras": cuantas, "dias": len(dias)}


def modelo(muestras=None):
    """El modelo con el que el backtest supone el costo de cruzar el libro y el no llenado de una límite. Mientras no haya
    `DIAS_MODELO` días con muestras propias de los dos pares, el spread es el supuesto conservador y `origen` dice
    `"supuesto"`: el reporte lo marca y el reajuste, en su paso, lo vuelve a calcular cuando los datos lleguen."""
    d = muestras_propias() if muestras is None else muestras
    propios = {par: percentil(valores, PERCENTIL_SPREAD) for par, valores in d["pares"].items()}
    completo = d["dias"] >= DIAS_MODELO and all(propios.get(p) is not None for p in lib_datos.PARES_OPERADOS)
    return {"origen": "propio" if completo else "supuesto", "listo": completo, "dias": d["dias"],
            "dias_necesarios": DIAS_MODELO, "falta_dias": max(0, DIAS_MODELO - d["dias"]), "muestras": d["muestras"],
            "percentil": PERCENTIL_SPREAD, "supuesto": SPREAD_SUPUESTO, "penetracion": PENETRACION_SPREADS,
            "sensibilidad": list(SENSIBILIDAD),
            "pares": [{"par": par, "spread": propios[par] if completo else SPREAD_SUPUESTO, "propio": propios.get(par),
                       "muestras": len(d["pares"].get(par) or [])} for par in lib_datos.PARES_OPERADOS]}


def spread_de(m, par):
    """La diferencia entre compra y venta con la que se cuenta ese par. Sin modelo, el supuesto: nunca el optimista."""
    return next((p["spread"] for p in (m or {}).get("pares") or [] if p["par"] == par), SPREAD_SUPUESTO)


# ── El no llenado condicionado: una límite se llena cuando el precio sigue en contra ────────────────────────────────────────

def margen_llenado(spread, factor=PENETRACION_SPREADS):
    """Cuánto por debajo del nivel tiene que irse el precio para contar la compra como llenada, relativo al nivel. Con el
    factor en 0 basta tocarlo: ese es el extremo optimista de la prueba de sensibilidad, no el supuesto de la casa."""
    return max(0.0, float(factor)) * max(0.0, float(spread))


def llena(nivel, bajo, spread, factor=PENETRACION_SPREADS):
    """Si una compra límite en `nivel` se habría llenado en una vela cuyo mínimo fue `bajo`. Tocar el nivel no alcanza: la
    cola de órdenes en ese precio se come a la nuestra hasta que el precio sigue bajando."""
    return bajo <= nivel * (1 - margen_llenado(spread, factor))


# ── El costo de una operación, lado por lado ─────────────────────────────────────────────────────────────────────────────────

def comisiones():
    """Las mismas del capital mínimo viable: las de la API si el conector real ya las escribió, o las supuestas."""
    return minimo_viable.comisiones()


def resultado(entrada, salida, por, spread, com):
    """Lo que deja una operación de una unidad, después de los costos de cada lado. `por` es `"objetivo"` (sale con una
    límite, maker) o `"stop"` (sale a mercado, taker, y además cruza el libro: le pega al otro lado y se lleva la diferencia
    entre compra y venta). `bruto` es lo que se vería sin costos: la diferencia entre los dos es lo que se lleva operar."""
    maker, taker, conversion = com["maker"], com["taker"], com["conversion"]
    comision_salida = taker if COMISION_SALIDA.get(por) == "taker" else maker
    deslizamiento = salida * (spread if por == "stop" else 0.0)
    precio = salida - deslizamiento
    pagado = entrada * (1 + maker + conversion)
    recibido = precio * (1 - comision_salida - conversion)
    costos = (entrada * (maker + conversion) + deslizamiento + precio * (comision_salida + conversion)) / pagado
    return {"por": por, "precio_entrada": entrada, "precio_salida": precio, "pagado": pagado, "recibido": recibido,
            "bruto": (salida - entrada) / entrada, "neto": (recibido - pagado) / pagado, "costos": costos}
