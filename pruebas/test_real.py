"""Pruebas del conector real y del paso a real, con un Binance falso en memoria.

Ninguna prueba sale a la red ni toca el llavero de verdad: el cliente de Binance es `BinanceFalso` y la llave es
inventada. Los precios son redondos a propósito.
"""
import hashlib
import hmac
import json
import os
import re
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


ID_BINANCE = re.compile(r"^[\.A-Z\:/a-z0-9_-]{1,36}$")


class BinanceFalso:
    """Lo mínimo de Binance para el conector: saldos, órdenes por id propio, protecciones y llenados con comisión.

    Revisa los ids como Binance (`ID_BINANCE`), rechaza un id repetido entre las órdenes abiertas y puede «cortar la red»
    justo **después** de ejecutar un pedido (`cortar_despues`), que es el caso difícil: Binance lo hizo y nadie se enteró."""

    def __init__(self, usdt=500.0, fdusd=0.0, btc=0.0, comision_base=0.0):
        self.saldos = {"USDT": usdt, "FDUSD": fdusd, "BTC": btc, "ETH": 0.0}
        self.ordenes, self.listas, self.llamadas, self.ajenas = {}, {}, [], []
        self.rechazar_oco = False
        self.comision_base = comision_base          # la comisión de la compra, cobrada en BTC (sin BNB)
        self.cortar_despues = set()                 # nombres de pedidos que «se cortan» después de hacerse
        self.permisos_extra = {}
        self.siguiente = 1

    def _id(self, cid):
        assert ID_BINANCE.match(cid), f"Binance no acepta este id: {cid!r} ({len(cid)} caracteres)"
        viva = self.ordenes.get(cid)
        if viva and viva["status"] in ("NEW", "PARTIALLY_FILLED"):
            raise bp.ErrorBinance(-2010, 400, "/api/v3/order")      # id repetido entre las abiertas
        return cid

    def _corte(self, que):
        if que in self.cortar_despues:
            self.cortar_despues.discard(que)
            raise bp.SinRed("timeout")

    def _orden(self, cid, par, precio, cantidad, lista=-1):
        self.siguiente += 1
        self.ordenes[cid] = {"clientOrderId": cid, "orderId": self.siguiente, "symbol": par, "status": "NEW",
                             "executedQty": "0", "cummulativeQuoteQty": "0", "price": precio, "origQty": cantidad,
                             "orderListId": lista, "llenos": []}
        return self.ordenes[cid]

    def sincronizar(self):
        return 0

    def cuenta(self):
        return {"canTrade": True, "balances": [{"asset": a, "free": str(v), "locked": "0"}
                                               for a, v in self.saldos.items()]}

    def permisos(self):
        return {"enableReading": True, "enableSpotAndMarginTrading": True, "enableWithdrawals": False,
                "ipRestrict": True, **self.permisos_extra}

    def comprar_con(self, par, monto, cid):
        self._id(cid)
        self.llamadas.append(("convertir", par, monto, cid))
        m = float(monto)
        self.saldos["USDT"] -= m
        self.saldos["FDUSD"] += m * 0.9995
        return {"status": "FILLED"}

    def comprar_limite(self, par, cantidad, precio, cid):
        self._id(cid)
        self.llamadas.append(("comprar", par, cantidad, precio, cid))
        o = self._orden(cid, par, precio, cantidad)
        self._corte("comprar")
        return o

    def llenar(self, cid, fraccion=1.0, sin_llenados=False):
        o = self.ordenes[cid]
        q = float(o["origQty"]) * fraccion
        comision = q * self.comision_base
        o.update(status="FILLED" if fraccion >= 1 else "PARTIALLY_FILLED", executedQty=str(q),
                 cummulativeQuoteQty=str(q * float(o["price"])))
        o["llenos"] = [] if sin_llenados else [{"qty": str(q), "quoteQty": str(q * float(o["price"])),
                                                "commission": str(comision), "commissionAsset": "BTC"}]
        self.saldos["BTC"] += q - comision
        self.saldos["FDUSD"] -= q * float(o["price"])

    def llenados(self, par, orden_id):
        return next((o["llenos"] for o in self.ordenes.values() if o["orderId"] == orden_id), [])

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

    def proteger(self, par, cantidad, objetivo, stop, lista, id_objetivo, id_stop):
        for cid in (lista, id_objetivo, id_stop):
            self._id(cid)
        self.llamadas.append(("proteger", par, cantidad, objetivo, stop, lista, id_objetivo, id_stop))
        if self.rechazar_oco:
            raise bp.ErrorBinance(self.rechazar_oco if type(self.rechazar_oco) is int else bp.FILTRO, 400,
                                  "/api/v3/orderList/oco")
        if float(cantidad) > self.saldos["BTC"] + 1e-12:
            raise bp.ErrorBinance(-2010, 400, "/api/v3/orderList/oco")
        for cid, precio in ((id_objetivo, objetivo), (id_stop, stop)):
            self._orden(cid, par, precio, cantidad, lista=1)
        self.listas[lista] = {"listClientOrderId": lista, "listOrderStatus": "EXECUTING",
                              "patas": {"o": id_objetivo, "s": id_stop}}
        self.saldos["BTC"] -= float(cantidad)
        self._corte("proteger")
        return self.listas[lista]

    def proteccion(self, lista):
        if lista not in self.listas:
            raise bp.ErrorBinance(bp.NO_EXISTE_LISTA, 400, "/api/v3/orderList")
        return self.listas[lista]

    def cerrar_lista(self, lista, pata):
        """Una pata de la OCO se llenó; la otra se cancela."""
        for suf in ("o", "s"):
            o = self.ordenes[self.listas[lista]["patas"][suf]]
            if suf == pata:
                q = float(o["origQty"])
                o.update(status="FILLED", executedQty=str(q), cummulativeQuoteQty=str(q * float(o["price"])))
                o["llenos"] = [{"qty": str(q), "quoteQty": str(q * float(o["price"])), "commission": "0",
                                "commissionAsset": "FDUSD"}]
                self.saldos["FDUSD"] += q * float(o["price"])
            else:
                o["status"] = "CANCELED"
        self.listas[lista]["listOrderStatus"] = "ALL_DONE"

    def cancelar_proteccion(self, par, lista):
        self.llamadas.append(("cancelar_proteccion", lista))
        if lista not in self.listas or self.listas[lista]["listOrderStatus"] != "EXECUTING":
            raise bp.ErrorBinance(bp.NO_EXISTE_LISTA, 400, "/api/v3/orderList")
        for suf in ("o", "s"):
            o = self.ordenes[self.listas[lista]["patas"][suf]]
            if o["status"] == "NEW":
                o["status"] = "CANCELED"
                self.saldos["BTC"] += float(o["origQty"]) if suf == "s" else 0.0
        self.listas[lista]["listOrderStatus"] = "ALL_DONE"

    def vender_mercado(self, par, cantidad, cid):
        self._id(cid)
        self.llamadas.append(("vender", par, cantidad, cid))
        q = float(cantidad)
        assert q <= self.saldos["BTC"] + 1e-12, "no se puede vender lo que no hay"
        self.saldos["BTC"] -= q
        self.saldos["FDUSD"] += q * 99_500.0
        o = self._orden(cid, par, "99500", cantidad)
        o.update(status="FILLED", executedQty=str(q), cummulativeQuoteQty=str(q * 99_500.0),
                 llenos=[{"qty": str(q), "quoteQty": str(q * 99_500.0), "commission": "0", "commissionAsset": "FDUSD"}])
        self._corte("vender")
        return o


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
        self.assertTrue(b.llamadas[1][4].startswith("pil-r-B"), "el id lleva el prefijo y la r de real")
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


class Cortes(Base):
    """Lo que pasa cuando la red se corta justo después de que Binance hizo algo: nunca se repite una compra o una venta."""

    def test_todos_los_ids_caben_en_binance(self):
        for par in real.LETRA_PAR:
            for estrategia in real.LETRA_ESTRATEGIA:
                base = real.base_de({"par": par, "estrategia": estrategia, "vela": 9_999_999_999_999})
                for cid in real.ids(base).values():
                    self.assertRegex(cid, ID_BINANCE)
                    self.assertLessEqual(len(cid), real.LARGO_MAXIMO_ID)
                    self.assertTrue(cid.startswith("pil-"))

    def test_la_misma_oportunidad_da_los_mismos_ids(self):
        self.assertEqual(real.base_de(OPCION), real.base_de({**OPCION}))
        self.assertNotEqual(real.base_de(OPCION), real.base_de({**OPCION, "vela": OPCION["vela"] + HORA}))

    def test_corte_al_comprar_no_compra_dos_veces(self):
        self.en_real()
        b = BinanceFalso()
        b.cortar_despues.add("comprar")
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        self.assertEqual(r["motivo"], "sin_confirmar")
        self.assertEqual(self.cuerpo()["posiciones"][0]["fase"], "enviando", "quedó guardada antes de mandarla")
        r2 = real.entrar(OPCION, AHORA + 1000, frenos=PUEDE, calibracion={}, cliente=b)
        self.assertEqual(r2["motivo"], "repetida")
        self.assertEqual([x[0] for x in b.llamadas].count("comprar"), 1)
        real.revisar(AHORA + 60_000, cliente=b)
        self.assertEqual(self.cuerpo()["posiciones"][0]["fase"], "", "la revisión la encontró por su id")

    def test_corte_al_comprar_y_no_llego_se_olvida(self):
        self.en_real()
        b = BinanceFalso()
        b.cortar_despues.add("comprar")
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        del b.ordenes[r["posicion"]["id"]]              # Binance nunca la recibió
        real.revisar(AHORA + real.ESPERA_ENVIO_MS + 60_000, cliente=b)
        self.assertEqual(self.cuerpo()["posiciones"], [])

    def test_corte_al_proteger_no_vende_ni_protege_dos_veces(self):
        self.en_real()
        b = BinanceFalso()
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"])
        b.cortar_despues.add("proteger")
        real.revisar(AHORA + 60_000, cliente=b)
        self.assertEqual(self.cuerpo()["posiciones"][0]["fase"], "protegiendo")
        e = real.revisar(AHORA + 120_000, cliente=b)
        tipos = [x[0] for x in b.llamadas]
        self.assertEqual(tipos.count("proteger"), 1)
        self.assertNotIn("vender", tipos)
        self.assertEqual(e["protegidas"], 1)

    def test_corte_al_vender_no_vende_dos_veces(self):
        self.en_real()
        b = BinanceFalso(btc=1.0)
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"])
        real.revisar(AHORA + 60_000, cliente=b)
        b.cortar_despues.add("vender")
        real.cerrar(None, AHORA + HORA, cliente=b)
        self.assertEqual(self.cuerpo()["posiciones"][0]["fase"], "vendiendo")
        real.revisar(AHORA + 2 * HORA, cliente=b)
        self.assertEqual([x[0] for x in b.llamadas].count("vender"), 1)
        self.assertEqual(self.cuerpo()["posiciones"], [])
        self.assertAlmostEqual(b.saldos["BTC"], 1.0, places=8, msg="el BTC de la persona sigue ahí")


class Casos(Base):
    def test_llenada_en_parte_se_protege_en_la_misma_vuelta(self):
        self.en_real()
        b = BinanceFalso()
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"], 0.5)
        e = real.revisar(AHORA + 60_000, cliente=b)          # todavía no vence
        tipos = [x[0] for x in b.llamadas]
        self.assertIn("cancelar", tipos)
        self.assertIn("proteger", tipos)
        self.assertEqual(e["protegidas"], 1)

    def test_la_comision_en_btc_no_se_toma_de_lo_ajeno(self):
        self.en_real()
        b = BinanceFalso(btc=1.0, comision_base=0.001)
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"])
        real.revisar(AHORA + 60_000, cliente=b)
        protegido = float([x for x in b.llamadas if x[0] == "proteger"][0][2])
        self.assertLessEqual(protegido, r["posicion"]["cantidad"] * (1 - 0.001) + 1e-12)
        real.cerrar(None, AHORA + HORA, cliente=b)
        self.assertGreaterEqual(b.saldos["BTC"], 1.0 - 1e-9, "el BTC de la persona sigue ahí")

    def test_una_llave_que_ahora_puede_retirar_no_opera(self):
        self.en_real()
        b = BinanceFalso()
        b.permisos_extra = {"enableWithdrawals": True}
        nucleo.escribir_json(real.ruta_conexion(), {"ok": True, "cuando_ms": AHORA - 2 * real.REVISAR_LLAVE_MS})
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        self.assertEqual(r["motivo"], "llave_insegura")
        self.assertNotIn("comprar", [x[0] for x in b.llamadas])

    def test_una_llave_que_puede_transferir_tampoco(self):
        class Transfiere(BinanceFalso):
            def permisos(self):
                return {**super().permisos(), "permitsUniversalTransfer": True}
        r = lib_real.conectar(LLAVE, SECRETO, AHORA, cliente=Transfiere())
        self.assertEqual(r["motivo"], "puede_retirar")

    def test_con_real_encendido_no_se_cambia_la_llave(self):
        self.en_real()
        self.assertEqual(lib_real.conectar(LLAVE, SECRETO, AHORA, cliente=BinanceFalso())["motivo"], "activo")

    def test_sin_conexion_al_conectar_no_se_guarda_nada(self):
        class Caido(BinanceFalso):
            def sincronizar(self):
                raise bp.SinRed("red")
        r = lib_real.conectar(LLAVE, SECRETO, AHORA, cliente=Caido())
        self.assertFalse(r["hecho"])
        self.assertEqual(r["motivo"], "sin_conexion")

    def test_rechazada_la_proteccion_despues_se_vende(self):
        self.en_real()
        b = BinanceFalso()
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"])
        real.revisar(AHORA + 60_000, cliente=b)
        lista = self.cuerpo()["posiciones"][0]["proteccion_id"]
        b.cancelar_proteccion("BTCFDUSD", lista)          # alguien la canceló desde Binance
        real.revisar(AHORA + HORA, cliente=b)
        self.assertIn("vender", [x[0] for x in b.llamadas])
        self.assertEqual(self.cuerpo()["posiciones"], [])

    def test_el_candado_no_deja_tocar_la_cuenta_a_dos_a_la_vez(self):
        self.en_real()
        import fcntl
        antes, real.ESPERA_CANDADO = real.ESPERA_CANDADO, 0.3
        otro = os.open(os.path.join(lib_estado.carpeta(), "real.candado"), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(otro, fcntl.LOCK_EX)                 # «otro proceso» (el motor) tiene la cuenta
            r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=BinanceFalso())
            e = real.revisar(AHORA, cliente=BinanceFalso())
        finally:
            fcntl.flock(otro, fcntl.LOCK_UN)
            os.close(otro)
            real.ESPERA_CANDADO = antes
        self.assertEqual(r["motivo"], "ocupado")
        self.assertIn("ocupado", [m["codigo"] for m in e["motivos"]])

    def test_una_propuesta_de_prueba_no_se_ejecuta_en_real(self):
        import lib_modos
        o = {**OPCION, "vela": OPCION["vela"], "tamano": {"precio": 100_000.0, "stop": 99_000.0, "monto": 14.0}}
        d, prop = lib_modos.proponer(o, AHORA)
        lib_modos.guardar(d)
        self.assertEqual(prop["ambiente"], lib_estado.PRUEBA)
        self.en_real()
        r = lib_modos.responder(prop["id"], True, AHORA + 1000)
        self.assertFalse(r["hecho"])
        self.assertEqual(r["motivo"], lib_modos.CAMBIO_AMBIENTE)


class SegundaRonda(Base):
    def test_las_patas_se_buscan_con_los_mismos_ids_que_se_mandan(self):
        self.en_real()
        b = BinanceFalso(btc=1.0)
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"])
        real.revisar(AHORA + 60_000, cliente=b)
        i = real.ids(self.cuerpo()["posiciones"][0]["base"])
        llamada = [x for x in b.llamadas if x[0] == "proteger"][0]
        self.assertEqual(llamada[5:], (i["proteccion"], i["objetivo"], i["stop"]))
        b.cerrar_lista(i["proteccion"], "o")
        saldo = self.cuerpo()["saldo"]
        real.revisar(AHORA + HORA, cliente=b)
        self.assertNotIn("vender", [x[0] for x in b.llamadas], "si la protección vendió, no se vende de nuevo")
        self.assertGreater(self.cuerpo()["saldo"], saldo, "y se anota la ganancia de verdad")
        self.assertAlmostEqual(b.saldos["BTC"], 1.0, places=8, msg="el BTC de la persona sigue ahí")
        self.assertEqual(self.razones()[-1], "objetivo")

    def test_un_error_que_no_se_entiende_no_vende(self):
        self.en_real()
        b = BinanceFalso(btc=1.0)
        b.rechazar_oco = -1003                       # un error cualquiera, que no es de filtros
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"])
        e = real.revisar(AHORA + 60_000, cliente=b)
        self.assertNotIn("vender", [x[0] for x in b.llamadas])
        self.assertEqual(self.cuerpo()["posiciones"][0]["fase"], "protegiendo", "se reintenta en la próxima vuelta")
        self.assertIn("binance", [m["codigo"] for m in e["motivos"]])
        b.rechazar_oco = False
        e = real.revisar(AHORA + 120_000, cliente=b)
        self.assertEqual(e["protegidas"], 1)

    def test_un_llenado_bajo_los_minimos_queda_como_polvo_y_no_se_atasca(self):
        self.en_real()
        b = BinanceFalso()
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"], 0.0001 / r["posicion"]["cantidad"] * 0.00001 / 0.0001)   # 0,00001 BTC: ~1 USDT
        real.revisar(AHORA + 60_000, cliente=b)
        self.assertNotIn("vender", [x[0] for x in b.llamadas])
        self.assertEqual(self.cuerpo()["posiciones"], [], "no queda atascada")

    def test_sin_los_llenados_a_la_vista_protege_de_menos_nunca_de_mas(self):
        self.en_real()
        b = BinanceFalso(btc=1.0)
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        b.llenar(r["posicion"]["id"], sin_llenados=True)
        real.revisar(AHORA + 60_000, cliente=b)
        protegido = float([x for x in b.llamadas if x[0] == "proteger"][0][2])
        self.assertLessEqual(protegido, r["posicion"]["cantidad"] * (1 - real.COMISION_SUPUESTA) + 1e-12)

    def test_no_se_apaga_con_ordenes_propias_abiertas_en_binance(self):
        self.en_real()
        b = BinanceFalso()
        b.comprar_limite("BTCFDUSD", "0.0001", "90000", "pil-r-BV1-e")       # una orden propia que el estado no conoce
        self.assertEqual(lib_real.desactivar(AHORA, cliente=b)["motivo"], "con_ordenes")
        self.assertEqual(lib_estado.activo(), lib_estado.REAL)

    def test_la_emergencia_cancela_lo_propio_aunque_el_estado_no_lo_conozca(self):
        self.en_real()
        b = BinanceFalso()
        b.comprar_limite("BTCFDUSD", "0.0001", "90000", "pil-r-BV1-e")
        self.assertTrue(lib_real.emergencia(AHORA, cliente=b)["hecho"])
        self.assertEqual(b.ordenes["pil-r-BV1-e"]["status"], "CANCELED")
        self.assertEqual(lib_estado.activo(), lib_estado.PRUEBA)

    def test_con_el_estado_frenado_igual_cancela_las_entradas_propias(self):
        self.en_real()
        b = BinanceFalso()
        b.comprar_limite("BTCFDUSD", "0.0001", "90000", "pil-r-BV1-e")
        os.remove(lib_estado.ruta(lib_estado.REAL))                         # el estado se perdió
        real.revisar(AHORA, cliente=b)
        self.assertEqual(b.ordenes["pil-r-BV1-e"]["status"], "CANCELED")

    def test_una_orden_mandada_con_corte_se_espera_antes_de_olvidarla(self):
        self.en_real()
        b = BinanceFalso()
        b.cortar_despues.add("comprar")
        r = real.entrar(OPCION, AHORA, frenos=PUEDE, calibracion={}, cliente=b)
        orden = b.ordenes.pop(r["posicion"]["id"])                           # Binance todavía no la muestra
        real.revisar(AHORA + 60_000, cliente=b)
        self.assertEqual(len(self.cuerpo()["posiciones"]), 1, "todavía se espera")
        b.ordenes[orden["clientOrderId"]] = orden                            # aparece tarde
        b.llenar(orden["clientOrderId"])
        e = real.revisar(AHORA + 120_000, cliente=b)
        self.assertEqual(e["protegidas"], 1)


if __name__ == "__main__":
    unittest.main()
