"""Pruebas del flujo en vivo (`lib_flujo`), del candado (`lib_candado`) y del trabajo del robot en vivo (`bin/vivo.py`).

Ninguna sale a la red: el WebSocket de Binance se reemplaza por un socket falso que contesta el saludo y manda marcos.
"""
import base64
import hashlib
import json
import os
import socket
import struct
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "bin"))

import lib_candado  # noqa: E402
import lib_datos  # noqa: E402
import lib_flujo  # noqa: E402
import vivo  # noqa: E402

AHORA = 1_770_732_300_000
MIN = 60_000


def kline(par="BTCFDUSD", intervalo="1m", t=AHORA, o=100.0, h=101.0, l=99.0, c=100.5, v=3.0, x=False):
    return {"stream": f"{par.lower()}@kline_{intervalo}", "data": {"e": "kline", "E": t + 1000, "s": par, "k": {
        "t": t, "T": t + 59_999, "s": par, "i": intervalo, "o": str(o), "h": str(h), "l": str(l), "c": str(c),
        "v": str(v), "x": x}}}


def marco_servidor(opcode, datos):
    largo = len(datos)
    cabeza = bytes([0x80 | opcode])
    if largo < 126:
        cabeza += bytes([largo])
    elif largo < 65536:
        cabeza += bytes([126]) + struct.pack("!H", largo)
    else:
        cabeza += bytes([127]) + struct.pack("!Q", largo)
    return cabeza + datos


class SocketFalso:
    """Contesta el saludo de WebSocket con la llave que corresponde y después entrega `marcos`, de a pedazos."""

    def __init__(self, marcos, llave_mala=False, codigo=101):
        self.marcos, self.llave_mala, self.codigo = list(marcos), llave_mala, codigo
        self.enviado, self.salida, self.cerrado = b"", b"", False

    def sendall(self, datos):
        self.enviado += datos
        if b"Sec-WebSocket-Key:" in datos and not self.salida:
            llave = datos.split(b"Sec-WebSocket-Key: ")[1].split(b"\r\n")[0].decode()
            acepta = base64.b64encode(hashlib.sha1((llave + lib_flujo.GUID).encode()).digest()).decode()
            if self.llave_mala:
                acepta = "x" + acepta
            self.salida = (f"HTTP/1.1 {self.codigo} Switching Protocols\r\nUpgrade: websocket\r\n"
                           f"Sec-WebSocket-Accept: {acepta}\r\n\r\n").encode() + b"".join(self.marcos)

    def recv(self, n):
        if not self.salida:
            raise socket.timeout()
        trozo, self.salida = self.salida[:7], self.salida[7:]     # de a poquito: el lector tiene que juntar
        return trozo

    def settimeout(self, _):
        pass

    def close(self):
        self.cerrado = True


def texto(m):
    return marco_servidor(0x1, json.dumps(m).encode())


class VelaDe(unittest.TestCase):
    def test_una_vela_buena(self):
        v = lib_flujo.vela_de(kline(x=True))
        self.assertEqual((v["par"], v["intervalo"], v["t"], v["c"], v["cerrada"]), ("BTCFDUSD", "1m", AHORA, 100.5, True))

    def test_lo_que_no_es_nuestro_se_descarta(self):
        self.assertIsNone(lib_flujo.vela_de(kline(par="PEPEUSDT")))
        self.assertIsNotNone(lib_flujo.vela_de(kline(par="DOGEUSDT")), "las ocho monedas sí se escuchan")
        self.assertIsNone(lib_flujo.vela_de(kline(intervalo="1h")))
        self.assertIsNone(lib_flujo.vela_de(kline(c="nan")))
        self.assertIsNone(lib_flujo.vela_de(kline(o=-1)))
        self.assertIsNone(lib_flujo.vela_de(kline(h=99.5)), "un alto bajo el cierre no es una vela")
        self.assertIsNone(lib_flujo.vela_de({"e": "trade"}))
        self.assertIsNone(lib_flujo.vela_de("hola"))

    def test_la_ruta_solo_lleva_pares_y_velas_conocidos(self):
        self.assertEqual(lib_flujo.ruta_de(["BTCFDUSD"], ["1m"]), "/stream?streams=btcfdusd@kline_1m")
        self.assertEqual(lib_flujo.ruta_de(lib_flujo.PARES).count("@kline_"), 20, "diez pares, de 1 s y de 1 m")
        with self.assertRaises(ValueError):
            lib_flujo.ruta_de(["BTCFDUSD/../x"])
        with self.assertRaises(ValueError):
            lib_flujo.ruta_de(["BTCFDUSD"], ["1d"])


class Flujo(unittest.TestCase):
    def flujo(self, s):
        # Un reloj que avanza 20 s en cada mirada: cuando se acaban los marcos, el silencio corta.
        reloj = iter(range(0, 10**6, 20))
        return lib_flujo.Flujo(abrir=lambda: s, reloj=lambda: next(reloj))

    def test_lee_marcos_partidos_y_contesta_el_ping(self):
        grande = kline(v=1.0)
        grande["relleno"] = "x" * 300                              # pasa de 125 bytes: largo de 2 bytes
        s = SocketFalso([texto(kline()), marco_servidor(0x9, b"hola"), texto(grande)])
        f = self.flujo(s)
        velas = []
        with self.assertRaises(lib_flujo.Caido):
            for v in f.velas():
                velas.append(v)
        self.assertEqual(len(velas), 2)
        self.assertIn(b"GET /stream?streams=btcfdusd@kline_1s", s.enviado)
        pong = s.enviado.split(b"\r\n\r\n", 1)[1]
        self.assertEqual(pong[0], 0x8A, "un pong de vuelta")
        self.assertTrue(pong[1] & 0x80, "el cliente siempre enmascara")

    def test_sin_la_llave_que_corresponde_no_conecta(self):
        with self.assertRaises(lib_flujo.Caido):
            self.flujo(SocketFalso([], llave_mala=True)).conectar()
        with self.assertRaises(lib_flujo.Caido):
            self.flujo(SocketFalso([], codigo=403)).conectar()

    def test_un_mensaje_gigante_corta(self):
        s = SocketFalso([marco_servidor(0x1, b"x" * (lib_flujo.MAXIMO_MENSAJE + 1))])
        with self.assertRaises(lib_flujo.Caido):
            list(self.flujo(s).velas())

    def test_el_silencio_corta(self):
        reloj = iter(range(0, 1000, 20))
        f = lib_flujo.Flujo(abrir=lambda: SocketFalso([]), reloj=lambda: next(reloj))
        with self.assertRaises(lib_flujo.Caido):
            list(f.velas())

    def test_detener_corta_sin_error(self):
        f = self.flujo(SocketFalso([]))
        self.assertEqual(list(f.velas(detenido=lambda: True)), [])


class Candado(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.antes = os.environ.get("PILOTA_DATOS")
        os.environ["PILOTA_DATOS"] = self.tmp.name

    def tearDown(self):
        if self.antes is None:
            os.environ.pop("PILOTA_DATOS", None)
        else:
            os.environ["PILOTA_DATOS"] = self.antes
        self.tmp.cleanup()

    def test_es_reentrante_en_el_mismo_proceso(self):
        with lib_candado.candado("x"):
            with lib_candado.candado("x"):
                pass

    def test_otro_proceso_no_entra(self):
        import subprocess
        codigo = ("import sys; sys.path.insert(0, %r); import lib_candado\n"
                  "try:\n    with lib_candado.unico('motor'): print('entro')\n"
                  "except lib_candado.YaCorriendo: print('ocupado')") % os.path.join(RAIZ, "bin")
        with lib_candado.unico("motor"):
            r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True,
                               env={**os.environ}, timeout=30)
        self.assertEqual(r.stdout.strip(), "ocupado")
        r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, env={**os.environ}, timeout=30)
        self.assertEqual(r.stdout.strip(), "entro", "al soltarlo, el siguiente entra")


class ConVela(unittest.TestCase):
    def test_los_segundos_mueven_la_vela_del_minuto(self):
        f = {}
        f["BTCFDUSD"] = vivo.con_vela(f, lib_flujo.vela_de(kline(o=100, h=101, l=99, c=100.5, v=3)))
        f["BTCFDUSD"] = vivo.con_vela(f, lib_flujo.vela_de(kline(intervalo="1s", t=AHORA + 30_000, o=100.5, h=102,
                                                                   l=100.4, c=101.8)))
        self.assertEqual(f["BTCFDUSD"], [AHORA, 100.0, 102.0, 99.0, 101.8, 3.0])
        # El primer segundo del minuto siguiente abre una vela nueva.
        f["BTCFDUSD"] = vivo.con_vela(f, lib_flujo.vela_de(kline(intervalo="1s", t=AHORA + MIN, o=101.8, h=101.9,
                                                                   l=101.7, c=101.9)))
        self.assertEqual(f["BTCFDUSD"][0], AHORA + MIN)


class FlujoFalso:
    """Entrega una lista de velas y después se cae."""

    def __init__(self, velas):
        self.lista, self.conectado = velas, 0

    def conectar(self):
        self.conectado += 1

    def cerrar(self):
        pass

    def velas(self, detenido=None):
        yield from self.lista
        raise lib_flujo.Caido("fin")


class Encender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.antes = os.environ.get("PILOTA_DATOS")
        os.environ["PILOTA_DATOS"] = self.tmp.name

    def tearDown(self):
        if self.antes is None:
            os.environ.pop("PILOTA_DATOS", None)
        else:
            os.environ["PILOTA_DATOS"] = self.antes
        self.tmp.cleanup()

    def test_al_cerrar_el_minuto_guarda_y_revisa_al_tiro(self):
        base = AHORA - 3 * MIN
        for par in lib_datos.PARES_OPERADOS:
            lib_datos.guardar_serie(par, "1m", [[base, 1, 1, 1, 1, 1], [base + MIN, 1, 1, 1, 1, 1]])
        velas = [lib_flujo.vela_de(kline(par=par, t=base + 2 * MIN, x=True)) for par in lib_datos.PARES_OPERADOS]
        revisiones = []
        with mock.patch.object(vivo, "revisar", side_effect=lambda c, ms, d: revisiones.append(ms) or
                               {"eventos": [], "piloto": {"decision": "sin_senal"}}), \
                mock.patch.object(vivo, "_ms", return_value=AHORA):
            r = vivo.encender({}, flujo=FlujoFalso(velas), cliente=object(), ciclos=1, latir=False, dormir=lambda s: None)
        self.assertTrue(r["ok"])
        self.assertEqual(revisiones, [AHORA, base + 3 * MIN], "una al conectar y otra en el instante en que cerró")
        for par in lib_datos.PARES_OPERADOS:
            self.assertEqual(lib_datos.leer_serie(par, "1m")[-1][0], base + 2 * MIN, "la vela cerrada quedó guardada")

    def test_dos_a_la_vez_no(self):
        with lib_candado.unico(vivo.TIPO):
            import subprocess
            codigo = ("import sys, json; sys.path.insert(0, %r); import vivo\n"
                      "print(json.dumps(vivo.encender({}, latir=False)['error']))") % os.path.join(RAIZ, "bin")
            r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, env={**os.environ},
                               timeout=60)
        self.assertEqual(r.stdout.strip(), '"ya_corriendo"', r.stderr[-500:])


class Grafico(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.antes = os.environ.get("PILOTA_DATOS")
        os.environ["PILOTA_DATOS"] = self.tmp.name

    def tearDown(self):
        if self.antes is None:
            os.environ.pop("PILOTA_DATOS", None)
        else:
            os.environ["PILOTA_DATOS"] = self.antes
        self.tmp.cleanup()

    def test_velas_y_marcas(self):
        base = AHORA // (5 * MIN) * (5 * MIN)
        lib_datos.guardar_serie("BTCFDUSD", "1m", [[base + i * MIN, 1, 2, 0.5, 1.5, 1] for i in range(12)])
        r = vivo.grafico({"par": "BTCFDUSD", "temporalidad": "5m"})["datos"]
        self.assertEqual(len(r["velas"]), 2, "solo las de 5 m completas")
        self.assertEqual(vivo.grafico({"par": "../etc", "temporalidad": "9z"})["datos"]["par"], "BTCFDUSD",
                         "lo que no conocemos vuelve al par y la vela de siempre")
        lineas = [{"ms": base, "par": "BTCFDUSD", "razon": "entrada_rebote", "orden": {"precio": 1.0, "estado": "puesta"}},
                  {"ms": base + MIN, "par": "BTCFDUSD", "razon": "entrada_rebote", "orden": {"precio": 1.0, "estado": "llenada"}},
                  {"ms": base + 2 * MIN, "par": "BTCFDUSD", "razon": "objetivo", "resultado": {"precio": 1.2, "neto": 0.3}},
                  {"ms": base + 3 * MIN, "par": "ETHFDUSD", "razon": "stop", "resultado": {"precio": 9, "neto": -1}}]
        m = vivo.marcas_de("BTCFDUSD", base, lineas)
        self.assertEqual([(x["tipo"], x["precio"]) for x in m], [("compra", 1.0), ("venta", 1.2)])


class OchoMonedas(Grafico):
    """Las ocho contra USDT: las velas largas se piden justo al cerrar y las de 1 m no pasan de 30 días."""

    def test_las_largas_se_piden_solo_cuando_cierran(self):
        hora = AHORA // (3600_000) * 3600_000
        with mock.patch.object(lib_datos, "bajar_serie", return_value=0) as bajar:
            self.assertEqual(vivo.largas_al_dia(None, hora + MIN, ("SOLUSDT",)), 0, "a mitad de hora no se pide nada")
            self.assertEqual(vivo.largas_al_dia(None, hora, ("SOLUSDT", "ADAUSDT")), 2 * sum(
                1 for t in vivo.LARGAS if hora % lib_datos.PASO_MS[t] == 0))
        self.assertTrue(all(c.args[1] in ("SOLUSDT", "ADAUSDT") for c in bajar.call_args_list))

    def test_el_minuto_se_guarda_sin_pasar_de_treinta_dias(self):
        n = vivo.MINUTOS_GUARDADOS
        inicio = AHORA - n * MIN
        lib_datos.guardar_serie("SOLUSDT", "1m", [[inicio + i * MIN, 1, 2, 0.5, 1.5, 1] for i in range(n)])
        vela = {"par": "SOLUSDT", "t": inicio + n * MIN, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1}
        self.assertEqual(vivo.guardar_minuto(None, vela), 1)
        velas = lib_datos.leer_serie("SOLUSDT", "1m")
        self.assertEqual(len(velas), n)
        self.assertEqual(velas[-1][0], vela["t"])

    def test_el_grafico_acepta_las_ocho(self):
        self.assertEqual(vivo.grafico({"par": "DOGEUSDT", "temporalidad": "1m"})["datos"]["par"], "DOGEUSDT")


if __name__ == "__main__":
    unittest.main()
