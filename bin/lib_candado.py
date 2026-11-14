#!/usr/bin/env python3
"""lib_candado — una sola cosa a la vez, entre procesos. Solo biblioteca estándar. No es una acción.

Dos usos:
- **Un solo trabajo de cada tipo** (`unico`): el motor, el muestreo y el robot en vivo toman su candado al partir y lo
  sueltan al terminar. Si ya hay uno corriendo, el segundo no parte (`YaCorriendo`). Dos motores a la vez revisan el mismo
  estado al mismo tiempo, y eso no puede pasar.
- **Una revisión a la vez** (`candado`): reconciliar lee y escribe el estado firmado; dos revisiones juntas se pisarían.

El candado lo suelta el sistema si el proceso muere: no queda nada trabado después de un corte de luz.
"""
import contextlib
import os
import time

import nucleo

try:
    import fcntl
except ImportError:          # Windows
    fcntl = None
    import msvcrt


class Ocupado(Exception):
    """Otro proceso tiene el candado y no lo soltó a tiempo."""


class YaCorriendo(Exception):
    """Ya hay un trabajo de este tipo corriendo."""


def ruta(nombre):
    carpeta = nucleo.carpeta_privada(os.path.join(nucleo.carpeta_datos(), "candados"))
    return os.path.join(carpeta, f"{nombre}.candado")


def _tomar(fd):
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    else:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)


def _soltar(fd):
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
    else:
        os.lseek(fd, 0, 0)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


_tomados = {}       # nombre → cuántas veces lo tomó este proceso (reentrante dentro del mismo proceso)


@contextlib.contextmanager
def candado(nombre, espera=30.0):
    """Toma el candado `nombre`, esperando hasta `espera` segundos. Es reentrante dentro del mismo proceso."""
    if _tomados.get(nombre):
        _tomados[nombre] += 1
        try:
            yield
        finally:
            _tomados[nombre] -= 1
        return
    fd = os.open(ruta(nombre), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        limite = time.monotonic() + max(0.0, espera)
        while True:
            try:
                _tomar(fd)
                break
            except OSError:
                if time.monotonic() >= limite:
                    raise Ocupado(nombre) from None
                time.sleep(0.1)
        _tomados[nombre] = 1
        try:
            yield
        finally:
            _tomados[nombre] = 0
            _soltar(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def unico(tipo):
    """El candado de un trabajo largo: si otro proceso ya lo tiene, `YaCorriendo` al tiro, sin esperar."""
    try:
        with candado(f"trabajo-{tipo}", espera=0):
            yield
    except Ocupado:
        raise YaCorriendo(tipo) from None


def huerfano():
    """Si el proceso que nos lanzó (la app) ya no está. En Mac y Linux el padre pasa a ser el 1: la app se cerró de golpe y
    nadie nos va a pedir parar, así que un trabajo largo tiene que terminar solo."""
    return hasattr(os, "getppid") and os.name != "nt" and os.getppid() == 1
