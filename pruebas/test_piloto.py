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
    def test_se_ofrecen_los_holding_y_la_rotacion(self):
        self.assertEqual(perfiles.ORDEN, ("holding", "holding_ocho", "compra_semanal", "rebalanceo", "cosecha",
                                          "indice_eeuu", "indice_semanal", "acciones_ocho",
                                          "semanal_rotacion", "nucleo_satelite", "cripto_acciones", "rotacion"))
        self.assertEqual(perfiles.pares_de("cripto_acciones"), ("BTCUSDT", "ETHUSDT", "SPYBUSDT", "QQQBUSDT"))
        self.assertTrue(all(p in perfiles.PERFILES and p not in perfiles.ORDEN for p in perfiles.RETIRADOS))
        self.assertIn(perfiles.SUGERIDO, perfiles.PERFILES)

    def test_cada_perfil_dice_si_opera_cripto_acciones_o_las_dos(self):
        mercado = {p: perfiles.mercado_de(p) for p in perfiles.ORDEN}
        self.assertEqual({p for p, m in mercado.items() if m == "acciones"}, {"indice_eeuu", "indice_semanal", "acciones_ocho"})
        self.assertEqual({p for p, m in mercado.items() if m == "mixto"}, {"cripto_acciones"})
        self.assertEqual(mercado["holding"], "cripto")
        self.assertTrue(all(p["mercado"] == mercado[p["id"]] for p in perfiles.parametros()["perfiles"]))

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
        self.assertFalse(perfiles.acepta("conservador", {**s, "temporalidad": "4h", "objetivo": 102_000.0, "par": "DOGEUSDT"}),
                         "el conservador no opera DOGE")
        self.assertTrue(perfiles.acepta("trader", {**s, "par": "DOGEUSDT"}))

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
        series = {(par, "1h"): vieja for par in perfiles.pares_de("trader")}
        senales, atrasadas = piloto.senales_de_ahora("trader", AHORA, series=series, ctx=(None, {}))
        self.assertEqual(senales, [])
        self.assertEqual(len(atrasadas), len(perfiles.pares_de("trader")), "cada moneda del perfil se mira")

    def test_la_vela_en_curso_no_cuenta(self):
        en_curso = [[AHORA - HORA // 2, 1, 1, 1, 1, 1]]
        series = {(par, "1h"): en_curso for par in perfiles.pares_de("trader")}
        _, atrasadas = piloto.senales_de_ahora("trader", AHORA, series=series, ctx=(None, {}))
        self.assertEqual(len(atrasadas), 8, "solo hay una vela y todavía no cierra")


class OchoMonedas(Base):
    def test_un_perfil_entra_en_una_moneda_contra_usdt(self):
        import lib_universo
        nucleo.escribir_json(lib_universo.ruta(), {"filtros": {"SOLUSDT": {**FILTROS, "par": "SOLUSDT", "moneda": "SOL",
                                                                         "paso": 0.001, "cantidad_minima": 0.001}},
                                                   "filtros_ms": AHORA})
        piloto.empezar("trader", 300, AHORA)
        s = {**SENAL, "par": "SOLUSDT", "entrada": 100.0, "stop": 98.0, "objetivo": 104.0}
        with mock.patch.object(piloto, "senales_de_ahora", return_value=([s], [])), \
                mock.patch.object(lib_ejecutor_prueba, "minutos_de", return_value=minutos({"SOLUSDT": 101.0})):
            r = piloto.decidir({"ahora_ms": AHORA, "ambiente": "prueba"})["piloto"]
        self.assertEqual((r["decision"], r["par"]), ("entrada", "SOLUSDT"))
        self.assertEqual([p["par"] for p in lib_ejecutor_prueba.guardado()["posiciones"]], ["SOLUSDT"])
        self.assertIn("entrada_rebote", self.razones())


class HoldingsEnVivo(Base):
    """Las variantes de holding en vivo: el mismo paso diario de la comparación (`lib_holding.paso`)."""
    DIA = lib_datos.DIA_MS

    def vuelta(self, ms, precios, bajos=None):
        with mock.patch.object(piloto, "precio_fresco", side_effect=lambda par, m: precios.get(par)), \
                mock.patch.object(piloto, "_bajo_de", side_effect=lambda par, dia: (bajos or {}).get(par)):
            return piloto.decidir({"ahora_ms": ms, "ambiente": "prueba"})["piloto"]

    def test_la_compra_semanal_deja_la_orden_mas_abajo_y_la_llena_al_dia_siguiente(self):
        piloto.empezar("compra_semanal", 520, AHORA)
        p = {"BTCUSDT": 100_000.0, "ETHUSDT": 4_000.0}
        self.assertEqual(self.vuelta(AHORA, p)["decision"], "esperando", "la orden queda puesta, no compra al tiro")
        self.assertEqual(self.vuelta(AHORA + HORA, p)["decision"], "esperando", "una vez por día")
        r = self.vuelta(AHORA + self.DIA, p, {"BTCUSDT": 98_000.0, "ETHUSDT": 4_100.0})
        self.assertEqual(r["decision"], "compra")
        lineas = [x for x in lib_registro.ultimas(lib_estado.PRUEBA, 20)[0] if x["razon"] == "compra_holding"]
        tipos = sorted((x["par"], x["orden"]["tipo"]) for x in lineas)
        self.assertEqual(tipos, [("BTCUSDT", "limite"), ("ETHUSDT", "mercado")], "BTC llegó al límite; ETH no")
        e = piloto.estado(AHORA + self.DIA, minutos={})
        self.assertEqual(sorted(t["par"] for t in e["tenencias"]), ["BTCUSDT", "ETHUSDT"])

    def test_la_cosecha_vende_una_parte_cuando_sube_harto(self):
        piloto.empezar("cosecha", 120, AHORA)
        self.vuelta(AHORA, {"BTCUSDT": 100.0, "ETHUSDT": 10.0})
        r = self.vuelta(AHORA + self.DIA, {"BTCUSDT": 140.0, "ETHUSDT": 10.0})
        self.assertEqual(r["decision"], "venta")
        self.assertIn("venta_holding", self.razones())
        self.assertIn("venta_holding", [x["razon"] for x in piloto.movimientos()])

    def test_sin_precio_no_hace_nada(self):
        piloto.empezar("holding_ocho", 100, AHORA)
        self.assertEqual(self.vuelta(AHORA, {"BTCUSDT": 1.0})["decision"], "sin_datos")


class MezclaEnVivo(HoldingsEnVivo):
    def test_cada_parte_compra_con_su_parte_del_monto(self):
        piloto.empezar("cripto_acciones", 200, AHORA)
        p = {"BTCUSDT": 100_000.0, "ETHUSDT": 4_000.0, "SPYBUSDT": 600.0, "QQQBUSDT": 500.0}
        self.vuelta(AHORA, p)
        r = self.vuelta(AHORA + self.DIA, p, {"BTCUSDT": 98_000.0, "SPYBUSDT": 590.0})
        self.assertEqual(r["decision"], "compra")
        self.assertEqual(set(r["partes"]), {"compra_semanal", "indice_semanal"})
        e = piloto.estado(AHORA + self.DIA, minutos={})
        self.assertEqual([x["perfil"] for x in e["mezcla"]], ["compra_semanal", "indice_semanal"])
        self.assertEqual(sorted(t["par"] for t in e["tenencias"]), ["BTCUSDT", "ETHUSDT", "QQQBUSDT", "SPYBUSDT"])
        self.assertAlmostEqual(e["valor"], sum(x["valor"] for x in e["mezcla"]))
        self.assertLess(e["valor"], 200, "las comisiones se pagan")


class RotacionEnVivo(Base):
    """La rotación con dinero ficticio: una vez por día pasa a las monedas que vienen más fuertes."""
    DIA = lib_datos.DIA_MS

    def diarias(self, subida):
        """60 días por moneda: cada una sube a su ritmo (`subida[par]` por día), con un poco de ruido."""
        hoy = AHORA // self.DIA * self.DIA
        return {par: [[hoy - (60 - i) * self.DIA, 0, 0, 0, 100 * (1 + subida.get(par, -0.001)) ** i * (1 + 0.002 * (i % 3)), 1]
                      for i in range(60)] for par in perfiles.pares_de("rotacion")}

    def vuelta(self, ms, subida, pasa=True):
        series = self.diarias(subida)
        with mock.patch.object(piloto, "_diaria", side_effect=lambda par: series.get(par, [])), \
                mock.patch.object(piloto, "contexto", return_value=(lambda m: {"pasa": pasa}, {})), \
                mock.patch.object(piloto, "precio_fresco", side_effect=lambda par, m: series[par][-1][4]):
            return piloto.decidir({"ahora_ms": ms, "ambiente": "prueba"})["piloto"]

    def test_compra_las_dos_mas_fuertes_y_cambia_la_que_se_cae(self):
        piloto.empezar("rotacion", 200, AHORA)
        r = self.vuelta(AHORA, {"SOLUSDT": 0.02, "TRXUSDT": 0.015, "BTCUSDT": 0.005})
        self.assertEqual((r["decision"], sorted(r["entran"])), ("rotacion", ["SOLUSDT", "TRXUSDT"]))
        self.assertEqual(self.vuelta(AHORA + HORA, {"SOLUSDT": 0.02})["decision"], "esperando", "una vez por día")
        # Al día siguiente TRX se cae y ADA pasa adelante: sale TRX, entra ADA, y SOL se queda.
        r = self.vuelta(AHORA + self.DIA, {"SOLUSDT": 0.02, "ADAUSDT": 0.03, "TRXUSDT": -0.01})
        self.assertEqual((r["salen"], r["entran"]), (["TRXUSDT"], ["ADAUSDT"]))
        self.assertEqual(self.razones().count("rotacion_compra"), 3)
        self.assertEqual(self.razones().count("rotacion_venta"), 1)
        e = piloto.estado(AHORA + self.DIA, minutos={})
        self.assertEqual(sorted(x["par"] for x in e["tenencias"]), ["ADAUSDT", "SOLUSDT"])
        self.assertLess(e["valor"], 250)

    def test_sin_el_permiso_de_btc_vende_todo_y_espera(self):
        piloto.empezar("rotacion", 200, AHORA)
        self.vuelta(AHORA, {"SOLUSDT": 0.02, "TRXUSDT": 0.015})
        r = self.vuelta(AHORA + self.DIA, {"SOLUSDT": 0.02, "TRXUSDT": 0.015}, pasa=False)
        self.assertEqual(sorted(r["salen"]), ["SOLUSDT", "TRXUSDT"])
        self.assertAlmostEqual(piloto.estado(AHORA + self.DIA, minutos={})["efectivo"], 200, delta=2)

    def test_sin_precio_fresco_no_mueve_nada(self):
        piloto.empezar("rotacion", 200, AHORA)
        series = self.diarias({"SOLUSDT": 0.02, "TRXUSDT": 0.015})
        with mock.patch.object(piloto, "_diaria", side_effect=lambda par: series.get(par, [])), \
                mock.patch.object(piloto, "contexto", return_value=(lambda m: {"pasa": True}, {})):
            r = piloto.decidir({"ahora_ms": AHORA, "ambiente": "prueba"})["piloto"]
        self.assertEqual(r["decision"], "sin_datos")
        self.assertNotIn("rotacion_compra", self.razones())


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
