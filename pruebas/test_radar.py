"""Pruebas del radar: qué está esperando el robot (`lib_radar`). Velas inventadas, sin red ni disco."""
import math
import os
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "bin"))

import lib_radar  # noqa: E402

HORA = 3_600_000


def velas(n=120, base=100.0):
    """Un precio que va y viene sin rumbo: el rebote aplica y la ruptura no."""
    salida = []
    for i in range(n):
        c = base + math.sin(i / 3) * 0.8
        salida.append([i * HORA, c - 0.1, c + 0.4, c - 0.4, c, 10.0])
    return salida


PASA = {"pasa": True, "motivo": ""}


class Radar(unittest.TestCase):
    def test_dice_el_gatillo_y_la_operacion_del_rebote(self):
        f = lib_radar.mirar_serie("BTCFDUSD", "1h", velas(), False, PASA, "trader", {})
        r = next(e for e in f["estrategias"] if e["estrategia"] == "rebote")
        self.assertIsNotNone(r["gatillo"])
        self.assertLess(r["gatillo"], f["precio"] + 1e-9)
        self.assertLess(r["stop"], r["entrada"])
        self.assertGreater(r["objetivo"], r["entrada"])
        self.assertAlmostEqual(r["rr"], (r["objetivo"] - r["entrada"]) / (r["entrada"] - r["stop"]))

    def test_la_ruptura_dice_que_el_dia_no_acompana(self):
        f = lib_radar.mirar_serie("BTCFDUSD", "1h", velas(), False, PASA, "trader", {})
        u = next(e for e in f["estrategias"] if e["estrategia"] == "ruptura")
        self.assertEqual(u["motivo"], "dia_no_al_alza")

    def test_con_btc_cayendo_nada_aplica(self):
        f = lib_radar.mirar_serie("BTCFDUSD", "1h", velas(), True, {"pasa": False, "motivo": "btc"}, "trader", {})
        self.assertTrue(all(e["motivo"] == "btc" for e in f["estrategias"]))
        self.assertEqual(f["espera"], "")

    def test_sin_velas_lo_dice(self):
        self.assertEqual(lib_radar.mirar_serie("BTCFDUSD", "1h", velas(10), True, PASA, "trader", {})["motivo"], "sin_datos")

    def test_la_historia_viaja_con_cada_jugada(self):
        h = {"rebote|BTCFDUSD|1h": {"n": 10, "ganadas": 4, "gana": 0.4, "neto_medio": -0.001, "por_objetivo": 4}}
        f = lib_radar.mirar_serie("BTCFDUSD", "1h", velas(), False, PASA, "trader", h)
        self.assertEqual(next(e for e in f["estrategias"] if e["estrategia"] == "rebote")["historia"]["n"], 10)

    def test_agrupar_cuenta_solo_lo_que_se_tomo(self):
        ops = [{"estrategia": "rebote", "par": "BTCFDUSD", "temporalidad": "1h", "motivo": "", "llenada": True,
                "permitida": True, "neto": 0.01, "por": "objetivo"},
               {"estrategia": "rebote", "par": "BTCFDUSD", "temporalidad": "1h", "motivo": "", "llenada": True,
                "permitida": True, "neto": -0.005, "por": "stop"},
               {"estrategia": "rebote", "par": "BTCFDUSD", "temporalidad": "1h", "motivo": "", "llenada": True,
                "permitida": False, "neto": 0.5, "por": "objetivo"}]
        g = lib_radar.agrupar(ops)["rebote|BTCFDUSD|1h"]
        self.assertEqual((g["n"], g["ganadas"]), (2, 1))
        self.assertAlmostEqual(g["neto_medio"], 0.0025)


if __name__ == "__main__":
    unittest.main()
