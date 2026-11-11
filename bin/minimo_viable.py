#!/usr/bin/env python3
"""minimo_viable — el capital más chico con el que Pilota puede operar de verdad. Solo biblioteca estándar.

  minimo_viable.py estado <entrada.json {"capital": 200}> <salida.json>     → {ok, datos}
  minimo_viable.py calcular <entrada.json {"capital": 200}> <salida.json>   → {ok, datos, error?}

«estado» no toca la red: devuelve el último cálculo guardado y, con el capital que le pasan, si alcanza. «calcular» lee de
Binance los filtros vigentes de los dos pares que se operan (tick, paso de cantidad, cantidad mínima y nocional mínimo), el
precio de la última vela cerrada y las comisiones, y saca el capital mínimo viable.

La cuenta sigue el mismo orden que el tamaño de una operación:
1. **Los mínimos de Binance.** La cantidad tiene que servir para la compra y para las dos patas de la protección automática
   (la OCO: una con el objetivo y otra con el stop). La pata del stop vale menos USDT, así que es la que manda.
2. **La reserva**: el 40 % del capital se queda en USDT y no se opera nunca.
3. **Dos posiciones a la vez**: lo que queda se reparte entre las dos.
4. **Riesgo máximo del 2 %** del capital por operación.
Capital mínimo = la posición mínima dividida por la parte del capital que una posición puede usar (la menor entre 2-3 y 4).

Lo que no se negocia aquí:
- **Precio de vela cerrada**, igual que el resto de Pilota: la vela en curso todavía puede cambiar.
- **Supuestos conservadores y marcados.** El stop se supone a `CAIDA_STOP` del precio (más abajo que cualquier estrategia: un
  stop más abajo pide más cantidad para pasar el nocional) y, mientras no haya llave, las comisiones son las supuestas con
  `origen: "supuesto"`; la pantalla lo dice. El conector real (su propio paso) deja las de la API en `mercado/comisiones.json`.
- **Nada de Binance se muestra tal cual**: los filtros son números y el par y su moneda se revisan contra los que conocemos.

Dónde queda: `<datos>/mercado/minimo.json` (lo que devuelve `medir()`, con la hora del cálculo).
"""
import math
import os
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

import lib_datos
import nucleo

#: Los pares que se compran (los de USDT solo dan historia y el filtro de BTC) y la moneda de cada uno.
PARES = ("BTCFDUSD", "ETHFDUSD")
MONEDAS = ("BTC", "ETH")
RESERVA = 0.40            # freno: el 40 % del capital se queda siempre en USDT
POSICIONES = 2            # freno: máximo 2 posiciones abiertas
RIESGO = 0.02             # freno: 2 % del capital por operación
#: Supuesto conservador para el stop: ninguna estrategia lo pone más abajo, y más abajo pide más cantidad para que la pata del
#: stop pase el nocional mínimo. Cuando una estrategia salga en dos mitades y la mitad no alcance el mínimo, sale entera: el
#: mínimo de aquí es el de la posición completa con su protección en los dos lados.
CAIDA_STOP = 0.05
SUBIDA_OBJETIVO = 0.02    # la otra pata (+2 %): su nocional nunca es el que manda, se informa igual
#: Mientras Pilota no tenga la llave: maker 0 % contra FDUSD, taker 0,1 % y la conversión USDT↔FDUSD (spread y comisión).
COMISIONES_SUPUESTAS = {"maker": 0.0, "taker": 0.001, "conversion": 0.0005}
COMISION_MAXIMA = 0.01    # una comisión mayor que esta no se cree: se vuelve a los supuestos
CAPITAL_MAXIMO = 1_000_000


def ruta_minimo():
    return os.path.join(lib_datos.carpeta_mercado(), "minimo.json")


def ruta_comisiones():
    return os.path.join(lib_datos.carpeta_mercado(), "comisiones.json")


# ── Redondear como redondea Binance ──────────────────────────────────────────────────────────────────────────────────────────

def subir_al_paso(valor, paso):
    """El múltiplo del paso igual o mayor que `valor`: así la cantidad es una que Binance acepta y no queda bajo el mínimo."""
    if paso <= 0:
        return valor
    p = Decimal(str(paso))
    return float((Decimal(str(valor)) / p).quantize(Decimal(1), rounding=ROUND_CEILING) * p)


def bajar_al_tick(precio, tick):
    """El múltiplo del tick igual o menor que `precio`. El stop se redondea para abajo: nocional más chico, cuenta más exigente."""
    if tick <= 0:
        return precio
    t = Decimal(str(tick))
    return float((Decimal(str(precio)) / t).quantize(Decimal(1), rounding=ROUND_FLOOR) * t)


# ── Lo que dice Binance ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _numero(filtro, clave, positivo=True):
    try:
        return lib_datos.numero(filtro.get(clave), positivo=positivo)
    except (TypeError, ValueError):
        raise lib_datos.Respuesta(f"Binance devolvió un «{clave}» que no entiendo.") from None


def filtros_de(simbolo, par, moneda):
    """Los filtros vigentes de un par, como los da exchangeInfo. Lo que no se entienda es un error: con filtros a medias no se
    calcula ningún mínimo (una orden rechazada por Binance es una posición sin protección)."""
    if not isinstance(simbolo, dict) or simbolo.get("symbol") != par or simbolo.get("baseAsset") != moneda:
        raise lib_datos.Respuesta("Binance no devolvió los filtros de ese par.")
    f = {"par": par, "moneda": moneda, "tick": 0.0, "paso": 0.0, "cantidad_minima": 0.0, "nocional_minimo": 0.0,
         "proteccion": simbolo.get("ocoAllowed") is True, "operando": simbolo.get("status") == "TRADING"}
    filtros = simbolo.get("filters")
    if not isinstance(filtros, list):
        raise lib_datos.Respuesta("Binance no dijo los mínimos de ese par.")
    for filtro in filtros:
        if not isinstance(filtro, dict):
            raise lib_datos.Respuesta("Binance devolvió un filtro que no entiendo.")
        tipo = filtro.get("filterType")
        if tipo == "PRICE_FILTER":
            f["tick"] = _numero(filtro, "tickSize")
        elif tipo == "LOT_SIZE":
            f["paso"] = _numero(filtro, "stepSize")
            f["cantidad_minima"] = _numero(filtro, "minQty")
        elif tipo in ("NOTIONAL", "MIN_NOTIONAL"):
            f["nocional_minimo"] = max(f["nocional_minimo"], _numero(filtro, "minNotional", positivo=False))
    if not (f["tick"] and f["paso"] and f["cantidad_minima"]):
        raise lib_datos.Respuesta("Binance no dijo los mínimos de ese par.")
    return f


def precio_cerrado(cliente, par, ahora_ms):
    """El cierre de la última vela de 1 h cerrada: el precio con el que se mide el mínimo, nunca la vela en curso."""
    paso = lib_datos.PASO_MS["1h"]
    fin = (ahora_ms // paso) * paso
    cerradas = [v for v in (lib_datos.vela_de(f, paso) for f in cliente.klines(par, "1h", fin - 3 * paso))
                if v[0] + paso <= ahora_ms]
    if not cerradas:
        raise lib_datos.Respuesta("Binance no dio ninguna vela cerrada de ese par.")
    return cerradas[-1][4]


def comisiones():
    """Las comisiones con las que se hace la cuenta: las que dejó escritas el conector real o, mientras no haya llave, las
    supuestas. `origen` dice cuál de las dos es y la pantalla lo muestra: una cuenta con costos supuestos se dice."""
    def valida(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= COMISION_MAXIMA

    d = nucleo.leer_json(ruta_comisiones(), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    c = dict(COMISIONES_SUPUESTAS, origen="supuesto")
    if isinstance(d, dict) and all(valida(d.get(k)) for k in ("maker", "taker")):
        c.update(maker=float(d["maker"]), taker=float(d["taker"]), origen="api")
    return c


# ── La cuenta ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def parte_del_capital():
    """Qué parte del capital puede usar una posición: lo que dejan la reserva y las dos posiciones, o lo que deja el riesgo
    máximo con el stop supuesto. Manda la menor, como en el tamaño de una operación."""
    return min((1 - RESERVA) / POSICIONES, RIESGO / CAIDA_STOP)


def posicion_minima(f, precio, com):
    """Lo menos que puede valer una posición de ese par: la cantidad más chica que Binance acepta en la compra y en las dos
    patas de la protección, más los costos de entrar y salir. Y el capital que hace falta para poder abrirla."""
    stop = bajar_al_tick(precio * (1 - CAIDA_STOP), f["tick"])
    objetivo = bajar_al_tick(precio * (1 + SUBIDA_OBJETIVO), f["tick"])
    if stop <= 0:
        raise lib_datos.Respuesta("Binance devolvió un precio que no entiendo.")
    cantidad = subir_al_paso(max(f["cantidad_minima"], f["nocional_minimo"] / precio, f["nocional_minimo"] / stop), f["paso"])
    entrada = cantidad * precio
    # Entrar es maker (límite post-only contra FDUSD), salir por el stop es taker, y hay que convertir USDT↔FDUSD.
    costos = entrada * (com["conversion"] + com["maker"] + com["taker"])
    posicion = entrada + costos
    motivo = "" if f["operando"] else "sin_operar"
    if f["operando"] and not f["proteccion"]:
        motivo = "sin_proteccion"
    return {**f, "precio": round(precio, 2), "stop": stop, "objetivo": objetivo, "cantidad": cantidad,
            "entrada": round(entrada, 2), "nocional_stop": round(cantidad * stop, 2), "costos": round(costos, 4),
            "posicion": round(posicion, 2), "capital": math.ceil(posicion / parte_del_capital()), "motivo": motivo}


def armar(pares, com, ahora_ms, capital=0):
    minimo = max((p["capital"] for p in pares), default=0)
    motivos = [{"codigo": p["motivo"], "par": p["par"]} for p in pares if p["motivo"]]
    return con_capital({"formato": 1, "calculado": True, "cuando": lib_datos.iso(ahora_ms), "moneda": "USDT",
                        "capital_minimo": minimo, "reserva": RESERVA, "posiciones": POSICIONES, "riesgo": RIESGO,
                        "caida_stop": CAIDA_STOP, "parte": round(parte_del_capital(), 4), "comisiones": com,
                        "pares": pares, "motivos": motivos, "listo": not motivos}, capital)


def con_capital(d, capital):
    """Le suma al cálculo si el capital de la persona alcanza. Sin red: sirve igual para lo guardado."""
    minimo = d.get("capital_minimo") or 0
    d["capital"] = capital
    d["alcanza"] = bool(minimo and capital >= minimo)   # sin cálculo no se dice que alcanza: todavía no se sabe
    d["falta"] = max(0, minimo - capital)
    return d


def medir(cliente, capital=0):
    """Pregunta a Binance y devuelve el cálculo completo, con una sola hora de referencia para los dos pares."""
    ahora = cliente.ahora_ms()
    simbolos = {s["symbol"]: s for s in cliente.info_pares(PARES) if isinstance(s, dict) and isinstance(s.get("symbol"), str)}
    com = comisiones()
    pares = [posicion_minima(filtros_de(simbolos.get(par), par, moneda), precio_cerrado(cliente, par, ahora), com)
             for par, moneda in zip(PARES, MONEDAS)]
    return armar(pares, com, ahora, capital)


def guardado():
    d = nucleo.leer_json(ruta_minimo(), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    if not isinstance(d, dict) or d.get("formato") != 1 or not d.get("calculado") or not isinstance(d.get("pares"), list):
        return {"formato": 1, "calculado": False, "moneda": "USDT", "capital_minimo": 0, "pares": [], "motivos": []}
    return d


# ── Las acciones ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _capital(d):
    v = d.get("capital")
    return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= CAPITAL_MAXIMO else 0


def estado(d):
    return {"ok": True, "datos": con_capital(guardado(), _capital(d))}


def calcular(d, cliente=None):
    """`cliente` solo se pasa en las pruebas (una API de juguete): la acción siempre habla con Binance."""
    capital = _capital(d)
    try:
        datos = medir(cliente or lib_datos.Binance(), capital)
    except lib_datos.Limitado:
        error = "limite"
    except lib_datos.Temporal:
        error = "red"
    except lib_datos.Respuesta:
        error = "respuesta"
    else:
        nucleo.escribir_json(ruta_minimo(), datos)
        return {"ok": True, "datos": datos, "error": ""}
    return {"ok": False, "datos": con_capital(guardado(), capital), "error": error}


if __name__ == "__main__":
    nucleo.script({"estado": estado, "calcular": calcular}, __doc__)
