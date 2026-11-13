"""Pruebas de seguir la tendencia y del tamaño por volatilidad (`lib_tendencia`). Puras: sin disco ni red."""
import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "bin"))

import lib_tendencia as T  # noqa: E402

DIA = T.DIA_MS
INICIO = 1_600_000_000_000 // DIA * DIA


def velas(cierres):
    return [[INICIO + i * DIA, c, c, c, c, 1.0] for i, c in enumerate(cierres)]


def subida(n, ritmo=0.01, ruido=0.0):
    return [100 * (1 + ritmo) ** i * (1 + ruido * ((-1) ** i)) for i in range(n)]


class Reglas(unittest.TestCase):
    def test_la_volatilidad_crece_con_el_ruido(self):
        self.assertLess(T.volatilidad(subida(60, ruido=0.005)), T.volatilidad(subida(60, ruido=0.03)))
        self.assertIsNone(T.volatilidad([1, 2, 3]))

    def test_el_tamano_se_achica_si_se_mueve_de_mas(self):
        self.assertAlmostEqual(T.tamano(4, 0.4, 0.6), 0.25)
        self.assertAlmostEqual(T.tamano(4, 1.2, 0.6), 0.125)
        self.assertAlmostEqual(T.tamano(4, 1.2, None), 0.25, msg="sin objetivo, el cupo entero")

    def test_tendencia_pide_estar_sobre_la_media_y_que_suba(self):
        self.assertTrue(T.en_tendencia(subida(200), 100))
        self.assertFalse(T.en_tendencia(subida(200, ritmo=-0.01), 100))
        self.assertFalse(T.en_tendencia(subida(50), 100), "sin historia suficiente no hay tendencia")

    def test_pesos_solo_de_las_que_suben(self):
        p = T.pesos_tendencia({"SOLUSDT": subida(200), "ADAUSDT": subida(200, ritmo=-0.01)}, media=100, cupos=2)
        self.assertEqual(list(p), ["SOLUSDT"])
        self.assertAlmostEqual(p["SOLUSDT"], 0.5)


class Simular(unittest.TestCase):
    def test_sube_con_lo_que_sube_y_paga_comisiones(self):
        d = {"SOLUSDT": velas(subida(400, ritmo=0.005, ruido=0.01))}
        regla = lambda tramos, actuales, pasa: T.pesos_tendencia(tramos, media=100, cupos=1)
        r = T.simular(100, d, INICIO + 150 * DIA, INICIO + 399 * DIA, {"taker": 0.001}, regla)
        self.assertTrue(r["listo"])
        self.assertGreater(r["rendimiento"], 0.5)
        self.assertLess(r["rendimiento"], (1.005 ** 249) - 1, "las comisiones y la diferencia de puntas se pagan")

    def test_en_caida_se_queda_en_usdt(self):
        d = {"ADAUSDT": velas(subida(400, ritmo=-0.005))}
        regla = lambda tramos, actuales, pasa: T.pesos_tendencia(tramos, media=100, cupos=1)
        r = T.simular(100, d, INICIO + 150 * DIA, INICIO + 399 * DIA, {"taker": 0.001}, regla)
        self.assertAlmostEqual(r["saldo"], 100)
        self.assertEqual(r["movimientos_total"], 0)

    def test_nunca_mira_el_futuro(self):
        # Una subida que empieza mañana no se puede haber comprado hoy.
        cierres = [100.0] * 300 + [200.0] * 10
        d = {"SOLUSDT": velas(cierres)}
        vistos = []
        def regla(tramos, actuales, pasa):
            vistos.append(tramos["SOLUSDT"][-1])
            return {}
        T.simular(100, d, INICIO + 299 * DIA, INICIO + 299 * DIA, {}, regla)
        self.assertEqual(vistos, [100.0])


if __name__ == "__main__":
    unittest.main()
