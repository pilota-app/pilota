#!/usr/bin/env python3
"""estado — el estado firmado de la app y el registro que no se borra. Solo biblioteca estándar.

  estado.py arrancar  <entrada.json {}>        <salida.json>   → {ok, datos}
  estado.py reiniciar <entrada.json {saldo}>   <salida.json>   → {ok, datos}

Ninguna de las dos toca la red.

`arrancar` es lo primero que corre al abrir la app: lee el estado de las dos cuentas —prueba y real llevan saldos,
frenos y registro separados— y revisa su huella. Si a una le falta el archivo, la huella no cuadra o la fecha es futura,
esa cuenta **arranca frenada en modo manual**, el motivo viaja en código para que la pantalla lo diga y queda una línea
en el registro (`bin/lib_estado.py`, `bin/lib_registro.py`). El archivo sospechoso no se pisa: la evidencia se guarda.

`reiniciar` deja el saldo de prueba en el monto que se eligió: una sola confirmación, al tiro, y anotado en el registro.
El saldo real no se reinicia nunca —lo dice Binance al reconciliar, en su paso—, así que esto es solo del modo prueba.

Las dos devuelven lo mismo: las dos cuentas con su arranque, sus montos y las últimas líneas de su registro con los
campos fijos (fecha, par, puntaje, razón, orden y resultado).
"""
import lib_estado
import nucleo


def arrancar(d, ahora_ms=None):
    """El estado de las dos cuentas al abrir la app. `ahora_ms` solo se pasa en las pruebas (una hora fija)."""
    return {"ok": True, "datos": lib_estado.arrancar(ahora_ms)}


def reiniciar(d, ahora_ms=None):
    """El saldo de prueba de nuevo en el monto elegido. Lo que escribe la persona llega en el archivo de entrada y se
    revisa acá también: el saldo es un monto en USDT, no más que el capital que Pilota se cree."""
    saldo = d.get("saldo", lib_estado.SALDO_SUGERIDO)
    if isinstance(saldo, bool) or not isinstance(saldo, (int, float)) or not 0 <= saldo <= lib_estado.SALDO_MAXIMO:
        return {"ok": False, "error": "monto", "datos": lib_estado.estado(ahora_ms)}
    return {"ok": True, "datos": lib_estado.reiniciar(float(saldo), ahora_ms)}


if __name__ == "__main__":
    nucleo.script({"arrancar": arrancar, "reiniciar": reiniciar}, __doc__)
