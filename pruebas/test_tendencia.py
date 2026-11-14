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

class Cruce(unittest.TestCase):
    """La regla del perfil tendencia: cada moneda con su parte mientras cierra sobre su media."""
    REPARTO = {"BTCUSDT": 0.6, "ETHUSDT": 0.4}

    def test_solo_las_que_cierran_sobre_su_media(self):
        p = T.pesos_cruce({"BTCUSDT": subida(60), "ETHUSDT": subida(60, ritmo=-0.01)}, self.REPARTO, 50)
        self.assertEqual(p, {"BTCUSDT": 0.6})
        self.assertIsNone(T.filas_cruce({"BTCUSDT": subida(60), "ETHUSDT": subida(20)}, self.REPARTO, 50),
                          "sin historia de una no se decide con media regla")

    def test_el_paso_vende_lo_que_sale_y_compra_con_lo_que_queda(self):
        libro = T.nuevo(100)
        movs = T.paso(libro, INICIO, {"BTCUSDT": 10.0}, {"BTCUSDT": 0.6}, 0.001)
        self.assertEqual([m["que"] for m in movs], ["compra"])
        self.assertAlmostEqual(libro["efectivo"], 40)
        self.assertEqual(T.paso(libro, INICIO, {"BTCUSDT": 10.1}, {"BTCUSDT": 0.6}, 0.001), [], "bajo el umbral no reajusta")
        movs = T.paso(libro, INICIO, {"BTCUSDT": 9.0}, {}, 0.001)
        self.assertEqual([m["que"] for m in movs], ["venta"])
        self.assertEqual(libro["cantidad"], {})
        self.assertLess(movs[0]["ganancia"], 0, "vendió más barato de lo que compró, con costos")

    def test_tras_un_golpe_no_compra_pero_lo_que_tiene_lo_mantiene(self):
        sube = subida(60)
        golpe = sube[:-3] + [sube[-3] * 0.93, sube[-3] * 0.95, sube[-3] * 0.97]
        filas = T.filas_cruce({"BTCUSDT": golpe}, {"BTCUSDT": 1.0}, 20, actuales=(), golpe=0.05)
        self.assertEqual((filas[0]["parte"], filas[0]["motivo"]), (0.0, "golpe"))
        filas = T.filas_cruce({"BTCUSDT": golpe}, {"BTCUSDT": 1.0}, 20, actuales=("BTCUSDT",), golpe=0.05)
        self.assertEqual(filas[0]["parte"], 1.0, "si ya la tiene, no la vende por el golpe")

    def test_una_mala_noticia_deja_esa_parte_en_usdt(self):
        noticia = {"persona": "Alguien", "que": "x", "fecha": "2026-11-10", "dia": -0.04, "activo": "BTC"}
        p = T.pesos_cruce({"BTCUSDT": subida(60), "ETHUSDT": subida(60)}, self.REPARTO, 50, noticias={"BTCUSDT": noticia})
        self.assertEqual(p, {"ETHUSDT": 0.4})

    def test_la_historia_cuenta_los_dias_del_mismo_lado_de_la_media(self):
        cierres = [100 * (1.002 ** i) for i in range(400)]
        h = T.historia_cruce(cierres, 50, 20)
        self.assertTrue(h["sobre"])
        self.assertEqual((h["sube"], h["cae"]), (1.0, 0.0), "si siempre sube, siempre subió y nunca cayó")
        self.assertGreater(h["dias"], 300)
        self.assertIsNone(T.historia_cruce(cierres[:150], 50, 20), "con poca historia no se dice un porcentaje")

    def test_simular_con_la_regla_de_cruce_sale_en_la_caida(self):
        cierres = subida(120) + subida(80, ritmo=-0.02)[1:]
        r = T.simular(100, {"BTCUSDT": velas([c * 1 for c in cierres]), "ETHUSDT": velas(cierres)}, INICIO, INICIO + 400 * DIA,
                      {"taker": 0.001}, lambda t, a, pasa: T.pesos_cruce(t, self.REPARTO, 50))
        self.assertTrue(r["listo"])
        quieto = cierres[-1] / cierres[60]
        self.assertGreater(r["saldo"] / 100, quieto, "vender bajo la media pierde menos que quedarse en la caída")


if __name__ == "__main__":
    unittest.main()
