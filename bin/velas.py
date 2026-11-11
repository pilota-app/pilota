#!/usr/bin/env python3
"""velas — las velas cerradas de Binance con las que Pilota decide. Solo biblioteca estándar.

  velas.py estado <entrada.json {"dias": 90}> <salida.json>      → {ok, datos}
  velas.py descargar <entrada.json {"dias": 90}> <salida.json>   → {ok, datos, error?}

«estado» no toca la red: mira lo guardado y deja escrito qué falta. «descargar» baja lo que falta de las 12 series (4 pares × 3
temporalidades) respetando los límites de la API. Mientras alguna serie no esté completa y continua, `datos.puede_operar` es
falso y `datos.motivos` dice por qué: Pilota no opera a ciegas.
"""
import lib_datos
import nucleo


def _dias(d):
    v = d.get("dias")
    return v if isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= lib_datos.DIAS_MINIMOS else lib_datos.DIAS_MINIMOS


def estado(d):
    return {"ok": True, "datos": lib_datos.escribir_estado(lib_datos.estado(_dias(d)))}


def descargar(d):
    dias = _dias(d)
    resumen = lib_datos.bajar_todo(lib_datos.Binance(), dias)
    datos = lib_datos.estado(dias)
    datos["descarga"] = resumen
    lib_datos.escribir_estado(datos)
    return {"ok": not resumen["error"], "datos": datos, "error": resumen["error"]}


if __name__ == "__main__":
    nucleo.script({"estado": estado, "descargar": descargar}, __doc__)
