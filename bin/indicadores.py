#!/usr/bin/env python3
"""indicadores — el valor de ahora de los indicadores de las siete familias. Solo biblioteca estándar.

  indicadores.py estado <entrada.json {}> <salida.json>   → {ok, datos}

No toca la red: calcula sobre las velas que ya están guardadas (`bin/lib_indicadores.py` y
`bin/lib_indicadores_mercado.py`) y deja el resultado en `<datos>/mercado/indicadores.json`. Cada serie trae las medias de 20,
50 y 200 velas, el ADX con sus dos direcciones, el RSI, el MACD con su señal y su histograma, las bandas de Bollinger con el
ATR, el volumen relativo con el OBV y el techo y el piso de las últimas velas; aparte van el contexto de BTC y el costo del
momento (comisión, diferencia entre compra y venta y conversión USDT↔FDUSD). Lo que no se puede calcular no se calcula: una
serie corta, atrasada o con hoyos, un contexto sin historial o una muestra del libro vieja quedan con su motivo.
"""
import lib_indicadores
import lib_indicadores_mercado
import nucleo


def estado(d, ahora_ms=None):
    """`ahora_ms` solo se pasa en las pruebas (una hora fija): la acción siempre calcula con la hora de ahora."""
    return {"ok": True, "datos": lib_indicadores.escribir_estado(lib_indicadores_mercado.estado(ahora_ms))}


if __name__ == "__main__":
    nucleo.script({"estado": estado}, __doc__)
