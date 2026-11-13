"""La llave de Alpaca para las noticias: se prueba antes de guardarla, vive en el llavero y nunca sale a la pantalla."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import lib_alpaca  # noqa: E402
import lib_llavero  # noqa: E402

LLAVE = "PK" + "A1" * 12            # inventada, con la forma de una Key ID
SECRETO = "s3" * 20                 # inventado, con la forma de una Secret Key
RESPUESTA = {"news": [{"id": 7, "created_at": "2026-11-13T12:00:00Z", "headline": "Un titular", "symbols": ["BTCUSD", "XYZ"]},
                      {"id": "malo"}]}


class LlaveroFalso:
    """Un llavero en memoria con el mismo `security` que usa lib_llavero."""

    def __init__(self):
        self.datos = {}

    def correr(self, args, entrada=None):
        class R:
            returncode, stdout = 0, ""
        r = R()
        if args[:2] == ["security", "-i"]:
            for linea in entrada.strip().splitlines():
                p = linea.split()
                self.datos[(p[p.index("-s") + 1], p[p.index("-a") + 1])] = p[p.index("-w") + 1]
        elif args[1] == "find-generic-password":
            clave = (args[args.index("-s") + 1], args[args.index("-a") + 1])
            if clave in self.datos:
                r.stdout = self.datos[clave]
            else:
                r.returncode = 44
        elif args[1] == "delete-generic-password":
            self.datos.pop((args[args.index("-s") + 1], args[args.index("-a") + 1]), None)
        return r


class Alpaca(unittest.TestCase):
    def setUp(self):
        self.llavero = LlaveroFalso()
        self.pedidos = []
        antes = (lib_llavero.correr, lib_llavero.disponible, lib_alpaca.pedir)
        lib_llavero.correr, lib_llavero.disponible = self.llavero.correr, lambda: True
        lib_alpaca.pedir = self.pedir
        self.addCleanup(lambda: setattr(lib_llavero, "correr", antes[0]) or setattr(lib_llavero, "disponible", antes[1])
                        or setattr(lib_alpaca, "pedir", antes[2]))
        self.responde = RESPUESTA

    def pedir(self, parametros, llave, secreto):
        self.pedidos.append((parametros, llave, secreto))
        if isinstance(self.responde, Exception):
            raise self.responde
        return self.responde

    def test_conectar_prueba_la_llave_y_la_guarda_en_el_llavero(self):
        r = lib_alpaca.conectar(LLAVE, SECRETO)
        self.assertTrue(r["ok"] and r["conectado"])
        self.assertEqual(r["pista"], LLAVE[:4] + "…" + LLAVE[-4:])
        self.assertEqual([n["id"] for n in r["ultimas"]], [7], "lo que no se entiende se salta")
        self.assertEqual(r["ultimas"][0]["simbolos"], ["BTCUSD"], "solo los símbolos que conocemos")
        self.assertNotIn(SECRETO, repr(r), "el secreto no vuelve a la pantalla")
        self.assertEqual(self.llavero.datos[(lib_alpaca.SERVICIO, lib_llavero.CUENTA_SECRETO)], SECRETO)
        self.assertNotIn((lib_llavero.SERVICIO, lib_llavero.CUENTA_LLAVE), self.llavero.datos, "no pisa la de Binance")

    def test_una_llave_que_alpaca_rechaza_no_se_guarda(self):
        self.responde = lib_alpaca.Falla("rechazada")
        r = lib_alpaca.conectar(LLAVE, SECRETO)
        self.assertEqual((r["ok"], r["motivo"], r["conectado"]), (False, "rechazada", False))
        self.assertEqual(self.llavero.datos, {})

    def test_un_formato_raro_no_sale_a_la_red(self):
        r = lib_alpaca.conectar("pk-con; espacios", SECRETO)
        self.assertEqual(r["motivo"], "formato")
        self.assertEqual(self.pedidos, [])

    def test_desconectar_borra_la_llave(self):
        lib_alpaca.conectar(LLAVE, SECRETO)
        r = lib_alpaca.desconectar()
        self.assertFalse(r["conectado"])
        self.assertEqual(self.llavero.datos, {})

    def test_una_respuesta_que_no_se_entiende_es_un_codigo(self):
        self.responde = {"otra": "cosa"}
        self.assertEqual(lib_alpaca.conectar(LLAVE, SECRETO)["motivo"], "respuesta")

    def test_al_dia_guarda_las_nuevas_y_la_pantalla_las_lee_sin_red(self):
        import tempfile
        carpeta = tempfile.mkdtemp()
        antes = os.environ.get("PILOTA_DATOS")
        os.environ["PILOTA_DATOS"] = carpeta
        self.addCleanup(lambda: os.environ.__setitem__("PILOTA_DATOS", antes) if antes else os.environ.pop("PILOTA_DATOS", None))
        self.assertIsNone(lib_alpaca.al_dia(1_794_571_200_000), "sin llave no hace nada")
        lib_alpaca.conectar(LLAVE, SECRETO)
        self.responde = {"news": [{"id": 9, "created_at": "2026-11-13T12:00:00Z", "headline": "Fed rate cut and Trump tariff",
                                   "symbols": ["BTCUSD"]}]}
        ms = 1_794_571_200_000 + 60_000
        lib_alpaca.al_dia(ms)
        self.pedidos.clear()
        r = lib_alpaca.recientes(ms)
        self.assertEqual(self.pedidos, [], "la pantalla no sale a la red")
        self.assertEqual([n["id"] for n in r["noticias"]], [9])
        self.assertEqual(r["noticias"][0]["tipos"], ["trump", "fed", "aranceles"])
        self.responde = lib_alpaca.Falla("sin_red")
        lib_alpaca.al_dia(ms + 60_000)
        self.assertEqual(lib_alpaca.recientes(ms)["motivo"], "sin_red")
        self.assertEqual(len(lib_alpaca.recientes(ms)["noticias"]), 1, "un fallo no borra lo que había")


if __name__ == "__main__":
    unittest.main()
