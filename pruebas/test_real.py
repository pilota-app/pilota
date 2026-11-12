"""Pruebas del conector real y del paso a real, con un Binance falso en memoria.

Ninguna prueba sale a la red ni toca el llavero de verdad: el cliente de Binance es `BinanceFalso` y la llave es
inventada. Los precios son redondos a propósito.
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "bin"))

import lib_binance_privado as bp  # noqa: E402
import lib_datos  # noqa: E402
import lib_ejecutor_real as real  # noqa: E402
import lib_estado  # noqa: E402
import lib_llavero  # noqa: E402
import lib_real  # noqa: E402
import lib_registro  # noqa: E402
import minimo_viable  # noqa: E402
import nucleo  # noqa: E402

AHORA = 1_770_732_300_000
HORA = lib_datos.PASO_MS["1h"]
FILTROS = {"par": "BTCFDUSD", "moneda": "BTC", "tick": 0.01, "paso": 0.00001, "cantidad_minima": 0.00001,
           "nocional_minimo": 5.0, "proteccion": True, "operando": True, "motivo": ""}
LLAVE = "A" * 64
SECRETO = "b" * 64
PUEDE = {"entradas": {"puede": True, "motivo": ""}}
OPCION = {"estrategia": "rebote", "par": "BTCFDUSD", "temporalidad": "1h", "vela": AHORA - HORA, "entrada": 100_000.0,
          "stop": 99_000.0, "objetivo": 101_500.0, "puntaje": 90, "permitida": True, "vence": AHORA + 3 * HORA}


class BinanceFalso:
    """Lo mínimo de Binance para el conector: saldos, órdenes por id propio y protecciones."""

    def __init__(self, usdt=500.0, fdusd=0.0, btc=0.0):
        self.saldos = {"USDT": usdt, "FDUSD": fdusd, "BTC": btc, "ETH": 0.0}
        self.ordenes, self.listas, self.llamadas = {}, {}, []
        self.rechazar_oco = False
        self.ajenas = []

    def sincronizar(self):
        return 0

    def cuenta(self):
        return {"canTrade": True, "balances": [{"asset": a, "free": str(v), "locked": "0"}
                                               for a, v in self.saldos.items()]}

    def permisos(self):
        return {"enableReading": True, "enableSpotAndMarginTrading": True, "enableWithdrawals": False,
                "ipRestrict": True}

    def comprar_con(self, par, monto, cid):
        self.llamadas.append(("convertir", par, monto))
        m = float(monto)
        self.saldos["USDT"] -= m
        self.saldos["FDUSD"] += m * 0.9995
        return {"status": "FILLED"}

    def comprar_limite(self, par, cantidad, precio, cid):
        self.llamadas.append(("comprar", par, cantidad, precio, cid))
        self.ordenes[cid] = {"clientOrderId": cid, "symbol": par, "status": "NEW", "executedQty": "0",
                             "cummulativeQuoteQty": "0", "price": precio, "origQty": cantidad, "orderListId": -1}
        return self.ordenes[cid]

    def llenar(self, cid, fraccion=1.0):
        o = self.ordenes[cid]
        q = float(o["origQty"]) * fraccion
        o.update(status="FILLED" if fraccion >= 1 else "PARTIALLY_FILLED", executedQty=str(q),
                 cummulativeQuoteQty=str(q * float(o["price"])))
        self.saldos["BTC"] += q
        self.saldos["FDUSD"] -= q * float(o["price"])

    def orden(self, par, cid):
        if cid not in self.ordenes:
            raise bp.ErrorBinance(bp.NO_EXISTE, 400, "/api/v3/order")
        return self.ordenes[cid]

    def abiertas(self, par):
        return [o for o in [*self.ordenes.values(), *self.ajenas]
                if o["symbol"] == par and o["status"] in ("NEW", "PARTIALLY_FILLED")]

    def cancelar(self, par, cid):
        self.llamadas.append(("cancelar", cid))
        o = self.ordenes.get(cid)
        if not o or o["status"] not in ("NEW", "PARTIALLY_FILLED"):
            raise bp.ErrorBinance(bp.CANCELAR_FALLO, 400, "/api/v3/order")
        o["status"] = "CANCELED"
        return o

    def proteger(self, par, cantidad, objetivo, stop, lista):
        self.llamadas.append(("proteger", par, cantidad, objetivo, stop, lista))
        if self.rechazar_oco:
            raise bp.ErrorBinance(-1013, 400, "/api/v3/orderList/oco")
        for suf, precio in (("o", objetivo), ("s", stop)):
            self.ordenes[f"{lista}-{suf}"] = {"clientOrderId": f"{lista}-{suf}", "symbol": par, "status": "NEW",
                                              "executedQty": "0", "cummulativeQuoteQty": "0", "price": precio,
                                              "origQty": cantidad, "orderListId": 1}
        self.listas[lista] = {"listClientOrderId": lista, "listOrderStatus": "EXECUTING"}
        self.saldos["BTC"] -= float(cantidad)
        return self.listas[lista]

    def proteccion(self, lista):
        return self.listas[lista]

    def cerrar_lista(self, lista, pata):
        """Una pata de la OCO se llenó; la otra se cancela."""
        for suf in ("o", "s"):
            o = self.ordenes[f"{lista}-{suf}"]
            if suf == pata:
                q = float(o["origQty"])
                o.update(status="FILLED", executedQty=str(q), cummulativeQuoteQty=str(q * float(o["price"])))
                self.saldos["FDUSD"] += q * float(o["price"])
            else:
                o["status"] = "CANCELED"
        self.listas[lista]["listOrderStatus"] = "ALL_DONE"

    def cancelar_proteccion(self, par, lista):
        self.llamadas.append(("cancelar_proteccion", lista))
        for suf in ("o", "s"):
            o = self.ordenes[f"{lista}-{suf}"]
            if o["status"] == "NEW":
                o["status"] = "CANCELED"
                self.saldos["BTC"] += float(o["origQty"]) if suf == "s" else 0.0
        self.listas[lista]["listOrderStatus"] = "ALL_DONE"

    def vender_mercado(self, par, cantidad, cid):
        self.llamadas.append(("vender", par, cantidad, cid))
        q = float(cantidad)
        self.saldos["BTC"] -= q
        self.saldos["FDUSD"] += q * 99_500.0
        return {"clientOrderId": cid, "status": "FILLED", "executedQty": str(q),
                "cummulativeQuoteQty": str(q * 99_500.0)}


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

    def en_real(self, saldo=200.0):
        lib_estado.guardar(lib_estado.REAL, lib_estado.nuevo(lib_estado.REAL, saldo, ahora_ms=AHORA - HORA))
        lib_estado.poner_interruptor(True, AHORA - HORA, presupuesto=saldo)

    def cuerpo(self):
        # Se lee «más tarde» que cualquier revisión de la prueba: un archivo de más adelante que ahora queda frenado.
        return lib_estado.cuerpo_de(lib_estado.cargar(lib_estado.REAL, ahora_ms=AHORA + 10 * HORA))

    def razones(self):
        filas, _ = lib_registro.ultimas(lib_estado.REAL, 50)       # de la más nueva a la más vieja
        return [linea["razon"] for linea in reversed(filas)]


class Interruptor(Base):
    def test_sin_interruptor_se_juega_en_prueba(self):
        self.assertEqual(lib_estado.activo(), lib_estado.PRUEBA)

    def test_el_interruptor_firmado_enciende_real_y_se_apaga(self):
        lib_estado.poner_interruptor(True, AHORA)
        self.assertEqual(lib_estado.activo(), lib_estado.REAL)
        lib_estado.poner_interruptor(False, AHORA)
        self.assertEqual(lib_estado.activo(), lib_estado.PRUEBA)

    def test_un_interruptor_tocado_a_mano_vuelve_a_prueba(self):
        lib_estado.poner_interruptor(False, AHORA)
        d = nucleo.leer_json(lib_estado.ruta_interruptor(), {})
        d["interruptor"]["real"] = True
        nucleo.escribir_json(lib_estado.ruta_interruptor(), d)
        self.assertEqual(lib_estado.activo(), lib_estado.PRUEBA, "una huella que no cuadra nunca enciende real")


class Cliente(unittest.TestCase):
    def test_firma_hmac_y_lista_blanca(self):
        visto = {}

        def pedir(metodo, url, cabeceras, cuerpo):
            visto.update(metodo=metodo, url=url, cabeceras=cabeceras, cuerpo=cuerpo)
            return 200, b"{}"
        c = bp.Privada(LLAVE, SECRETO, pedir=pedir, reloj=lambda: 1000)
        c.cuenta()
        consulta = visto["url"].split("?", 1)[1]
        datos, firma = consulta.rsplit("&signature=", 1)
        self.assertEqual(firma, hmac.new(SECRETO.encode(), datos.encode(), hashlib.sha256).hexdigest())
        self.assertEqual(visto["cabeceras"]["X-MBX-APIKEY"], LLAVE)
        self.assertTrue(visto["url"].startswith("https://api.binance.com/api/v3/account?"))
        with self.assertRaises(ValueError):
            c.llamar("POST", "/sapi/v1/capital/withdraw/apply", {"coin": "USDT"})
        self.assertNotIn(SECRETO, repr(c))

    def test_un_post_va_en_el_cuerpo_y_no_en_la_url(self):
        visto = {}

        def pedir(metodo, url, cabeceras, cuerpo):
            visto.update(url=url, cuerpo=cuerpo)
            return 200, b"{}"
        bp.Privada(LLAVE, SECRETO, pedir=pedir, reloj=lambda: 1000).comprar_limite("BTCFDUSD", "0.001", "1", "pil-r-x")
        self.assertNotIn("?", visto["url"])
        self.assertIn(b"LIMIT_MAKER", visto["cuerpo"])

    def test_errores_de_binance_viajan_como_codigo(self):
        c = bp.Privada(LLAVE, SECRETO, pedir=lambda *a: (400, b'{"code":-2010,"msg":"x"}'), reloj=lambda: 1)
        with self.assertRaises(bp.ErrorBinance) as e:
            c.cuenta()
        self.assertEqual(e.exception.codigo, -2010)
        c = bp.Privada(LLAVE, SECRETO, pedir=lambda *a: (503, b"{}"), reloj=lambda: 1)
        with self.assertRaises(bp.SinRed):
            c.cuenta()

    def test_numeros_como_los_pide_binance(self):
        self.assertEqual(bp.texto(0.00014, 0.00001), "0.00014")
        self.assertEqual(bp.texto(94830.0, 0.01), "94830.00")
        self.assertEqual(bp.texto(12, 1), "12")


class Llavero(unittest.TestCase):
    def test_el_secreto_nunca_va_como_argumento(self):
        vistos = []

        def correr(args, entrada=None):
            vistos.append((args, entrada))

            class R:
                returncode = 0
                stdout = LLAVE if args[-2:] == [lib_llavero.CUENTA_LLAVE, "-w"] else SECRETO
            return R()
        antes, lib_llavero.correr = lib_llavero.correr, correr
        disp, lib_llavero.disponible = lib_llavero.disponible, lambda: True
        try:
            lib_llavero.guardar(LLAVE, SECRETO)
        finally:
            lib_llavero.correr, lib_llavero.disponible = antes, disp
        for args, _ in vistos:
            self.assertNotIn(SECRETO, " ".join(args))
        self.assertIn(SECRETO, vistos[0][1], "el secreto va por la entrada estándar de `security -i`")

    def test_solo_letras_y_numeros(self):
        self.assertFalse(lib_llavero.valida("abc; rm -rf ~" + "a" * 40))
        self.assertTrue(lib_llavero.valida(LLAVE))
        self.assertEqual(lib_llavero.pista(LLAVE), "AAAA…AAAA")


class Conector(Base):
    def test_sin_real_encendido_no_pone_nada(self):
        b = BinanceFalso()
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        self.assertEqual(r["motivo"], "sin_ambiente")
        self.assertEqual(b.llamadas, [])

    def test_entra_con_limit_maker_y_convierte_solo_lo_que_falta(self):
        self.en_real()
        b = BinanceFalso()
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        self.assertTrue(r["puesta"], r)
        tipos = [x[0] for x in b.llamadas]
        self.assertEqual(tipos, ["convertir", "comprar"])
        self.assertTrue(b.llamadas[1][4].startswith("pil-r-BTCFDUSD-"), "el id lleva el prefijo y la r de real")
        self.assertLessEqual(float(b.llamadas[0][2]), r["posicion"]["monto"] * 1.01)
        self.assertEqual(self.cuerpo()["posiciones"][0]["estado"], "puesta")

    def test_sin_saldo_en_binance_no_compra(self):
        self.en_real()
        b = BinanceFalso(usdt=1.0)
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        self.assertEqual(r["motivo"], "sin_saldo")
        self.assertNotIn("comprar", [x[0] for x in b.llamadas])

    def test_llenada_queda_protegida_y_cierra_con_el_resultado_de_verdad(self):
        self.en_real()
        b = BinanceFalso()
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"])
        e = real.revisar(AHORA + 60_000, cliente=b)
        self.assertEqual(e["protegidas"], 1, "llenada → protegida en la misma revisión")
        p = self.cuerpo()["posiciones"][0]
        b.cerrar_lista(p["proteccion_id"], "o")
        saldo_antes = self.cuerpo()["saldo"]
        e = real.revisar(AHORA + HORA, cliente=b)
        self.assertEqual(e["abiertas"] + e["puestas"], 0)
        self.assertGreater(self.cuerpo()["saldo"], saldo_antes, "por el objetivo, el saldo sube")
        self.assertEqual(self.cuerpo()["operaciones"], 1)
        self.assertEqual(self.razones()[-1], "objetivo")

    def test_si_binance_no_acepta_la_proteccion_vende_al_tiro(self):
        self.en_real()
        b = BinanceFalso()
        b.rechazar_oco = True
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"])
        e = real.revisar(AHORA + 60_000, cliente=b)
        self.assertIn("vender", [x[0] for x in b.llamadas])
        self.assertEqual(e["abiertas"], 0, "nada queda abierto sin protección")
        self.assertIn("proteccion_sin_confirmar", self.razones(), "y queda en el registro que no se borra")
        self.assertAlmostEqual(b.saldos["BTC"], 0.0, places=8)

    def test_nunca_vende_monedas_que_no_compro(self):
        self.en_real()
        b = BinanceFalso(btc=1.0)          # la persona ya tenía 1 BTC suyo
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"])
        real.revisar(AHORA + 60_000, cliente=b)
        protegido = float([x for x in b.llamadas if x[0] == "proteger"][0][2])
        self.assertAlmostEqual(protegido, r["posicion"]["cantidad"], places=8)
        real.cerrar(None, AHORA + HORA, cliente=b)
        self.assertAlmostEqual(b.saldos["BTC"], 1.0, places=8, msg="el BTC de la persona sigue ahí")

    def test_vencida_sin_llenar_se_cancela_y_no_mueve_el_saldo(self):
        self.en_real()
        b = BinanceFalso()
        real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        saldo = self.cuerpo()["saldo"]
        real.revisar(AHORA + 4 * HORA, cliente=b)
        self.assertIn("cancelar", [x[0] for x in b.llamadas])
        self.assertEqual(self.cuerpo()["posiciones"], [])
        self.assertEqual(self.cuerpo()["saldo"], saldo)

    def test_vencida_a_medias_protege_lo_comprado(self):
        self.en_real()
        b = BinanceFalso()
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"], 0.5)
        real.revisar(AHORA + 4 * HORA, cliente=b)
        tipos = [x[0] for x in b.llamadas]
        self.assertIn("cancelar", tipos)
        self.assertIn("proteger", tipos)

    def test_lo_ajeno_no_se_toca_y_lo_propio_huerfano_se_cancela(self):
        self.en_real()
        b = BinanceFalso()
        b.ajenas = [{"clientOrderId": "mia-de-la-persona", "symbol": "BTCFDUSD", "status": "NEW", "orderListId": -1}]
        b.comprar_limite("BTCFDUSD", "0.0001", "90000", "pil-r-BTCFDUSD-1-entrada")   # quedó sin guardar
        real.revisar(AHORA, cliente=b)
        canceladas = [x[1] for x in b.llamadas if x[0] == "cancelar"]
        self.assertEqual(canceladas, ["pil-r-BTCFDUSD-1-entrada"])

    def test_sin_conexion_no_inventa_nada(self):
        self.en_real()
        b = BinanceFalso()
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)

        class Caido(BinanceFalso):
            def sincronizar(self):
                raise bp.SinRed("red")
        e = real.revisar(AHORA + 60_000, cliente=Caido())
        self.assertIn("sin_conexion", [m["codigo"] for m in e["motivos"]])
        self.assertEqual(self.cuerpo()["posiciones"][0]["id"], r["posicion"]["id"])

    def test_cerrar_todo_cancela_la_proteccion_y_vende(self):
        self.en_real()
        b = BinanceFalso()
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"])
        real.revisar(AHORA + 60_000, cliente=b)
        c = real.cerrar(None, AHORA + HORA, cliente=b)
        self.assertEqual(c["cerradas"], 1)
        tipos = [x[0] for x in b.llamadas]
        self.assertLess(tipos.index("cancelar_proteccion"), tipos.index("vender"))
        self.assertEqual(self.cuerpo()["posiciones"], [])


class PasoAReal(Base):
    def test_requisitos_parten_en_rojo_y_no_se_activa(self):
        r = lib_real.activar(100, lib_real.FRASE, AHORA)
        self.assertFalse(r["hecho"])
        self.assertEqual(r["motivo"], "requisitos")
        self.assertEqual(lib_estado.activo(), lib_estado.PRUEBA)

    def test_una_llave_que_puede_retirar_no_se_acepta(self):
        class Retira(BinanceFalso):
            def permisos(self):
                return {**super().permisos(), "enableWithdrawals": True}
        r = lib_real.conectar(LLAVE, SECRETO, AHORA, cliente=Retira())
        self.assertFalse(r["hecho"])
        self.assertEqual(r["motivo"], "puede_retirar")

    def test_una_llave_sin_ip_no_cumple(self):
        class SinIp(BinanceFalso):
            def permisos(self):
                return {**super().permisos(), "ipRestrict": False}
        lib_real.conectar(LLAVE, SECRETO, AHORA, cliente=SinIp())
        llave = [x for x in lib_real.requisitos(AHORA, simulacion={"listo": True}) if x["id"] == "llave"][0]
        self.assertFalse(llave["cumple"])
        self.assertFalse(llave["ip"])

    def test_la_conexion_no_guarda_la_llave(self):
        lib_real.conectar(LLAVE, SECRETO, AHORA, cliente=BinanceFalso())
        with open(lib_real.ruta_conexion(), encoding="utf-8") as f:
            texto = f.read()
        self.assertNotIn(LLAVE, texto)
        self.assertNotIn(SECRETO, texto)

    def test_con_todo_en_verde_pide_la_frase_y_un_presupuesto_que_cabe(self):
        lib_real.conectar(LLAVE, SECRETO, AHORA, cliente=BinanceFalso(usdt=300))
        cuerpo = lib_estado.nuevo(lib_estado.PRUEBA, 200, ahora_ms=AHORA - 8 * lib_datos.DIA_MS)
        lib_estado.guardar(lib_estado.PRUEBA, {**cuerpo, "operaciones": 6})
        import simular
        nucleo.escribir_json(simular.ruta(), {"formato": 1, "listo": True, "monto": 100})
        self.assertTrue(all(x["cumple"] for x in lib_real.requisitos(AHORA)), lib_real.requisitos(AHORA))
        self.assertEqual(lib_real.activar(100, "operar", AHORA)["motivo"], "frase")
        self.assertEqual(lib_real.activar(10_000, lib_real.FRASE, AHORA)["motivo"], "presupuesto")
        self.assertTrue(lib_real.activar(100, lib_real.FRASE.lower(), AHORA)["hecho"])
        self.assertEqual(lib_estado.activo(), lib_estado.REAL)
        self.assertEqual(self.cuerpo()["saldo"], 100)

    def test_no_se_apaga_con_posiciones_y_la_emergencia_cierra_y_apaga(self):
        self.en_real()
        b = BinanceFalso()
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"])
        real.revisar(AHORA + 60_000, cliente=b)
        self.assertEqual(lib_real.desactivar(AHORA)["motivo"], "con_posiciones")
        self.assertTrue(lib_real.emergencia(AHORA + HORA, cliente=b)["hecho"])
        self.assertEqual(lib_estado.activo(), lib_estado.PRUEBA)


if __name__ == "__main__":
    unittest.main()
