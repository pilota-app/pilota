#!/usr/bin/env python3
"""senales — las señales crudas de las tres estrategias, con el filtro de BTC. Solo biblioteca estándar.

  senales.py estado <entrada.json {}> <salida.json>   → {ok, datos}

No toca la red: calcula los indicadores sobre las velas que ya están guardadas y les aplica las tres estrategias
(`bin/lib_estrategias.py`), dejando el resultado en `<datos>/mercado/senales.json`. Cada señal dice par, temporalidad, nivel
de entrada, stop y objetivo, y nada más: el puntaje, la exigencia y el tamaño de la orden son de sus propios pasos. Si BTC
cae, ninguna señal queda permitida y se dice por qué; lo que no se puede mirar (una serie corta o con hoyos, el contexto de
BTC, la tendencia diaria de un par) queda con su motivo en vez de un número inventado.
"""
import lib_estrategias
import nucleo


def estado(d, ahora_ms=None):
    """`ahora_ms` solo se pasa en las pruebas (una hora fija): la acción siempre calcula con la hora de ahora."""
    return {"ok": True, "datos": lib_estrategias.escribir_estado(lib_estrategias.estado(ahora_ms))}


if __name__ == "__main__":
    nucleo.script({"estado": estado}, __doc__)
