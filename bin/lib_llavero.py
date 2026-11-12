#!/usr/bin/env python3
"""lib_llavero — la llave de Binance en el llavero del sistema, nunca en un archivo. Solo biblioteca estándar. No es una
acción.

Hoy solo en Mac: usa el comando `security` del sistema (el llavero de inicio de sesión de la persona).

Lo que no se negocia aquí:
- **La llave nunca toca el disco de Pilota** ni el registro: vive en el llavero, con el nombre de servicio `SERVICIO`.
- **El secreto nunca va como argumento de un comando** (los argumentos los ve cualquier programa del equipo): se le pasa a
  `security -i` por la entrada estándar.
- **Solo letras y números.** Las llaves de Binance (HMAC) son así; cualquier otra cosa se rechaza antes de guardarla, y por
  eso nunca hay que escapar nada.
- `correr` se reemplaza en las pruebas: así se prueba sin tocar el llavero de verdad.
"""
import re
import shutil
import subprocess
import sys

SERVICIO = "app.pilota.binance"
CUENTA_LLAVE, CUENTA_SECRETO = "api_key", "secret"
FORMATO = re.compile(r"^[A-Za-z0-9]{32,128}$")
TIEMPO = 15


class Llavero(Exception):
    """El llavero no respondió como se esperaba."""


def _correr(args, entrada=None):
    return subprocess.run(args, input=entrada, capture_output=True, text=True, timeout=TIEMPO)


correr = _correr


def disponible():
    """Si este equipo tiene un llavero que Pilota sabe usar (hoy, el de Mac)."""
    return sys.platform == "darwin" and shutil.which("security") is not None


def valida(texto):
    return isinstance(texto, str) and bool(FORMATO.match(texto))


def guardar(llave, secreto):
    """Guarda (o reemplaza) la llave y el secreto. Devuelve `True` o lanza `Llavero`."""
    if not (valida(llave) and valida(secreto)):
        raise Llavero("formato")
    if not disponible():
        raise Llavero("sin_llavero")
    ordenes = "".join(f"add-generic-password -U -s {SERVICIO} -a {cuenta} -w {valor}\n"
                      for cuenta, valor in ((CUENTA_LLAVE, llave), (CUENTA_SECRETO, secreto)))
    r = correr(["security", "-i"], ordenes)
    if r.returncode != 0:
        raise Llavero("no_guardo")
    if leer() != (llave, secreto):
        raise Llavero("no_guardo")
    return True


def _leer_uno(cuenta):
    r = correr(["security", "find-generic-password", "-s", SERVICIO, "-a", cuenta, "-w"])
    if r.returncode != 0:
        return None
    valor = (r.stdout or "").strip()
    return valor if valida(valor) else None


def leer():
    """La llave y el secreto, o `None` si no hay (o si no son de la forma esperada)."""
    if not disponible():
        return None
    llave, secreto = _leer_uno(CUENTA_LLAVE), _leer_uno(CUENTA_SECRETO)
    return (llave, secreto) if llave and secreto else None


def borrar():
    """Borra la llave y el secreto del llavero. No falla si ya no estaban."""
    if not disponible():
        return False
    for cuenta in (CUENTA_LLAVE, CUENTA_SECRETO):
        correr(["security", "delete-generic-password", "-s", SERVICIO, "-a", cuenta])
    return leer() is None


def pista(llave):
    """Cómo se muestra una llave: los primeros 4 y los últimos 4. Nunca el secreto."""
    return f"{llave[:4]}…{llave[-4:]}" if valida(llave) else ""
