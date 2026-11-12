#!/usr/bin/env python3
"""vivo — la prueba en vivo con un perfil: el robot opera solo con dinero ficticio y los precios de ahora. Solo biblioteca
estándar.

  vivo.py estado   <entrada.json {}>                <salida.json>   → {ok, datos}
  vivo.py empezar  <entrada.json {perfil, monto}>   <salida.json>   → {ok, datos, error?}
  vivo.py detener  <entrada.json {}>                <salida.json>   → {ok, datos}

Ninguna toca la red: el muestreo trae los precios y las velas, y el motor da las vueltas (`bin/lib_piloto.py`). Empezar
reinicia el saldo de prueba al monto elegido; el saldo real no se toca nunca desde aquí.
"""
import lib_piloto
import nucleo


def estado(d=None, ahora_ms=None):
    return {"ok": True, "datos": lib_piloto.estado(ahora_ms)}


def empezar(d=None, ahora_ms=None):
    d = d if isinstance(d, dict) else {}
    r = lib_piloto.empezar(d.get("perfil"), d.get("monto"), ahora_ms)
    if not r["ok"]:
        return {"ok": False, "error": r["error"], "datos": lib_piloto.estado(ahora_ms)}
    return {"ok": True, "datos": lib_piloto.estado(ahora_ms)}


def detener(d=None, ahora_ms=None):
    lib_piloto.detener(ahora_ms)
    return {"ok": True, "datos": lib_piloto.estado(ahora_ms)}


if __name__ == "__main__":
    nucleo.script({"estado": estado, "empezar": empezar, "detener": detener}, __doc__)
