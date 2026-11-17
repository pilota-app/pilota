"""Pruebas de las formas de holdear (`lib_holding`). Puras: sin disco ni red."""
import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "bin"))

import lib_holding as H  # noqa: E402

DIA = H.DIA_MS
INICIO = 1_600_000_000_000 // DIA * DIA
BTC = {"BTCUSDT": 1.0}


def velas(cierres, bajos=None):
    return [[INICIO + i * DIA, c, c, (bajos or cierres)[i], c, 1.0] for i, c in enumerate(cierres)]


def correr(cierres, reglas, bajos=None, monto=100):
    return H.simular(monto, {"BTCUSDT": velas(cierres, bajos)}, INICIO, INICIO + (len(cierres) - 1) * DIA, reglas,
                     {"taker": 0.001})


class Compras(unittest.TestCase):
    def test_compra_por_partes_una_por_semana(self):
        r = correr([100.0] * 60, {"reparto": BTC, "partes": 4})
        compras = [m for m in r["movimientos"] if m["que"] == "compra"]
        self.assertEqual(len(compras), 4)
        self.assertEqual([(c["ms"] - INICIO) // DIA for c in compras], [0, 7, 14, 21])
        self.assertAlmostEqual(r["libro"]["efectivo"], 0, places=6)
        self.assertLess(r["saldo"], 100, "con el precio quieto, las comisiones se notan")

    def test_la_orden_mas_abajo_se_llena_si_mañana_llega(self):
        cierres = [100.0] * 10
        bajos = [100.0, 98.0] + [100.0] * 8               # al día siguiente el mínimo toca 98
        r = correr(cierres, {"reparto": BTC, "partes": 1, "descuento": 0.01}, bajos)
        c = next(m for m in r["movimientos"] if m["que"] == "compra")
        self.assertEqual((c["por"], c["precio"]), ("limite", 99.0))

    def test_si_no_llega_compra_al_cierre_y_no_se_salta_la_semana(self):
        r = correr([100.0, 105.0] + [105.0] * 8, {"reparto": BTC, "partes": 1, "descuento": 0.01})
        c = next(m for m in r["movimientos"] if m["que"] == "compra")
        self.assertEqual(c["por"], "cierre")
        self.assertGreater(c["precio"], 105.0)

    def test_nunca_mira_el_futuro(self):
        # El mínimo del mismo día de la orden no la llena: solo el del día siguiente.
        r = correr([100.0, 101.0, 101.0], {"reparto": BTC, "partes": 1, "descuento": 0.01}, [90.0, 101.0, 101.0])
        c = next(m for m in r["movimientos"] if m["que"] == "compra")
        self.assertEqual(c["por"], "cierre")


class Ventas(unittest.TestCase):
    def test_el_rebalanceo_vende_lo_que_sobra_si_sube(self):
        cierres = [100.0] * 8 + [300.0] * 20
        r = correr(cierres, {"reparto": BTC, "partes": 1, "rebalanceo": {"cripto": 0.5, "banda": 0.1}})
        ventas = [m for m in r["movimientos"] if m["que"] == "venta"]
        self.assertEqual(ventas[0]["por"], "rebalanceo")
        h = r["libro"]
        en_cripto = sum(q * 300.0 for q in h["tenencias"].values())
        self.assertAlmostEqual(en_cripto / (en_cripto + h["efectivo"]), 0.5, delta=0.01)

    def test_la_cosecha_vende_al_subir_y_recompra_al_bajar(self):
        cierres = [100.0] * 3 + [140.0] * 3 + [110.0] * 3
        r = correr(cierres, {"reparto": BTC, "partes": 1, "cosecha": {"sube": 0.3, "vende": 0.25, "recompra": 0.15}})
        por = [(m["que"], m["por"]) for m in r["movimientos"]]
        self.assertEqual(por, [("compra", "semana"), ("venta", "cosecha"), ("compra", "recompra")])
        self.assertGreater(r["movimientos"][1]["ganancia"], 0)

    def test_sin_recompra_la_plata_queda_esperando(self):
        r = correr([100.0] * 3 + [140.0] * 5, {"reparto": BTC, "partes": 1,
                                                 "cosecha": {"sube": 0.3, "vende": 0.25, "recompra": 0.15}})
        self.assertIn("BTCUSDT", r["libro"]["guardado"])
        self.assertGreater(r["libro"]["efectivo"], 0)


if __name__ == "__main__":
    unittest.main()
