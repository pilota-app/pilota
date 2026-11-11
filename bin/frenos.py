#!/usr/bin/env python3
"""frenos — los frenos que Pilota no se puede saltar y en qué estado la dejan. Solo biblioteca estándar.

  frenos.py estado      <entrada.json {}>            <salida.json>   → {ok, datos}
  frenos.py pausar      <entrada.json {pausar}>      <salida.json>   → {ok, datos}
  frenos.py desbloquear <entrada.json {}>            <salida.json>   → {ok, datos}

Ninguna toca la red: todo sale del estado firmado de cada cuenta (saldo, capital de referencia, libro de aportes, racha,
día, pausa y desbloqueos), de las comisiones que haya escritas y de las velas cerradas que ya están en disco.

`estado` **revisa los frenos y los deja aplicados** (`bin/lib_frenos.py`): tras cualquier freno el modo vuelve a manual y
cada freno nuevo queda anotado en el registro que no se borra, una sola vez. Mirar los frenos es aplicarlos: no hay un
modo «solo mirar» que deje a Pilota operando con un freno puesto. Si el archivo de estado de una cuenta no es de fiar, no
se pisa: esa cuenta ya viene frenada en manual.

`pausar` cancela las entradas y **nunca** toca una protección automática: lo que está abierto sigue protegido y la
respuesta dice con cuántas posiciones protegidas se queda. `pausar: 0` quita la pausa y no abre nada por su cuenta.

`desbloquear` es el desbloqueo del piso, a mano: en real la primera vez solo lo pide y arranca la espera de 24 h, y recién
pasada la espera lo aplica (como máximo dos veces, y el piso absoluto no se desbloquea nunca). Aplicarlo es un reinicio
documentado del capital de referencia y queda en el registro. En prueba es al tiro.

Las tres devuelven lo mismo: las dos cuentas con sus frenos y, arriba, los de la que está activa.
"""
import lib_frenos
import nucleo


def estado(d, ahora_ms=None):
    """`ahora_ms` solo se pasa en las pruebas (una hora fija): la acción siempre revisa con la hora de ahora."""
    return {"ok": True, "datos": lib_frenos.escribir(lib_frenos.revisar(ahora_ms))}


def pausar(d, ahora_ms=None):
    """«Pausar» o «Seguir». Lo que elige la persona llega en el archivo de entrada y se revisa acá también: es un sí o un
    no, nada más."""
    pausa = d.get("pausar", 1)
    if isinstance(pausa, bool) or not isinstance(pausa, (int, float)) or pausa not in (0, 1):
        return {"ok": False, "error": "pausa", "datos": lib_frenos.estado(ahora_ms)}
    lib_frenos.pausar(bool(pausa), ahora_ms=ahora_ms)
    return {"ok": True, "datos": lib_frenos.escribir(lib_frenos.revisar(ahora_ms))}


def desbloquear(d, ahora_ms=None):
    """El desbloqueo del piso. Si no hay nada que desbloquear, si ya no quedan desbloqueos o si la espera no terminó, no
    pasa nada y el motivo viaja en código para que la pantalla lo diga."""
    r = lib_frenos.desbloquear(ahora_ms=ahora_ms)
    return {"ok": True, "datos": lib_frenos.escribir({**lib_frenos.revisar(ahora_ms), "hecho": r["hecho"],
                                                      "motivo_desbloqueo": r["motivo"]})}


if __name__ == "__main__":
    nucleo.script({"estado": estado, "pausar": pausar, "desbloquear": desbloquear}, __doc__)
