#!/usr/bin/env python3
"""propuestas — los tres modos y las propuestas que vencen. Solo biblioteca estándar.

  propuestas.py estado    <entrada.json {}>                      <salida.json>   → {ok, datos}
  propuestas.py decidir   <entrada.json {}>                      <salida.json>   → {ok, datos}
  propuestas.py responder <entrada.json {id, si}>                 <salida.json>   → {ok, datos, error?}
  propuestas.py modo      <entrada.json {modo, confirmaciones}>   <salida.json>   → {ok, datos, error?}
  propuestas.py ajustar   <entrada.json {vencimiento, monto}>     <salida.json>   → {ok, datos, error?}

Ninguna toca la red: todo sale del estado firmado de la cuenta, de las velas cerradas que ya están en disco, del último
backtest y de la última calibración.

`estado` dice en cuál de los tres modos quedó la cuenta, cuáles se pueden usar y por qué no, qué propuestas esperan un
«Sí» y cuánto les queda, cuántas vencieron hoy y con qué exigencia se mide el puntaje. **Mirar también es aplicar**
(`bin/lib_modos.py`): la propuesta que se pasó de su hora vence acá y queda en el registro que no se borra. Lo que no
hace es proponer ni operar.

`decidir` es una vuelta de decisión ahora mismo —la que hace el motor cada 5 minutos—: con la mejor oportunidad de ahora,
el modo propone y espera (manual), opera solo si el puntaje es claramente alto y el monto cabe en el que elegiste
(semiautomático) u opera solo (automático). Si nadie responde una propuesta, vence: no hay ningún camino donde el
silencio opere.

`responder` es el «Sí» o el «No» a una propuesta. El «Sí» vuelve a calcular el tamaño y los frenos **de ahora** antes de
poner la orden: la propuesta es una foto, no una orden guardada. El «No» queda anotado como lo que es, quedarse en USDT.

`modo` cambia el modo: sin calibración el semiautomático y el automático quedan deshabilitados con el motivo a la vista,
con un freno puesto tampoco se pueden elegir y el automático pide dos confirmaciones (`confirmaciones: 2`). `ajustar`
guarda cuánto espera una propuesta (5, 15 o 60 min) y hasta cuánto opera solo el semiautomático, en USDT.
"""
import lib_modos
import nucleo


def estado(d=None, ahora_ms=None):
    """`ahora_ms` solo se pasa en las pruebas (una hora fija): la acción siempre mira con la hora de ahora."""
    return {"ok": True, "datos": lib_modos.estado(ahora_ms)}


def decidir(d=None, ahora_ms=None):
    """Una vuelta de decisión ahora mismo. Devuelve el estado de los modos con lo que decidió esta vuelta al lado."""
    r = lib_modos.decidir(ahora_ms=ahora_ms)
    return {"ok": True, "datos": {**lib_modos.estado(ahora_ms), "decision": r["modos"]}}


def responder(d, ahora_ms=None):
    """El «Sí» o el «No» de la persona. Lo que elige llega en el archivo de entrada y se revisa acá también: un id de
    propuesta y un sí o un no, nada más."""
    identificador = d.get("id")
    if identificador is not None and not isinstance(identificador, str):
        return {"ok": False, "error": "sin_propuesta", "datos": lib_modos.estado(ahora_ms)}
    si = d.get("si", 1)
    if isinstance(si, bool) or not isinstance(si, (int, float)) or si not in (0, 1):
        return {"ok": False, "error": "pausa", "datos": lib_modos.estado(ahora_ms)}
    r = lib_modos.responder(identificador or None, bool(si), ahora_ms=ahora_ms)
    return {"ok": True, "datos": {**r["datos"], "hecho": r["hecho"], "motivo_respuesta": r["motivo"],
                                  "respondida": r["propuesta"], "si": bool(si)}}


def modo(d, ahora_ms=None):
    """El modo que eligió la persona, con sus confirmaciones. Un modo que no es uno de los tres no se intenta siquiera."""
    cual = d.get("modo")
    if cual not in lib_modos.MODOS:
        return {"ok": False, "error": "modo", "datos": lib_modos.estado(ahora_ms)}
    confirmaciones = d.get("confirmaciones", 0)
    if isinstance(confirmaciones, bool) or not isinstance(confirmaciones, (int, float)):
        confirmaciones = 0
    r = lib_modos.elegir(cual, int(confirmaciones), ahora_ms=ahora_ms)
    return {"ok": True, "datos": {**r["datos"], "hecho": r["hecho"], "motivo_cambio": r["motivo"],
                                  "faltan": r.get("faltan", 0), "pedido": cual}}


def ajustar(d, ahora_ms=None):
    """Cuánto espera una propuesta y hasta cuánto opera solo el semiautomático. Lo que no venga no se cambia."""
    vencimiento = d.get("vencimiento")
    monto = d.get("monto")
    for valor in (vencimiento, monto):
        if valor is not None and (isinstance(valor, bool) or not isinstance(valor, (int, float))):
            return {"ok": False, "error": "monto", "datos": lib_modos.estado(ahora_ms)}
    r = lib_modos.ajustar(vencimiento, monto, ahora_ms=ahora_ms)
    if not r["hecho"]:
        return {"ok": False, "error": r["motivo"], "datos": r["datos"]}
    return {"ok": True, "datos": {**r["datos"], "hecho": True, "motivo_ajuste": ""}}


if __name__ == "__main__":
    nucleo.script({"estado": estado, "decidir": decidir, "responder": responder, "modo": modo, "ajustar": ajustar},
                  __doc__)
