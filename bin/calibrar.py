#!/usr/bin/env python3
"""calibrar — la calibración del puntaje: el año apartado, los pesos por ventanas y la prueba final. Solo biblioteca
estándar.

  calibrar.py estado <entrada.json {}> <salida.json>   → {ok, datos}
  calibrar.py correr <entrada.json {}> <salida.json>   → {ok, datos}

Ninguna de las dos toca la red.

`estado` no calibra nada: devuelve la última calibración guardada o, si no hay ninguna, el modelo sin calibrar con la
exigencia alta y los montos topados (`<datos>/mercado/calibracion.json`).

`correr` es la pasada lenta: aparta el último año antes de mirar un solo peso, recorre el historial una vez puntuando
cada señal cruda, ajusta los pesos de las siete familias por ventanas (12 meses para ajustar y los 3 siguientes para
probar, como máximo 3 vueltas y diciendo cuántas se dieron), vuelve a correr el backtest con el puntaje y la exigencia
puestos y hace la prueba final **una sola vez** con el año apartado, contra un criterio escrito antes de correrla
(`bin/lib_calibracion.py`). Deja escrito el estado del modelo —«Validado», o «No validado» con la exigencia 85 y los
montos topados— y el reporte contra quedarse en USDT y contra comprar BTC y esperar.

Antes de calibrar va la compuerta de casos: sin el backtest de señales crudas corrido no se calibra nada y se dice
(`sin_backtest`). Si el historial no alcanza para el año apartado y las ventanas, tampoco (`falta_historia`), y si en
las ventanas no hay casos que no se pisen, se dice cuántos faltan (`pocos_casos`). Haber tenido que usar el plan B de
la compuerta deja el modelo en «No validado», pase lo que pase en la prueba final.
"""
import lib_calibracion
import nucleo


def estado(d):
    """La última calibración guardada. No calibra ni recorre nada."""
    return {"ok": True, "datos": lib_calibracion.guardada()}


def correr(d, ahora_ms=None):
    """La calibración completa, dejada escrita. `ahora_ms` solo se pasa en las pruebas (una hora fija): la acción
    siempre calibra con la hora de ahora."""
    return {"ok": True, "datos": lib_calibracion.escribir(lib_calibracion.calibrar(ahora_ms))}


if __name__ == "__main__":
    nucleo.script({"estado": estado, "correr": correr}, __doc__)
