#!/usr/bin/env python3
"""simular — «si hubiera puesto X USDT»: el historial guardado recorrido con las reglas de hoy. Solo biblioteca estándar.

  simular.py estado <entrada.json {}>              <salida.json>   → {ok, datos}
  simular.py correr <entrada.json {monto, dias}>   <salida.json>   → {ok, datos}

Ninguna de las dos toca la red: recorre las velas que ya están guardadas (`bin/lib_simulacion.py`). El resultado queda en
`<datos>/mercado/simulacion.json`. Es una cuenta aparte, en memoria: el saldo de prueba y el real no se tocan.
"""
import json
import os

import backtest
import lib_datos
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
    r = lib_simulacion.simular(d.get("monto"), d.get("dias"), recorrido)
    r["cuando"] = lib_datos.iso(ahora_ms or lib_datos.ahora_local_ms())
    return {"ok": True, "datos": {**lib_simulacion.parametros(), "ultima": escribir(r)}}


if __name__ == "__main__":
    nucleo.script({"estado": estado, "correr": correr}, __doc__)
