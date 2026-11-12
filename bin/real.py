#!/usr/bin/env python3
"""real — conectar Binance y operar con dinero de verdad. Solo biblioteca estándar.

  real.py estado       <entrada.json {}>                      <salida.json>   → {ok, datos}
  real.py conectar     <entrada.json {llave, secreto}>        <salida.json>   → {ok, datos, error?}
  real.py revisar      <entrada.json {}>                      <salida.json>   → {ok, datos}
  real.py desconectar  <entrada.json {}>                      <salida.json>   → {ok, datos, error?}
  real.py activar      <entrada.json {presupuesto, frase}>    <salida.json>   → {ok, datos, error?}
  real.py desactivar   <entrada.json {}>                      <salida.json>   → {ok, datos, error?}
  real.py emergencia   <entrada.json {}>                      <salida.json>   → {ok, datos, error?}

La llave y el secreto llegan en el archivo de entrada (nunca como argumento) y se guardan en el llavero del sistema
(`bin/lib_llavero.py`): no se escriben en ningún archivo de Pilota ni vuelven en la respuesta. Ver `bin/lib_real.py`.
"""
import lib_real
import nucleo


def _respuesta(r):
    d = lib_real.estado()
    if isinstance(r, dict) and not r.get("hecho", True):
        return {"ok": False, "datos": d, "error": r.get("motivo") or "no_se_pudo"}
    return {"ok": True, "datos": d}


def estado(d, ahora_ms=None):
    return {"ok": True, "datos": lib_real.estado(ahora_ms)}


def conectar(d, ahora_ms=None):
    d = d if isinstance(d, dict) else {}
    return _respuesta(lib_real.conectar(d.get("llave"), d.get("secreto"), ahora_ms))


def revisar(d, ahora_ms=None):
    lib_real.revisar(ahora_ms)
    return {"ok": True, "datos": lib_real.estado(ahora_ms)}


def desconectar(d, ahora_ms=None):
    return _respuesta(lib_real.desconectar(ahora_ms))


def activar(d, ahora_ms=None):
    d = d if isinstance(d, dict) else {}
    return _respuesta(lib_real.activar(d.get("presupuesto"), d.get("frase"), ahora_ms))


def desactivar(d, ahora_ms=None):
    return _respuesta(lib_real.desactivar(ahora_ms))


def emergencia(d, ahora_ms=None):
    return _respuesta(lib_real.emergencia(ahora_ms))


if __name__ == "__main__":
    nucleo.script({"estado": estado, "conectar": conectar, "revisar": revisar, "desconectar": desconectar,
                   "activar": activar, "desactivar": desactivar, "emergencia": emergencia}, __doc__)
