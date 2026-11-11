#!/usr/bin/env python3
"""operar_prueba — el ejecutor del modo prueba, con dinero ficticio. Solo biblioteca estándar.

  operar_prueba.py estado <entrada.json {}> <salida.json>   → {ok, datos}

No toca la red: todo sale del estado firmado de la cuenta de prueba (saldo, posiciones y sus órdenes), de las velas de 1 m
que ya están en disco y de los mínimos de Binance del último cálculo del capital mínimo viable.

`estado` **recorre las velas de 1 m que faltaban y deja aplicado lo que pasó** (`bin/lib_ejecutor_prueba.py`): las entradas
que se llenaron con su protección simulada, las que vencieron canceladas, los stops y objetivos que se cruzaron cobrados en
el saldo ficticio y el stop móvil donde quedó, cada cosa con su línea en el registro que no se borra. Mirar es aplicar,
igual que en los frenos: no hay un «solo mirar» que deje una posición cruzada abierta. Si el archivo de estado de la cuenta
no es de fiar, no se pisa y no se toca nada.

La respuesta trae el saldo ficticio, las posiciones con su protección y lo que valen ahora, las órdenes puestas con su id,
hasta cuándo llegan las velas de 1 m que las cuidan (en prueba la protección existe solo con el motor encendido) y, si
falta algo para operar, el motivo en código.

Entrar y cerrar los piden el motor y los tres modos, en sus pasos (`lib_ejecutor_prueba.entrar` y `.cerrar`): una orden que
no pasó antes por el tamaño y por los frenos no se pone nunca. El saldo de prueba se reinicia en `estado.py reiniciar`: una
sola confirmación, al tiro y queda en el registro.
"""
import lib_ejecutor_prueba
import nucleo


def estado(d, ahora_ms=None):
    """`ahora_ms` solo se pasa en las pruebas (una hora fija): la acción siempre revisa con la hora de ahora."""
    return {"ok": True, "datos": lib_ejecutor_prueba.escribir(lib_ejecutor_prueba.revisar(ahora_ms))}


if __name__ == "__main__":
    nucleo.script({"estado": estado}, __doc__)
