#!/usr/bin/env python3
"""noticias — la llave de Alpaca para leer noticias con su hora exacta. Solo biblioteca estándar.

  noticias.py estado       <entrada.json {}>                 <salida.json>   → {ok, datos}
  noticias.py conectar     <entrada.json {llave, secreto}>   <salida.json>   → {ok, datos, error?}
  noticias.py revisar      <entrada.json {}>                 <salida.json>   → {ok, datos, error?}
  noticias.py desconectar  <entrada.json {}>                 <salida.json>   → {ok, datos}

La llave y el secreto llegan en el archivo de entrada (nunca como argumento), se prueban contra Alpaca y se guardan en el
llavero del sistema: no se escriben en ningún archivo de Pilota ni vuelven en la respuesta. Ver `bin/lib_alpaca.py`.
"""
import lib_alpaca
import nucleo


def _respuesta(r):
    if r.get("ok") is False and r.get("motivo"):
        return {"ok": False, "datos": r, "error": r["motivo"]}
    return {"ok": True, "datos": r}


def estado(d, ahora_ms=None):
    return {"ok": True, "datos": lib_alpaca.estado()}


def conectar(d, ahora_ms=None):
    d = d if isinstance(d, dict) else {}
    return _respuesta(lib_alpaca.conectar(d.get("llave"), d.get("secreto")))


def revisar(d, ahora_ms=None):
    return _respuesta(lib_alpaca.revisar())


def desconectar(d, ahora_ms=None):
    return _respuesta(lib_alpaca.desconectar())


if __name__ == "__main__":
    nucleo.script({"estado": estado, "conectar": conectar, "revisar": revisar, "desconectar": desconectar}, __doc__)
