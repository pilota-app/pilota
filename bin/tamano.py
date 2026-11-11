#!/usr/bin/env python3
"""tamano — cuánto se compraría ahora en cada oportunidad, en USDT. Solo biblioteca estándar.

  tamano.py estado <entrada.json {}> <salida.json>   → {ok, datos}

No toca la red: la cuenta sale del puntaje de ahora (los niveles de entrada y de stop de cada señal), del estado
firmado de la cuenta activa (el capital y las posiciones abiertas) y de los filtros que dejó el último cálculo del
capital mínimo viable. Lo deja escrito en `<datos>/mercado/tamano.json`.

El orden es fijo (`bin/lib_tamano.py`): los mínimos de Binance, la reserva del 40 % en USDT, las dos posiciones y el
riesgo máximo del 2 % del capital. El monto es el menor entre el riesgo dividido por la distancia al stop y lo
disponible para esa posición, y nunca más que el tope mientras el modelo esté «Aún sin validar».

Lo que no alcanza no se estira: si el monto queda bajo el mínimo de Binance no hay orden y el motivo viaja en código
(`bajo_minimo`, con cuánto haría falta por posición y de capital) para que la pantalla lo diga. Sin los filtros de
Binance, con la cuenta arrancada frenada o sin capital tampoco hay tamaño, y cada caso dice cuál es.
"""
import lib_tamano
import nucleo


def estado(d, ahora_ms=None):
    """`ahora_ms` solo se pasa en las pruebas (una hora fija): la acción siempre mide con la hora de ahora."""
    return {"ok": True, "datos": lib_tamano.escribir(lib_tamano.estado(ahora_ms))}


if __name__ == "__main__":
    nucleo.script({"estado": estado}, __doc__)
