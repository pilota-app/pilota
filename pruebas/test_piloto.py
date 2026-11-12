"""Pruebas de los perfiles y de la prueba en vivo (`lib_perfiles`, `lib_piloto`).

Cada prueba corre con su carpeta temporal y precios inventados: ninguna sale a la red.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "bin"))

import lib_datos  # noqa: E402
import lib_ejecutor_prueba  # noqa: E402
import lib_estado  # noqa: E402
import lib_perfiles as perfiles  # noqa: E402
import lib_piloto as piloto  # noqa: E402
import lib_registro  # noqa: E402
import lib_tamano  # noqa: E402
import minimo_viable  # noqa: E402
import nucleo  # noqa: E402

AHORA = 1_770_732_300_000
MIN = lib_datos.PASO_MS["1m"]
HORA = lib_datos.PASO_MS["1h"]
SEMANA = 7 * lib_datos.DIA_MS
FILTROS = {"par": "BTCFDUSD", "moneda": "BTC", "tick": 0.01, "paso": 0.00001, "cantidad_minima": 0.00001,
           "nocional_minimo": 5.0, "proteccion": True, "operando": True, "motivo": ""}
SENAL = {"estrategia": "rebote", "par": "BTCFDUSD", "temporalidad": "1h", "vela": AHORA - 2 * HORA,
         "entrada": 100_000.0, "stop": 99_000.0, "objetivo": 101_500.0, "permitida": True, "vence": AHORA + 3 * HORA}


def minutos(precios, hasta=AHORA):
    """Una vela de 1 m por par, cerrada justo antes de `hasta`, con ese precio."""
    return {par: [[hasta - MIN, p, p, p, p, 1.0]] for par, p in precios.items()}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.antes = os.environ.get("PILOTA_DATOS")
        os.environ["PILOTA_DATOS"] = os.path.join(self.tmp.name, "datos")
        nucleo.escribir_json(minimo_viable.ruta_minimo(), {
            "formato": 1, "calculado": True, "cuando": lib_datos.iso(AHORA), "moneda": "USDT", "capital_minimo": 40,
            "pares": [{**FILTROS, "capital": 40}, {**FILTROS, "par": "ETHFDUSD", "moneda": "ETH", "capital": 40}],
            "motivos": [], "listo": True})

    def tearDown(self):
        if self.antes is None:
            os.environ.pop("PILOTA_DATOS", None)
        else:
            os.environ["PILOTA_DATOS"] = self.antes
        self.tmp.cleanup()

    def razones(self):
        filas, _ = lib_registro.ultimas(lib_estado.PRUEBA, 100)
        return [x["razon"] for x in reversed(filas)]


class Perfiles(unittest.TestCase):
    def test_hay_cinco_y_el_sugerido_existe(self):
        self.assertEqual(perfiles.ORDEN, ("holding", "conservador", "equilibrado", "trader", "scalper"))
        self.assertIn(perfiles.SUGERIDO, perfiles.PERFILES)

    def test_ningun_perfil_arriesga_mas_que_el_tamano(self):
        for p in perfiles.PERFILES.values():
            self.assertLessEqual(p.get("riesgo", 0), lib_tamano.RIESGO)

    def test_la_relacion_filtra_por_perfil(self):
        s = {**SENAL, "objetivo": 101_500.0}            # gana 1,5 por cada 1 que arriesga
        self.assertAlmostEqual(perfiles.relacion(s), 1.5)
        self.assertTrue(perfiles.acepta("equilibrado", s))
        self.assertTrue(perfiles.acepta("trader", s))
        self.assertFalse(perfiles.acepta("conservador", s), "pide 2 y además solo mira 4 h")
        self.assertFalse(perfiles.acepta("holding", s), "el holding no opera señales")
        self.assertFalse(perfiles.acepta("scalper", s), "el scalper solo mira 5 m")

    def test_agrupar_arma_velas_de_cinco_minutos_completas(self):
        base = 1_770_000_000_000 // (5 * MIN) * (5 * MIN)
        velas = [[base + i * MIN, 10 + i, 20 + i, 5 + i, 11 + i, 1.0] for i in range(12)]
        r = perfiles.agrupar(velas, 5)
        self.assertEqual(len(r), 2, "la tercera tiene solo 2 minutos: no se usa")
        self.assertEqual(r[0], [base, 10, 24, 5, 15, 5.0])

    def test_el_tamano_del_perfil_achica_el_riesgo(self):
        com = {"maker": 0.0, "taker": 0.0, "conversion": 0.0}
        normal = lib_tamano.tamano(10_000.0, 100_000.0, 90_000.0, FILTROS, com)   # stop lejos: manda el riesgo
        chico = perfiles.tamano("conservador", 10_000.0, 100_000.0, 90_000.0, FILTROS, com)
        self.assertEqual(normal["manda"], "riesgo")
        self.assertAlmostEqual(chico["cantidad"], normal["cantidad"] / 2, places=5)

    def test_el_perfil_respeta_su_maximo_de_posiciones(self):
        t = perfiles.tamano("conservador", 1000.0, 100_000.0, 99_000.0, FILTROS, abiertas=1)
        self.assertEqual((t["puede"], t["motivo"]), (False, "posiciones_llenas"))


class Empezar(Base):
    def test_un_perfil_que_no_existe_no_empieza(self):
        self.assertEqual(piloto.empezar("loco", 100, AHORA)["error"], "sin_perfil")

    def test_un_monto_raro_no_empieza(self):
        self.assertEqual(piloto.empezar("trader", 0, AHORA)["error"], "monto")
        self.assertEqual(piloto.empezar("trader", 10**12, AHORA)["error"], "monto")

    def test_empezar_reinicia_el_saldo_y_queda_en_el_registro(self):
        self.assertTrue(piloto.empezar("trader", 100, AHORA)["ok"])
        cuenta = lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA + HORA)
        self.assertEqual(cuenta["saldo"], 100.0)
        self.assertEqual(self.razones()[-2:], ["saldo_reiniciado", "perfil_empezado"])
        self.assertTrue(piloto.guardado()["activo"])

    def test_detener_deja_de_operar(self):
        piloto.empezar("trader", 100, AHORA)
        piloto.detener(AHORA + HORA)
        self.assertFalse(piloto.guardado()["activo"])
        self.assertEqual(self.razones()[-1], "perfil_detenido")

    def test_en_real_no_empieza(self):
        with mock.patch.object(lib_estado, "activo", return_value=lib_estado.REAL):
            self.assertEqual(piloto.empezar("trader", 100, AHORA)["error"], "no_es_prueba")


class Decidir(Base):
    def test_sin_perfil_deciden_los_modos_de_siempre(self):
        with mock.patch.object(piloto.lib_modos, "decidir", return_value={"modos": "x"}) as modos:
            self.assertEqual(piloto.decidir({"ahora_ms": AHORA, "ambiente": "prueba"}), {"modos": "x"})
        modos.assert_called_once()

    def test_en_real_deciden_los_modos_aunque_haya_perfil(self):
        piloto.empezar("trader", 100, AHORA)
        with mock.patch.object(piloto.lib_modos, "decidir", return_value={"modos": "x"}) as modos:
            piloto.decidir({"ahora_ms": AHORA, "ambiente": "real"})
        modos.assert_called_once()

    def test_una_senal_aceptada_se_pone_con_su_proteccion(self):
        piloto.empezar("equilibrado", 1000, AHORA - HORA)
        with mock.patch.object(piloto, "senales_de_ahora", return_value=([dict(SENAL)], [])):
            r = piloto.decidir({"ahora_ms": AHORA, "ambiente": "prueba"})
        self.assertEqual(r["piloto"]["decision"], "entrada", r)
        cuerpo = lib_estado.cuerpo_de(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA + HORA))
        p = lib_ejecutor_prueba.nuestras(cuerpo)[0]
        self.assertEqual((p["par"], p["stop"], p["objetivo"]), ("BTCFDUSD", 99_000.0, 101_500.0))
        self.assertIn("entrada_rebote", self.razones())

    def test_la_misma_vela_no_se_intenta_dos_veces(self):
        piloto.empezar("equilibrado", 1000, AHORA - HORA)
        with mock.patch.object(piloto, "senales_de_ahora", return_value=([dict(SENAL)], [])):
            piloto.decidir({"ahora_ms": AHORA, "ambiente": "prueba"})
            r = piloto.decidir({"ahora_ms": AHORA + 5 * MIN, "ambiente": "prueba"})
        self.assertEqual(r["piloto"]["decision"], "sin_senal")
        self.assertEqual(self.razones().count("entrada_rebote"), 1)

    def test_sin_velas_al_dia_lo_dice(self):
        piloto.empezar("trader", 1000, AHORA - HORA)
        r = piloto.decidir({"ahora_ms": AHORA, "ambiente": "prueba"})
        self.assertEqual(r["piloto"]["decision"], "sin_datos")


class SenalesDeAhora(unittest.TestCase):
    def test_una_serie_atrasada_no_da_senales(self):
        vieja = [[AHORA - 10 * HORA, 1, 1, 1, 1, 1]]
        series = {(par, "1h"): vieja for par in lib_datos.PARES_OPERADOS}
        senales, atrasadas = piloto.senales_de_ahora("trader", AHORA, series=series, ctx=(None, {}))
        self.assertEqual(senales, [])
        self.assertEqual(len(atrasadas), 2)

    def test_la_vela_en_curso_no_cuenta(self):
        en_curso = [[AHORA - HORA // 2, 1, 1, 1, 1, 1]]
        series = {(par, "1h"): en_curso for par in lib_datos.PARES_OPERADOS}
        _, atrasadas = piloto.senales_de_ahora("trader", AHORA, series=series, ctx=(None, {}))
        self.assertEqual(len(atrasadas), 2, "solo hay una vela y todavía no cierra")


class Holding(Base):
    PRECIOS = {"BTCFDUSD": 100_000.0, "ETHFDUSD": 4_000.0}

    def vuelta(self, ms, precios=None):
        with mock.patch.object(lib_ejecutor_prueba, "minutos_de", return_value=minutos(precios or self.PRECIOS, ms)):
            return piloto.decidir({"ahora_ms": ms, "ambiente": "prueba"})

    def test_compra_una_parte_por_semana(self):
        piloto.empezar("holding", 120, AHORA)
        self.assertEqual(self.vuelta(AHORA)["piloto"]["decision"], "compra")
        self.assertEqual(self.vuelta(AHORA + HORA)["piloto"]["decision"], "esperando")
        self.assertEqual(self.vuelta(AHORA + SEMANA)["piloto"]["decision"], "compra")
        h = piloto.guardado()["holding"]
        self.assertEqual(h["partes"], 2)
        self.assertAlmostEqual(h["efectivo"], 100.0)
        self.assertEqual(self.razones().count("compra_holding"), 4, "dos semanas por dos monedas")

    def test_no_compra_mas_partes_de_las_que_tiene(self):
        piloto.empezar("holding", 120, AHORA)
        for i in range(perfiles.PERFILES["holding"]["partes"] + 2):
            r = self.vuelta(AHORA + i * SEMANA)
        self.assertEqual(r["piloto"]["decision"], "completo")
        self.assertAlmostEqual(piloto.guardado()["holding"]["efectivo"], 0.0, places=6)

    def test_sin_precio_no_compra(self):
        piloto.empezar("holding", 120, AHORA)
        with mock.patch.object(lib_ejecutor_prueba, "minutos_de", return_value={}):
            r = piloto.decidir({"ahora_ms": AHORA, "ambiente": "prueba"})
        self.assertEqual(r["piloto"]["decision"], "sin_datos")

    def test_el_valor_sigue_al_precio(self):
        piloto.empezar("holding", 120, AHORA)
        self.vuelta(AHORA)
        arriba = {k: v * 1.1 for k, v in self.PRECIOS.items()}
        e = piloto.estado(AHORA + HORA, minutos=minutos(arriba, AHORA + HORA))
        # 10 USDT comprados (sin comisión supuesta serían 11 ahora): sube algo menos de 1 USDT.
        self.assertGreater(e["ganancia"], 0.9)
        self.assertLess(e["ganancia"], 1.0)
        self.assertEqual(len(e["tenencias"]), 2)
        self.assertEqual(e["movimientos"][0]["razon"], "compra_holding")


if __name__ == "__main__":
    unittest.main()
