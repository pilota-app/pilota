#!/usr/bin/env python3
"""lib_flujo — los precios de Binance en vivo, empujados por Binance (WebSocket). Solo biblioteca estándar. No es una acción.

La API REST hay que preguntarla; el flujo llega solo. Binance manda la vela en curso de cada par **cada segundo** (`kline_1s`)
y la de 1 minuto (`kline_1m`) con la marca de cuándo cerró. Con eso el robot ve el precio al segundo y decide en el instante
en que cierra una vela, no cinco minutos después.

Lo que no se negocia aquí (igual que en `lib_datos`):
- **Un solo destino**: `stream.binance.com`, puerto 9443, por TLS con el certificado revisado, y solo la ruta de los flujos
  públicos de velas (`ruta_de`). Sin proxies del entorno y sin redirecciones: el saludo tiene que contestar 101 con la llave
  de WebSocket que corresponde, o se corta.
- **Nada de afuera se cree tal cual.** Cada mensaje pasa por `vela_de`: el par tiene que ser uno de los que se operan, la
  temporalidad la pedida y cada número finito y positivo. Lo demás se descarta.
- **Topes**: un mensaje de más de `MAXIMO_MENSAJE` bytes corta la conexión. Si en `SILENCIO_MAXIMO` segundos no llega nada,
  la conexión se da por muerta y se vuelve a abrir.
- **Solo lectura.** Es el flujo público: no lleva llave, no puede operar nada.
"""
import base64
import hashlib
import json
import math
import os
import socket
import ssl
import struct
import time

import lib_datos

HOST = "stream.binance.com"
PUERTO = 9443
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
INTERVALOS = ("1s", "1m")
MAXIMO_MENSAJE = 64 * 1024
SILENCIO_MAXIMO = 30
#: Cada cuánto se revisa «Detener» mientras se espera un mensaje.
TROZO = 1.0


#: Los pares que escucha el flujo: los dos de siempre (contra FDUSD, los del dinero real) y las ocho monedas contra USDT.
PARES = lib_datos.PARES_OPERADOS + tuple(p for p in lib_datos.ACTIVOS if p not in lib_datos.PARES_OPERADOS)


class Caido(Exception):
    """La conexión se cortó o no se pudo abrir. Se vuelve a intentar."""


class _Parar(Exception):
    """Pidieron «Detener» mientras se esperaba un mensaje."""


def ruta_de(pares, intervalos=INTERVALOS):
    """La ruta del flujo combinado de velas de esos pares. Solo pares que se operan y solo los intervalos conocidos."""
    nombres = []
    for par in pares:
        if par not in PARES:
            raise ValueError(f"Par no permitido en el flujo: {par!r}")
        for i in intervalos:
            if i not in INTERVALOS:
                raise ValueError(f"Intervalo no permitido en el flujo: {i!r}")
            nombres.append(f"{par.lower()}@kline_{i}")
    return "/stream?streams=" + "/".join(nombres)


def _numero(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


def vela_de(mensaje):
    """Una vela del flujo como la usa Pilota, o `None` si el mensaje no es lo que esperamos.
    → {"par", "intervalo", "t" (apertura en ms), "o", "h", "l", "c", "v", "cerrada", "evento_ms"}"""
    if not isinstance(mensaje, dict):
        return None
    d = mensaje.get("data", mensaje)
    k = d.get("k") if isinstance(d, dict) else None
    if not isinstance(k, dict) or d.get("e") != "kline":
        return None
    par, intervalo = k.get("s"), k.get("i")
    if par not in PARES or intervalo not in INTERVALOS:
        return None
    t, evento = k.get("t"), d.get("E")
    if isinstance(t, bool) or not isinstance(t, int) or t <= 0:
        return None
    numeros = [_numero(k.get(c)) for c in ("o", "h", "l", "c", "v")]
    if any(n is None for n in numeros) or min(numeros[:4]) <= 0:
        return None
    o, h, l, c, v = numeros
    if not (l <= min(o, c) and h >= max(o, c)):
        return None
    return {"par": par, "intervalo": intervalo, "t": t, "o": o, "h": h, "l": l, "c": c, "v": v,
            "cerrada": k.get("x") is True, "evento_ms": evento if isinstance(evento, int) else None}


# ── El WebSocket, lo mínimo (RFC 6455) ───────────────────────────────────────────────────────────────────────────────

def _marco(opcode, datos=b""):
    """Un marco del cliente: siempre enmascarado, como pide el protocolo."""
    mascara = os.urandom(4)
    largo = len(datos)
    cabeza = bytes([0x80 | opcode])
    if largo < 126:
        cabeza += bytes([0x80 | largo])
    elif largo < 65536:
        cabeza += bytes([0x80 | 126]) + struct.pack("!H", largo)
    else:
        cabeza += bytes([0x80 | 127]) + struct.pack("!Q", largo)
    return cabeza + mascara + bytes(b ^ mascara[i % 4] for i, b in enumerate(datos))


class Flujo:
    """Una conexión al flujo de velas. `abrir` se reemplaza en las pruebas por un socket falso: ninguna sale a la red."""

    def __init__(self, pares=PARES, abrir=None, reloj=time.monotonic):
        self.ruta = ruta_de(pares)
        self._abrir = abrir or self._abrir_red
        self._reloj = reloj
        self.s = None
        self._resto = b""

    def _abrir_red(self):
        crudo = socket.create_connection((HOST, PUERTO), timeout=10)
        contexto = ssl.create_default_context()
        return contexto.wrap_socket(crudo, server_hostname=HOST)

    def conectar(self):
        try:
            self.s = self._abrir()
            llave = base64.b64encode(os.urandom(16)).decode()
            pedido = (f"GET {self.ruta} HTTP/1.1\r\nHost: {HOST}:{PUERTO}\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: {llave}\r\nSec-WebSocket-Version: 13\r\n"
                      "User-Agent: Pilota\r\n\r\n")
            self.s.sendall(pedido.encode())
            cabeza = b""
            while b"\r\n\r\n" not in cabeza:
                trozo = self.s.recv(4096)
                if not trozo:
                    raise Caido("cerrado_en_saludo")
                cabeza += trozo
                if len(cabeza) > 16384:
                    raise Caido("saludo_largo")
            cabeza, self._resto = cabeza.split(b"\r\n\r\n", 1)
            lineas = cabeza.decode("latin-1").split("\r\n")
            if not lineas or " 101 " not in lineas[0] + " ":
                raise Caido("sin_101")
            campos = {ln.split(":", 1)[0].strip().lower(): ln.split(":", 1)[1].strip() for ln in lineas[1:] if ":" in ln}
            esperada = base64.b64encode(hashlib.sha1((llave + GUID).encode()).digest()).decode()
            if campos.get("sec-websocket-accept") != esperada:
                raise Caido("llave_no_cuadra")
            self.s.settimeout(TROZO)
        except (OSError, ssl.SSLError) as e:
            self.cerrar()
            raise Caido(e.__class__.__name__) from None

    def cerrar(self):
        if self.s is not None:
            try:
                self.s.close()
            except OSError:
                pass
        self.s, self._resto = None, b""

    def _leer(self, n, detenido):
        """Lee exactamente `n` bytes. Revisa «Detener» y el silencio cada `TROZO` segundos."""
        while len(self._resto) < n:
            if detenido is not None and detenido():
                raise _Parar
            try:
                trozo = self.s.recv(65536)
            except socket.timeout:
                if self._reloj() - self._ultimo > SILENCIO_MAXIMO:
                    raise Caido("silencio") from None
                continue
            except (OSError, ssl.SSLError) as e:
                raise Caido(e.__class__.__name__) from None
            if not trozo:
                raise Caido("cerrado")
            self._resto += trozo
            self._ultimo = self._reloj()
        datos, self._resto = self._resto[:n], self._resto[n:]
        return datos

    def mensajes(self, detenido=None):
        """Los mensajes de texto del flujo, ya como JSON, hasta que la conexión caiga (`Caido`) o pidan parar."""
        if self.s is None:
            self.conectar()
        self._ultimo = self._reloj()
        partes = b""
        try:
            while True:
                b1, b2 = self._leer(2, detenido)
                opcode, fin = b1 & 0x0F, bool(b1 & 0x80)
                largo = b2 & 0x7F
                if b2 & 0x80:
                    raise Caido("servidor_enmascarado")
                if largo == 126:
                    largo = struct.unpack("!H", self._leer(2, detenido))[0]
                elif largo == 127:
                    largo = struct.unpack("!Q", self._leer(8, detenido))[0]
                if largo + len(partes) > MAXIMO_MENSAJE:
                    raise Caido("mensaje_grande")
                datos = self._leer(largo, detenido) if largo else b""
                if opcode == 0x9:                       # ping: Binance lo manda cada rato y pide el pong
                    self.s.sendall(_marco(0xA, datos))
                    continue
                if opcode == 0xA:
                    continue
                if opcode == 0x8:
                    raise Caido("cerrado_por_binance")
                if opcode in (0x1, 0x0):
                    partes += datos
                    if not fin:
                        continue
                    texto, partes = partes, b""
                    try:
                        yield json.loads(texto.decode("utf-8"))
                    except (UnicodeDecodeError, ValueError):
                        continue
                    continue
                raise Caido("marco_desconocido")
        except _Parar:
            return
        finally:
            if detenido is not None and detenido():
                self.cerrar()

    def velas(self, detenido=None):
        """Solo las velas que pasan `vela_de`."""
        for m in self.mensajes(detenido):
            v = vela_de(m)
            if v is not None:
                yield v
