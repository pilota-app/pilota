#!/usr/bin/env python3
"""panel — la pantalla principal. Solo biblioteca estándar.

  panel.py estado <entrada.json {}>                      <salida.json>   → {ok, datos}
  panel.py local  <entrada.json {moneda, tasa}>          <salida.json>   → {ok, datos, error?}

Ninguna de las dos toca la red.

`estado` es todo lo que se ve al abrir Pilota, armado de lo que ya está escrito (`bin/lib_panel.py`): la banda de prueba
o real, el saldo en USDT con su línea del piso y su referencia aproximada en moneda local, los medidores de puntaje y
exigencia de cada par, las posiciones con lo que llevan ganado, su stop y su objetivo, las propuestas que esperan un
«Sí» con su cuenta atrás, el estado del motor, las últimas líneas del registro, la línea diaria y lo que cuenta la
mascota. No decide ni opera nada.

`local` guarda la moneda en la que se quiere ver la referencia y a cuánto está un USDT en ella. Es solo para mirar: la
operación es siempre en USDT, el número lo escribe la persona y no sale de su computador.
"""
import lib_panel
import nucleo


def estado(d=None, ahora_ms=None):
    """`ahora_ms` solo se pasa en las pruebas (una hora fija): la acción siempre mira con la hora de ahora."""
    return {"ok": True, "datos": lib_panel.estado(ahora_ms)}


def local(d, ahora_ms=None):
    """La moneda de referencia y su tasa. Lo que escribe la persona llega en el archivo de entrada y se revisa acá
    también: un código de moneda y un número, nada más. Lo que no venga no se cambia."""
    moneda = d.get("moneda")
    if moneda is not None and not isinstance(moneda, str):
        return {"ok": False, "error": "moneda", "datos": lib_panel.local()}
    tasa = d.get("tasa")
    if tasa is not None and (isinstance(tasa, bool) or not isinstance(tasa, (int, float))):
        return {"ok": False, "error": "tasa", "datos": lib_panel.local()}
    r = lib_panel.guardar_local(moneda, tasa, ahora_ms=ahora_ms)
    if not r["hecho"]:
        return {"ok": False, "error": r["motivo"], "datos": r["datos"]}
    return {"ok": True, "datos": {**lib_panel.estado(ahora_ms), "local": r["datos"], "hecho": True}}


if __name__ == "__main__":
    nucleo.script({"estado": estado, "local": local}, __doc__)
