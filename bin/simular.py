#!/usr/bin/env python3
"""simular — «si hubiera puesto X USDT»: el historial guardado recorrido con las reglas de hoy. Solo biblioteca estándar.

  simular.py estado <entrada.json {}>              <salida.json>   → {ok, datos}
  simular.py correr <entrada.json {monto, dias}>   <salida.json>   → {ok, datos}
  simular.py mapa   <entrada.json {}>              <salida.json>   → {ok, datos}   (el mapa de inicios)

`correr` devuelve además los cinco perfiles lado a lado (`lib_simulacion.comparar`), cada uno con sus movimientos.

Ninguna de las dos toca la red: recorre las velas que ya están guardadas (`bin/lib_simulacion.py`). El resultado queda en
`<datos>/mercado/simulacion.json`. Es una cuenta aparte, en memoria: el saldo de prueba y el real no se tocan.
"""
import json
import os

import backtest
import lib_datos
import lib_costos
import lib_tamano
import lib_simulacion
import nucleo


def ruta():
    return os.path.join(lib_datos.carpeta_mercado(), "simulacion.json")


def guardado():
    try:
        with open(ruta(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def escribir(d):
    nucleo.escribir_json(ruta(), d)
    return d


def estado(d, ahora_ms=None):
    return {"ok": True, "datos": {**lib_simulacion.parametros(), "ultima": guardado()}}


def correr(d, ahora_ms=None):
    d = d if isinstance(d, dict) else {}
    recorrido = backtest.correr(ahora_ms, sensibilidad=False, con_todas=True)
    r = lib_simulacion.comparar(d.get("monto"), d.get("dias"), recorrido)
    r["cuando"] = lib_datos.iso(ahora_ms or lib_datos.ahora_local_ms())
    return {"ok": True, "datos": {**lib_simulacion.parametros(), "ultima": escribir(r)}}


def mapa(d, ahora_ms=None):
    """El mapa de inicios (`lib_simulacion.mapa`): cuánto habría dejado cada perfil empezando en distintas fechas."""
    ms = (ahora_ms or lib_datos.ahora_local_ms()) // lib_datos.DIA_MS * lib_datos.DIA_MS
    com = lib_tamano.comisiones(lib_costos.comisiones())
    return {"ok": True, "datos": lib_simulacion.mapa(100, com, ms)}


if __name__ == "__main__":
    nucleo.script({"estado": estado, "correr": correr, "mapa": mapa}, __doc__)
