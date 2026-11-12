"""Pruebas de la simulación con monto («si hubiera puesto X USDT»).

Cada prueba corre con su carpeta temporal y con operaciones inventadas: ninguna sale a la red. Los precios son redondos a
propósito, así las cuentas se saben de memoria.
"""
import os
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "bin"))

import lib_datos  # noqa: E402
import lib_frenos  # noqa: E402
import lib_simulacion as sim  # noqa: E402
import minimo_viable  # noqa: E402
import nucleo  # noqa: E402

DIA = lib_datos.DIA_MS
HORA = lib_datos.PASO_MS["1h"]
INICIO = 1_767_225_600_000          # 1 de enero de 2026, 00:00 UTC
FILTROS = {"par": "BTCFDUSD", "moneda": "BTC", "tick": 0.01, "paso": 0.00001, "cantidad_minima": 0.00001,
           "nocional_minimo": 5.0, "proteccion": True, "operando": True, "motivo": ""}
PARES = {"BTCFDUSD": FILTROS}
SIN_COSTOS = {"maker": 0.0, "taker": 0.0, "conversion": 0.0}


def op(dia, neto, horas=2, nivel=100_000.0, stop=99_000.0, par="BTCFDUSD", permitida=True):
    """Una operación cerrada del backtest: entra a las 10:00 del día `dia` y sale `horas` después con `neto`."""
    entrada = INICIO + dia * DIA + 10 * HORA
    return {"par": par, "estrategia": "ruptura", "temporalidad": "1h", "nivel": nivel, "stop": stop,
            "objetivo": nivel * 1.015, "entrada_ms": entrada, "salida_ms": entrada + horas * HORA, "neto": neto,
            "llenada": True, "permitida": permitida, "motivo": ""}


class Cartera(unittest.TestCase):
    def test_una_ganadora_mueve_el_saldo_por_su_tamano(self):
        # 100 USDT, 2 % de riesgo = 2 USDT; stop a 1 % → 200 USDT, pero lo disponible para una posición manda.
        r = sim.cartera([op(0, 0.015)], 100.0, PARES, SIN_COSTOS)
        self.assertEqual(r["operaciones"], 1)
        self.assertEqual(r["ganadas"], 1)
        self.assertGreater(r["saldo"], 100.0)
        self.assertLess(r["saldo"], 101.5, "nunca entra con todo el saldo: la reserva del 40 % se queda en USDT")

    def test_la_curva_parte_en_el_monto_y_termina_en_el_saldo(self):
        r = sim.cartera([op(0, 0.015), op(1, -0.01)], 100.0, PARES, SIN_COSTOS, desde_ms=INICIO)
        self.assertEqual(r["curva"][0], [INICIO, 100.0])
        self.assertAlmostEqual(r["curva"][-1][1], r["saldo"], places=5)
        self.assertEqual((r["ganadas"], r["perdidas"]), (1, 1))

    def test_no_mas_de_dos_posiciones_a_la_vez(self):
        ops = [op(0, 0.01, horas=10), op(0, 0.01, horas=10), op(0, 0.01, horas=10)]
        ops[1]["entrada_ms"] += 1
        ops[2]["entrada_ms"] += 2
        r = sim.cartera(ops, 1000.0, PARES, SIN_COSTOS)
        self.assertEqual(r["operaciones"], 2)
        self.assertEqual(r["saltadas"]["posiciones"], 1)

    def test_cuatro_perdidas_seguidas_paran_el_dia(self):
        ops = [op(0, -0.001, horas=1) for _ in range(6)]
        for i, o in enumerate(ops):
            o["entrada_ms"] += i * 2 * HORA
            o["salida_ms"] = o["entrada_ms"] + HORA
        r = sim.cartera(ops, 1000.0, PARES, SIN_COSTOS)
        self.assertEqual(r["operaciones"], lib_frenos.RACHA_MAXIMA)
        self.assertEqual(r["saltadas"]["racha"], 2)

    def test_al_otro_dia_la_racha_vuelve_a_cero(self):
        ops = [op(0, -0.001, horas=1) for _ in range(5)] + [op(1, 0.01)]
        for i, o in enumerate(ops[:5]):
            o["entrada_ms"] += i * 2 * HORA
            o["salida_ms"] = o["entrada_ms"] + HORA
        r = sim.cartera(ops, 1000.0, PARES, SIN_COSTOS)
        self.assertEqual(r["operaciones"], lib_frenos.RACHA_MAXIMA + 1)

    def test_el_tope_achica_el_monto(self):
        sin_tope = sim.cartera([op(0, 0.015)], 1000.0, PARES, SIN_COSTOS)
        con_tope = sim.cartera([op(0, 0.015)], 1000.0, PARES, SIN_COSTOS, tope=15.0)
        self.assertAlmostEqual(con_tope["ganancia"], 15.0 * 0.015, places=2)
        self.assertGreater(sin_tope["ganancia"], con_tope["ganancia"])

    def test_bajo_el_minimo_de_binance_no_entra(self):
        r = sim.cartera([op(0, 0.015)], 10.0, PARES, SIN_COSTOS, tope=1.0)
        self.assertEqual(r["operaciones"], 0)
        self.assertEqual(r["saltadas"]["tamano"], 1)

    def test_fuera_de_la_ventana_no_cuenta(self):
        r = sim.cartera([op(0, 0.015), op(5, 0.015)], 100.0, PARES, SIN_COSTOS, desde_ms=INICIO + 3 * DIA)
        self.assertEqual(r["operaciones"], 1)

    def test_ralear_deja_el_primero_y_el_ultimo(self):
        puntos = [[i, i] for i in range(1000)]
        r = sim.ralear(puntos, 50)
        self.assertEqual(len(r), 50)
        self.assertEqual((r[0], r[-1]), ([0, 0], [999, 999]))


class Simular(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.antes = os.environ.get("PILOTA_DATOS")
        os.environ["PILOTA_DATOS"] = os.path.join(self.tmp.name, "datos")

    def tearDown(self):
        if self.antes is None:
            os.environ.pop("PILOTA_DATOS", None)
        else:
            os.environ["PILOTA_DATOS"] = self.antes
        self.tmp.cleanup()

    def minimos(self):
        nucleo.escribir_json(minimo_viable.ruta_minimo(), {
            "formato": 1, "calculado": True, "cuando": lib_datos.iso(INICIO), "moneda": "USDT", "capital_minimo": 40,
            "pares": [{**FILTROS, "capital": 40}], "motivos": [], "listo": True})

    def recorrido(self, ops):
        return {"ventana": {"desde": INICIO, "hasta": INICIO + 100 * DIA}, "todas": ops}

    def test_dice_que_falta_el_monto_o_el_periodo(self):
        self.assertEqual(sim.simular(None, 90, {})["motivo"], "sin_monto")
        self.assertEqual(sim.simular(5, 90, {})["motivo"], "sin_monto")
        self.assertEqual(sim.simular(100, 7, {})["motivo"], "sin_periodo")

    def test_sin_minimos_de_binance_no_simula(self):
        self.assertEqual(sim.simular(100, 90, self.recorrido([op(95, 0.01)]))["motivo"], "sin_minimos")

    def test_solo_cuentan_las_permitidas_y_dice_el_periodo(self):
        self.minimos()
        ops = [op(95, 0.01), op(96, 0.01, permitida=False)]
        r = sim.simular(100, 30, self.recorrido(ops), calibracion={})
        self.assertTrue(r["listo"])
        self.assertEqual(r["pilota"]["operaciones"], 1)
        self.assertEqual(r["dias_reales"], 30)
        self.assertTrue(r["sin_exigencia"], "sin calibrar, el resultado lo dice")
        self.assertEqual(r["usdt"]["saldo"], 100)

    def test_sin_operaciones_en_el_periodo_lo_dice(self):
        self.minimos()
        r = sim.simular(100, 30, self.recorrido([op(10, 0.01)]), calibracion={})
        self.assertFalse(r["listo"])
        self.assertEqual(r["motivo"], "sin_operaciones")


if __name__ == "__main__":
    unittest.main()
