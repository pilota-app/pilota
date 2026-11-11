#!/usr/bin/env python3
"""puntaje — el puntaje de 0 a 100 de cada oportunidad de ahora. Solo biblioteca estándar.

  puntaje.py estado <entrada.json {}> <salida.json>   → {ok, datos}
  puntaje.py medir  <entrada.json {}> <salida.json>   → {ok, datos}

Ninguna de las dos toca la red.

`estado` no recorre nada: convierte en una nota de 0 a 100 cada una de las siete familias de indicadores que ya están
calculadas sobre las velas guardadas y las junta, con su peso, en el puntaje de cada señal cruda (`bin/lib_puntaje.py`),
dejando el resultado en `<datos>/mercado/puntaje.json`. Al lado de cada puntaje van la probabilidad de ganar que dicen
las operaciones del historial que puntuaron como esta —las de su tramo de puntaje— y la ganancia esperada después de
costos (comisión de los dos lados, diferencia entre compra y venta y conversión USDT↔FDUSD), las dos con su rango de
confianza y diciendo con cuántos casos están calculadas. También va el puntaje de quedarse en USDT, que es la vara con
la que se comparan las demás, y el supuesto de las velas sin velas de 1 m, marcado con cuántas veces acertó.

`medir` es la pasada lenta que hace falta una vez: recorre el historial, puntúa cada señal cruda antes de seguirla,
resuelve cada salida con la regla de las velas sin 1 m y reparte las operaciones por tramos de puntaje, dejando la tabla
en `<datos>/mercado/tramos.json`. Es de ahí de donde `estado` saca la probabilidad sin volver a recorrer nada.

Lo que no se puede mirar no se puntúa: sin una de las tres familias clave (para dónde va el precio, cómo viene BTC y qué
se lleva el costo) hay un motivo, no un puntaje inventado; sin una de las otras cuatro, el puntaje sale con las que tienen
dato, con los pesos renormalizados y marcado. Con pocos casos no hay probabilidad: se dice cuántos hay y cuántos hacen
falta.

Con qué pesos y con qué exigencia se mira el puntaje lo dice la calibración guardada (`bin/lib_calibracion.py`):
mientras no haya ninguna, el modelo queda «sin calibrar», las siete familias pesan lo mismo y la exigencia —el corte
para entrar— es la alta.
"""
import lib_calibracion
import lib_puntaje
import nucleo


def estado(d, ahora_ms=None):
    """`ahora_ms` solo se pasa en las pruebas (una hora fija): la acción siempre puntúa con la hora de ahora."""
    calibracion = lib_calibracion.guardada()
    return {"ok": True, "datos": lib_puntaje.escribir_estado(lib_puntaje.estado(ahora_ms, calibracion=calibracion))}


def medir(d, ahora_ms=None):
    """Los tramos de puntaje, medidos sobre el historial con los pesos de la calibración y dejados escritos.
    `ahora_ms`, solo en las pruebas."""
    calibracion = lib_calibracion.guardada()
    return {"ok": True, "datos": lib_puntaje.escribir_tramos(lib_puntaje.medir(ahora_ms, calibracion=calibracion))}


if __name__ == "__main__":
    nucleo.script({"estado": estado, "medir": medir}, __doc__)
