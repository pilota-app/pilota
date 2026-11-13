"""Pruebas de lo propio de Pilota en Python. Cada una corre con una carpeta temporal: nunca toca datos reales.

Ninguna prueba sale a la red: la API de Binance se reemplaza por una de juguete (`ApiFalsa`) con velas inventadas. Los datos
ficticios son de Ana Pérez y Matías Soto.
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "bin"))

import backtest  # noqa: E402
import estado as accion_estado  # noqa: E402  (el módulo se llama igual que varias funciones «estado»)
import frenos  # noqa: E402
import historial  # noqa: E402
import indicadores  # noqa: E402
import lib_calibracion  # noqa: E402
import lib_costos  # noqa: E402
import lib_datos  # noqa: E402  (después de sys.path: bin/ no es un paquete instalado)
import lib_estado  # noqa: E402
import lib_estrategias  # noqa: E402
import lib_frenos  # noqa: E402
import lib_indicadores  # noqa: E402
import lib_indicadores_mercado  # noqa: E402
import lib_puntaje  # noqa: E402
import lib_registro  # noqa: E402
import lib_resolucion  # noqa: E402
import lib_tamano  # noqa: E402
import lib_trabajo  # noqa: E402
import minimo_viable  # noqa: E402
import muestreo  # noqa: E402
import nucleo  # noqa: E402
import puntaje  # noqa: E402
import senales  # noqa: E402
import tamano  # noqa: E402

#: Un lunes cualquiera a las 14:05 UTC, para que las cuentas no dependan de cuándo se corren las pruebas.
AHORA = 1_770_732_300_000
#: Los filtros que devuelve la API de juguete: el mismo orden de magnitud que los de verdad, pero inventados.
FILTROS = {"BTCFDUSD": {"tick": "0.01", "paso": "0.00001", "cantidad": "0.00001", "nocional": "5.00"},
           "ETHFDUSD": {"tick": "0.01", "paso": "0.0001", "cantidad": "0.0001", "nocional": "5.00"}}


def velas_que_suben(n, temporalidad, hasta_ms=AHORA, desde=100.0, sube=1.0):
    """Velas ficticias que suben (o bajan) parejo, la última cerrada justo antes de `hasta_ms`. Con una serie así los
    indicadores dan valores que se saben de memoria: las medias son exactas, el RSI es 100 y el ADX también."""
    paso = lib_datos.PASO_MS[temporalidad]
    fin = (hasta_ms // paso) * paso
    return [[fin - (n - i) * paso, desde + sube * i - 0.5, desde + sube * i + 1, desde + sube * i - 1,
             desde + sube * i, 10.0] for i in range(n)]


def velas_que_van_y_vienen(n, temporalidad, hasta_ms=AHORA, desde=100.0, mueve=2.0):
    """Velas ficticias que suben y bajan sin ir a ninguna parte: con una serie así el ADX queda cerca de cero y las bandas
    de Bollinger se quedan quietas, que es lo que mira la estrategia de rebote."""
    paso = lib_datos.PASO_MS[temporalidad]
    fin = (hasta_ms // paso) * paso
    filas = []
    for i in range(n):
        base = desde + (mueve if i % 2 else 0.0)
        filas.append([fin - (n - i) * paso, base, base + 0.5, base - 0.5, base, 10.0])
    return filas


def muestra_guardada(ms=AHORA, compra=95000.1, venta=95000.4):
    """La última muestra del libro en el plan del muestreo, como la deja `muestreo.py`. Precios inventados."""
    medio = (venta + compra) / 2
    pares = [{"par": p, "compra": compra, "compra_cantidad": 0.5, "venta": venta, "venta_cantidad": 0.3,
              "spread": round(venta - compra, 8), "spread_relativo": (venta - compra) / medio, "trades": 20,
              "ultimo": venta} for p in lib_datos.PARES_OPERADOS]
    return lib_trabajo.guardar_plan("muestreo", {"formato": 1,
                                                 "ultima": {"cuando": lib_datos.iso(ms), "ms": ms, "pares": pares}})


def correr(script, *args, entrada=None, datos=None):
    """Corre bin/<script> como lo corre el host: lo de la persona en un archivo de entrada y el último argumento es la salida."""
    with tempfile.TemporaryDirectory() as tmp:
        archivos = []
        if entrada is not None:
            ruta = os.path.join(tmp, "entrada.json")
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(entrada, f)
            archivos.append(ruta)
        salida = os.path.join(tmp, "salida.json")
        entorno = {**os.environ, "HOME": tmp, "PILOTA_DATOS": datos or os.path.join(tmp, "datos")}
        r = subprocess.run([sys.executable, os.path.join(RAIZ, "bin", script), *args, *archivos, salida],
                           capture_output=True, text=True, timeout=60, env=entorno)
        if r.returncode != 0:
            raise AssertionError(r.stderr)
        with open(salida, encoding="utf-8") as f:
            return json.load(f)


class Detencion:
    """«Detener» después de unas páginas: lo que haría la persona a la mitad de una descarga larga."""

    def __init__(self, paginas):
        self.quedan = paginas

    def detenido(self):
        if self.quedan <= 0:
            return True
        self.quedan -= 1
        return False


class ApiFalsa:
    """La API pública de Binance, de juguete: velas inventadas y, si se le pide, un «espera» como el 429 de verdad."""

    def __init__(self, ahora_ms=AHORA, pide_esperar=0, siempre=None, proteccion=True, estado_par="TRADING", listado=0):
        self.ahora = ahora_ms
        self.pide_esperar = pide_esperar
        self.siempre = siempre          # una excepción para responder siempre lo mismo (red cortada, respuesta rara)
        self.proteccion = proteccion    # si los pares aceptan protección automática (OCO)
        self.estado_par = estado_par
        self.listado = listado          # la primera vela que existe: un par más nuevo que la ventana que se pide
        self.pedidos = []
        self.dormido = []

    def simbolo(self, par):
        f = FILTROS[par]
        return {"symbol": par, "baseAsset": par[:3], "quoteAsset": par[3:], "status": self.estado_par,
                "ocoAllowed": self.proteccion,
                "filters": [{"filterType": "PRICE_FILTER", "tickSize": f["tick"], "minPrice": f["tick"]},
                            {"filterType": "LOT_SIZE", "stepSize": f["paso"], "minQty": f["cantidad"], "maxQty": "9000"},
                            {"filterType": "NOTIONAL", "minNotional": f["nocional"]}]}

    def __call__(self, ruta, parametros=None):
        self.pedidos.append((ruta, parametros))
        if self.siempre:
            raise self.siempre
        if self.pide_esperar:
            self.pide_esperar -= 1
            raise lib_datos.Limitado(3)
        if ruta == "/api/v3/time":
            return {"serverTime": self.ahora}
        if ruta == "/api/v3/exchangeInfo":
            return {"symbols": [self.simbolo(p) for p in json.loads(parametros["symbols"])]}
        if ruta == "/api/v3/ticker/bookTicker":
            return {"symbol": parametros["symbol"], "bidPrice": "95000.10", "bidQty": "0.50",
                    "askPrice": "95000.40", "askQty": "0.30"}
        if ruta == "/api/v3/trades":
            return [{"id": 1, "price": "95000.20", "qty": "0.010", "quoteQty": "950.0",
                     "time": self.ahora - 2000, "isBuyerMaker": False, "isBestMatch": True},
                    {"id": 2, "price": "95000.30", "qty": "0.020", "quoteQty": "1900.0",
                     "time": self.ahora - 500, "isBuyerMaker": True, "isBestMatch": True}]
        paso = lib_datos.PASO_MS[parametros["interval"]]
        desde, precio, filas = (max(parametros["startTime"], self.listado) // paso) * paso, 100.0, []
        while desde <= self.ahora and len(filas) < parametros["limit"]:
            filas.append([desde, f"{precio}", f"{precio + 1}", f"{precio - 1}", f"{precio + 0.5}", "12.5",
                          desde + paso - 1, "1250.0", 10, "6.0", "600.0", "0"])
            desde, precio = desde + paso, precio + 0.5
        return filas

    def cliente(self):
        return lib_datos.Binance(pedir=self, dormir=self.dormido.append)


class ApiConHoyo(ApiFalsa):
    """Una vela del medio que no viene en la página: el hoyo que la revisión de continuidad tiene que encontrar. Con
    `veces=1` la segunda vez sí la entrega (una página que llegó incompleta); con `veces=None` Binance no la tiene nunca."""

    def __init__(self, par="BTCFDUSD", temporalidad="1d", atras=3, veces=1, **kw):
        super().__init__(**kw)
        paso = lib_datos.PASO_MS[temporalidad]
        self.par, self.temporalidad, self.veces = par, temporalidad, veces
        self.hoyo = (self.ahora // paso) * paso - atras * paso

    def __call__(self, ruta, parametros=None):
        filas = super().__call__(ruta, parametros)
        if (ruta != "/api/v3/klines" or parametros.get("symbol") != self.par
                or parametros.get("interval") != self.temporalidad):
            return filas
        quedan = [f for f in filas if f[0] != self.hoyo]
        if len(quedan) == len(filas) or (self.veces is not None and self.veces <= 0):
            return filas
        if self.veces is not None:
            self.veces -= 1
        return quedan


class ConCarpeta(unittest.TestCase):
    """Cada prueba con su carpeta de datos: lib_datos escribe donde dice PILOTA_DATOS."""

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


class HablarConBinance(ConCarpeta):
    def test_la_url_solo_puede_ser_de_binance(self):
        self.assertEqual(lib_datos.url_api("/api/v3/klines", {"symbol": "BTCFDUSD", "interval": "1h"}),
                         "https://api.binance.com/api/v3/klines?symbol=BTCFDUSD&interval=1h")
        for ruta in ("https://ejemplo.invalid/api/v3/klines", "/api/v3/order", "/api/v3/klines/../order", ""):
            with self.assertRaises(ValueError):
                lib_datos.url_api(ruta)

    def test_ante_un_limite_espera_lo_que_pide_binance_y_reintenta(self):
        api = ApiFalsa(pide_esperar=1)
        cliente = api.cliente()
        self.assertEqual(cliente.ahora_ms(), AHORA)
        self.assertEqual(cliente.esperas, 1)
        self.assertIn(3, api.dormido)          # los segundos que pidió Binance, no los nuestros

    def test_si_binance_no_contesta_se_rinde_despues_de_varios_intentos(self):
        api = ApiFalsa(siempre=lib_datos.Temporal("sin red"))
        with self.assertRaises(lib_datos.Temporal):
            api.cliente().ahora_ms()
        self.assertEqual(len(api.pedidos), lib_datos.INTENTOS)

    def test_una_vela_que_no_cuadra_no_entra(self):
        paso = lib_datos.PASO_MS["1h"]
        buena = [AHORA // paso * paso, "100", "101", "99", "100.5", "12.5", 0]
        self.assertEqual(lib_datos.vela_de(buena, paso)[0], AHORA // paso * paso)
        for mala in ([buena[0] + 60_000, "100", "101", "99", "100.5", "12.5", 0],   # fuera de hora
                     [buena[0], "100", "99", "101", "100.5", "12.5", 0],            # máximo bajo el mínimo
                     [buena[0], "no", "101", "99", "100.5", "12.5", 0],
                     [buena[0], "100", "101"]):
            with self.assertRaises(lib_datos.Respuesta):
                lib_datos.vela_de(mala, paso)


class VelasGuardadas(ConCarpeta):
    def test_solo_guarda_velas_cerradas(self):
        paso = lib_datos.PASO_MS["1d"]
        fin = AHORA // paso * paso                      # la vela de hoy: todavía abierta
        api = ApiFalsa()
        nuevas = lib_datos.bajar_serie(api.cliente(), "BTCFDUSD", "1d", dias=3, ahora_ms=AHORA)
        self.assertEqual(nuevas, 3)
        self.assertEqual([v[0] for v in lib_datos.leer_serie("BTCFDUSD", "1d")],
                         [fin - 3 * paso, fin - 2 * paso, fin - paso])
        e = lib_datos.estado_serie("BTCFDUSD", "1d", dias=3, ahora_ms=AHORA)
        self.assertEqual((e["estado"], e["motivo"], e["velas"], e["esperadas"]), ("listo", "", 3, 3))

    def test_lo_que_ya_esta_no_se_vuelve_a_pedir(self):
        api = ApiFalsa()
        lib_datos.bajar_serie(api.cliente(), "ETHFDUSD", "1d", dias=3, ahora_ms=AHORA)
        otra = ApiFalsa()
        self.assertEqual(lib_datos.bajar_serie(otra.cliente(), "ETHFDUSD", "1d", dias=3, ahora_ms=AHORA), 0)
        self.assertEqual(otra.pedidos, [])

    def test_un_hueco_se_detecta_y_se_rellena(self):
        paso = lib_datos.PASO_MS["1d"]
        fin = AHORA // paso * paso
        lib_datos.guardar_serie("BTCUSDT", "1d", [[fin - 3 * paso, 100.0, 101.0, 99.0, 100.5, 1.0],
                                                  [fin - paso, 100.0, 101.0, 99.0, 100.5, 1.0]])
        e = lib_datos.estado_serie("BTCUSDT", "1d", dias=3, ahora_ms=AHORA)
        self.assertEqual((e["estado"], e["motivo"], e["cuantas"]), ("incompleto", "huecos", 1))
        self.assertEqual(e["huecos"], [{"desde": fin - 2 * paso, "hasta": fin - 2 * paso, "faltan": 1}])
        self.assertEqual(lib_datos.bajar_serie(ApiFalsa().cliente(), "BTCUSDT", "1d", dias=3, ahora_ms=AHORA), 1)
        self.assertEqual(lib_datos.estado_serie("BTCUSDT", "1d", dias=3, ahora_ms=AHORA)["estado"], "listo")

    def test_una_serie_corta_dice_cuantas_velas_faltan(self):
        paso = lib_datos.PASO_MS["1d"]
        fin = AHORA // paso * paso
        lib_datos.guardar_serie("ETHUSDT", "1d", [[fin - paso, 100.0, 101.0, 99.0, 100.5, 1.0]])
        e = lib_datos.estado_serie("ETHUSDT", "1d", dias=3, ahora_ms=AHORA)
        self.assertEqual((e["estado"], e["motivo"], e["cuantas"]), ("incompleto", "faltan_velas", 2))

    def test_una_serie_atrasada_no_sirve_para_decidir(self):
        paso = lib_datos.PASO_MS["1h"]
        fin = AHORA // paso * paso
        lib_datos.guardar_serie("BTCFDUSD", "1h", [[fin - i * paso, 100.0, 101.0, 99.0, 100.5, 1.0] for i in range(10, 2, -1)])
        e = lib_datos.estado_serie("BTCFDUSD", "1h", dias=1, ahora_ms=AHORA)
        self.assertEqual((e["estado"], e["motivo"], e["cuantas"]), ("incompleto", "atrasado", 2))

    def test_un_archivo_roto_se_ignora_y_se_baja_de_nuevo(self):
        with open(lib_datos.ruta_serie("BTCFDUSD", "4h"), "w", encoding="utf-8") as f:
            f.write('{"formato": 1, "velas": [[1, 2]]}')
        self.assertEqual(lib_datos.leer_serie("BTCFDUSD", "4h"), [])

    def test_no_se_guarda_ninguna_serie_que_no_sea_de_las_nuestras(self):
        for par, temporalidad in (("PEPEUSDT", "1h"), ("BTCFDUSD", "5m"), ("../otra", "1h")):
            with self.assertRaises(ValueError):
                lib_datos.ruta_serie(par, temporalidad)

    def test_si_binance_se_cae_lo_bajado_queda_y_se_dice_el_motivo(self):
        resumen = lib_datos.bajar_todo(ApiFalsa(siempre=lib_datos.Temporal("sin red")).cliente(), dias=3)
        self.assertEqual((resumen["error"], resumen["nuevas"]), ("red", 0))
        self.assertGreater(resumen["esperas"], 0)
        self.assertEqual(lib_datos.bajar_todo(ApiFalsa(siempre=lib_datos.Limitado(5)).cliente(), dias=3)["error"], "limite")

    def test_con_las_doce_series_completas_se_puede_operar(self):
        resumen = lib_datos.bajar_todo(ApiFalsa().cliente(), dias=3)
        e = lib_datos.estado(dias=3, ahora_ms=AHORA)
        self.assertEqual(resumen["error"], "")
        self.assertEqual(len(e["series"]), len(lib_datos.PARES) * len(lib_datos.TEMPORALIDADES))
        self.assertEqual(e["motivos"], [])
        self.assertTrue(e["puede_operar"])


class TramosResumibles(ConCarpeta):
    """`bajar_tramo`: lo que hace que «Detener» y «Seguir donde quedó» no pierdan ni repitan nada."""

    def test_un_tramo_se_retoma_donde_quedo(self):
        paso = lib_datos.PASO_MS[lib_datos.MINUTO]
        fin = AHORA // paso * paso
        inicio = fin - 3 * lib_datos.DIA_MS           # 4320 velas de 1 m: cinco páginas de 1000
        corta = Detencion(2)                          # dos páginas y «Detener»
        a = lib_datos.bajar_tramo(ApiFalsa().cliente(), "BTCFDUSD", lib_datos.MINUTO, inicio, fin, detener=corta.detenido)
        self.assertEqual((a["cortado"], a["paginas"], a["nuevas"]), (True, 2, 2000))
        self.assertEqual(a["siguiente"], inicio + 2000 * paso)
        self.assertEqual(len(lib_datos.leer_serie("BTCFDUSD", lib_datos.MINUTO)), 2000)   # ya en disco, no en memoria
        otra = ApiFalsa()
        b = lib_datos.bajar_tramo(otra.cliente(), "BTCFDUSD", lib_datos.MINUTO, a["siguiente"], fin)
        self.assertEqual((b["cortado"], b["siguiente"], b["nuevas"]), (False, fin, 2320))
        velas = lib_datos.leer_serie("BTCFDUSD", lib_datos.MINUTO)
        self.assertEqual(len(velas), 3 * 24 * 60)
        self.assertEqual(lib_datos.huecos(velas, lib_datos.MINUTO), [])    # continua: con ella sí se puede calcular
        self.assertEqual(lib_datos.fin_continuo(velas, lib_datos.MINUTO, inicio), fin)

    def test_la_ventana_de_un_minuto_se_corre_y_suelta_lo_viejo(self):
        paso = lib_datos.PASO_MS[lib_datos.MINUTO]
        fin = AHORA // paso * paso
        viejas = [[fin - (5000 - i) * paso, 100.0, 101.0, 99.0, 100.5, 1.0] for i in range(10)]
        lib_datos.guardar_serie("ETHFDUSD", lib_datos.MINUTO, viejas)
        inicio = fin - 1000 * paso
        lib_datos.bajar_tramo(ApiFalsa().cliente(), "ETHFDUSD", lib_datos.MINUTO, inicio, fin, recortar_desde=inicio)
        velas = lib_datos.leer_serie("ETHFDUSD", lib_datos.MINUTO)
        self.assertEqual(len(velas), 1000)
        self.assertTrue(all(v[0] >= inicio for v in velas))

    def test_la_historia_que_no_existe_se_pide_una_vez_y_no_más(self):
        paso = lib_datos.PASO_MS["1d"]
        fin = AHORA // paso * paso
        inicio = fin - 100 * paso
        nuevo = ApiFalsa(listado=fin - 10 * paso)     # un par más nuevo que la ventana (FDUSD)
        a = lib_datos.bajar_tramo(nuevo.cliente(), "BTCFDUSD", "1d", inicio, fin)
        self.assertEqual((a["siguiente"], a["nuevas"], a["paginas"]), (fin, 10, 1))
        vacio = ApiFalsa(listado=fin + paso)          # ni una vela en toda la ventana
        b = lib_datos.bajar_tramo(vacio.cliente(), "ETHFDUSD", "1d", inicio, fin)
        self.assertEqual((b["siguiente"], b["nuevas"], b["paginas"]), (fin, 0, 1))

    def test_la_serie_de_un_minuto_solo_es_de_los_pares_que_se_operan(self):
        self.assertTrue(lib_datos.serie_valida("BTCFDUSD", lib_datos.MINUTO))
        for par, temporalidad in (("PEPEUSDT", "1m"), ("BTCUSDT", "5m"), ("BTCFDUSD", "5m")):
            self.assertFalse(lib_datos.serie_valida(par, temporalidad))
            with self.assertRaises(ValueError):
                lib_datos.ruta_serie(par, temporalidad)


class LibroYTrades(ConCarpeta):
    """Lo que Binance no guarda: el mejor precio de compra y de venta y los últimos trades, muestreados y guardados."""

    def test_el_libro_trae_las_dos_puntas_y_su_diferencia(self):
        libro = ApiFalsa().cliente().libro("BTCFDUSD")
        self.assertEqual((libro["compra"], libro["venta"]), (95000.10, 95000.40))
        self.assertAlmostEqual(libro["spread"], 0.30, places=6)
        # La diferencia relativa va sobre el precio medio y se guarda entera: en un par líquido es del orden de 1e-6, así que
        # redondearla la borraría (3,16e-06). El redondeo es solo de la pantalla.
        self.assertEqual(libro["spread_relativo"], (95000.40 - 95000.10) / ((95000.10 + 95000.40) / 2))
        self.assertNotEqual(round(libro["spread_relativo"], 8), libro["spread_relativo"])

    def test_un_libro_que_no_se_entiende_no_se_cree(self):
        bueno = {"symbol": "BTCFDUSD", "bidPrice": "100", "bidQty": "1", "askPrice": "101", "askQty": "1"}
        for malo in ({**bueno, "bidPrice": "102"},            # la compra por sobre la venta: imposible
                     {**bueno, "askPrice": "no"},
                     {**bueno, "bidPrice": "-1"},
                     {**bueno, "symbol": "ETHFDUSD"},         # la respuesta no es del par que pedimos
                     ["una lista"]):
            cliente = lib_datos.Binance(pedir=lambda ruta, parametros=None, m=malo: m, dormir=lambda s: None)
            with self.assertRaises(lib_datos.Respuesta):
                cliente.libro("BTCFDUSD")

    def test_los_trades_dicen_de_que_lado_llego_la_orden(self):
        trades = ApiFalsa().cliente().trades("BTCFDUSD")
        self.assertEqual([t[1] for t in trades], [95000.20, 95000.30])
        self.assertEqual([t[3] for t in trades], [True, False])   # el primero lo apuró un comprador; el segundo, un vendedor

    def test_el_libro_y_los_trades_solo_de_los_pares_que_conocemos(self):
        for par in ("DOGEUSDT", "../otro", ""):
            with self.assertRaises(ValueError):
                ApiFalsa().cliente().libro(par)
            with self.assertRaises(ValueError):
                ApiFalsa().cliente().trades(par)

    def test_una_muestra_guardada_no_se_reescribe_nunca(self):
        m = lib_datos.guardar_muestra({"ms": AHORA, "par": "BTCFDUSD", "compra": 95000.1, "venta": 95000.4, "trades": []})
        lib_datos.guardar_muestra({**m, "ms": AHORA + 300_000})
        ruta = lib_datos.ruta_muestras(AHORA)
        with open(ruta, encoding="utf-8") as f:
            lineas = [json.loads(x) for x in f if x.strip()]
        self.assertEqual([x["ms"] for x in lineas], [AHORA, AHORA + 300_000])
        self.assertEqual(lib_datos.meses_con_muestras(), ["2026-02"])
        if os.name != "nt":
            self.assertEqual(os.stat(ruta).st_mode & 0o777, 0o600)   # las muestras son de la persona y de nadie más


class HistorialDeTresAnos(ConCarpeta):
    """El trabajo que baja los 3 años por etapas, con su avance, «Detener» y «Seguir donde quedó»."""

    def test_el_plan_son_las_doce_series_de_tres_anos(self):
        plan = historial.armar(AHORA)
        r = historial.resumen(plan)
        self.assertEqual(len(plan["series"]), len(lib_datos.PARES) * len(historial.ETAPAS))
        self.assertEqual(plan["dias"], lib_datos.DIAS_HISTORIAL)
        self.assertEqual([e["temporalidad"] for e in r["etapas"]], list(historial.ETAPAS))
        self.assertEqual((r["estado"], r["pct"], r["velas"]), ("nunca", 0, 0))
        self.assertEqual(r["esperadas"], sum(s["esperadas"] for s in plan["series"]))
        self.assertGreater(r["falta_segundos"], 0)                 # el tiempo estimado se dice desde antes de empezar

    def test_baja_los_tres_anos_por_etapas_y_deja_el_avance_escrito(self):
        r = historial.descargar({}, ApiFalsa().cliente(), ahora_ms=AHORA, dias=5, latir=False)
        d = r["datos"]
        self.assertEqual((r["ok"], r["error"]), (True, ""))
        self.assertEqual((d["estado"], d["faltan"], d["pct"], d["falta_segundos"]), ("listo", 0, 100, 0))
        self.assertTrue(all(e["listo"] for e in d["etapas"]))
        self.assertEqual(d["velas"], sum(e["velas"] for e in d["etapas"]))
        self.assertEqual((d["huecos"], d["continuo"]), (0, True))   # revisado par por par al terminar cada uno
        guardado = historial.estado({}, ahora_ms=AHORA)["datos"]   # se lee de disco, sin red
        self.assertEqual((guardado["estado"], guardado["pct"], guardado["velas"]), ("listo", 100, d["velas"]))

    def test_las_etapas_van_de_lo_mas_barato_a_lo_mas_caro(self):
        api = ApiFalsa()
        historial.descargar({}, api.cliente(), ahora_ms=AHORA, dias=5, latir=False)
        pedidas = [p[1]["interval"] for p in api.pedidos if p[0] == "/api/v3/klines"]
        self.assertEqual(sorted(set(pedidas), key=pedidas.index), list(historial.ETAPAS))
        self.assertEqual(len(pedidas), len(lib_datos.PARES) * len(historial.ETAPAS))   # un tramo, un pedido: nada repetido

    def test_los_limites_de_binance_se_esperan_y_la_descarga_sigue(self):
        api = ApiFalsa(pide_esperar=2)                             # dos 429 seguidos y después contesta
        cliente = api.cliente()
        r = historial.descargar({}, cliente, ahora_ms=AHORA, dias=5, latir=False)
        self.assertEqual((r["ok"], r["datos"]["estado"], r["datos"]["pct"]), (True, "listo", 100))
        self.assertEqual(cliente.esperas, 2)
        self.assertIn(3, api.dormido)                              # los segundos que pidió Binance, no los nuestros

    def test_al_terminar_cada_par_se_revisa_la_continuidad_y_se_rellena_el_hoyo(self):
        api = ApiConHoyo()                                         # a la primera página le falta una vela del medio
        d = historial.descargar({}, api.cliente(), ahora_ms=AHORA, dias=5, latir=False)["datos"]
        self.assertEqual((d["estado"], d["huecos"], d["continuo"]), ("listo", 0, True))
        velas = lib_datos.leer_serie("BTCFDUSD", "1d")
        self.assertEqual(lib_datos.huecos(velas, "1d"), [])        # quedó continua: con ella sí se puede calcular
        self.assertIn(api.hoyo, [v[0] for v in velas])

    def test_un_hoyo_que_binance_no_entrega_queda_anotado_y_se_reintenta(self):
        api = ApiConHoyo(veces=None)                               # esa vela no la entrega nunca
        d = historial.descargar({}, api.cliente(), ahora_ms=AHORA, dias=5, latir=False)["datos"]
        self.assertEqual((d["huecos"], d["continuo"]), (1, False))
        self.assertEqual([e["huecos"] for e in d["etapas"]], [1, 0, 0])
        self.assertEqual(d["faltan"], 0)                           # la ventana está recorrida: lo que falta es la vela
        sano = ApiFalsa()                                          # a la vuelta siguiente Binance ya la tiene
        otra = historial.descargar({}, sano.cliente(), ahora_ms=AHORA, dias=5, latir=False)["datos"]
        self.assertEqual((otra["huecos"], otra["continuo"], otra["estado"]), (0, True, "listo"))
        self.assertEqual(len(sano.pedidos), 1)                     # un solo pedido: el del hoyo, nada más

    def test_si_binance_se_cae_queda_lo_bajado_y_se_sigue_donde_quedo(self):
        caido = historial.descargar({}, ApiFalsa(siempre=lib_datos.Temporal("sin red")).cliente(),
                                    ahora_ms=AHORA, dias=5, latir=False)
        self.assertEqual((caido["ok"], caido["error"], caido["datos"]["estado"]), (False, "red", "error"))
        seguir = historial.descargar({}, ApiFalsa().cliente(), ahora_ms=AHORA, dias=5, latir=False)
        self.assertEqual(seguir["datos"]["estado"], "listo")
        otra = ApiFalsa()
        historial.descargar({}, otra.cliente(), ahora_ms=AHORA, dias=5, latir=False)
        self.assertEqual(otra.pedidos, [])                         # lo que ya está no se vuelve a pedir

    def test_si_la_persona_detiene_la_descarga_se_puede_seguir(self):
        cliente = ApiFalsa().cliente()
        velas_de = cliente.klines

        def una_pagina_y_detener(par, temporalidad, desde):        # «Detener» en medio de la descarga
            filas = velas_de(par, temporalidad, desde)
            lib_trabajo.detener("historial")
            return filas

        cliente.klines = una_pagina_y_detener
        d = historial.descargar({}, cliente, ahora_ms=AHORA, dias=5, latir=False)["datos"]
        self.assertEqual(d["estado"], "detenido")
        self.assertGreater(d["velas"], 0)
        self.assertGreater(d["faltan"], 0)
        self.assertLess(d["pct"], 100)
        seguir = historial.descargar({}, ApiFalsa().cliente(), ahora_ms=AHORA, dias=5, latir=False)
        self.assertEqual((seguir["datos"]["estado"], seguir["datos"]["pct"]), ("listo", 100))

    def test_un_trabajo_sin_latido_quedo_interrumpido(self):
        historial.descargar({}, ApiFalsa().cliente(), ahora_ms=AHORA, dias=5, latir=False)
        plan = lib_trabajo.leer_plan("historial")
        nucleo.escribir_json(lib_trabajo.ruta_plan("historial"), {**plan, "estado": "corriendo"})
        d = historial.estado({}, ahora_ms=AHORA)["datos"]
        self.assertEqual((d["estado"], d["corriendo"]), ("interrumpido", False))

    def test_detener_sin_nada_corriendo_no_hace_nada(self):
        self.assertFalse(lib_trabajo.detener("historial"))
        r = historial.detener({})
        self.assertEqual((r["ok"], r["datos"]["estado"], r["datos"]["deteniendo"]), (True, "nunca", False))


class MuestreoDelMercado(ConCarpeta):
    """El trabajo que cada 5 minutos guarda una muestra del mercado y pone al día las velas de 1 m."""

    def test_un_ciclo_guarda_una_muestra_de_cada_par_y_las_velas_de_un_minuto(self):
        dormidos = []
        r = muestreo.encender({}, ApiFalsa().cliente(), ahora_ms=AHORA, dias=1, dormir=dormidos.append,
                              ciclos=1, latir=False)
        d = r["datos"]
        self.assertEqual((r["ok"], r["error"]), (True, ""))
        self.assertEqual((d["muestras"], d["ciclos"]), (len(lib_datos.PARES_OPERADOS), 1))
        self.assertEqual((d["pct"], d["faltan"], d["etapa"]), (100, 0, "muestras"))
        self.assertEqual(d["velas"], len(lib_datos.PARES_OPERADOS) * 24 * 60)
        self.assertEqual([p["par"] for p in d["ultima"]["pares"]], list(lib_datos.PARES_OPERADOS))
        self.assertEqual(d["proxima"], AHORA + muestreo.CICLO_SEGUNDOS * 1000)
        self.assertEqual(dormidos, [])                              # con un solo ciclo no hay nada que esperar
        for par in lib_datos.PARES_OPERADOS:
            velas = lib_datos.leer_serie(par, lib_datos.MINUTO)
            self.assertEqual(len(velas), 24 * 60)
            self.assertEqual(lib_datos.huecos(velas, lib_datos.MINUTO), [])
        with open(lib_datos.ruta_muestras(AHORA), encoding="utf-8") as f:
            muestras = [json.loads(x) for x in f if x.strip()]
        self.assertEqual([m["par"] for m in muestras], list(lib_datos.PARES_OPERADOS))
        self.assertGreater(muestras[0]["venta"], muestras[0]["compra"])
        self.assertEqual(len(muestras[0]["trades"]), 2)
        # La diferencia relativa llega al archivo con toda su precisión: es la base del modelo de spread del backtest.
        libro = ApiFalsa().cliente().libro("BTCFDUSD")
        self.assertEqual(muestras[0]["spread_relativo"], libro["spread_relativo"])
        guardado = muestreo.estado({}, ahora_ms=AHORA)["datos"]     # se lee de disco, sin red
        self.assertEqual((guardado["muestras"], guardado["pct"], guardado["mes_desde"]), (2, 100, "2026-02"))
        self.assertEqual((guardado["sin_cobertura"], guardado["fallos"]), ([], 0))
        self.assertFalse(guardado["corriendo"])

    def test_entre_ciclos_espera_cinco_minutos_en_trozos_cortos(self):
        dormidos = []
        r = muestreo.encender({}, ApiFalsa().cliente(), ahora_ms=AHORA, dias=1, dormir=dormidos.append,
                              ciclos=2, latir=False)
        self.assertEqual((r["datos"]["ciclos"], r["datos"]["muestras"]), (2, 4))
        self.assertEqual(sum(dormidos), muestreo.CICLO_SEGUNDOS)
        self.assertGreater(len(dormidos), 1)                        # en trozos: «Detener» no espera cinco minutos

    def test_detener_corta_la_espera_y_lo_guardado_queda(self):
        # El ciclo no se corta solo: lo corta «Detener» en medio de la espera. Los 3 ciclos son solo un tope para que, si
        # alguna vez dejara de cortarse, la prueba falle en vez de quedarse muestreando para siempre.
        r = muestreo.encender({}, ApiFalsa().cliente(), ahora_ms=AHORA, dias=1,
                              dormir=lambda s: lib_trabajo.detener("muestreo"), ciclos=3, latir=False)
        self.assertEqual((r["datos"]["estado"], r["datos"]["ciclos"]), ("detenido", 1))
        self.assertEqual(r["datos"]["muestras"], len(lib_datos.PARES_OPERADOS))

    def test_una_vuelta_que_falla_no_deja_de_muestrear(self):
        # Lo que no se guarde hoy no se recupera nunca: un tropezón de red se anota y en el próximo ciclo se vuelve a intentar.
        api = ApiFalsa()
        fallas = [lib_datos.INTENTOS]      # la primera vuelta no resulta ni reintentando

        def a_veces(ruta, parametros=None):
            if ruta == "/api/v3/ticker/bookTicker" and fallas[0]:
                fallas[0] -= 1
                raise lib_datos.Temporal("sin red")
            return api(ruta, parametros)

        cliente = lib_datos.Binance(pedir=a_veces, dormir=lambda s: None)
        d = muestreo.encender({}, cliente, ahora_ms=AHORA, dias=1, dormir=lambda s: None, ciclos=2, latir=False)["datos"]
        self.assertEqual((d["estado"], d["error"]), ("listo", ""))      # la vuelta buena borra el tropezón
        self.assertEqual((d["ciclos"], d["muestras"], d["fallos"]), (1, len(lib_datos.PARES_OPERADOS), 0))

    def test_la_ventana_sin_muestras_queda_escrita_y_se_cierra_con_la_vuelta_buena(self):
        # La muestra que no se tomó no se recupera: queda escrito desde cuándo no hubo libro, cuántas vueltas y por qué.
        api = ApiFalsa()
        fallas = [2 * lib_datos.INTENTOS]      # las dos primeras vueltas no resultan ni reintentando

        def a_veces(ruta, parametros=None):
            if ruta == "/api/v3/ticker/bookTicker" and fallas[0]:
                fallas[0] -= 1
                raise lib_datos.Temporal("sin red")
            return api(ruta, parametros)

        cliente = lib_datos.Binance(pedir=a_veces, dormir=lambda s: None)
        d = muestreo.encender({}, cliente, ahora_ms=AHORA, dias=1, dormir=lambda s: None, ciclos=3, latir=False)["datos"]
        self.assertEqual((d["ciclos"], d["fallos"]), (1, 0))
        self.assertEqual(len(d["sin_cobertura"]), 1)                # dos vueltas malas seguidas son un solo hueco
        hueco = d["sin_cobertura"][0]
        self.assertEqual((hueco["ciclos"], hueco["error"], hueco["abierto"]), (2, "red", False))
        self.assertEqual((hueco["desde"], hueco["hasta"]), (AHORA, AHORA))
        guardado = muestreo.estado({}, ahora_ms=AHORA)["datos"]     # el hueco queda en disco, no solo en memoria
        self.assertEqual(guardado["sin_cobertura"], d["sin_cobertura"])

    def test_si_el_ciclo_se_corta_a_la_mitad_lo_guardado_se_cuenta_y_el_hueco_queda_abierto(self):
        api = ApiFalsa()

        def medio_caido(ruta, parametros=None):
            if ruta == "/api/v3/ticker/bookTicker" and parametros["symbol"] == "ETHFDUSD":
                raise lib_datos.Temporal("sin red")
            return api(ruta, parametros)

        cliente = lib_datos.Binance(pedir=medio_caido, dormir=lambda s: None)
        d = muestreo.encender({}, cliente, dias=1, ahora_ms=AHORA, dormir=lambda s: None, ciclos=1, latir=False)["datos"]
        self.assertEqual((d["muestras"], d["ciclos"], d["fallos"]), (1, 0, 1))   # la de BTC se guardó; la de ETH, no
        with open(lib_datos.ruta_muestras(AHORA), encoding="utf-8") as f:
            self.assertEqual([json.loads(x)["par"] for x in f if x.strip()], ["BTCFDUSD"])
        self.assertTrue(d["sin_cobertura"][0]["abierto"])            # sigue abierto: ninguna vuelta buena lo cerró

    def test_despues_de_varias_vueltas_malas_seguidas_se_rinde_y_lo_dice(self):
        # Sin `ahora_ms`: con Binance caído ni la hora se puede preguntar, y el trabajo igual parte en vez de caerse.
        r = muestreo.encender({}, ApiFalsa(siempre=lib_datos.Temporal("sin red")).cliente(), dias=1,
                              dormir=lambda s: None, ciclos=20, latir=False)
        self.assertEqual((r["ok"], r["error"], r["datos"]["estado"]), (False, "red", "error"))
        self.assertEqual((r["datos"]["fallos"], r["datos"]["muestras"]), (muestreo.FALLOS_SEGUIDOS, 0))
        self.assertGreater(r["datos"]["proxima"], 0)                   # igual dice cuándo sería el próximo intento
        hueco = r["datos"]["sin_cobertura"][0]                          # el rato sin muestras queda escrito, y abierto
        self.assertEqual((hueco["ciclos"], hueco["error"], hueco["abierto"]), (muestreo.FALLOS_SEGUIDOS, "red", True))

    def test_apagar_deja_la_marca_que_el_trabajo_revisa(self):
        t = lib_trabajo.nuevo("muestreo", muestreo.ETAPAS, {}, latir=False)
        self.assertTrue(muestreo.apagar({})["datos"]["deteniendo"])
        self.assertTrue(t.detenido())


class CapitalMinimoViable(ConCarpeta):
    """El capital mínimo viable: con los mínimos de Binance, la reserva, las dos posiciones y la protección en los dos lados."""

    def test_la_cantidad_minima_sirve_para_la_compra_y_para_las_dos_patas(self):
        d = minimo_viable.medir(ApiFalsa().cliente(), capital=200)
        self.assertTrue(d["calculado"])
        self.assertEqual([p["par"] for p in d["pares"]], list(minimo_viable.PARES))
        for p in d["pares"]:
            self.assertGreaterEqual(p["cantidad"], p["cantidad_minima"])
            self.assertEqual(Decimal(str(p["cantidad"])) % Decimal(str(p["paso"])), 0)   # un múltiplo del paso: Binance la acepta
            self.assertEqual(Decimal(str(p["stop"])) % Decimal(str(p["tick"])), 0)
            self.assertLess(p["stop"], p["precio"])
            self.assertLess(p["precio"], p["objetivo"])
            self.assertGreaterEqual(p["entrada"], p["nocional_minimo"])
            self.assertGreaterEqual(p["nocional_stop"], p["nocional_minimo"])        # la pata del stop es la que manda
            self.assertEqual(p["motivo"], "")
        self.assertTrue(d["listo"])

    def test_el_capital_minimo_deja_la_reserva_y_las_dos_posiciones(self):
        d = minimo_viable.medir(ApiFalsa().cliente())
        for p in d["pares"]:
            para_esta = p["capital"] * (1 - minimo_viable.RESERVA) / minimo_viable.POSICIONES
            self.assertGreaterEqual(round(para_esta, 6), p["posicion"])                  # cabe dejando el 40 % en USDT
            self.assertLessEqual(p["posicion"] * minimo_viable.CAIDA_STOP,
                                 p["capital"] * minimo_viable.RIESGO)                    # y sin pasar el 2 % de riesgo
            self.assertGreater(p["posicion"], p["entrada"])                              # los costos están contados
        self.assertEqual(d["capital_minimo"], max(p["capital"] for p in d["pares"]))

    def test_dice_si_el_capital_que_hay_alcanza(self):
        d = minimo_viable.medir(ApiFalsa().cliente(), capital=200)
        self.assertEqual((d["capital"], d["alcanza"], d["falta"]), (200, True, 0))
        corto = minimo_viable.con_capital(dict(d), 1)
        self.assertEqual((corto["alcanza"], corto["falta"]), (False, d["capital_minimo"] - 1))
        sin_nada = minimo_viable.con_capital(dict(d), 0)
        self.assertEqual((sin_nada["alcanza"], sin_nada["falta"]), (False, d["capital_minimo"]))

    def test_un_par_sin_proteccion_automatica_o_detenido_no_queda_listo(self):
        d = minimo_viable.medir(ApiFalsa(proteccion=False).cliente())
        self.assertFalse(d["listo"])
        self.assertEqual({m["codigo"] for m in d["motivos"]}, {"sin_proteccion"})
        detenido = minimo_viable.medir(ApiFalsa(estado_par="HALT").cliente())
        self.assertEqual({m["codigo"] for m in detenido["motivos"]}, {"sin_operar"})

    def test_sin_los_minimos_de_binance_no_se_inventa_ninguno(self):
        bueno = ApiFalsa().simbolo("BTCFDUSD")
        for malo in ({**bueno, "filters": []},
                     {**bueno, "filters": [{"filterType": "LOT_SIZE", "stepSize": "cero", "minQty": "1"}]},
                     {**bueno, "filters": "no es una lista"},
                     {**bueno, "baseAsset": "DOGE"},
                     {**bueno, "symbol": "ETHFDUSD"},
                     None):
            with self.assertRaises(lib_datos.Respuesta):
                minimo_viable.filtros_de(malo, "BTCFDUSD", "BTC")

    def test_los_filtros_solo_se_piden_de_los_pares_que_conocemos(self):
        with self.assertRaises(ValueError):
            ApiFalsa().cliente().info_pares(["PEPEUSDT"])

    def test_las_comisiones_de_la_api_mandan_sobre_las_supuestas(self):
        supuestas = minimo_viable.medir(ApiFalsa().cliente())
        self.assertEqual(supuestas["comisiones"]["origen"], "supuesto")
        nucleo.escribir_json(minimo_viable.ruta_comisiones(), {"maker": 0.001, "taker": 0.001})
        vigentes = minimo_viable.medir(ApiFalsa().cliente())
        self.assertEqual(vigentes["comisiones"]["origen"], "api")
        self.assertGreater(vigentes["pares"][0]["costos"], supuestas["pares"][0]["costos"])
        nucleo.escribir_json(minimo_viable.ruta_comisiones(), {"maker": 0.9, "taker": 0.001})
        self.assertEqual(minimo_viable.medir(ApiFalsa().cliente())["comisiones"]["origen"], "supuesto")

    def test_si_binance_se_cae_se_dice_el_motivo_y_queda_lo_ya_calculado(self):
        hecho = minimo_viable.calcular({"capital": 200}, ApiFalsa().cliente())
        self.assertEqual((hecho["ok"], hecho["error"]), (True, ""))
        caido = minimo_viable.calcular({"capital": 200}, ApiFalsa(siempre=lib_datos.Temporal("sin red")).cliente())
        self.assertEqual((caido["ok"], caido["error"]), (False, "red"))
        self.assertEqual(caido["datos"]["capital_minimo"], hecho["datos"]["capital_minimo"])
        limitada = minimo_viable.calcular({}, ApiFalsa(siempre=lib_datos.Limitado(5)).cliente())
        self.assertEqual(limitada["error"], "limite")
        self.assertEqual(minimo_viable.estado({"capital": 200})["datos"]["capital_minimo"],
                         hecho["datos"]["capital_minimo"])   # lo guardado se lee sin tocar la red

    def test_el_precio_es_el_de_la_ultima_vela_cerrada(self):
        paso = lib_datos.PASO_MS["1h"]
        api = ApiFalsa()
        precio = minimo_viable.precio_cerrado(api.cliente(), "BTCFDUSD", AHORA)
        filas = api("/api/v3/klines", {"symbol": "BTCFDUSD", "interval": "1h", "startTime": AHORA - 3 * paso, "limit": 1000})
        velas = [lib_datos.vela_de(f, paso) for f in filas]
        cerradas = [v for v in velas if v[0] + paso <= AHORA]
        self.assertEqual(precio, cerradas[-1][4])
        self.assertNotEqual(precio, velas[-1][4])            # la vela en curso no se usa


class AccionMinimo(unittest.TestCase):
    def test_sin_calcular_la_pantalla_lo_dice(self):
        r = correr("minimo_viable.py", "estado", entrada={"capital": 200})
        self.assertTrue(r["ok"])
        self.assertFalse(r["datos"]["calculado"])
        self.assertEqual((r["datos"]["capital"], r["datos"]["alcanza"], r["datos"]["pares"]), (200, False, []))

    def test_un_capital_fuera_de_rango_no_cuenta(self):
        for capital in (-5, 10 ** 9, 2.5, "mucho", True, None):
            self.assertEqual(correr("minimo_viable.py", "estado", entrada={"capital": capital})["datos"]["capital"], 0)


class AccionVelas(unittest.TestCase):
    def test_sin_historial_no_se_opera_y_queda_escrito_el_motivo(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            r = correr("velas.py", "estado", entrada={}, datos=datos)
            self.assertTrue(r["ok"])
            self.assertFalse(r["datos"]["puede_operar"])
            self.assertEqual(len(r["datos"]["series"]), 12)
            self.assertEqual({m["codigo"] for m in r["datos"]["motivos"]}, {"sin_datos"})
            with open(os.path.join(datos, "mercado", "estado.json"), encoding="utf-8") as f:
                escrito = json.load(f)
            self.assertEqual(escrito["motivos"], r["datos"]["motivos"])

    def test_los_dias_fuera_de_rango_vuelven_a_los_noventa(self):
        for dias in (0, -5, 4000, "muchos", None):
            self.assertEqual(correr("velas.py", "estado", entrada={"dias": dias})["datos"]["dias"], 90)
        self.assertEqual(correr("velas.py", "estado", entrada={"dias": 30})["datos"]["dias"], 30)

    @unittest.skipUnless(os.path.exists(os.path.join(RAIZ, "acciones.json")), "acciones.json lo arma pieza.py")
    def test_las_acciones_declaradas_mandan_todo_por_archivo(self):
        # Regla de oro: lo que escribe la persona nunca va como argumento del proceso.
        with open(os.path.join(RAIZ, "acciones.json"), encoding="utf-8") as f:
            acciones = json.load(f)["acciones"]
        for nombre, script in (("velasEstado", "velas.py"), ("velasDescargar", "velas.py"),
                               ("minimoEstado", "minimo_viable.py"), ("minimoCalcular", "minimo_viable.py"),
                               ("historialEstado", "historial.py"), ("historialDescargar", "historial.py"),
                               ("historialDetener", "historial.py"), ("muestreoEstado", "muestreo.py"),
                               ("muestreoEncender", "muestreo.py"), ("muestreoApagar", "muestreo.py"),
                               ("indicadoresEstado", "indicadores.py")):
            a = acciones[nombre]
            self.assertEqual(a["entrada"], "archivo")
            self.assertEqual(a["script"], script)
            self.assertFalse(any(x.startswith("$") for x in a["args"]))
        # Los dos trabajos largos duran lo que duren: el host los corta cuando dejan de latir, no por reloj.
        for nombre in ("historialDescargar", "muestreoEncender"):
            self.assertEqual(acciones[nombre]["limite"], "trabajo")
            self.assertTrue(acciones[nombre]["progreso"])


class AccionesDeLosTrabajos(unittest.TestCase):
    def test_el_estado_de_los_dos_trabajos_no_toca_la_red(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            h = correr("historial.py", "estado", entrada={}, datos=datos)
            self.assertTrue(h["ok"])
            self.assertEqual((h["datos"]["estado"], h["datos"]["pct"], h["datos"]["velas"]), ("nunca", 0, 0))
            self.assertEqual(h["datos"]["dias"], lib_datos.DIAS_HISTORIAL)
            self.assertEqual(len(h["datos"]["etapas"]), len(historial.ETAPAS))
            m = correr("muestreo.py", "estado", entrada={}, datos=datos)
            self.assertTrue(m["ok"])
            self.assertEqual((m["datos"]["estado"], m["datos"]["muestras"], m["datos"]["pct"]), ("nunca", 0, 0))
            self.assertEqual(m["datos"]["dias"], lib_datos.DIAS_MINUTOS)
            with open(os.path.join(datos, "mercado", "historial.json"), encoding="utf-8") as f:
                self.assertEqual(len(json.load(f)["series"]), 12)   # el plan queda escrito, listo para seguir

    def test_detener_y_apagar_sin_nada_corriendo_responden_igual(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            for script, accion in (("historial.py", "detener"), ("muestreo.py", "apagar")):
                r = correr(script, accion, entrada={}, datos=datos)
                self.assertEqual((r["ok"], r["datos"]["estado"], r["datos"]["deteniendo"]), (True, "nunca", False))


class IndicadoresConocidos(unittest.TestCase):
    """Las cuentas de siempre, sobre series ficticias cuyos valores se saben de memoria: así un cambio en la fórmula se nota."""

    def test_la_media_simple_y_la_exponencial_sobre_una_serie_conocida(self):
        self.assertEqual(lib_indicadores.sma([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])
        # Sembrada con la media simple de las primeras n, la exponencial de una serie que sube parejo atrasa (n−1)/2 velas.
        self.assertEqual(lib_indicadores.ema([1, 2, 3, 4, 5], 3), [None, None, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(lib_indicadores.ema([float(i) for i in range(100)], 5)[-1], 97.0, places=9)
        self.assertEqual(lib_indicadores.sma([1, 2], 5), [None, None])          # sin velas suficientes no se inventa nada
        self.assertEqual(lib_indicadores.ema([1, 2], 5), [None, None])
        for n in (0, -3):
            with self.assertRaises(ValueError):
                lib_indicadores.sma([1, 2, 3], n)

    def test_el_rsi_de_wilder_sobre_una_serie_conocida(self):
        # Dos velas: +1 y −1 dejan el RSI en 50; la tercera (+1) lo deja en 75 con el suavizado de Wilder.
        self.assertEqual(lib_indicadores.rsi([10, 11, 10, 11], 2), [None, None, 50.0, 75.0])
        self.assertEqual(lib_indicadores.rsi([float(i) for i in range(40)])[-1], 100.0)        # todo sube
        self.assertEqual(lib_indicadores.rsi([float(40 - i) for i in range(40)])[-1], 0.0)     # todo baja
        self.assertEqual(lib_indicadores.rsi([5.0] * 40)[-1], 50.0)                            # sin movimiento, neutral
        self.assertEqual(lib_indicadores.rsi([5.0] * 10), [None] * 10)

    def test_el_macd_es_la_diferencia_entre_las_dos_medias_exponenciales(self):
        cierres = [float(i) for i in range(200)]
        m = lib_indicadores.macd(cierres)
        self.assertEqual([len(m["macd"]), len(m["senal"]), len(m["histograma"])], [len(cierres)] * 3)
        self.assertIsNone(m["macd"][lib_indicadores.MACD_LENTA - 2])          # recién existe con la media larga
        self.assertIsNotNone(m["macd"][lib_indicadores.MACD_LENTA - 1])
        self.assertIsNone(m["senal"][lib_indicadores.MACD_LENTA + lib_indicadores.MACD_SENAL - 3])
        self.assertIsNotNone(m["senal"][lib_indicadores.MACD_LENTA + lib_indicadores.MACD_SENAL - 2])
        self.assertAlmostEqual(m["macd"][-1], lib_indicadores.ema(cierres, 12)[-1] - lib_indicadores.ema(cierres, 26)[-1],
                               places=12)
        # En una serie que sube de a 1, las dos medias atrasan 5,5 y 12,5 velas: la diferencia es 7 y la señal la alcanza.
        self.assertAlmostEqual(m["macd"][-1], 7.0, places=6)
        self.assertAlmostEqual(m["histograma"][-1], 0.0, places=6)
        plano = lib_indicadores.macd([5.0] * 200)
        self.assertAlmostEqual(plano["macd"][-1], 0.0, places=9)
        self.assertAlmostEqual(plano["histograma"][-1], 0.0, places=9)

    def test_el_adx_mide_la_fuerza_sin_decir_para_que_lado(self):
        def de(velas):
            return lib_indicadores.adx([v[2] for v in velas], [v[3] for v in velas], [v[4] for v in velas])

        arriba = de(velas_que_suben(100, "1h"))
        self.assertIsNone(arriba["adx"][2 * lib_indicadores.ADX_PERIODO - 2])     # se suaviza dos veces: existe en la vela 2n−1
        self.assertIsNotNone(arriba["adx"][2 * lib_indicadores.ADX_PERIODO - 1])
        self.assertAlmostEqual(arriba["adx"][-1], 100.0, places=9)
        self.assertAlmostEqual(arriba["di_mas"][-1], 50.0, places=9)
        self.assertAlmostEqual(arriba["di_menos"][-1], 0.0, places=9)
        abajo = de(velas_que_suben(100, "1h", desde=200.0, sube=-1.0))
        self.assertAlmostEqual(abajo["adx"][-1], 100.0, places=9)                 # la misma fuerza, para el otro lado
        self.assertAlmostEqual(abajo["di_mas"][-1], 0.0, places=9)
        self.assertAlmostEqual(abajo["di_menos"][-1], 50.0, places=9)
        plano = de(velas_que_suben(100, "1h", sube=0.0))
        self.assertEqual((plano["adx"][-1], plano["di_mas"][-1], plano["di_menos"][-1]), (0.0, 0.0, 0.0))
        self.assertEqual(de(velas_que_suben(10, "1h"))["adx"], [None] * 10)       # sin velas suficientes, ninguno
        with self.assertRaises(ValueError):
            lib_indicadores.adx([1.0, 2.0], [1.0], [1.0, 2.0])


class IndicadoresDeLasSeries(ConCarpeta):
    """`de_serie`: el valor de ahora sobre lo guardado, solo si la serie está cerrada, completa y seguida."""

    def test_los_valores_de_ahora_salen_de_la_ventana_completa(self):
        lib_datos.guardar_serie("BTCFDUSD", "1h", velas_que_suben(lib_indicadores.VENTANA, "1h"))
        s = lib_indicadores.de_serie("BTCFDUSD", "1h", AHORA)
        self.assertEqual((s["listo"], s["motivo"], s["velas"]), (True, "", lib_indicadores.VENTANA))
        self.assertEqual(s["cierre"], 499.0)
        # Los cierres son 100, 101, … 499: cada media es el promedio exacto de sus últimas velas.
        self.assertAlmostEqual(s["tendencia"]["media_20"], 489.5, places=9)
        self.assertAlmostEqual(s["tendencia"]["media_50"], 474.5, places=9)
        self.assertAlmostEqual(s["tendencia"]["media_200"], 399.5, places=9)
        self.assertAlmostEqual(s["tendencia"]["adx"], 100.0, places=9)
        self.assertAlmostEqual(s["tendencia"]["di_mas"], 50.0, places=9)
        self.assertEqual(s["impulso"]["rsi"], 100.0)
        self.assertAlmostEqual(s["impulso"]["macd"], 7.0, places=6)

    def test_la_vela_en_curso_no_entra_en_el_calculo(self):
        paso = lib_datos.PASO_MS["1h"]
        fin = (AHORA // paso) * paso
        cerradas = velas_que_suben(lib_indicadores.VENTANA, "1h")
        lib_datos.guardar_serie("ETHFDUSD", "1h", cerradas)
        solas = lib_indicadores.de_serie("ETHFDUSD", "1h", AHORA)
        lib_datos.guardar_serie("ETHFDUSD", "1h", cerradas + [[fin, 9000.0, 9999.0, 8000.0, 9500.0, 3.0]])
        con_la_de_ahora = lib_indicadores.de_serie("ETHFDUSD", "1h", AHORA)
        self.assertEqual(con_la_de_ahora, solas)       # la vela de la hora en curso todavía puede cambiar: no se usa
        self.assertEqual(con_la_de_ahora["vela"], fin - paso)

    def test_una_serie_corta_atrasada_o_con_hoyos_no_da_indicadores(self):
        vacia = lib_indicadores.de_serie("BTCUSDT", "1d", AHORA)
        self.assertEqual((vacia["listo"], vacia["motivo"], vacia["cuantas"]), (False, "sin_datos", lib_indicadores.VENTANA))
        self.assertNotIn("tendencia", vacia)           # sin velas no hay número que mostrar, ni siquiera uno a medias
        lib_datos.guardar_serie("BTCUSDT", "1d", velas_que_suben(100, "1d"))
        corta = lib_indicadores.de_serie("BTCUSDT", "1d", AHORA)
        self.assertEqual((corta["motivo"], corta["cuantas"]), ("faltan_velas", lib_indicadores.VENTANA - 100))
        paso = lib_datos.PASO_MS["1h"]
        lib_datos.guardar_serie("BTCUSDT", "1h", velas_que_suben(lib_indicadores.VENTANA, "1h", hasta_ms=AHORA - 3 * paso))
        atrasada = lib_indicadores.de_serie("BTCUSDT", "1h", AHORA)
        self.assertEqual((atrasada["motivo"], atrasada["cuantas"]), ("atrasado", 3))
        con_hoyo = velas_que_suben(lib_indicadores.VENTANA + 1, "1h")
        del con_hoyo[200]
        lib_datos.guardar_serie("ETHUSDT", "1h", con_hoyo)
        hoyo = lib_indicadores.de_serie("ETHUSDT", "1h", AHORA)
        self.assertEqual((hoyo["motivo"], hoyo["cuantas"], hoyo["velas"]), ("huecos", 1, lib_indicadores.VENTANA))

    def test_el_estado_va_por_par_y_temporalidad_y_queda_escrito(self):
        lib_datos.guardar_serie("BTCFDUSD", "1h", velas_que_suben(lib_indicadores.VENTANA, "1h"))
        r = indicadores.estado({}, AHORA)
        self.assertTrue(r["ok"])
        d = r["datos"]
        self.assertEqual(len(d["series"]), len(lib_datos.PARES) * len(lib_datos.TEMPORALIDADES))
        self.assertEqual((d["listas"], d["listo"]), (1, False))
        self.assertEqual({(s["par"], s["temporalidad"]) for s in d["series"] if s["listo"]}, {("BTCFDUSD", "1h")})
        self.assertEqual({m["codigo"] for m in d["motivos"]}, {"sin_datos"})
        with open(lib_indicadores.ruta_indicadores(), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["motivos"], d["motivos"])   # lo leen el puntaje y el motor sin recorrer las velas


class IndicadoresDeMercadoConocidos(unittest.TestCase):
    """Las otras cinco familias, sobre series ficticias cuyos valores se saben de memoria."""

    def test_las_bandas_de_bollinger_sobre_una_serie_conocida(self):
        # Con 2 velas y 1 desvío: la media de 1 y 2 es 1,5 y el desvío 0,5, así que las bandas quedan en 2 y en 1.
        b = lib_indicadores_mercado.bollinger([1.0, 2.0, 3.0, 4.0], n=2, k=1.0)
        self.assertEqual(b["media"], [None, 1.5, 2.5, 3.5])
        self.assertEqual(b["alta"], [None, 2.0, 3.0, 4.0])
        self.assertEqual(b["baja"], [None, 1.0, 2.0, 3.0])
        self.assertEqual(b["posicion"], [None, 1.0, 1.0, 1.0])   # subiendo parejo, el cierre pega en la banda de arriba
        self.assertAlmostEqual(b["ancho"][1], 1 / 1.5, places=12)
        plano = lib_indicadores_mercado.bollinger([5.0] * 30)
        self.assertEqual((plano["alta"][-1], plano["baja"][-1]), (5.0, 5.0))
        self.assertIsNone(plano["ancho"][-1])                    # sin banda no hay ancho ni posición que inventar
        self.assertIsNone(plano["posicion"][-1])

    def test_el_atr_de_wilder_sobre_una_serie_conocida(self):
        altos, bajos, cierres = ([v[i] for v in velas_que_suben(100, "1h")] for i in (2, 3, 4))
        rango = lib_indicadores_mercado.atr(altos, bajos, cierres)
        self.assertIsNone(rango[lib_indicadores_mercado.ATR_PERIODO - 1])   # recién existe con n rangos verdaderos
        self.assertIsNotNone(rango[lib_indicadores_mercado.ATR_PERIODO])
        self.assertAlmostEqual(rango[-1], 2.0, places=9)         # cada vela se mueve 2: el alto y el bajo a 1 del cierre
        self.assertEqual(lib_indicadores_mercado.atr(altos[:5], bajos[:5], cierres[:5]), [None] * 5)
        self.assertIsNone(lib_indicadores_mercado.rango_verdadero(altos, bajos, cierres)[0])
        with self.assertRaises(ValueError):
            lib_indicadores_mercado.atr([1.0, 2.0], [1.0], [1.0, 2.0])

    def test_el_volumen_relativo_y_el_obv_sobre_una_serie_conocida(self):
        velas = velas_que_suben(60, "1h")
        cierres, volumenes = [v[4] for v in velas], [v[5] for v in velas]
        relativo = lib_indicadores_mercado.volumen_relativo(volumenes, 20)
        self.assertIsNone(relativo[19])                          # la vela no entra en su propio promedio
        self.assertEqual(relativo[-1], 1.0)                      # el volumen de siempre: lo normal
        con_golpe = [*volumenes[:-1], volumenes[-1] * 3]
        self.assertEqual(lib_indicadores_mercado.volumen_relativo(con_golpe, 20)[-1], 3.0)
        acumulado = lib_indicadores_mercado.obv(cierres, volumenes)
        self.assertEqual((acumulado[0], acumulado[-1]), (0.0, 10.0 * 59))   # todas las velas cierran más arriba
        self.assertEqual(lib_indicadores_mercado.obv_relativo(cierres, volumenes, 20)[-1], 1.0)
        bajando = [v[4] for v in velas_que_suben(60, "1h", desde=200.0, sube=-1.0)]
        self.assertEqual(lib_indicadores_mercado.obv_relativo(bajando, volumenes, 20)[-1], -1.0)
        self.assertEqual(lib_indicadores_mercado.obv_relativo([5.0] * 60, volumenes, 20)[-1], 0.0)
        with self.assertRaises(ValueError):
            lib_indicadores_mercado.obv([1.0, 2.0], [1.0])

    def test_los_maximos_y_minimos_rotos_no_cuentan_la_vela_que_los_rompe(self):
        altos, bajos, cierres = ([v[i] for v in velas_que_suben(60, "1h")] for i in (2, 3, 4))
        r = lib_indicadores_mercado.rupturas(altos, bajos, cierres, 20)
        self.assertIsNone(r["maximo"][19])
        # Subiendo de a 1, el cierre pega justo en el techo de las 20 anteriores: tocarlo no es romperlo.
        self.assertEqual(r["maximo"][-1], cierres[-1])
        self.assertFalse(r["rompio_maximo"][-1])
        self.assertEqual(r["distancia_maximo"][-1], 0.0)
        self.assertEqual(r["minimo"][-1], bajos[-21])
        self.assertGreater(r["distancia_minimo"][-1], 0)
        salto = [*cierres[:-1], cierres[-1] + 50]
        self.assertTrue(lib_indicadores_mercado.rupturas(altos, bajos, salto, 20)["rompio_maximo"][-1])
        caida = [*cierres[:-1], bajos[-21] - 1]
        self.assertTrue(lib_indicadores_mercado.rupturas(altos, bajos, caida, 20)["rompio_minimo"][-1])
        for n in (0, -2):
            with self.assertRaises(ValueError):
                lib_indicadores_mercado.rupturas(altos, bajos, cierres, n)

    def test_el_cambio_de_cada_vela(self):
        self.assertEqual(lib_indicadores_mercado.cambios([]), [])
        cambios = lib_indicadores_mercado.cambios([100.0, 101.0, 100.0])
        self.assertIsNone(cambios[0])
        self.assertAlmostEqual(cambios[1], 0.01, places=12)
        self.assertAlmostEqual(cambios[2], -1 / 101, places=12)


class IndicadoresDeMercadoDeLasSeries(ConCarpeta):
    """Las cinco familias que se suman a cada serie, el contexto de BTC y el costo de ahora, sobre lo guardado."""

    def test_cada_serie_al_dia_trae_las_cinco_familias(self):
        lib_datos.guardar_serie("BTCFDUSD", "1h", velas_que_suben(lib_indicadores.VENTANA, "1h"))
        s = lib_indicadores.de_serie("BTCFDUSD", "1h", AHORA, lib_indicadores_mercado.valores)
        self.assertTrue(s["listo"])
        v = s["volatilidad"]
        self.assertAlmostEqual(v["banda_media"], 489.5, places=9)       # la media de 20, la misma de la tendencia
        self.assertLess(v["banda_baja"], s["cierre"])
        self.assertLess(s["cierre"], v["banda_alta"])
        self.assertAlmostEqual(v["posicion"], (s["cierre"] - v["banda_baja"]) / (v["banda_alta"] - v["banda_baja"]),
                               places=12)
        self.assertAlmostEqual(v["atr"], 2.0, places=9)
        self.assertAlmostEqual(v["atr_relativo"], 2.0 / 499.0, places=12)
        self.assertEqual((s["volumen"]["relativo"], s["volumen"]["obv_relativo"]), (1.0, 1.0))
        self.assertEqual(s["estructura"]["maximo"], s["cierre"])
        self.assertFalse(s["estructura"]["rompio_maximo"])
        self.assertAlmostEqual(s["cambio"], 1 / 498.0, places=12)

    def test_una_serie_sin_historial_no_trae_ninguna_familia(self):
        s = lib_indicadores.de_serie("ETHFDUSD", "4h", AHORA, lib_indicadores_mercado.valores)
        self.assertEqual((s["listo"], s["motivo"]), (False, "sin_datos"))
        for familia in ("cambio", "volatilidad", "volumen", "estructura"):
            self.assertNotIn(familia, s)           # una familia más no relaja la continuidad: sin velas, ningún número

    def test_el_contexto_es_btc_en_un_dia(self):
        sin = lib_indicadores_mercado.contexto([])
        self.assertEqual((sin["listo"], sin["motivo"], sin["par"]), (False, "sin_datos", "BTCUSDT"))
        lib_datos.guardar_serie("BTCUSDT", "1d", velas_que_suben(lib_indicadores.VENTANA, "1d"))
        c = lib_indicadores_mercado.estado(AHORA)["contexto"]
        self.assertEqual((c["listo"], c["motivo"], c["temporalidad"]), (True, "", "1d"))
        self.assertTrue(c["sobre_media"])                              # 400 días subiendo de a 1
        self.assertAlmostEqual(c["cambio"], 1 / 498.0, places=12)
        self.assertAlmostEqual(c["distancia_media"], (499.0 - 399.5) / 399.5, places=12)
        lib_datos.guardar_serie("BTCUSDT", "1d", velas_que_suben(lib_indicadores.VENTANA, "1d", desde=900.0, sube=-1.0))
        cae = lib_indicadores_mercado.estado(AHORA)["contexto"]
        self.assertFalse(cae["sobre_media"])
        self.assertLess(cae["cambio"], 0)

    def test_el_costo_sale_de_la_ultima_muestra_del_libro(self):
        sin = lib_indicadores_mercado.costo(AHORA)
        self.assertEqual((sin["listo"], sin["origen"]), (False, "supuesto"))
        self.assertEqual({m["codigo"] for m in sin["motivos"]}, {"sin_muestras"})
        self.assertTrue(all(p["total"] is None for p in sin["pares"]))
        muestra_guardada(AHORA - 60_000)
        c = lib_indicadores_mercado.costo(AHORA)
        self.assertTrue(c["listo"])
        p = c["pares"][0]
        self.assertEqual((p["par"], p["motivo"], p["cuantas"]), ("BTCFDUSD", "", 1))
        self.assertAlmostEqual(p["spread_relativo"], 0.3 / 95000.25, places=15)
        # Entrar es maker, salir por el stop es taker, y hay que convertir USDT↔FDUSD: el mismo orden del capital mínimo.
        self.assertAlmostEqual(p["total"], 0.0005 + 0.001 + 0.3 / 95000.25, places=15)

    def test_una_muestra_vieja_o_rara_no_da_costo(self):
        minutos = lib_indicadores_mercado.MUESTRA_VIGENTE_MIN + 1
        muestra_guardada(AHORA - minutos * 60_000)
        vieja = lib_indicadores_mercado.costo(AHORA)
        self.assertFalse(vieja["listo"])
        self.assertEqual({m["codigo"] for m in vieja["motivos"]}, {"muestra_vieja"})
        self.assertEqual((vieja["pares"][0]["cuantas"], vieja["pares"][0]["total"]), (minutos, None))
        # Un archivo tocado a mano no da números: ni una diferencia imposible, ni una fecha que no puede ser, ni un texto.
        for ultima in ({"ms": AHORA - 60_000, "pares": [{"par": "BTCFDUSD", "compra": 95000.1, "venta": 95000.4,
                                                         "spread_relativo": 0.9}]},
                       {"ms": AHORA + 3 * lib_datos.DIA_MS, "pares": [{"par": "BTCFDUSD", "compra": 95000.1,
                                                                       "venta": 95000.4, "spread_relativo": 3.2e-06}]},
                       {"ms": "ayer", "pares": []}):
            lib_trabajo.guardar_plan("muestreo", {"formato": 1, "ultima": ultima})
            raro = lib_indicadores_mercado.costo(AHORA)
            self.assertEqual({m["codigo"] for m in raro["motivos"]}, {"sin_muestras"})
            self.assertTrue(all(p["spread_relativo"] is None for p in raro["pares"]))

    def test_el_estado_pide_las_series_el_contexto_y_el_costo(self):
        for par in lib_datos.PARES:
            for temporalidad in lib_datos.TEMPORALIDADES:
                lib_datos.guardar_serie(par, temporalidad, velas_que_suben(lib_indicadores.VENTANA, temporalidad))
        sin_costo = lib_indicadores_mercado.estado(AHORA)
        self.assertEqual(sin_costo["listas"], 12)
        self.assertTrue(sin_costo["contexto"]["listo"])
        self.assertFalse(sin_costo["listo"])      # las 12 series al día, pero sin muestra del libro no hay costo
        muestra_guardada(AHORA)
        e = indicadores.estado({}, AHORA)["datos"]
        self.assertTrue(e["listo"])
        self.assertEqual((e["bollinger"], e["atr"], e["volumen"], e["ruptura"]),
                         ([lib_indicadores_mercado.BOLLINGER_VELAS, lib_indicadores_mercado.BOLLINGER_DESVIOS],
                          lib_indicadores_mercado.ATR_PERIODO, lib_indicadores_mercado.VOLUMEN_VELAS,
                          lib_indicadores_mercado.RUPTURA_VELAS))
        self.assertTrue(all("estructura" in s for s in e["series"]))
        with open(lib_indicadores.ruta_indicadores(), encoding="utf-8") as f:
            escrito = json.load(f)                # lo leen el puntaje y el motor sin recorrer las velas de nuevo
        self.assertEqual([p["par"] for p in escrito["costo"]["pares"]], list(lib_datos.PARES_OPERADOS))
        self.assertTrue(escrito["contexto"]["listo"])


class AccionIndicadores(unittest.TestCase):
    def test_sin_historial_se_dice_que_falta_en_vez_de_mostrar_un_numero(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            r = correr("indicadores.py", "estado", entrada={}, datos=datos)
            self.assertTrue(r["ok"])
            self.assertFalse(r["datos"]["listo"])
            self.assertEqual(r["datos"]["ventana"], lib_indicadores.VENTANA)
            self.assertEqual(len(r["datos"]["series"]), 12)
            self.assertEqual({m["codigo"] for m in r["datos"]["motivos"]}, {"sin_datos"})
            self.assertFalse(any("tendencia" in s for s in r["datos"]["series"]))
            self.assertFalse(any("volatilidad" in s for s in r["datos"]["series"]))
            # Sin velas tampoco hay contexto, y sin muestra del libro tampoco hay costo: cada uno con su motivo.
            self.assertEqual(r["datos"]["contexto"]["motivo"], "sin_datos")
            costo = r["datos"]["costo"]
            self.assertEqual((costo["listo"], costo["origen"]), (False, "supuesto"))
            self.assertEqual({m["codigo"] for m in costo["motivos"]}, {"sin_muestras"})
            with open(os.path.join(datos, "mercado", "indicadores.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["motivos"], r["datos"]["motivos"])


class EstrategiasConocidas(unittest.TestCase):
    """Las tres estrategias y el filtro de BTC, con números redondos: las reglas se leen en la prueba."""

    def vela(self, **cambios):
        """Lo que una vela le da a las estrategias (lo que arma `vela_de`): cada prueba cambia solo lo que mira."""
        v = {"par": "BTCFDUSD", "temporalidad": "4h", "ms": AHORA, "cierre": 101.0, "maximo": 100.0,
             "rompio_maximo": True, "relativo": 2.0, "atr": 2.0, "banda_baja": 100.0, "banda_media": 110.0,
             "posicion": 0.0, "adx": 15.0}
        v.update(cambios)
        return v

    def test_la_ruptura_entra_con_limite_en_el_nivel_roto(self):
        s = lib_estrategias.ruptura(self.vela(), True)
        self.assertEqual((s["estrategia"], s["lado"], s["orden"]), ("ruptura", "compra", "limite"))
        self.assertEqual(s["entrada"], 100.0)            # el nivel roto, no el cierre: se espera a que el precio vuelva
        self.assertEqual(s["stop"], 100.0 - lib_estrategias.STOP_ATR_RUPTURA * 2.0)
        self.assertAlmostEqual(s["objetivo"], 100.0 * (1 + lib_estrategias.OBJETIVO_RUPTURA), places=9)
        self.assertAlmostEqual(s["distancia_stop"], 0.03, places=12)
        self.assertAlmostEqual(s["distancia_objetivo"], lib_estrategias.OBJETIVO_RUPTURA, places=12)
        self.assertEqual(s["vence"], AHORA + (lib_estrategias.VIGENCIA_VELAS + 1) * lib_datos.PASO_MS["4h"])

    def test_la_ruptura_pide_volumen_y_el_dia_al_alza(self):
        for al_alza in (None, False):                    # la tendencia diaria no se supone: sin saberla no se entra
            self.assertIsNone(lib_estrategias.ruptura(self.vela(), al_alza))
        self.assertIsNone(lib_estrategias.ruptura(self.vela(rompio_maximo=False), True))
        self.assertIsNone(lib_estrategias.ruptura(self.vela(relativo=1.0), True))
        self.assertIsNone(lib_estrategias.ruptura(self.vela(atr=None), True))
        self.assertIsNone(lib_estrategias.ruptura(self.vela(atr=1000.0), True))   # el stop quedaría bajo cero

    def test_el_rebote_entra_en_la_banda_de_abajo_y_sale_en_la_media(self):
        s = lib_estrategias.rebote(self.vela(cierre=99.0))
        self.assertEqual((s["estrategia"], s["entrada"], s["stop"], s["objetivo"]), ("rebote", 99.0, 97.0, 110.0))
        # Con el precio todavía sobre la banda, la entrada es la banda: una compra post-only no va sobre el precio.
        self.assertEqual(lib_estrategias.rebote(self.vela(cierre=100.5, posicion=0.02))["entrada"], 100.0)
        self.assertIsNone(lib_estrategias.rebote(self.vela(adx=30.0)))            # con tendencia no es un rango
        self.assertIsNone(lib_estrategias.rebote(self.vela(posicion=0.5)))        # en medio de la banda no es rebote
        self.assertIsNone(lib_estrategias.rebote(self.vela(banda_media=99.0)))    # el objetivo no puede quedar abajo
        self.assertIsNone(lib_estrategias.rebote(self.vela(atr=None)))

    def test_si_btc_cae_el_filtro_no_deja_entrar(self):
        self.assertEqual(lib_estrategias.filtro_btc(None)["motivo"], "sin_contexto")
        self.assertEqual(lib_estrategias.filtro_btc({"cambio": 0.01, "sobre_media": None})["motivo"], "sin_contexto")
        cae = lib_estrategias.filtro_btc({"cambio": -lib_estrategias.CAIDA_BTC, "sobre_media": True})
        self.assertEqual((cae["pasa"], cae["motivo"]), (False, "btc_cae"))
        bajo = lib_estrategias.filtro_btc({"cambio": 0.01, "sobre_media": False})
        self.assertEqual((bajo["pasa"], bajo["motivo"]), (False, "btc_bajo_media"))
        bien = lib_estrategias.filtro_btc({"cambio": 0.01, "sobre_media": True})
        self.assertEqual((bien["pasa"], bien["motivo"], bien["par"]), (True, "", "BTCUSDT"))

    def test_la_tendencia_diaria_y_el_filtro_no_miran_el_futuro(self):
        paso, larga = lib_datos.PASO_MS["1d"], lib_indicadores.MEDIAS[-1]
        velas = velas_que_suben(lib_indicadores.VENTANA, "1d")
        al_alza = lib_estrategias.al_alza_en(velas)
        self.assertIsNone(al_alza(velas[0][0]))                  # antes de que cierre la primera vela no se sabe nada
        self.assertIsNone(lib_estrategias.tendencia_diaria(velas)[larga - 2])
        self.assertIsNone(al_alza(velas[larga - 2][0] + paso))   # la media de 200 recién existe en la vela 200
        self.assertTrue(al_alza(velas[larga - 1][0] + paso))
        self.assertTrue(al_alza(velas[-1][0] + paso))
        baja = velas_que_suben(lib_indicadores.VENTANA, "1d", desde=900.0, sube=-1.0)
        self.assertFalse(lib_estrategias.al_alza_en(baja)(baja[-1][0] + paso))
        c = lib_estrategias.contexto_diario(velas)[-1]
        self.assertAlmostEqual(c["cambio"], 1 / 498.0, places=12)
        self.assertTrue(c["sobre_media"])
        self.assertTrue(lib_estrategias.filtro_en(velas)(velas[-1][0] + paso)["pasa"])
        frenado = lib_estrategias.filtro_en(baja)(baja[-1][0] + paso)
        self.assertEqual((frenado["pasa"], frenado["motivo"]), (False, "btc_bajo_media"))
        self.assertEqual(lib_estrategias.filtro_en(velas)(velas[0][0])["motivo"], "sin_contexto")

    def test_de_velas_mira_cada_vela_de_la_serie(self):
        velas = velas_que_suben(60, "1h")
        pasa = lambda ms: lib_estrategias.filtro_btc({"cambio": 0.01, "sobre_media": True})   # noqa: E731
        subiendo = lib_estrategias.de_velas("BTCFDUSD", "1h", velas, al_alza=lambda ms: True, filtro=pasa)
        self.assertEqual(len(subiendo), len(velas))
        # Subiendo parejo, el cierre pega justo en el techo (tocarlo no es romperlo) y queda en la banda de arriba: nada.
        self.assertEqual([s for vela in subiendo for s in vela], [])
        con_salto = [*velas[:-1], [velas[-1][0], 159.0, 170.0, 158.0, 169.0, 40.0]]
        s = lib_estrategias.de_velas("BTCFDUSD", "1h", con_salto, al_alza=lambda ms: True, filtro=pasa)[-1][0]
        self.assertEqual((s["estrategia"], s["entrada"]), ("ruptura", 159.0))
        self.assertLess(s["stop"], s["entrada"])
        self.assertLess(s["entrada"], s["objetivo"])
        self.assertTrue(s["permitida"])
        # Sin el contexto de BTC la señal se ve, pero no se puede entrar; sin la tendencia diaria no se mira siquiera.
        sin_filtro = lib_estrategias.de_velas("BTCFDUSD", "1h", con_salto, al_alza=lambda ms: True)[-1][0]
        self.assertEqual((sin_filtro["permitida"], sin_filtro["filtro"]), (False, "sin_contexto"))
        self.assertEqual(lib_estrategias.de_velas("BTCFDUSD", "1h", con_salto, filtro=pasa)[-1], [])


class SenalesDeLasSeries(ConCarpeta):
    """Las señales de ahora sobre lo guardado: las cuatro series de entrada, el filtro de BTC y quedarse en USDT."""

    def guardar_todo(self):
        for par in lib_datos.PARES:
            for temporalidad in lib_datos.TEMPORALIDADES:
                lib_datos.guardar_serie(par, temporalidad, velas_que_suben(lib_indicadores.VENTANA, temporalidad))

    def con_ruptura(self, par, temporalidad):
        """Cambia la última vela guardada por una que rompe el techo de las anteriores con volumen. Devuelve el nivel."""
        velas = lib_datos.leer_serie(par, temporalidad)
        ultima = velas[-1]
        techo = max(v[2] for v in velas[-1 - lib_indicadores_mercado.RUPTURA_VELAS:-1])
        velas[-1] = [ultima[0], techo, techo + 11.0, techo - 1.0, techo + 10.0, ultima[5] * 4]
        lib_datos.guardar_serie(par, temporalidad, velas)
        return techo

    def fila(self, e, par, temporalidad):
        return next(s for s in e["series"] if (s["par"], s["temporalidad"]) == (par, temporalidad))

    def test_sin_historial_no_hay_ninguna_senal_y_se_dice_que_falta(self):
        e = lib_estrategias.estado(AHORA)
        self.assertFalse(e["listo"])
        self.assertEqual((e["senales"], e["entrables"]), ([], 0))
        self.assertEqual([(s["par"], s["temporalidad"]) for s in e["series"]],
                         [(p, t) for p in lib_datos.PARES_OPERADOS for t in lib_estrategias.TEMPORALIDADES_SENAL])
        self.assertEqual({m["codigo"] for m in e["motivos"]}, {"sin_contexto", "sin_tendencia_diaria", "sin_datos"})
        self.assertEqual((e["filtro"]["pasa"], e["filtro"]["motivo"]), (False, "sin_contexto"))
        self.assertEqual(e["usdt"]["razon"], "btc")      # con el filtro frenado, quedarse es la única salida
        self.assertTrue(all(s["al_alza"] is None for s in e["series"]))

    def test_con_todo_al_dia_y_sin_gatillo_no_se_inventa_ninguna_senal(self):
        self.guardar_todo()
        e = lib_estrategias.estado(AHORA)
        self.assertTrue(e["listo"])                      # las cuatro series, el contexto de BTC y los dos días al alza
        self.assertTrue(e["filtro"]["pasa"])
        self.assertTrue(all(s["al_alza"] for s in e["series"]))
        self.assertEqual((e["senales"], e["entrables"]), ([], 0))
        self.assertEqual(e["usdt"]["razon"], "sin_oportunidad")

    def test_una_ruptura_con_volumen_y_el_dia_al_alza_da_su_senal(self):
        self.guardar_todo()
        techo = self.con_ruptura("BTCFDUSD", "4h")
        e = lib_estrategias.estado(AHORA)
        self.assertEqual(e["entrables"], 1)
        s = e["senales"][0]
        self.assertEqual((s["estrategia"], s["par"], s["temporalidad"]), ("ruptura", "BTCFDUSD", "4h"))
        self.assertEqual((s["entrada"], s["permitida"]), (techo, True))
        self.assertAlmostEqual(s["distancia_objetivo"], lib_estrategias.OBJETIVO_RUPTURA, places=12)
        self.assertEqual(self.fila(e, "BTCFDUSD", "4h")["senales"], [s])
        self.assertEqual(self.fila(e, "BTCFDUSD", "1h")["senales"], [])
        self.assertEqual(e["usdt"]["razon"], "hay_oportunidades")

    def test_un_rebote_en_la_banda_de_abajo_con_el_adx_bajo_da_su_senal(self):
        self.guardar_todo()
        velas = velas_que_van_y_vienen(lib_indicadores.VENTANA, "1h")
        velas[-1] = [velas[-1][0], 100.0, 100.5, 98.0, 98.5, 10.0]   # una caída bajo la banda, sin tendencia
        lib_datos.guardar_serie("ETHFDUSD", "1h", velas)
        e = lib_estrategias.estado(AHORA)
        s = self.fila(e, "ETHFDUSD", "1h")["senales"][0]
        self.assertEqual((s["estrategia"], s["entrada"], s["permitida"]), ("rebote", 98.5, True))
        self.assertLess(s["stop"], s["entrada"])
        self.assertLess(s["entrada"], s["objetivo"])     # el objetivo es la media de la banda
        self.assertEqual(e["entrables"], 1)

    def test_si_btc_cae_la_senal_se_ve_pero_no_se_puede_entrar(self):
        self.guardar_todo()
        self.con_ruptura("ETHFDUSD", "4h")
        lib_datos.guardar_serie("BTCUSDT", "1d",
                                velas_que_suben(lib_indicadores.VENTANA, "1d", desde=900.0, sube=-1.0))
        e = lib_estrategias.estado(AHORA)
        self.assertEqual((e["filtro"]["pasa"], e["filtro"]["motivo"]), (False, "btc_bajo_media"))
        self.assertEqual(len(e["senales"]), 1)           # la señal cruda sigue estando: lo que no se puede es entrar
        self.assertEqual((e["senales"][0]["permitida"], e["senales"][0]["filtro"]), (False, "btc_bajo_media"))
        self.assertEqual((e["entrables"], e["usdt"]["razon"]), (0, "btc"))
        self.assertFalse(self.fila(e, "BTCFDUSD", "4h")["al_alza"])   # y el día de BTC tampoco viene al alza

    def test_sin_la_serie_de_un_dia_la_ruptura_de_ese_par_no_se_mira(self):
        self.guardar_todo()
        self.con_ruptura("ETHFDUSD", "1h")
        lib_datos.guardar_serie("ETHUSDT", "1d", [])     # la serie con la que se mide el día de ETH
        e = lib_estrategias.estado(AHORA)
        self.assertEqual(e["senales"], [])
        fila = self.fila(e, "ETHFDUSD", "1h")
        self.assertTrue(fila["listo"])                   # la serie de entrada está al día: lo que falta es la de 1 d
        self.assertIsNone(fila["al_alza"])
        self.assertEqual(fila["par_diario"], "ETHUSDT")
        self.assertIn({"codigo": "sin_tendencia_diaria", "par": "ETHUSDT", "temporalidad": "1d",
                       "n": lib_indicadores.VENTANA}, e["motivos"])
        self.assertFalse(e["listo"])
        self.assertTrue(self.fila(e, "BTCFDUSD", "1h")["al_alza"])    # al otro par no le falta nada

    def test_las_senales_pueden_salir_de_los_indicadores_ya_calculados(self):
        self.guardar_todo()
        ya = lib_indicadores_mercado.estado(AHORA)       # el motor calcula los indicadores una sola vez y los pasa
        self.assertEqual(lib_estrategias.estado(AHORA, ya), lib_estrategias.estado(AHORA))

    def test_el_estado_queda_escrito_para_el_backtest_y_el_motor(self):
        self.guardar_todo()
        e = senales.estado({}, AHORA)["datos"]
        with open(lib_estrategias.ruta_senales(), encoding="utf-8") as f:
            escrito = json.load(f)
        self.assertEqual((escrito["cuando"], escrito["motivos"]), (e["cuando"], e["motivos"]))
        self.assertEqual(escrito["estrategias"], ["ruptura", "rebote", "usdt"])
        self.assertEqual(escrito["parametros"]["volumen_ruptura"], lib_estrategias.VOLUMEN_RUPTURA)
        self.assertEqual(escrito["temporalidades"], list(lib_estrategias.TEMPORALIDADES_SENAL))


class AccionSenales(unittest.TestCase):
    def test_sin_historial_no_hay_senales_en_vez_de_una_entrada_inventada(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            r = correr("senales.py", "estado", entrada={}, datos=datos)
            self.assertTrue(r["ok"])
            self.assertFalse(r["datos"]["listo"])
            self.assertEqual(r["datos"]["senales"], [])
            self.assertEqual(len(r["datos"]["series"]), 4)
            self.assertEqual(r["datos"]["filtro"]["motivo"], "sin_contexto")
            self.assertEqual(r["datos"]["usdt"]["razon"], "btc")
            self.assertEqual({m["codigo"] for m in r["datos"]["motivos"]},
                             {"sin_contexto", "sin_tendencia_diaria", "sin_datos"})
            with open(os.path.join(datos, "mercado", "senales.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["motivos"], r["datos"]["motivos"])


def serie_con_una_operacion(temporalidad="1h", n=None, como="objetivo"):
    """Una serie que sube parejo y, cuatro velas antes del final, una operación completa: la vela que rompe el techo con
    volumen (la señal), la que vuelve al nivel (ahí se llena la orden límite) y la que cierra la operación. `como` dice en
    qué termina: en el objetivo, en el stop, o en una vela que tocó los dos (la ambigua). Devuelve las velas y el nivel."""
    velas = velas_que_suben(n or lib_indicadores.VENTANA, temporalidad)
    i = len(velas) - 4
    nivel = max(v[2] for v in velas[i - lib_indicadores_mercado.RUPTURA_VELAS:i])
    # La ruptura: cierra sobre el techo de las 20 anteriores con 4 veces el volumen de siempre.
    velas[i] = [velas[i][0], nivel, nivel + 11.0, nivel - 1.0, nivel + 10.0, 40.0]
    # La vuelta al nivel: el precio lo atraviesa (ahí se llena) sin llegar al stop ni al objetivo.
    velas[i + 1] = [velas[i + 1][0], nivel + 2.0, nivel + 2.0, nivel - 1.0, nivel, 10.0]
    arriba = nivel + 20.0 if como != "stop" else nivel + 0.5
    abajo = nivel - 10.0 if como != "objetivo" else nivel - 0.5
    velas[i + 2] = [velas[i + 2][0], nivel, arriba, abajo, nivel + (15.0 if como != "stop" else -9.0), 10.0]
    return velas, nivel


def una_operacion(estrategia="ruptura", par="BTCFDUSD", temporalidad="1h", entrada=0, salida=1, neto=0.01,
                  permitida=True, motivo=""):
    """Una operación ya recorrida, como la deja `backtest.seguir`: lo justo para probar la compuerta."""
    return {"estrategia": estrategia, "par": par, "temporalidad": temporalidad, "senal_ms": entrada,
            "permitida": permitida, "filtro": "", "nivel": 100.0, "limite": 99.95, "stop": 98.0, "objetivo": 101.5,
            "llenada": True, "entrada_ms": entrada, "salida_ms": salida, "velas": 1, "por": "objetivo",
            "bruto": neto, "neto": neto, "costos": 0.0015, "ambigua": False, "motivo": motivo}


def operaciones_seguidas(estrategia, par, temporalidad, cuantas, tramo=0):
    """`cuantas` operaciones que no se pisan entre sí, en un rato que no se pisa con los de otro tramo: así los casos de la
    compuerta se cuentan de memoria."""
    paso = lib_datos.PASO_MS["1h"]
    desde = tramo * 2000 * paso
    return [una_operacion(estrategia, par, temporalidad, desde + i * 2 * paso, desde + (i * 2 + 1) * paso)
            for i in range(cuantas)]


class CostosDeUnaOperacion(unittest.TestCase):
    """Los costos de cada lado y el no llenado condicionado, con números que se leen en la prueba."""

    COM = {"maker": 0.0, "taker": 0.001, "conversion": 0.0005, "origen": "supuesto"}

    def test_salir_por_el_objetivo_paga_maker_y_salir_por_el_stop_paga_taker_y_el_spread(self):
        gana = lib_costos.resultado(100.0, 101.5, "objetivo", 0.0005, self.COM)
        self.assertEqual(gana["precio_salida"], 101.5)        # una límite no cruza el libro: no paga la diferencia
        self.assertAlmostEqual(gana["bruto"], 0.015, places=12)
        self.assertAlmostEqual(gana["neto"], (101.5 * 0.9995 - 100.05) / 100.05, places=12)
        self.assertLess(gana["neto"], gana["bruto"])          # entre los dos está lo que se lleva operar
        pierde = lib_costos.resultado(100.0, 98.0, "stop", 0.0005, self.COM)
        self.assertAlmostEqual(pierde["precio_salida"], 98.0 * (1 - 0.0005), places=12)
        self.assertAlmostEqual(pierde["bruto"], -0.02, places=12)
        self.assertAlmostEqual(pierde["neto"], (98.0 * 0.9995 * 0.9985 - 100.05) / 100.05, places=12)
        self.assertGreater(pierde["costos"], gana["costos"])  # el stop es taker y además cruza el libro

    def test_una_limite_se_llena_cuando_el_precio_sigue_en_contra(self):
        self.assertEqual(lib_costos.margen_llenado(0.0005, 2.0), 0.001)
        self.assertTrue(lib_costos.llena(100.0, 100.0, 0.0005, 0.0))     # con el factor en 0, tocarla basta
        self.assertFalse(lib_costos.llena(100.0, 100.0, 0.0005))         # tocarla no alcanza: hay cola en ese precio
        self.assertFalse(lib_costos.llena(100.0, 99.96, 0.0005))
        self.assertTrue(lib_costos.llena(100.0, 99.94, 0.0005))
        self.assertFalse(lib_costos.llena(100.0, 99.94, 0.0005, 3.0))    # cuanto más se pide, menos se llena

    def test_el_percentil_es_un_valor_que_de_verdad_paso(self):
        self.assertIsNone(lib_costos.percentil([], 0.9))
        self.assertEqual(lib_costos.percentil([3.0, 1.0, 2.0], 0.9), 3.0)
        self.assertEqual(lib_costos.percentil(list(range(10)), 0.9), 8)


class ModeloDeSpread(ConCarpeta):
    """De dónde sale la diferencia entre compra y venta con la que se recorre el historial."""

    def guardar_muestras(self, dias, spread=0.00002):
        for d in range(dias):
            for par in lib_datos.PARES_OPERADOS:
                lib_datos.guardar_muestra({"ms": AHORA - d * lib_datos.DIA_MS, "par": par, "compra": 100.0,
                                           "venta": 100.002, "spread": 0.002,
                                           "spread_relativo": spread * (1 + d / 100), "trades": []})

    def test_sin_muestras_propias_el_spread_es_el_supuesto_conservador(self):
        m = lib_costos.modelo()
        self.assertEqual((m["origen"], m["listo"], m["dias"]), ("supuesto", False, 0))
        self.assertEqual(m["falta_dias"], lib_costos.DIAS_MODELO)
        self.assertEqual([p["spread"] for p in m["pares"]], [lib_costos.SPREAD_SUPUESTO] * 2)
        self.assertEqual(lib_costos.spread_de(m, "BTCFDUSD"), lib_costos.SPREAD_SUPUESTO)
        self.assertEqual(lib_costos.spread_de(None, "BTCFDUSD"), lib_costos.SPREAD_SUPUESTO)

    def test_con_pocos_dias_el_supuesto_sigue_mandando(self):
        self.guardar_muestras(10)
        m = lib_costos.modelo()
        self.assertEqual((m["origen"], m["dias"], m["falta_dias"]), ("supuesto", 10, lib_costos.DIAS_MODELO - 10))
        self.assertEqual(m["muestras"], 20)
        self.assertIsNotNone(m["pares"][0]["propio"])          # ya se mide, pero todavía no manda
        self.assertEqual(m["pares"][0]["spread"], lib_costos.SPREAD_SUPUESTO)

    def test_con_sesenta_dias_de_muestras_propias_manda_lo_medido(self):
        self.guardar_muestras(lib_costos.DIAS_MODELO)
        m = lib_costos.modelo()
        esperado = 0.00002 * (1 + 53 / 100)                    # el percentil 90 de los 60 días, no el promedio
        self.assertEqual((m["origen"], m["listo"], m["dias"]), ("propio", True, lib_costos.DIAS_MODELO))
        self.assertAlmostEqual(m["pares"][0]["spread"], esperado, places=12)
        self.assertAlmostEqual(lib_costos.spread_de(m, "ETHFDUSD"), esperado, places=12)
        self.assertLess(lib_costos.spread_de(m, "BTCFDUSD"), lib_costos.SPREAD_SUPUESTO)

    def test_una_linea_que_no_se_entiende_no_cuenta_y_el_resto_sirve(self):
        self.guardar_muestras(2)
        with open(lib_datos.ruta_muestras(AHORA), "a", encoding="utf-8") as f:
            f.write("esto no es json\n")
            f.write('{"ms": 0, "par": "BTCFDUSD", "spread_relativo": 0.00001}\n')
            f.write('{"ms": %d, "par": "BTCFDUSD", "spread_relativo": 2.0}\n' % AHORA)
            f.write('{"ms": %d, "par": "LTCUSDT", "spread_relativo": 0.00001}\n' % AHORA)
        self.assertEqual(lib_costos.modelo()["muestras"], 4)


class BacktestDeSenalesCrudas(ConCarpeta):
    """El recorrido del historial: empalme, llenado condicionado, salida y costos."""

    COM = {"maker": 0.0, "taker": 0.001, "conversion": 0.0005, "origen": "supuesto"}

    def guardar_todo(self):
        for par in lib_datos.PARES:
            for temporalidad in lib_datos.TEMPORALIDADES:
                lib_datos.guardar_serie(par, temporalidad, velas_que_suben(lib_indicadores.VENTANA, temporalidad))

    def recorrido(self, velas, temporalidad="1h", factor=lib_costos.PENETRACION_SPREADS, al_alza=True):
        """Las señales crudas de esa serie y su recorrido, con el filtro de BTC dejando entrar."""
        pasa = lambda ms: lib_estrategias.filtro_btc({"cambio": 0.01, "sobre_media": True})   # noqa: E731
        senales = backtest.senales_de("BTCFDUSD", temporalidad, velas, al_alza=lambda ms: al_alza, filtro=pasa)
        return backtest.recorrer(velas, senales, lib_costos.SPREAD_SUPUESTO, self.COM, factor)

    def test_la_senal_se_llena_recien_en_la_vela_siguiente_y_cierra_en_el_objetivo(self):
        velas, nivel = serie_con_una_operacion()
        ops = self.recorrido(velas)
        self.assertEqual(len(ops), 1)
        o = ops[0]
        self.assertEqual((o["estrategia"], o["por"], o["motivo"]), ("ruptura", "objetivo", ""))
        self.assertEqual(o["nivel"], nivel)
        self.assertEqual(o["limite"], nivel * (1 - lib_costos.SPREAD_SUPUESTO))
        self.assertGreater(o["entrada_ms"], o["senal_ms"])     # nunca se llena en la vela que la decidió
        self.assertEqual(o["velas"], 2)
        self.assertAlmostEqual(o["bruto"], lib_estrategias.OBJETIVO_RUPTURA, places=12)
        self.assertLess(o["neto"], o["bruto"])                 # los costos de los dos lados ya están restados
        self.assertFalse(o["ambigua"])

    def test_una_limite_que_el_precio_no_atraviesa_no_es_una_operacion(self):
        velas, nivel = serie_con_una_operacion()
        ops = self.recorrido(velas, factor=200.0)              # pedirle mucha penetración: no se llena ninguna
        self.assertEqual((len(ops), ops[0]["llenada"], ops[0]["motivo"]), (1, False, "sin_llenar"))
        self.assertIsNone(ops[0]["neto"])
        r = backtest.resumen(ops)
        self.assertEqual((r["senales"], r["llenadas"], r["operaciones"], r["sin_llenar"]), (1, 0, 0, 1))
        self.assertIsNone(r["aciertos"])                       # con cero operaciones no se inventa un acierto

    def test_una_vela_que_toco_el_stop_y_el_objetivo_se_cuenta_como_stop(self):
        velas, _ = serie_con_una_operacion(como="ambas")
        o = self.recorrido(velas)[0]
        self.assertEqual((o["por"], o["ambigua"]), ("stop", True))
        self.assertLess(o["neto"], 0)
        self.assertEqual(backtest.resumen([o])["ambiguas"], 1)
        perdiendo = self.recorrido(serie_con_una_operacion(como="stop")[0])[0]
        self.assertEqual((perdiendo["por"], perdiendo["ambigua"]), ("stop", False))

    def test_el_supuesto_de_la_vela_ambigua_se_revisa_con_las_velas_de_un_minuto(self):
        paso, minuto = lib_datos.PASO_MS["1h"], lib_datos.PASO_MS[lib_datos.MINUTO]
        apertura = (AHORA // paso) * paso - paso
        o = dict(una_operacion(), ambigua=True, salida_ms=apertura + paso, stop=99.0, objetivo=110.0)
        quietas = [[apertura + i * minuto, 102.0, 105.0, 100.0, 102.0, 1.0] for i in range(paso // minuto)]
        sube = [*quietas]
        sube[30] = [apertura + 30 * minuto, 102.0, 111.0, 100.0, 110.5, 1.0]
        d = backtest.validar_ambiguas([o], {"BTCFDUSD": sube})
        self.assertEqual((d["velas"], d["con_1m"], d["objetivo_primero"], d["stop_primero"]), (1, 1, 1, 0))
        self.assertEqual((d["supuesto"], d["acierto"]), ("stop_primero", 0.0))   # esa vez el supuesto se equivocó
        baja = [*quietas]
        baja[10] = [apertura + 10 * minuto, 102.0, 105.0, 98.0, 99.0, 1.0]
        self.assertEqual(backtest.validar_ambiguas([o], {"BTCFDUSD": baja})["acierto"], 1.0)
        # Sin la ventana de 1 m completa no se revisa nada: media ventana no dice qué se cruzó primero.
        a_medias = backtest.validar_ambiguas([o], {"BTCFDUSD": sube[:20]})
        self.assertEqual((a_medias["velas"], a_medias["con_1m"], a_medias["acierto"]), (1, 0, None))

    def test_el_calentamiento_no_da_operaciones(self):
        velas, _ = serie_con_una_operacion()
        corta = velas[-(lib_indicadores.VELAS_CALENTAMIENTO - 100):]
        self.assertEqual(self.recorrido(corta), [])            # la señal cae dentro del calentamiento: no cuenta
        self.assertEqual(len(self.recorrido(velas)), 1)

    def test_sin_la_tendencia_diaria_la_ruptura_no_se_mira(self):
        velas, _ = serie_con_una_operacion()
        self.assertEqual(self.recorrido(velas, al_alza=None), [])
        self.assertEqual(self.recorrido(velas, al_alza=False), [])

    def test_el_empalme_usa_el_par_contra_usdt_y_lo_marca(self):
        self.guardar_todo()
        velas, e = backtest.empalmar("BTCFDUSD", "1h")
        self.assertEqual((e["empalmada"], e["prestadas"], e["motivo"]), (False, 0, ""))
        # El par contra FDUSD empieza más tarde: lo de antes se pide prestado al par contra USDT.
        lib_datos.guardar_serie("BTCFDUSD", "1h", velas_que_suben(100, "1h", desde=400.0))
        velas, e = backtest.empalmar("BTCFDUSD", "1h")
        self.assertEqual((e["empalmada"], e["par_prestado"]), (True, "BTCUSDT"))
        self.assertEqual((e["propias"], e["prestadas"], e["velas"]), (100, 300, lib_indicadores.VENTANA))
        self.assertEqual(e["corte"], velas[-100][0])
        self.assertEqual((e["motivo"], e["huecos"]), ("", 0))
        self.assertEqual(len(velas), len(lib_datos.leer_serie("BTCUSDT", "1h")))
        self.assertEqual(lib_datos.huecos(velas, "1h"), [])    # el empalme no deja un hoyo en el medio

    def test_una_serie_vacia_corta_o_con_hoyos_no_se_recorre(self):
        _, e = backtest.empalmar("ETHFDUSD", "4h")
        self.assertEqual((e["motivo"], e["faltan"]), ("sin_datos", backtest.VELAS_MINIMAS))
        lib_datos.guardar_serie("ETHFDUSD", "4h", velas_que_suben(50, "4h"))
        lib_datos.guardar_serie("ETHUSDT", "4h", [])
        _, e = backtest.empalmar("ETHFDUSD", "4h")
        self.assertEqual((e["motivo"], e["faltan"]), ("faltan_velas", backtest.VELAS_MINIMAS - 50))
        velas = velas_que_suben(lib_indicadores.VENTANA, "4h")
        lib_datos.guardar_serie("ETHFDUSD", "4h", [*velas[:10], *velas[12:]])
        _, e = backtest.empalmar("ETHFDUSD", "4h")
        self.assertEqual((e["motivo"], e["huecos"]), ("huecos", 1))

    def test_la_compuerta_no_cuenta_dos_veces_las_que_se_solapan(self):
        paso = lib_datos.PASO_MS["1h"]
        pisadas = [una_operacion(entrada=0, salida=10 * paso), una_operacion(entrada=5 * paso, salida=15 * paso),
                   una_operacion(entrada=12 * paso, salida=20 * paso)]
        self.assertEqual(backtest.sin_solapar(pisadas), 2)     # tres operaciones, dos ratos de mercado
        self.assertEqual(backtest.sin_solapar([]), 0)
        c = backtest.compuerta(pisadas)
        clave = ("ruptura", "BTCFDUSD", "1h")
        tramo = next(t for t in c["tramos"] if (t["estrategia"], t["par"], t["temporalidad"]) == clave)
        self.assertEqual((tramo["operaciones"], tramo["casos"]), (3, 2))
        self.assertEqual(tramo["faltan"], backtest.CASOS_MINIMOS - 2)

    def test_la_compuerta_pide_los_casos_de_cada_estrategia_par_y_temporalidad(self):
        todas, tramo = [], 0
        for estrategia in backtest.ESTRATEGIAS_ENTRADA:
            for par in lib_datos.PARES_OPERADOS:
                for temporalidad in lib_estrategias.TEMPORALIDADES_SENAL:
                    todas += operaciones_seguidas(estrategia, par, temporalidad, backtest.CASOS_MINIMOS, tramo)
                    tramo += 1
        c = backtest.compuerta(todas)
        self.assertEqual((c["plan"], c["plan_b"], c["no_validado"], c["listo"]), ("normal", False, False, True))
        self.assertEqual(len(c["tramos"]), 8)                  # 2 estrategias × 2 pares × 2 temporalidades
        self.assertTrue(all(t["casos"] == backtest.CASOS_MINIMOS for t in c["tramos"]))
        # Una operación que el filtro de BTC no dejaba entrar no es un caso, y una que no cerró tampoco.
        c = backtest.compuerta([*todas, una_operacion(permitida=False), una_operacion(motivo="sin_cerrar")])
        self.assertEqual(c["operaciones"], 8 * backtest.CASOS_MINIMOS)

    def test_si_un_tramo_no_llega_a_los_casos_se_aplica_el_plan_b_escrito(self):
        def armar(saltar):
            todas, tramo = [], 0
            for estrategia in backtest.ESTRATEGIAS_ENTRADA:
                for par in lib_datos.PARES_OPERADOS:
                    for temporalidad in lib_estrategias.TEMPORALIDADES_SENAL:
                        if (estrategia, par, temporalidad) not in saltar:
                            todas += operaciones_seguidas(estrategia, par, temporalidad, backtest.CASOS_MINIMOS, tramo)
                        tramo += 1
            return todas
        # Falta una temporalidad: los tramos se ensanchan y las dos se cuentan juntas.
        ancho = backtest.compuerta(armar({("ruptura", "BTCFDUSD", "4h")}))
        self.assertEqual((ancho["plan"], ancho["plan_b"], ancho["no_validado"]), ("ancho", True, True))
        self.assertEqual(sorted(t["temporalidad"] for t in ancho["tramos"]), [""] * 4)
        # Falta un par entero: queda un solo tramo por estrategia.
        unico = backtest.compuerta(armar({("ruptura", "BTCFDUSD", t) for t in lib_estrategias.TEMPORALIDADES_SENAL}))
        self.assertEqual(unico["plan"], "unico")
        self.assertEqual(sorted(t["estrategia"] for t in unico["tramos"]), ["rebote", "ruptura"])
        # Y si ni juntando todo alcanza, se dice: con el plan B no se puede dar nada por validado.
        poca = backtest.compuerta(operaciones_seguidas("rebote", "BTCFDUSD", "1h", 5))
        self.assertEqual((poca["plan"], poca["no_validado"], poca["listo"]), ("insuficiente", True, False))
        self.assertEqual([n["nivel"] for n in poca["niveles"]], ["normal", "ancho", "unico"])

    def test_el_reporte_compara_con_quedarse_en_usdt_y_con_comprar_y_esperar(self):
        velas = velas_que_suben(10, "1d", desde=100.0, sube=10.0)
        esperar = backtest.comprar_y_esperar(velas, lib_costos.SPREAD_SUPUESTO, self.COM)
        self.assertEqual(esperar["operaciones"], 1)
        self.assertAlmostEqual(esperar["caida_maxima"], 0.01, places=12)   # el mínimo de la primera vela, 1 bajo 100
        self.assertAlmostEqual(esperar["bruto"], 0.9, places=12)
        self.assertLess(esperar["rendimiento"], esperar["bruto"])
        self.assertEqual(backtest.comprar_y_esperar([], lib_costos.SPREAD_SUPUESTO, self.COM)["operaciones"], 0)
        bajando = backtest.comprar_y_esperar(velas_que_suben(10, "1d", desde=190.0, sube=-10.0),
                                             lib_costos.SPREAD_SUPUESTO, self.COM)
        self.assertGreater(bajando["caida_maxima"], 0.4)
        self.assertEqual(backtest.quedarse_en_usdt(), {"que": "usdt", "operaciones": 0, "rendimiento": 0.0,
                                                       "bruto": 0.0, "caida_maxima": 0.0})

    def test_la_curva_dice_el_rendimiento_y_la_caida_maxima(self):
        paso = lib_datos.PASO_MS["1h"]
        ops = [una_operacion(entrada=0, salida=paso, neto=0.1), una_operacion(entrada=paso, salida=2 * paso, neto=-0.5),
               una_operacion(entrada=2 * paso, salida=3 * paso, neto=0.2)]
        c = backtest.curva(ops)
        self.assertAlmostEqual(c["rendimiento"], 1.1 * 0.5 * 1.2 - 1, places=12)
        self.assertAlmostEqual(c["caida_maxima"], 0.5, places=12)
        self.assertEqual(backtest.curva([]), {"rendimiento": 0.0, "caida_maxima": 0.0})


class BacktestCompleto(ConCarpeta):
    """El recorrido completo sobre lo guardado: las cuatro series de entrada, la compuerta y el reporte."""

    def guardar_todo(self):
        for par in lib_datos.PARES:
            for temporalidad in lib_datos.TEMPORALIDADES:
                lib_datos.guardar_serie(par, temporalidad, velas_que_suben(lib_indicadores.VENTANA, temporalidad))

    def test_sin_historial_no_se_recorre_nada_y_se_dice_que_falta(self):
        d = backtest.correr(AHORA)
        self.assertFalse(d["listo"])
        self.assertEqual(d["resumen"]["senales"], 0)
        self.assertEqual({m["codigo"] for m in d["motivos"]},
                         {"sin_contexto", "sin_tendencia_diaria", "sin_datos"})
        self.assertEqual(len(d["series"]), 4)
        self.assertEqual(d["compuerta"]["plan"], "insuficiente")
        self.assertEqual(d["modelo"]["origen"], "supuesto")

    def test_con_todo_al_dia_recorre_las_cuatro_series_y_encuentra_la_operacion(self):
        self.guardar_todo()
        velas, nivel = serie_con_una_operacion("4h")
        lib_datos.guardar_serie("BTCFDUSD", "4h", velas)
        d = backtest.correr(AHORA)
        self.assertTrue(d["listo"])
        self.assertEqual(d["resumen"]["operaciones"], 1)
        fila = next(s for s in d["series"] if (s["par"], s["temporalidad"]) == ("BTCFDUSD", "4h"))
        self.assertEqual((fila["senales"], fila["resumen"]["operaciones"]), (1, 1))
        self.assertEqual(d["operaciones"][0]["nivel"], nivel)
        self.assertEqual(d["ventana"]["desde"], min(e["desde"] for e in d["empalmes"]))
        self.assertGreater(d["ventana"]["dias"], 60)                             # las 400 velas de 4 h son 66 días
        self.assertTrue(d["supuestos"]["sin_exigencia"])
        self.assertEqual(d["supuestos"]["spread"], "supuesto")
        self.assertEqual(d["referencias"]["usdt"]["rendimiento"], 0.0)
        self.assertEqual(d["referencias"]["btc"]["operaciones"], 1)
        self.assertEqual([s["factor"] for s in d["sensibilidad"]], list(lib_costos.SENSIBILIDAD))
        principal = next(s for s in d["sensibilidad"] if s["principal"])
        self.assertEqual(principal["resumen"], d["resumen"])

    def test_la_sensibilidad_muestra_cuanto_cambia_si_una_limite_se_llena_mas_facil(self):
        self.guardar_todo()
        lib_datos.guardar_serie("BTCFDUSD", "4h", serie_con_una_operacion("4h")[0])
        d = backtest.correr(AHORA, factor=200.0)                 # pidiendo una penetración imposible
        self.assertEqual((d["resumen"]["senales"], d["resumen"]["llenadas"]), (1, 0))
        self.assertEqual(d["parametros"]["penetracion"], 200.0)
        facil = next(s for s in d["sensibilidad"] if s["factor"] == 0.0)
        self.assertEqual(facil["resumen"]["llenadas"], 1)        # con tocar el nivel sí se habría llenado
        self.assertFalse(facil["principal"])

    def test_la_exigencia_entra_por_el_gancho_que_usa_la_calibracion(self):
        self.guardar_todo()
        lib_datos.guardar_serie("BTCFDUSD", "4h", serie_con_una_operacion("4h")[0])
        sin_rupturas = backtest.correr(AHORA, filtrar=lambda s: s["estrategia"] != "ruptura")
        self.assertEqual(sin_rupturas["resumen"]["senales"], 0)
        self.assertFalse(sin_rupturas["supuestos"]["sin_exigencia"])
        self.assertTrue(backtest.correr(AHORA)["supuestos"]["sin_exigencia"])

    def test_el_reporte_queda_escrito_para_el_puntaje_y_la_calibracion(self):
        self.guardar_todo()
        self.assertFalse(backtest.guardado()["corrido"])         # antes de correrlo no se inventa ningún número
        self.assertEqual(backtest.guardado()["resumen"]["operaciones"], 0)
        d = backtest.correr_accion({}, AHORA)["datos"]
        with open(backtest.ruta_backtest(), encoding="utf-8") as f:
            escrito = json.load(f)
        self.assertEqual((escrito["cuando"], escrito["corrido"]), (d["cuando"], True))
        self.assertEqual(escrito["parametros"]["casos_minimos"], backtest.CASOS_MINIMOS)
        self.assertEqual(escrito["parametros"]["supuesto_ambiguo"], backtest.SUPUESTO_AMBIGUO)
        self.assertEqual(backtest.guardado()["cuando"], d["cuando"])


class AccionBacktest(unittest.TestCase):
    def test_sin_historial_el_backtest_dice_que_falta_en_vez_de_un_resultado(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            r = correr("backtest.py", "estado", entrada={}, datos=datos)
            self.assertTrue(r["ok"])
            self.assertFalse(r["datos"]["corrido"])
            self.assertEqual(r["datos"]["compuerta"]["casos_minimos"], 300)
            r = correr("backtest.py", "correr", entrada={}, datos=datos)
            self.assertTrue(r["ok"])
            self.assertFalse(r["datos"]["listo"])
            self.assertEqual(r["datos"]["resumen"]["operaciones"], 0)
            self.assertEqual({m["codigo"] for m in r["datos"]["motivos"]},
                             {"sin_contexto", "sin_tendencia_diaria", "sin_datos"})
            with open(os.path.join(datos, "mercado", "backtest.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["motivos"], r["datos"]["motivos"])


#: El stop y el objetivo de las velas ambiguas de las pruebas: números inventados y redondos.
STOP_AMBIGUO, OBJETIVO_AMBIGUO = 99.0, 110.0


def vela_ambigua(apertura, volumen=10.0):
    """Una vela que tocó el stop y el objetivo: con velas de 1 h no se sabe qué se cruzó primero."""
    return [apertura, 102.0, OBJETIVO_AMBIGUO + 1.0, STOP_AMBIGUO - 1.0, 102.0, volumen]


def minutos_de(apertura, temporalidad="1h", cruza="", cuando=10):
    """Las velas de 1 m de una vela, quietas entre el stop y el objetivo, y en el minuto `cuando` una que cruza el stop, el
    objetivo o los dos a la vez (`cruza`)."""
    minuto, paso = lib_datos.PASO_MS[lib_datos.MINUTO], lib_datos.PASO_MS[temporalidad]
    velas = [[apertura + i * minuto, 102.0, 105.0, 100.0, 102.0, 1.0] for i in range(paso // minuto)]
    if cruza:
        alto = OBJETIVO_AMBIGUO + 1.0 if cruza in ("objetivo", "ambas") else 105.0
        bajo = STOP_AMBIGUO - 1.0 if cruza in ("stop", "ambas") else 100.0
        velas[cuando] = [apertura + cuando * minuto, 102.0, alto, bajo, 102.0, 1.0]
    return velas


class ReglaDeLasVelasSin1m(ConCarpeta):
    """La regla explícita de la vela que tocó el stop y el objetivo —el supuesto conservador, con su etiqueta— y su
    validación contra los días que sí tienen velas de 1 m."""

    PASO = lib_datos.PASO_MS["1h"]

    def apertura(self, atras=1):
        """La apertura de una vela de 1 h cerrada, para que las cuentas no dependan de cuándo se corre la prueba."""
        return (AHORA // self.PASO) * self.PASO - atras * self.PASO

    def ops_y_minutos(self, cuantas, cruza="stop"):
        """`cuantas` operaciones ambiguas, cada una en su propia vela de 1 h, con las velas de 1 m de todas."""
        base = self.apertura(atras=cuantas + 1)
        ops, velas = [], []
        for i in range(cuantas):
            apertura = base + i * self.PASO
            ops.append(dict(una_operacion(), ambigua=True, salida_ms=apertura + self.PASO,
                            stop=STOP_AMBIGUO, objetivo=OBJETIVO_AMBIGUO))
            velas.extend(minutos_de(apertura, cruza=cruza))
        return ops, {"BTCFDUSD": velas}

    def test_los_parametros_dicen_la_regla_y_sus_etiquetas(self):
        p = lib_resolucion.parametros()
        self.assertEqual(p["supuesto"], backtest.SUPUESTO_AMBIGUO)       # la regla es una sola, aquí y en el backtest
        self.assertEqual((p["por_supuesto"], p["dias_1m"]), ("stop", lib_datos.DIAS_MINUTOS))
        self.assertEqual(p["etiquetas"], [lib_resolucion.CLARA, lib_resolucion.CON_1M, lib_resolucion.SIN_1M])

    def test_una_vela_que_toco_un_solo_nivel_no_necesita_ningun_supuesto(self):
        resolver = lambda v: lib_resolucion.resolver(v, STOP_AMBIGUO, OBJETIVO_AMBIGUO)    # noqa: E731
        abierta = resolver([0, 102.0, 105.0, 100.0, 103.0, 10.0])
        self.assertEqual((abierta["por"], abierta["ambigua"], abierta["etiqueta"]), ("", False, lib_resolucion.CLARA))
        gana = resolver([0, 102.0, 111.0, 100.0, 110.5, 10.0])
        self.assertEqual((gana["por"], gana["ambigua"], gana["etiqueta"]), ("objetivo", False, lib_resolucion.CLARA))
        pierde = resolver([0, 102.0, 105.0, 98.0, 99.5, 10.0])
        self.assertEqual((pierde["por"], pierde["ambigua"], pierde["etiqueta"]), ("stop", False, lib_resolucion.CLARA))

    def test_sin_velas_de_un_minuto_manda_el_supuesto_conservador(self):
        r = lib_resolucion.resolver(vela_ambigua(self.apertura()), STOP_AMBIGUO, OBJETIVO_AMBIGUO)
        self.assertEqual((r["por"], r["ambigua"], r["con_1m"]), ("stop", True, False))
        self.assertEqual((r["etiqueta"], r["supuesto"]), (lib_resolucion.SIN_1M, "stop_primero"))

    def test_con_la_ventana_de_un_minuto_completa_se_resuelve_de_verdad(self):
        apertura = self.apertura()
        vela = vela_ambigua(apertura)
        for cruza in ("objetivo", "stop"):
            trozo = lib_resolucion.trozo_de(minutos_de(apertura, cruza=cruza), apertura, self.PASO)
            r = lib_resolucion.resolver(vela, STOP_AMBIGUO, OBJETIVO_AMBIGUO, trozo)
            self.assertEqual((r["por"], r["etiqueta"], r["con_1m"]), (cruza, lib_resolucion.CON_1M, True))
            self.assertEqual(r["minutos"], self.PASO // lib_datos.PASO_MS[lib_datos.MINUTO])
        # Si el mismo minuto tocó los dos niveles, del minuto no se baja más: vuelve a mandar el supuesto.
        ambas = lib_resolucion.trozo_de(minutos_de(apertura, cruza="ambas"), apertura, self.PASO)
        r = lib_resolucion.resolver(vela, STOP_AMBIGUO, OBJETIVO_AMBIGUO, ambas)
        self.assertEqual((r["por"], r["etiqueta"], r["con_1m"]), ("stop", lib_resolucion.SIN_1M, False))

    def test_media_ventana_de_un_minuto_no_resuelve_nada(self):
        apertura = self.apertura()
        minutos = minutos_de(apertura, cruza="objetivo")
        self.assertEqual(len(lib_resolucion.trozo_de(minutos, apertura, self.PASO)), 60)
        self.assertIsNone(lib_resolucion.trozo_de(minutos[:40], apertura, self.PASO))      # la ventana cortada no sirve
        self.assertIsNone(lib_resolucion.trozo_de([*minutos[:30], *minutos[31:]], apertura, self.PASO))   # ni con un hoyo
        self.assertIsNone(lib_resolucion.trozo_de(minutos, apertura, lib_datos.PASO_MS[lib_datos.MINUTO]))
        self.assertIsNone(lib_resolucion.trozo_de([], apertura, self.PASO))

    def test_la_operacion_se_cierra_en_la_primera_vela_que_cruza(self):
        base = self.apertura(atras=3)
        velas = [[base + i * self.PASO, 102.0, 105.0, 100.0, 102.0, 10.0] for i in range(3)]
        abierta = lib_resolucion.cerrar(velas, 0, STOP_AMBIGUO, OBJETIVO_AMBIGUO, "1h")
        self.assertEqual((abierta["por"], abierta["motivo"], abierta["velas"]), ("", "sin_cerrar", 0))
        self.assertIsNone(abierta["precio"])
        velas[2] = vela_ambigua(velas[2][0])
        r = lib_resolucion.cerrar(velas, 0, STOP_AMBIGUO, OBJETIVO_AMBIGUO, "1h")
        self.assertEqual((r["i"], r["velas"], r["por"], r["precio"]), (2, 3, "stop", STOP_AMBIGUO))
        self.assertEqual((r["salida_ms"], r["etiqueta"]), (velas[2][0] + self.PASO, lib_resolucion.SIN_1M))
        # Con las velas de 1 m de esa vela, la misma operación cierra en el objetivo.
        con = lib_resolucion.cerrar(velas, 0, STOP_AMBIGUO, OBJETIVO_AMBIGUO, "1h",
                                    minutos_de(velas[2][0], cruza="objetivo"))
        self.assertEqual((con["por"], con["precio"], con["etiqueta"]),
                         ("objetivo", OBJETIVO_AMBIGUO, lib_resolucion.CON_1M))
        # Una operación a la que se le acabaron las velas que se le daban no cerró: no es un resultado.
        self.assertEqual(lib_resolucion.cerrar(velas, 0, STOP_AMBIGUO, OBJETIVO_AMBIGUO, "1h", maximo=2)["motivo"],
                         "sin_cerrar")

    def test_la_misma_operacion_resuelta_con_y_sin_un_minuto(self):
        apertura = self.apertura()
        velas = [vela_ambigua(apertura)]
        cambia = lib_resolucion.comparar(velas, 0, STOP_AMBIGUO, OBJETIVO_AMBIGUO, "1h",
                                         minutos_de(apertura, cruza="objetivo"))
        self.assertEqual((cambia["igual"], cambia["ambigua"], cambia["revisada"]), (False, True, True))
        self.assertEqual((cambia["con_1m"]["por"], cambia["sin_1m"]["por"]), ("objetivo", "stop"))
        acierta = lib_resolucion.comparar(velas, 0, STOP_AMBIGUO, OBJETIVO_AMBIGUO, "1h",
                                          minutos_de(apertura, cruza="stop"))
        self.assertTrue(acierta["igual"])

    def test_la_validacion_cuenta_las_ambiguas_las_revisadas_y_en_cuantas_acerto(self):
        ops, minutos = self.ops_y_minutos(1, cruza="objetivo")
        d = lib_resolucion.validar(ops, minutos)
        self.assertEqual((d["velas"], d["con_1m"], d["sin_1m"]), (1, 1, 0))
        self.assertEqual((d["objetivo_primero"], d["stop_primero"]), (1, 0))
        self.assertEqual((d["distintas"], d["iguales"], d["acierto"]), (1, 0, 0.0))   # esa vez el supuesto se equivocó
        self.assertFalse(d["validado"])                                              # una sola vela no valida nada
        cuantas = lib_resolucion.VELAS_VALIDACION
        d = lib_resolucion.validar(*self.ops_y_minutos(cuantas))
        self.assertEqual((d["velas"], d["stop_primero"], d["iguales"]), (cuantas, cuantas, cuantas))
        self.assertEqual((d["resueltas"], d["acierto"], d["validado"]), (cuantas, 1.0, True))
        self.assertEqual((d["ventana"]["pares"], d["etiqueta"]), (["BTCFDUSD"], lib_resolucion.SIN_1M))

    def test_el_minuto_que_tampoco_resuelve_no_cuenta_como_acierto_ni_como_error(self):
        d = lib_resolucion.validar(*self.ops_y_minutos(1, cruza="ambas"))
        self.assertEqual((d["con_1m"], d["sin_resolver"], d["resueltas"]), (1, 1, 0))
        self.assertIsNone(d["acierto"])

    def test_una_ambigua_sin_velas_de_un_minuto_se_cuenta_aparte(self):
        ops, _ = self.ops_y_minutos(1)
        d = lib_resolucion.validar(ops, {})
        self.assertEqual((d["velas"], d["con_1m"], d["sin_1m"]), (1, 0, 1))
        self.assertEqual((d["acierto"], d["validado"], d["ventana"]["velas"]), (None, False, 0))

    def test_las_velas_que_no_fueron_ambiguas_no_se_revisan(self):
        ops, minutos = self.ops_y_minutos(1)
        d = lib_resolucion.validar([dict(o, ambigua=False) for o in ops], minutos)
        self.assertEqual((d["velas"], d["con_1m"], d["sin_1m"]), (0, 0, 0))
        self.assertIsNone(d["acierto"])

    def test_sin_velas_pasadas_la_validacion_lee_las_de_un_minuto_guardadas(self):
        ops, minutos = self.ops_y_minutos(2)
        lib_datos.guardar_serie("BTCFDUSD", lib_datos.MINUTO, minutos["BTCFDUSD"])
        d = lib_resolucion.validar(ops)
        self.assertEqual((d["velas"], d["con_1m"], d["iguales"]), (2, 2, 2))
        self.assertEqual((d["dias_1m"], d["minimo"]), (lib_datos.DIAS_MINUTOS, lib_resolucion.VELAS_VALIDACION))
        self.assertEqual(lib_resolucion.validar([])["velas"], 0)       # sin operaciones no hay nada que validar


#: Los valores de una oportunidad cualquiera, ya puntuable: los usan las pruebas de los pesos y de las familias que faltan.
VALORES = {"cierre": 110.0, "media_20": 108.0, "media_50": 105.0, "media_200": 100.0, "adx": 30.0, "rsi": 55.0,
           "histograma": 0.11, "ancho": 0.03, "atr_relativo": 0.01, "volumen_relativo": 1.6, "obv_relativo": 0.2,
           "rompio_maximo": True, "rompio_minimo": False, "distancia_maximo": 0.005, "distancia_minimo": 0.04,
           "btc_cambio": 0.01, "btc_distancia": 0.05, "costo_comision": 0.001, "costo_spread": 0.0004,
           "costo_conversion": 0.0001, "distancia_objetivo": 0.015, "distancia_stop": 0.01}

#: La misma oportunidad con todo en contra: las siete familias tienen que dar cero, sin salirse de la escala.
EN_CONTRA = {"cierre": 90.0, "media_20": 95.0, "media_50": 98.0, "media_200": 100.0, "adx": 1.0, "rsi": 95.0,
             "histograma": -9.0, "ancho": 0.9, "atr_relativo": 0.9, "volumen_relativo": 0.1, "obv_relativo": -0.9,
             "rompio_maximo": False, "rompio_minimo": True, "distancia_maximo": 0.5, "distancia_minimo": 0.5,
             "btc_cambio": -0.5, "btc_distancia": -0.5, "costo_comision": 0.01, "costo_spread": 0.01,
             "costo_conversion": 0.01, "distancia_objetivo": 0.015, "distancia_stop": 0.01}


def ambiguas_revisadas(velas=12, con_1m=3, stop_primero=2):
    """La validación del supuesto de las velas sin 1 m, como la deja `backtest.validar_ambiguas`."""
    objetivo = con_1m - stop_primero
    return {"supuesto": backtest.SUPUESTO_AMBIGUO, "velas": velas, "con_1m": con_1m, "stop_primero": stop_primero,
            "objetivo_primero": objetivo, "sin_resolver": 0,
            "acierto": (stop_primero / con_1m) if con_1m else None}


def operaciones_puntuadas(puntaje, cuantas, ganadoras, tramo=0, par="BTCFDUSD", temporalidad="1h"):
    """`cuantas` operaciones ya recorridas y **puntuadas**, que no se pisan entre sí: `ganadoras` de ellas salieron por el
    objetivo y el resto por el stop. Es lo que deja `lib_puntaje.seguir`, con números ficticios y redondos."""
    ops = operaciones_seguidas("ruptura", par, temporalidad, cuantas, tramo)
    nombre = lib_puntaje.nombre_tramo(*lib_puntaje.bordes_de(puntaje))
    for i, o in enumerate(ops):
        gana = i < ganadoras
        o.update(puntaje=puntaje, tramo=nombre, por="objetivo" if gana else "stop", bruto=0.02 if gana else -0.01,
                 neto=0.02 if gana else -0.01, etiqueta=lib_resolucion.CLARA)
    return ops


def tabla_de_tramos(aciertos=0.75, cuantas=40, no_validado=True):
    """Los cinco tramos de puntaje medidos, como los deja `lib_puntaje.medir`: todos con casos de sobra y la misma tasa de
    acierto, para que la prueba sepa de memoria qué probabilidad tiene que salir."""
    ops = []
    for i, desde in enumerate(lib_puntaje.TRAMOS_PUNTAJE[:-1]):
        ops += operaciones_puntuadas(desde + 10.0, cuantas, int(round(cuantas * aciertos)), tramo=i)
    return {"formato": 1, "corrido": True, "cuando": lib_datos.iso(AHORA), "operaciones": len(ops), "sin_puntaje": 0,
            "tramos": lib_puntaje.tramos_de_puntaje(ops), "no_validado": no_validado,
            "supuestos": {"sin_1m": lib_resolucion.SUPUESTO_SIN_1M, "regla": lib_resolucion.parametros(),
                          "ambiguas": lib_resolucion.validar(ops, {}), "etiquetas": {lib_resolucion.CLARA: len(ops)},
                          "spread": "supuesto", "empalme": False, "sin_exigencia": True}}


def reporte_guardado(normal=0, ancho=0, aciertos=0.6, con_1m=3, no_validado=False):
    """Un backtest guardado de juguete: lo justo para que el puntaje encuentre (o no) el tramo de una oportunidad de
    ruptura en BTCFDUSD 4 h, con sus operaciones y sus casos."""
    def tramo(par, temporalidad, casos):
        ganadoras = int(round(aciertos * casos))
        return {"estrategia": "ruptura", "par": par, "temporalidad": temporalidad, "operaciones": casos,
                "casos": casos, "faltan": 0, "alcanza": True,
                "resumen": {"senales": casos, "operaciones": casos, "ganadoras": ganadoras,
                            "aciertos": (ganadoras / casos) if casos else None}}
    niveles = [{"nivel": "normal", "claves": ["estrategia", "par", "temporalidad"],
                "tramos": [tramo("BTCFDUSD", "4h", normal)]},
               {"nivel": "ancho", "claves": ["estrategia", "par"], "tramos": [tramo("BTCFDUSD", "", ancho)]}]
    return {"formato": 1, "corrido": True, "cuando": lib_datos.iso(AHORA),
            "compuerta": {"niveles": niveles, "no_validado": no_validado},
            "supuestos": {"ambiguas": ambiguas_revisadas(con_1m=con_1m), "spread": "supuesto", "empalme": False,
                          "sin_exigencia": True}}


class NotasDeLasFamilias(unittest.TestCase):
    """De un indicador a una nota de 0 a 100 con sus parámetros y su razón: las rampas y las bandas, con números
    ficticios que se leen en la prueba."""

    COM = {"maker": 0.0, "taker": 0.001, "conversion": 0.0005, "origen": "supuesto"}

    def test_una_rampa_va_de_0_a_100_y_se_recorta_en_los_extremos(self):
        self.assertEqual(lib_puntaje.rampa(15.0, 15.0, 40.0), 0.0)
        self.assertEqual(lib_puntaje.rampa(40.0, 15.0, 40.0), 100.0)
        self.assertEqual(lib_puntaje.rampa(27.5, 15.0, 40.0), 50.0)
        self.assertEqual(lib_puntaje.rampa(1000.0, 15.0, 40.0), 100.0)      # recortada: nunca pasa de 100
        self.assertEqual(lib_puntaje.rampa(0.25, 0.5, 0.0), 50.0)           # al revés: menos es mejor (el costo)
        self.assertIsNone(lib_puntaje.rampa(None, 0.0, 1.0))                # sin valor no hay nota inventada

    def test_una_banda_vale_100_en_el_medio_y_baja_en_los_dos_bordes(self):
        banda = lambda v: lib_puntaje.banda(v, 30.0, 45.0, 65.0, 85.0)      # noqa: E731  (el RSI)
        self.assertEqual((banda(45.0), banda(55.0), banda(65.0)), (100.0, 100.0, 100.0))
        self.assertEqual((banda(37.5), banda(75.0)), (50.0, 50.0))
        self.assertEqual((banda(30.0), banda(85.0), banda(100.0)), (0.0, 0.0, 0.0))
        self.assertIsNone(banda(None))

    def test_cada_familia_dice_con_que_numeros_puntuo_y_por_que(self):
        fs = lib_puntaje.familias(VALORES)
        self.assertEqual(sorted(fs), sorted(lib_puntaje.FAMILIAS))
        for nombre, f in fs.items():
            self.assertEqual(f["familia"], nombre)
            self.assertTrue(0.0 <= f["nota"] <= lib_puntaje.PUNTAJE_MAXIMO, nombre)   # la escala, siempre acotada
            self.assertTrue(2 <= len(f["parametros"]) <= 3, nombre)          # dos o tres parámetros por familia, no más
            self.assertTrue(all(p["valor"] is not None for p in f["parametros"]), nombre)
            self.assertIn(f["razon"], lib_puntaje.RAZONES[nombre])
        # La razón es la de estos números: sube parejo con fuerza, el techo recién roto, BTC bien y el costo bajo
        self.assertEqual([fs[f]["razon"] for f in lib_puntaje.FAMILIAS],
                         ["subiendo_con_fuerza", "acelerando", "se_mueve_lo_justo", "volumen_acompana",
                          "techo_recien_roto", "btc_bien", "costo_bajo"])

    def test_con_todo_en_contra_las_siete_notas_llegan_a_cero_y_no_se_pasan(self):
        fs = lib_puntaje.familias(EN_CONTRA)
        self.assertEqual([fs[f]["nota"] for f in lib_puntaje.FAMILIAS], [0.0] * 7)
        for nombre, f in fs.items():
            self.assertIn(f["razon"], lib_puntaje.RAZONES[nombre])
        self.assertEqual([fs[f]["razon"] for f in lib_puntaje.FAMILIAS],
                         ["bajando", "sobrecomprado", "muy_movido", "volumen_en_contra", "piso_roto", "btc_cayendo",
                          "costo_se_lleva_mucho"])
        # Sin uno de sus números, la familia dice cuál le faltó en vez de inventar la nota
        sin = lib_puntaje.familias({**VALORES, "obv_relativo": None})["volumen"]
        self.assertEqual((sin["nota"], sin["razon"]), (None, "sin_obv_relativo"))
        self.assertIsNone(next(p["valor"] for p in sin["parametros"] if p["nombre"] == "obv_relativo"))

    def test_la_tendencia_pide_las_medias_en_orden_y_fuerza(self):
        arriba = {"cierre": 110.0, "media_20": 108.0, "media_50": 105.0, "media_200": 100.0,
                  "adx": lib_puntaje.ADX_CON_FUERZA}
        t = lib_puntaje.tendencia(arriba)
        self.assertEqual((t["nota"], t["razon"]), (100.0, "subiendo_con_fuerza"))
        self.assertEqual([(p["nombre"], p["valor"], p["nota"]) for p in t["parametros"]],
                         [("medias", 3.0, 100.0), ("adx", lib_puntaje.ADX_CON_FUERZA, 100.0)])
        floja = lib_puntaje.tendencia({**arriba, "adx": lib_puntaje.ADX_SIN_FUERZA})
        self.assertEqual((floja["nota"], floja["razon"]), (50.0, "subiendo_sin_fuerza"))
        abajo = lib_puntaje.tendencia({"cierre": 90.0, "media_20": 95.0, "media_50": 98.0, "media_200": 100.0,
                                       "adx": 5.0})
        self.assertEqual((abajo["nota"], abajo["razon"]), (0.0, "bajando"))
        sin = lib_puntaje.tendencia({**arriba, "media_200": None})
        self.assertEqual((sin["nota"], sin["razon"]), (None, "sin_medias"))

    def test_el_costo_se_puntua_contra_lo_que_la_oportunidad_promete(self):
        gratis = {"costo_comision": 0.0, "costo_spread": 0.0, "costo_conversion": 0.0, "distancia_objetivo": 0.015}
        self.assertEqual(lib_puntaje.costo(gratis)["nota"], 100.0)
        # si entrar y salir se lleva la mitad de lo que promete, la familia costo vale cero
        caro = lib_puntaje.costo({**gratis, "costo_spread": 0.015 * lib_puntaje.COSTO_PARTE_MAXIMA})
        self.assertEqual((caro["nota"], caro["razon"]), (0.0, "costo_se_lleva_mucho"))
        c = lib_puntaje.costo(VALORES)                                       # los tres suman el 10 % del objetivo
        self.assertAlmostEqual(c["nota"], 80.0, places=12)
        self.assertEqual((c["razon"], [p["nombre"] for p in c["parametros"]]),
                         ("costo_bajo", ["comision", "spread", "conversion"]))
        sin = lib_puntaje.costo({**gratis, "costo_spread": None})
        self.assertEqual((sin["nota"], sin["razon"]), (None, "sin_spread"))
        # Y el costo se mide contra lo que la oportunidad promete: sin eso tampoco hay nota
        self.assertEqual(lib_puntaje.costo({**gratis, "distancia_objetivo": None})["razon"], "sin_costo")

    def test_la_estructura_castiga_perseguir_un_nivel_ya_roto(self):
        roto = {"rompio_maximo": True, "rompio_minimo": False, "distancia_maximo": 0.0, "distancia_minimo": 0.05}
        e = lib_puntaje.estructura(roto)                                     # recién roto: el límite está en el nivel
        self.assertEqual((e["nota"], e["razon"]), (100.0, "techo_recien_roto"))
        self.assertEqual([(p["nombre"], p["valor"]) for p in e["parametros"]],
                         [("nivel_roto", 1.0), ("distancia", 0.0)])
        pasado = lib_puntaje.estructura({**roto, "distancia_maximo": lib_puntaje.EXTENSION_MAXIMA})
        self.assertEqual((pasado["nota"], pasado["razon"]), (0.0, "nivel_ya_pasado"))
        # con el piso roto no hay estructura que mirar: la nota es cero, no importa lo demás
        piso = lib_puntaje.estructura({**roto, "rompio_minimo": True})
        self.assertEqual((piso["nota"], piso["razon"], piso["parametros"][0]["valor"]), (0.0, "piso_roto", -1.0))
        sin = lib_puntaje.estructura({**roto, "distancia_minimo": None})
        self.assertEqual((sin["nota"], sin["razon"]), (None, "sin_nivel_roto"))

    def test_las_siete_notas_se_juntan_en_un_puntaje_con_su_desglose(self):
        p = lib_puntaje.puntaje_de(VALORES)
        notas = [f["nota"] for f in p["familias"]]
        self.assertTrue(0.0 <= p["puntaje"] <= lib_puntaje.PUNTAJE_MAXIMO)   # un solo número, en la misma escala
        self.assertAlmostEqual(p["puntaje"], sum(notas) / 7, places=12)      # al empezar, todas pesan lo mismo
        self.assertEqual((p["motivo"], p["faltan"], p["renormalizado"]), ("", [], False))
        # El desglose dice, familia por familia, con qué peso entró y qué parte del puntaje le tocó
        self.assertEqual([f["familia"] for f in p["familias"]], list(lib_puntaje.FAMILIAS))
        self.assertAlmostEqual(math.fsum(f["parte"] for f in p["familias"]), 1.0, places=12)
        self.assertEqual({f["peso"] for f in p["familias"]}, {1.0})
        self.assertAlmostEqual(math.fsum(f["nota"] * f["parte"] for f in p["familias"]), p["puntaje"], places=12)

    def test_sin_una_familia_clave_no_hay_puntaje(self):
        v = dict(VALORES)
        self.assertIsNotNone(lib_puntaje.puntaje_de(v)["puntaje"])
        p = lib_puntaje.puntaje_de({**v, "costo_spread": None})
        self.assertIsNone(p["puntaje"])                                      # sin el costo no se inventa un puntaje
        self.assertEqual((p["motivo"], p["faltan"], p["renormalizado"]), ("sin_costo", ["costo"], False))
        self.assertEqual(len(p["familias"]), 7)                              # las otras seis notas siguen a la vista
        sin = next(f for f in p["familias"] if f["familia"] == "costo")
        self.assertEqual((sin["nota"], sin["razon"]), (None, "sin_spread"))  # y la familia dice qué número le faltó
        self.assertEqual({f["parte"] for f in p["familias"]}, {0.0})         # sin puntaje, ninguna familia aportó nada
        # Las tres clave son para dónde va el precio, cómo viene BTC y qué se lleva el costo: ninguna se puede suplir
        self.assertEqual(lib_puntaje.FAMILIAS_CLAVE, ("tendencia", "contexto", "costo"))
        self.assertEqual(lib_puntaje.puntaje_de({**v, "media_200": None})["motivo"], "sin_tendencia")
        self.assertEqual(lib_puntaje.puntaje_de({**v, "btc_cambio": None})["motivo"], "sin_contexto")

    def test_una_familia_sin_dato_renormaliza_los_pesos_y_queda_marcado(self):
        sin_volumen = {**VALORES, "obv_relativo": None}
        p = lib_puntaje.puntaje_de(sin_volumen)
        otras = [f["nota"] for f in p["familias"] if f["familia"] != "volumen"]
        self.assertAlmostEqual(p["puntaje"], sum(otras) / 6, places=12)      # el volumen sale del promedio, no entra en 0
        self.assertEqual((p["faltan"], p["renormalizado"], p["motivo"]), (["volumen"], True, ""))
        partes = {f["familia"]: f["parte"] for f in p["familias"]}
        self.assertEqual(partes["volumen"], 0.0)
        self.assertAlmostEqual(math.fsum(partes.values()), 1.0, places=12)   # los pesos renormalizados siguen sumando 1
        self.assertAlmostEqual(partes["tendencia"], 1 / 6, places=12)
        # Y el peso que tenía la familia que falta se reparte entre las demás en la proporción que traían
        pesos = {**lib_puntaje.PESOS_BASE, "volumen": 5.0, "impulso": 3.0}
        con_pesos = lib_puntaje.puntaje_de(sin_volumen, pesos)
        partes = {f["familia"]: f["parte"] for f in con_pesos["familias"]}
        self.assertAlmostEqual(partes["impulso"], 3 / 8, places=12)
        self.assertAlmostEqual(partes["tendencia"], 1 / 8, places=12)
        self.assertTrue(con_pesos["renormalizado"])

    def test_los_pesos_son_el_gancho_de_la_calibracion(self):
        self.assertEqual(lib_puntaje.PESOS_BASE, {f: 1.0 for f in lib_puntaje.FAMILIAS})
        solo = lib_puntaje.puntaje_de(VALORES, {**{f: 0.0 for f in lib_puntaje.FAMILIAS}, "tendencia": 1.0})
        self.assertAlmostEqual(solo["puntaje"], lib_puntaje.tendencia(VALORES)["nota"], places=12)
        self.assertEqual(lib_puntaje.puntaje_de(VALORES, {f: 0.0 for f in lib_puntaje.FAMILIAS})["motivo"],
                         "sin_pesos")

    def test_mientras_no_haya_calibracion_el_modelo_no_esta_calibrado_y_la_exigencia_es_85(self):
        m = lib_puntaje.modelo()
        self.assertEqual((m["estado"], m["calibrado"], m["motivo"]),
                         (lib_puntaje.MODELO_SIN_CALIBRAR, False, "sin_calibracion"))
        self.assertEqual(m["estado"], "sin_calibrar")
        self.assertEqual((m["exigencia"], m["pesos"]), (85.0, lib_puntaje.PESOS_BASE))
        self.assertEqual(m["exigencia"], lib_puntaje.EXIGENCIA_SIN_CALIBRAR)
        # La calibración, en su paso, es la que mueve las tres cosas; sin ella no se toman sus pesos a medias
        a_medias = lib_puntaje.modelo({"estado": "validado", "exigencia": 72.0})
        self.assertEqual((a_medias["estado"], a_medias["exigencia"]), ("sin_calibrar", 85.0))
        ya = lib_puntaje.modelo({"calibrado": True, "estado": "validado", "exigencia": 72.0, "cuando": "2026-01-01",
                                 "pesos": {**lib_puntaje.PESOS_BASE, "costo": 2.0}})
        self.assertEqual((ya["estado"], ya["exigencia"], ya["pesos"]["costo"]), ("validado", 72.0, 2.0))

    def test_quedarse_en_usdt_tambien_puntua_y_es_la_vara(self):
        pasa = lib_estrategias.filtro_btc({"cambio": 0.01, "sobre_media": True})
        cae = lib_estrategias.filtro_btc({"cambio": -0.05, "sobre_media": True})
        con_algo = lib_puntaje.quedarse(pasa, [{"permitida": True}])
        self.assertEqual((con_algo["puntaje"], con_algo["razon"], con_algo["sola"]),
                         (lib_puntaje.PUNTAJE_USDT, "hay_oportunidades", False))
        self.assertEqual(lib_puntaje.quedarse(pasa, [])["puntaje"], lib_puntaje.PUNTAJE_MAXIMO)
        frenado = lib_puntaje.quedarse(cae, [{"permitida": False}])
        self.assertEqual((frenado["puntaje"], frenado["razon"]), (lib_puntaje.PUNTAJE_MAXIMO, "btc"))
        # quedarse quieto no es una apuesta: no tiene probabilidad y su ganancia esperada es cero, exacta
        self.assertEqual(con_algo["ganancia"]["esperada"], 0.0)
        self.assertIsNone(con_algo["ganancia"]["probabilidad"])
        # Las dos opciones están en la misma escala, así que se comparan de frente: gana la que más puntúa
        buena = {"permitida": True, "puntaje": lib_puntaje.PUNTAJE_USDT + 1}
        mala = {"permitida": True, "puntaje": lib_puntaje.PUNTAJE_USDT - 1}
        self.assertIs(lib_puntaje.mejor_de([mala, con_algo]), con_algo)
        self.assertIs(lib_puntaje.mejor_de([buena, con_algo]), buena)
        # Una oportunidad que no se puede entrar o que no tiene puntaje no compite con quedarse quieto
        self.assertIs(lib_puntaje.mejor_de([{"permitida": False, "puntaje": 99.0}, con_algo]), con_algo)
        self.assertIs(lib_puntaje.mejor_de([{"permitida": True, "puntaje": None}, con_algo]), con_algo)
        self.assertIsNone(lib_puntaje.mejor_de([{"permitida": True, "puntaje": None}]))

    def test_el_rango_de_la_probabilidad_sale_de_los_casos_que_no_se_pisan(self):
        bajo, alto = lib_puntaje.wilson(0.6, 40)
        self.assertLess(bajo, 0.6)
        self.assertGreater(alto, 0.6)
        angosto = lib_puntaje.wilson(0.6, 400)                               # con diez veces más casos, diez veces más
        self.assertGreater(angosto[0], bajo)                                 # angosto el rango
        self.assertLess(angosto[1], alto)
        self.assertLessEqual(lib_puntaje.wilson(1.0, 50)[1], 1.0)            # Wilson nunca promete más de 1
        self.assertGreater(lib_puntaje.wilson(1.0, 50)[0], 0.0)
        self.assertEqual(lib_puntaje.wilson(0.6, 0), (None, None))           # sin casos no hay rango
        self.assertEqual(lib_puntaje.wilson(None, 40), (None, None))

    def test_la_probabilidad_sale_del_tramo_del_backtest_y_dice_de_cual(self):
        ops = operaciones_seguidas("ruptura", "BTCFDUSD", "1h", 40)
        for o in ops[:16]:
            o["neto"] = -0.01                                                # 24 de 40: el 60 % de aciertos
        c = backtest.compuerta(ops)
        ev = lib_puntaje.evidencia({"corrido": True, "compuerta": c}, "ruptura", "BTCFDUSD", "1h")
        self.assertEqual((ev["origen"], ev["casos"], ev["operaciones"], ev["ganadoras"]), ("normal", 40, 40, 24))
        self.assertAlmostEqual(ev["aciertos"], 0.6, places=12)
        self.assertLess(ev["bajo"], ev["aciertos"])
        self.assertGreater(ev["alto"], ev["aciertos"])
        self.assertEqual(ev["motivo"], "")
        self.assertTrue(ev["no_validado"])        # la compuerta no llegó a sus casos: nada de esto está validado
        # Sin backtest no hay probabilidad, y con un tramo de pocos casos tampoco: una tasa de cuatro es una anécdota
        self.assertEqual(lib_puntaje.evidencia({}, "ruptura", "BTCFDUSD", "1h")["motivo"], "sin_backtest")
        pocas = lib_puntaje.evidencia({"corrido": True, "compuerta": backtest.compuerta(ops[:4])},
                                      "ruptura", "BTCFDUSD", "1h")
        self.assertEqual((pocas["motivo"], pocas["aciertos"]), ("pocos_casos", None))

    def test_si_el_tramo_fino_no_alcanza_se_usa_el_ancho_y_queda_dicho(self):
        ev = lib_puntaje.evidencia(reporte_guardado(normal=10, ancho=120), "ruptura", "BTCFDUSD", "4h")
        self.assertEqual((ev["origen"], ev["casos"]), ("ancho", 120))
        self.assertTrue(ev["no_validado"])        # el plan B no se tapa: la probabilidad viene de un tramo ensanchado
        fino = lib_puntaje.evidencia(reporte_guardado(normal=120, ancho=400), "ruptura", "BTCFDUSD", "4h")
        self.assertEqual((fino["origen"], fino["casos"], fino["no_validado"]), ("normal", 120, False))

    def test_la_ganancia_esperada_es_despues_de_costos_y_va_con_su_rango(self):
        senal = {"entrada": 100.0, "stop": 98.0, "objetivo": 101.5}
        g = lib_puntaje.ganancia(senal, 0.0005, self.COM, {"aciertos": 0.6, "bajo": 0.4, "alto": 0.8})
        self.assertAlmostEqual(g["gana"], lib_costos.resultado(100.0, 101.5, "objetivo", 0.0005, self.COM)["neto"],
                               places=12)
        self.assertAlmostEqual(g["pierde"], lib_costos.resultado(100.0, 98.0, "stop", 0.0005, self.COM)["neto"],
                               places=12)
        self.assertLess(g["gana"], 0.015)                                    # los costos ya están restados
        self.assertLess(g["pierde"], -0.02)                                  # y al stop le suman, no le restan
        self.assertAlmostEqual(g["esperada"], 0.6 * g["gana"] + 0.4 * g["pierde"], places=12)
        self.assertLess(g["bajo"], g["esperada"])
        self.assertGreater(g["alto"], g["esperada"])
        self.assertEqual(g["probabilidad"], 0.6)
        # Sin probabilidad no hay esperada, pero lo que gana y lo que pierde son cuentas: ahí están
        sin = lib_puntaje.ganancia(senal, 0.0005, self.COM, None)
        self.assertIsNone(sin["esperada"])
        self.assertAlmostEqual(sin["gana"], g["gana"], places=12)
        self.assertIsNone(lib_puntaje.ganancia(senal, None, self.COM)["gana"])

    def test_el_supuesto_de_las_velas_sin_un_minuto_queda_marcado(self):
        s = lib_puntaje.supuestos(reporte_guardado(normal=120))
        self.assertEqual(s["sin_1m"], backtest.SUPUESTO_AMBIGUO)             # el stop se cruza antes que el objetivo
        self.assertEqual(s["sin_1m"], "stop_primero")
        self.assertEqual((s["validado"], s["dias_1m"]), (True, lib_datos.DIAS_MINUTOS))
        self.assertAlmostEqual(s["acierto"], 2 / 3, places=12)
        self.assertEqual(s["ambiguas"]["velas"], 12)
        self.assertTrue(s["sin_exigencia"])                                  # la probabilidad viene sin exigencia
        # Si de esas velas todavía no hay ninguna con 1 m, el supuesto está sin validar y se dice
        sin = lib_puntaje.supuestos(reporte_guardado(normal=120, con_1m=0))
        self.assertEqual((sin["validado"], sin["acierto"]), (False, None))
        self.assertFalse(lib_puntaje.supuestos({})["corrido"])

    def test_la_capa_que_recorre_las_velas_puntua_cada_senal_cruda(self):
        velas, _ = serie_con_una_operacion("1h")
        pasa = lambda ms: lib_estrategias.filtro_btc({"cambio": 0.01, "sobre_media": True})   # noqa: E731
        contexto = lambda ms: {"cambio": 0.01, "cierre": 100.0, "media_200": 90.0}            # noqa: E731
        puntuadas = lib_puntaje.de_velas("BTCFDUSD", "1h", velas, al_alza=lambda ms: True, filtro=pasa,
                                         contexto_btc=contexto, spread=lib_costos.SPREAD_SUPUESTO, com=self.COM)
        self.assertEqual(len(puntuadas), len(velas))
        suyas = [s for fila in puntuadas for s in fila]
        self.assertEqual([s["estrategia"] for s in suyas], ["ruptura"])
        self.assertEqual(len(suyas[0]["familias"]), 7)
        self.assertTrue(0.0 < suyas[0]["puntaje"] <= 100.0)
        self.assertEqual(suyas[0]["motivo"], "")
        self.assertIn("entrada", suyas[0])                                   # la señal cruda llega entera, con puntaje
        # Sin el contexto de BTC ninguna señal queda puntuada: la familia contexto no se inventa
        sin = lib_puntaje.de_velas("BTCFDUSD", "1h", velas, al_alza=lambda ms: True, filtro=pasa,
                                   spread=lib_costos.SPREAD_SUPUESTO, com=self.COM)
        suya = [s for fila in sin for s in fila][0]
        self.assertEqual((suya["puntaje"], suya["motivo"]), (None, "sin_contexto"))


class TramosDePuntaje(ConCarpeta):
    """La probabilidad de ganar y la ganancia esperada después de costos por tramos de puntaje, medidas sobre el backtest
    de señales crudas y resueltas con la regla de las velas sin 1 m."""

    def guardar_todo(self):
        for par in lib_datos.PARES:
            for temporalidad in lib_datos.TEMPORALIDADES:
                lib_datos.guardar_serie(par, temporalidad, velas_que_suben(lib_indicadores.VENTANA, temporalidad))

    def test_los_tramos_son_cinco_y_cada_puntaje_cae_en_el_suyo(self):
        self.assertEqual(lib_puntaje.TRAMOS_PUNTAJE, (0.0, 20.0, 40.0, 60.0, 80.0, 100.0))
        self.assertEqual(lib_puntaje.bordes_de(0.0), (0.0, 20.0))
        self.assertEqual(lib_puntaje.bordes_de(19.99), (0.0, 20.0))
        self.assertEqual(lib_puntaje.bordes_de(20.0), (20.0, 40.0))      # el borde de abajo entra, el de arriba no
        self.assertEqual(lib_puntaje.bordes_de(100.0), (80.0, 100.0))    # salvo el último: el 100 no queda afuera
        self.assertIsNone(lib_puntaje.bordes_de(None))                   # sin puntaje no hay tramo
        self.assertEqual(lib_puntaje.nombre_tramo(60.0, 80.0), "60-80")
        tramos = lib_puntaje.tramos_de_puntaje([])
        self.assertEqual([t["tramo"] for t in tramos], ["0-20", "20-40", "40-60", "60-80", "80-100"])
        # Un tramo sin operaciones es un tramo con cero casos, no un tramo que no existe, y no inventa ninguna tasa
        self.assertTrue(all(t["casos"] == 0 and t["pocos"] and t["motivo"] == "pocos_casos" for t in tramos))
        self.assertTrue(all(t["aciertos"] is None and t["esperada"] is None for t in tramos))

    def test_cada_tramo_dice_con_que_frecuencia_gano_y_cuanto_dejo(self):
        ops = operaciones_puntuadas(70.0, 40, 24)                        # 24 de 40: el 60 % de las veces
        tramos = lib_puntaje.tramos_de_puntaje(ops)
        t = next(x for x in tramos if x["tramo"] == "60-80")
        self.assertEqual((t["operaciones"], t["casos"], t["ganadoras"], t["perdedoras"]), (40, 40, 24, 16))
        self.assertAlmostEqual(t["aciertos"], 0.6, places=12)
        self.assertEqual((t["pocos"], t["motivo"], t["casos_minimos"]), (False, "", lib_puntaje.CASOS_PROBABILIDAD))
        self.assertLess(t["bajo"], t["aciertos"])                        # Wilson, con los casos que no se pisan
        self.assertGreater(t["alto"], t["aciertos"])
        self.assertAlmostEqual(t["gana_medio"], 0.02, places=12)
        self.assertAlmostEqual(t["pierde_medio"], -0.01, places=12)
        self.assertAlmostEqual(t["esperada"], 0.6 * 0.02 + 0.4 * -0.01, places=12)
        self.assertLess(t["esperada_bajo"], t["esperada"])               # el rango de la esperada sale del de la tasa
        self.assertGreater(t["esperada_alto"], t["esperada"])
        # Una operación cuenta en su tramo y en ninguno más, y las que no cerraron o no se podían entrar no cuentan
        self.assertEqual(sum(x["operaciones"] for x in tramos), 40)
        colados = [*ops, dict(ops[0], motivo="sin_cerrar", neto=None), dict(ops[0], permitida=False),
                   dict(ops[0], puntaje=None, tramo="")]
        t = next(x for x in lib_puntaje.tramos_de_puntaje(colados) if x["tramo"] == "60-80")
        self.assertEqual(t["operaciones"], 40)

    def test_un_tramo_con_pocos_casos_lo_dice_en_vez_de_dar_una_probabilidad(self):
        tabla = {"formato": 1, "corrido": True,
                 "tramos": lib_puntaje.tramos_de_puntaje(operaciones_puntuadas(70.0, 4, 3))}
        t = lib_puntaje.de_tramo(tabla, 70.0)
        self.assertEqual((t["operaciones"], t["casos"], t["pocos"], t["motivo"]), (4, 4, True, "pocos_casos"))
        ev = lib_puntaje.evidencia({}, "ruptura", "BTCFDUSD", "1h", puntaje=70.0, tramos=tabla)
        self.assertEqual((ev["motivo"], ev["aciertos"], ev["casos"]), ("pocos_casos", None, 4))
        self.assertEqual((ev["casos_minimos"], ev["pocos"]), (lib_puntaje.CASOS_PROBABILIDAD, True))

    def test_la_probabilidad_sale_del_tramo_de_puntaje_de_la_oportunidad(self):
        tabla = tabla_de_tramos(aciertos=0.75)
        ev = lib_puntaje.evidencia(reporte_guardado(normal=120), "ruptura", "BTCFDUSD", "4h",
                                   puntaje=70.0, tramos=tabla)
        self.assertEqual((ev["fuente"], ev["tramo"], ev["casos"]), ("puntaje", "60-80", 40))
        self.assertAlmostEqual(ev["aciertos"], 0.75, places=12)          # la del tramo, no el 60 % de la compuerta
        self.assertEqual((ev["desde"], ev["hasta"], ev["motivo"]), (60.0, 80.0, ""))
        self.assertTrue(ev["no_validado"])                               # medido con los pesos de partida
        # Si el tramo de esta oportunidad no tiene casos, se baja al tramo de la compuerta y queda dicho de dónde salió
        flacos = {**tabla, "tramos": [dict(t, operaciones=0, casos=0, ganadoras=0, aciertos=None, bajo=None,
                                           alto=None, pocos=True, motivo="pocos_casos") for t in tabla["tramos"]]}
        ev = lib_puntaje.evidencia(reporte_guardado(normal=120), "ruptura", "BTCFDUSD", "4h",
                                   puntaje=70.0, tramos=flacos)
        self.assertEqual((ev["fuente"], ev["origen"], ev["casos"]), ("compuerta", "normal", 120))
        self.assertAlmostEqual(ev["aciertos"], 0.6, places=12)
        self.assertEqual(ev["tramo"], "60-80")                           # cuál es su tramo se dice igual
        # Y sin tramos medidos ni backtest corrido no hay ninguna probabilidad inventada
        self.assertEqual(lib_puntaje.evidencia({}, "ruptura", "BTCFDUSD", "4h", puntaje=70.0)["motivo"],
                         "sin_backtest")

    def test_medir_recorre_el_historial_puntuando_cada_senal_antes_de_seguirla(self):
        self.guardar_todo()
        lib_datos.guardar_serie("BTCFDUSD", "4h", serie_con_una_operacion("4h")[0])
        d = lib_puntaje.medir(AHORA)
        self.assertTrue(d["corrido"])
        self.assertTrue(d["listo"])
        self.assertEqual((d["resumen"]["operaciones"], d["operaciones"], d["sin_puntaje"]), (1, 1, 0))
        fila = next(s for s in d["series"] if (s["par"], s["temporalidad"]) == ("BTCFDUSD", "4h"))
        self.assertEqual((fila["senales"], fila["puntuadas"], fila["operaciones"]), (1, 1, 1))
        self.assertEqual(len(d["tramos"]), len(lib_puntaje.TRAMOS_PUNTAJE) - 1)
        suyos = [t for t in d["tramos"] if t["operaciones"]]
        self.assertEqual(len(suyos), 1)                                  # la única operación cae en un solo tramo
        self.assertEqual((suyos[0]["casos"], suyos[0]["ganadoras"]), (1, 1))
        self.assertTrue(suyos[0]["pocos"])                               # con una operación no hay probabilidad
        # El supuesto de las velas sin 1 m es el de la regla, en un solo lugar, y queda marcado con su validación
        self.assertEqual(d["supuestos"]["sin_1m"], lib_resolucion.SUPUESTO_SIN_1M)
        self.assertEqual(d["supuestos"]["regla"]["supuesto"], backtest.SUPUESTO_AMBIGUO)
        self.assertEqual(d["supuestos"]["etiquetas"][lib_resolucion.CLARA], 1)
        self.assertEqual(d["supuestos"]["ambiguas"]["velas"], 0)
        self.assertTrue(d["supuestos"]["sin_exigencia"])                 # se mide sobre las señales crudas
        self.assertTrue(d["no_validado"])                                # con los pesos de partida nada está validado
        self.assertEqual(d["modelo"]["estado"], "sin_calibrar")
        self.assertEqual(d["parametros"]["tramos"], list(lib_puntaje.TRAMOS_PUNTAJE))

    def test_una_vela_que_toco_el_stop_y_el_objetivo_se_resuelve_con_la_regla(self):
        self.guardar_todo()
        lib_datos.guardar_serie("BTCFDUSD", "4h", serie_con_una_operacion("4h", como="ambas")[0])
        d = lib_puntaje.medir(AHORA)
        suyos = [t for t in d["tramos"] if t["operaciones"]]
        self.assertEqual((len(suyos), suyos[0]["ambiguas"], suyos[0]["ganadoras"]), (1, 1, 0))
        self.assertEqual(d["supuestos"]["etiquetas"][lib_resolucion.SIN_1M], 1)
        self.assertEqual(d["supuestos"]["ambiguas"]["velas"], 1)
        self.assertFalse(d["supuestos"]["ambiguas"]["validado"])         # sin velas de 1 m de ese día no se valida nada

    def test_sin_historial_no_hay_tramos_medidos_y_se_dice_que_falta(self):
        d = lib_puntaje.medir(AHORA)
        self.assertFalse(d["listo"])
        self.assertEqual({m["codigo"] for m in d["motivos"]}, {"sin_contexto", "sin_tendencia_diaria", "sin_datos"})
        self.assertEqual(d["operaciones"], 0)
        self.assertTrue(all(t["casos"] == 0 for t in d["tramos"]))
        self.assertFalse(lib_puntaje.tramos_guardados()["corrido"])      # antes de medir no se inventa ningún número
        self.assertEqual(len(lib_puntaje.tramos_guardados()["tramos"]), len(lib_puntaje.TRAMOS_PUNTAJE) - 1)

    def test_los_tramos_medidos_quedan_escritos_y_el_puntaje_los_encuentra(self):
        lib_puntaje.escribir_tramos(tabla_de_tramos(aciertos=0.75))
        guardados = lib_puntaje.tramos_guardados()
        self.assertTrue(guardados["corrido"])
        t = lib_puntaje.de_tramo(guardados, 85.0)
        self.assertEqual(t["tramo"], "80-100")
        self.assertAlmostEqual(t["aciertos"], 0.75, places=12)
        self.assertIsNone(lib_puntaje.de_tramo(guardados, None))         # una oportunidad sin puntaje no tiene tramo
        self.assertIsNone(lib_puntaje.de_tramo({"corrido": False}, 85.0))


class PuntajeDeAhora(ConCarpeta):
    """El puntaje de ahora sobre lo guardado: cada señal cruda con sus siete notas, su probabilidad y su ganancia."""

    def guardar_todo(self):
        for par in lib_datos.PARES:
            for temporalidad in lib_datos.TEMPORALIDADES:
                lib_datos.guardar_serie(par, temporalidad, velas_que_suben(lib_indicadores.VENTANA, temporalidad))

    def con_ruptura(self, par, temporalidad):
        """La última vela guardada pasa a ser una que rompe el techo de las anteriores con volumen (como en las señales)."""
        velas = lib_datos.leer_serie(par, temporalidad)
        ultima = velas[-1]
        techo = max(v[2] for v in velas[-1 - lib_indicadores_mercado.RUPTURA_VELAS:-1])
        velas[-1] = [ultima[0], techo, techo + 11.0, techo - 1.0, techo + 10.0, ultima[5] * 4]
        lib_datos.guardar_serie(par, temporalidad, velas)
        return techo

    def test_sin_historial_no_hay_nada_que_puntuar_y_quedarse_es_la_unica(self):
        e = lib_puntaje.estado(AHORA)
        self.assertFalse(e["listo"])
        self.assertEqual(e["opciones"], [])
        self.assertEqual(len(e["series"]), 4)
        self.assertEqual((e["usdt"]["puntaje"], e["usdt"]["razon"]), (lib_puntaje.PUNTAJE_MAXIMO, "btc"))
        self.assertEqual(e["mejor"]["estrategia"], "usdt")
        self.assertIn("sin_backtest", {m["codigo"] for m in e["motivos"]})
        self.assertIn("sin_muestras", {m["codigo"] for m in e["motivos"]})
        self.assertEqual(e["supuestos"]["sin_1m"], backtest.SUPUESTO_AMBIGUO)
        self.assertFalse(e["supuestos"]["corrido"])

    def test_una_ruptura_al_dia_se_puntua_familia_por_familia(self):
        self.guardar_todo()
        techo = self.con_ruptura("BTCFDUSD", "4h")
        muestra_guardada(AHORA)
        e = lib_puntaje.estado(AHORA)
        self.assertEqual(len(e["opciones"]), 1)
        o = e["opciones"][0]
        self.assertEqual((o["estrategia"], o["par"], o["temporalidad"], o["entrada"]),
                         ("ruptura", "BTCFDUSD", "4h", techo))
        notas = {f["familia"]: f["nota"] for f in o["familias"]}
        self.assertEqual(sorted(notas), sorted(lib_puntaje.FAMILIAS))
        self.assertEqual((notas["tendencia"], notas["volatilidad"]), (100.0, 100.0))   # sube parejo y se mueve lo justo
        # Cada nota llega con los parámetros que la formaron y su razón: así se puede contar por qué puntuó eso
        for f in o["familias"]:
            self.assertTrue(2 <= len(f["parametros"]) <= 3, f["familia"])
            self.assertIn(f["razon"], lib_puntaje.RAZONES[f["familia"]])
        costo = next(f for f in o["familias"] if f["familia"] == "costo")
        self.assertEqual([p["nombre"] for p in costo["parametros"]], ["comision", "spread", "conversion"])
        self.assertTrue(0.0 < o["puntaje"] <= 100.0)
        self.assertEqual(o["motivo"], "")
        self.assertEqual(e["usdt"]["puntaje"], lib_puntaje.PUNTAJE_USDT)
        self.assertEqual(e["mejor"]["puntaje"], max(o["puntaje"], lib_puntaje.PUNTAJE_USDT))
        # Lo que gana y lo que pierde son cuentas; la probabilidad todavía no, porque falta recorrer el historial
        self.assertGreater(o["ganancia"]["gana"], 0)
        self.assertLess(o["ganancia"]["pierde"], 0)
        self.assertIsNone(o["ganancia"]["esperada"])
        self.assertEqual(o["evidencia"]["motivo"], "sin_backtest")

    def test_el_puntaje_de_ahora_dice_con_que_modelo_y_con_que_exigencia_se_mira(self):
        self.guardar_todo()
        self.con_ruptura("BTCFDUSD", "4h")
        muestra_guardada(AHORA)
        e = lib_puntaje.estado(AHORA)
        self.assertEqual(e["modelo"]["estado"], "sin_calibrar")               # todavía no hay ninguna calibración
        self.assertEqual((e["exigencia"], e["modelo"]["exigencia"]), (85.0, 85.0))
        self.assertEqual(e["pesos"], lib_puntaje.PESOS_BASE)
        self.assertEqual(e["claves"], list(lib_puntaje.FAMILIAS_CLAVE))
        self.assertFalse(e["opciones"][0]["renormalizado"])                   # con las siete familias no hay nada que
        self.assertEqual(e["opciones"][0]["faltan"], [])                      # renormalizar
        # Cuando la calibración, en su paso, deje sus pesos y su exigencia, el puntaje de ahora sale con ellos
        cal = {"calibrado": True, "estado": "validado", "exigencia": 70.0, "cuando": lib_datos.iso(AHORA),
               "pesos": {**{f: 0.0 for f in lib_puntaje.FAMILIAS}, "tendencia": 1.0}}
        con = lib_puntaje.estado(AHORA, calibracion=cal)
        self.assertEqual((con["exigencia"], con["modelo"]["estado"]), (70.0, "validado"))
        o = con["opciones"][0]
        nota = next(f["nota"] for f in o["familias"] if f["familia"] == "tendencia")
        self.assertAlmostEqual(o["puntaje"], nota, places=12)

    def test_sin_la_muestra_del_libro_la_oportunidad_queda_sin_puntaje(self):
        self.guardar_todo()
        self.con_ruptura("BTCFDUSD", "4h")
        e = lib_puntaje.estado(AHORA)                 # el muestreo nunca corrió: no hay costo de ahora
        o = e["opciones"][0]
        self.assertEqual((o["puntaje"], o["motivo"]), (None, "sin_costo"))
        # La comisión se sabe (la da la API), la diferencia entre compra y venta no: la familia dice justo eso
        costo = next(f for f in o["familias"] if f["familia"] == "costo")
        self.assertEqual((costo["nota"], costo["razon"]), (None, "sin_spread"))
        self.assertIsNotNone(next(p["valor"] for p in costo["parametros"] if p["nombre"] == "comision"))
        self.assertIsNone(o["ganancia"]["gana"])      # sin la diferencia entre compra y venta tampoco hay cuenta
        self.assertEqual(e["mejor"]["estrategia"], "usdt")
        self.assertIn("sin_muestras", {m["codigo"] for m in e["motivos"]})

    def test_con_el_historial_recorrido_la_oportunidad_trae_probabilidad(self):
        self.guardar_todo()
        self.con_ruptura("BTCFDUSD", "4h")
        muestra_guardada(AHORA)
        e = lib_puntaje.estado(AHORA, reporte=reporte_guardado(normal=120))
        o = e["opciones"][0]
        g = o["ganancia"]
        self.assertEqual((o["evidencia"]["origen"], o["evidencia"]["casos"]), ("normal", 120))
        self.assertAlmostEqual(g["probabilidad"], 0.6, places=12)
        self.assertAlmostEqual(g["esperada"], 0.6 * g["gana"] + 0.4 * g["pierde"], places=12)
        self.assertLess(g["bajo"], g["esperada"])
        self.assertGreater(g["alto"], g["esperada"])
        # Y el supuesto de las velas sin 1 m viaja marcado con la probabilidad que ayudó a calcular
        self.assertEqual(e["supuestos"]["sin_1m"], "stop_primero")
        self.assertTrue(e["supuestos"]["validado"])
        self.assertAlmostEqual(e["supuestos"]["acierto"], 2 / 3, places=12)

    def test_la_probabilidad_de_ahora_sale_del_tramo_de_puntaje_medido(self):
        self.guardar_todo()
        self.con_ruptura("BTCFDUSD", "4h")
        muestra_guardada(AHORA)
        e = lib_puntaje.estado(AHORA, reporte=reporte_guardado(normal=120), tramos=tabla_de_tramos(aciertos=0.75))
        o = e["opciones"][0]
        ev, g = o["evidencia"], o["ganancia"]
        self.assertEqual(ev["fuente"], "puntaje")
        self.assertEqual(ev["tramo"], lib_puntaje.nombre_tramo(*lib_puntaje.bordes_de(o["puntaje"])))
        self.assertAlmostEqual(g["probabilidad"], 0.75, places=12)     # la de su tramo, no la del par y la temporalidad
        self.assertAlmostEqual(g["esperada"], 0.75 * g["gana"] + 0.25 * g["pierde"], places=12)
        self.assertLess(g["bajo"], g["esperada"])
        self.assertGreater(g["alto"], g["esperada"])
        self.assertEqual([t["tramo"] for t in e["tramos"]], ["0-20", "20-40", "40-60", "60-80", "80-100"])
        self.assertTrue(e["medicion"]["corrido"])
        self.assertEqual(e["supuestos"]["sin_1m"], lib_resolucion.SUPUESTO_SIN_1M)
        self.assertEqual(e["supuestos"]["regla"]["dias_1m"], lib_datos.DIAS_MINUTOS)
        # Mientras los tramos no estén medidos se dice, y la probabilidad sale del tramo de la compuerta
        sin = lib_puntaje.estado(AHORA, reporte=reporte_guardado(normal=120))
        self.assertEqual(sin["opciones"][0]["evidencia"]["fuente"], "compuerta")
        self.assertIn("sin_tramos", {m["codigo"] for m in sin["motivos"]})
        self.assertFalse(sin["medicion"]["corrido"])

    def test_si_btc_cae_la_oportunidad_se_puntua_pero_no_se_puede_entrar(self):
        self.guardar_todo()
        self.con_ruptura("ETHFDUSD", "4h")
        muestra_guardada(AHORA)
        lib_datos.guardar_serie("BTCUSDT", "1d",
                                velas_que_suben(lib_indicadores.VENTANA, "1d", desde=900.0, sube=-1.0))
        e = lib_puntaje.estado(AHORA)
        o = e["opciones"][0]
        self.assertEqual((o["permitida"], o["filtro"]), (False, "btc_bajo_media"))
        self.assertIsNotNone(o["puntaje"])            # el puntaje se ve: lo que no se puede es entrar
        self.assertEqual(e["mejor"]["estrategia"], "usdt")
        self.assertEqual((e["usdt"]["puntaje"], e["usdt"]["razon"]), (lib_puntaje.PUNTAJE_MAXIMO, "btc"))

    def test_el_puntaje_puede_salir_de_lo_ya_calculado_y_queda_escrito(self):
        self.guardar_todo()
        muestra_guardada(AHORA)
        ya = lib_indicadores_mercado.estado(AHORA)    # el motor, en su paso, los calcula una sola vez y los pasa
        self.assertEqual(lib_puntaje.estado(AHORA, indicadores=ya), lib_puntaje.estado(AHORA))
        e = puntaje.estado({}, AHORA)["datos"]
        with open(lib_puntaje.ruta_puntaje(), encoding="utf-8") as f:
            escrito = json.load(f)
        self.assertEqual((escrito["cuando"], escrito["motivos"]), (e["cuando"], e["motivos"]))
        self.assertEqual(escrito["familias"], list(lib_puntaje.FAMILIAS))
        self.assertEqual(escrito["maximo"], lib_puntaje.PUNTAJE_MAXIMO)
        self.assertEqual(escrito["parametros"]["casos_probabilidad"], lib_puntaje.CASOS_PROBABILIDAD)
        self.assertEqual(escrito["modelo"]["estado"], "sin_calibrar")
        self.assertEqual(escrito["exigencia"], lib_puntaje.EXIGENCIA_SIN_CALIBRAR)


class AccionPuntaje(unittest.TestCase):
    def test_sin_historial_no_hay_puntaje_en_vez_de_un_numero_inventado(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            r = correr("puntaje.py", "estado", entrada={}, datos=datos)
            self.assertTrue(r["ok"])
            self.assertFalse(r["datos"]["listo"])
            self.assertEqual(r["datos"]["opciones"], [])
            self.assertEqual(r["datos"]["usdt"]["puntaje"], 100.0)
            self.assertEqual(r["datos"]["modelo"]["estado"], "sin_calibrar")   # sin calibración, la exigencia es la alta
            self.assertEqual(r["datos"]["exigencia"], 85.0)
            self.assertEqual(r["datos"]["supuestos"]["sin_1m"], "stop_primero")
            self.assertIn("sin_backtest", {m["codigo"] for m in r["datos"]["motivos"]})
            with open(os.path.join(datos, "mercado", "puntaje.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["motivos"], r["datos"]["motivos"])

    def test_medir_sin_historial_deja_los_tramos_en_cero_en_vez_de_inventarlos(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            r = correr("puntaje.py", "medir", entrada={}, datos=datos)
            self.assertTrue(r["ok"])
            self.assertFalse(r["datos"]["listo"])
            self.assertEqual(r["datos"]["operaciones"], 0)
            self.assertEqual([t["tramo"] for t in r["datos"]["tramos"]],
                             ["0-20", "20-40", "40-60", "60-80", "80-100"])
            self.assertEqual(r["datos"]["parametros"]["casos_minimos"], 30)
            self.assertEqual(r["datos"]["supuestos"]["sin_1m"], "stop_primero")
            with open(os.path.join(datos, "mercado", "tramos.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["motivos"], r["datos"]["motivos"])


def notas_falsas(**cambios):
    """Las siete notas de una oportunidad: todas en la mitad de la escala salvo las que diga `cambios`."""
    return {**{f: lib_puntaje.NOTA_MEDIA for f in lib_puntaje.FAMILIAS}, **cambios}


#: Dos grupos de notas pensados para que los pesos de partida **no** puedan separar lo bueno de lo malo (las dos
#: puntúan 50 con todas las familias pesando lo mismo) y la calibración sí: subiéndole el peso a la tendencia, las que
#: ganan quedan arriba de las que pierden. Es lo que la prueba sabe de memoria.
NOTAS_GANA = notas_falsas(tendencia=100.0, impulso=0.0)
NOTAS_PIERDE = notas_falsas(tendencia=0.0, impulso=100.0)


def operacion_con_notas(notas, neto, senal_ms):
    """Una operación ya recorrida y puntuada, como la deja `lib_puntaje.seguir`, con las notas de sus siete familias
    pegadas: es lo único que la calibración necesita para volver a puntuarla con otros pesos."""
    paso = lib_datos.PASO_MS["1h"]
    o = una_operacion("ruptura", "BTCFDUSD", "1h", senal_ms + paso, senal_ms + 2 * paso, neto)
    return {**o, "senal_ms": senal_ms, "por": "objetivo" if neto > 0 else "stop",
            "etiqueta": lib_resolucion.CLARA, "puntaje": None, "tramo": "", "notas": notas}


def ops_calibracion(desde, hasta, cada_dias=2):
    """Operaciones que no se pisan entre sí, una cada `cada_dias` días: las de tendencia alta ganan y las de tendencia
    baja pierden, siempre igual, así se sabe de memoria qué tiene que elegir la calibración."""
    ops = []
    for i, ms in enumerate(range(desde, hasta, cada_dias * lib_datos.DIA_MS)):
        gana = i % 2 == 0
        ops.append(operacion_con_notas(NOTAS_GANA if gana else NOTAS_PIERDE, 0.02 if gana else -0.01, ms))
    return ops


def recorrido_falso(ops, desde, hasta):
    """Un historial ya recorrido, como lo deja `lib_calibracion.recorrido`: lo justo para calibrar sin recorrer
    ninguna vela. La tabla de notas va vacía a propósito: lo que mide la prueba son las operaciones."""
    return {"ahora": AHORA, "cuando": lib_datos.iso(AHORA), "ops": ops, "tabla": {},
            "ventana": lib_calibracion.tramo(desde, hasta), "series": [], "empalmes": [],
            "comisiones": lib_costos.comisiones(), "modelo": lib_costos.modelo(),
            "penetracion": lib_costos.PENETRACION_SPREADS, "motivos": [], "listo": True}


def backtest_falso(plan="normal"):
    """Un backtest de señales crudas guardado, con su compuerta: la que decide si el plan B deja calibrar."""
    return {"formato": 1, "corrido": True, "cuando": lib_datos.iso(AHORA), "series": [],
            "compuerta": {"casos_minimos": backtest.CASOS_MINIMOS, "operaciones": 900, "plan": plan,
                          "plan_b": plan != "normal", "no_validado": plan != "normal", "niveles": [], "tramos": [],
                          "listo": plan == "normal"}}


def medida_falsa(casos=120, neto=0.02, rendimiento=1.5, caida=0.1):
    """Lo que midió la prueba final, como lo deja `lib_calibracion.medir_puntuadas`."""
    return {**lib_calibracion.medida_vacia(70.0), "operaciones": casos, "casos": casos, "aciertos": 0.6,
            "neto_medio": neto, "rendimiento": rendimiento, "caida_maxima": caida, "objetivo": neto, "pocos": False}


class CalibracionDelPuntaje(ConCarpeta):
    """El año apartado, los pesos ajustados por ventanas con sus vueltas contadas, el backtest de nuevo con puntaje y
    exigencia, y la prueba final una sola vez con el criterio escrito antes."""

    DESDE, HASTA = AHORA - 1095 * lib_datos.DIA_MS, AHORA

    def guardar_todo(self):
        for par in lib_datos.PARES:
            for temporalidad in lib_datos.TEMPORALIDADES:
                lib_datos.guardar_serie(par, temporalidad, velas_que_suben(lib_indicadores.VENTANA, temporalidad))

    def calibrada(self, plan="normal", anterior=None, ops=None):
        """La calibración completa sobre operaciones ficticias de tres años, con la compuerta en `plan`."""
        r = recorrido_falso(ops if ops is not None else ops_calibracion(self.DESDE, self.HASTA),
                            self.DESDE, self.HASTA)
        return lib_calibracion.calibrar(AHORA, recorrida=r, reporte=backtest_falso(plan),
                                        anterior=anterior if anterior is not None else lib_calibracion.sin_calibrar())

    def test_el_ultimo_ano_se_aparta_antes_de_calibrar(self):
        a = lib_calibracion.apartar(lib_calibracion.tramo(self.DESDE, self.HASTA))
        self.assertEqual((a["dias"], a["nueva"], a["motivo"]), (lib_calibracion.DIAS_APARTADOS, True, ""))
        self.assertEqual(a["hasta"], self.HASTA)
        self.assertEqual(a["desde"], self.HASTA - lib_calibracion.DIAS_APARTADOS * lib_datos.DIA_MS)
        # Sin historial para el año apartado y las ventanas de antes, no se calibra nada y se dice cuánto falta
        corta = lib_calibracion.apartar(lib_calibracion.tramo(self.HASTA - 500 * lib_datos.DIA_MS, self.HASTA))
        self.assertEqual((corta["nueva"], corta["motivo"]), (False, "falta_historia"))
        self.assertEqual(corta["faltan_dias"], corta["dias_minimos"] - 500)
        sin = lib_calibracion.apartar({})
        self.assertEqual((sin["desde"], sin["nueva"], sin["motivo"]), (None, False, "falta_historia"))

    def test_la_prueba_final_no_se_repite_sobre_datos_ya_vistos(self):
        ventana = lib_calibracion.tramo(self.DESDE, self.HASTA)
        poco = lib_calibracion.apartar(ventana, {"hasta": self.HASTA - 30 * lib_datos.DIA_MS})
        self.assertEqual((poco["nueva"], poco["repetida"], poco["motivo"]), (False, True, "prueba_repetida"))
        self.assertEqual(poco["faltan_dias"], lib_calibracion.DIAS_PRUEBA_NUEVA - 30)
        # Con un tramo nuevo de verdad, la prueba final se puede volver a hacer: pero solo sobre ese tramo
        nuevo = lib_calibracion.apartar(ventana, {"hasta": self.HASTA - 120 * lib_datos.DIA_MS})
        self.assertEqual((nuevo["nueva"], nuevo["dias"], nuevo["motivo"]), (True, 120, ""))
        self.assertEqual(nuevo["desde"], self.HASTA - 120 * lib_datos.DIA_MS)

    def test_las_ventanas_son_doce_meses_para_ajustar_y_tres_para_probar(self):
        corte = self.HASTA - lib_calibracion.DIAS_APARTADOS * lib_datos.DIA_MS
        vs = lib_calibracion.ventanas_de(self.DESDE, corte)
        self.assertEqual([v["n"] for v in vs], list(range(1, len(vs) + 1)))
        self.assertTrue(vs)
        for v in vs:
            self.assertEqual(v["ajustar"]["dias"], lib_calibracion.MESES_AJUSTAR * lib_calibracion.DIAS_MES)
            self.assertEqual(v["probar"]["dias"], lib_calibracion.MESES_PROBAR * lib_calibracion.DIAS_MES)
            self.assertEqual(v["ajustar"]["hasta"], v["probar"]["desde"])   # se prueba con lo que viene después
            self.assertLessEqual(v["probar"]["hasta"], corte)               # nunca con el año apartado
        self.assertEqual(vs[1]["ajustar"]["desde"] - vs[0]["ajustar"]["desde"],
                         lib_calibracion.MESES_PROBAR * lib_calibracion.MES_MS)
        self.assertLessEqual(len(vs), lib_calibracion.VENTANAS_MAXIMAS)
        self.assertEqual(lib_calibracion.ventanas_de(None, corte), [])      # sin historial no hay ventanas

    def test_el_tramo_apartado_no_entra_en_el_ajuste(self):
        corte = self.HASTA - lib_calibracion.DIAS_APARTADOS * lib_datos.DIA_MS
        vs = lib_calibracion.ventanas_de(self.DESDE, corte)
        ops = ops_calibracion(self.DESDE, self.HASTA)
        ajuste, prueba = lib_calibracion.pools(ops, vs)
        self.assertTrue(ajuste and prueba)
        self.assertLess(max(o["senal_ms"] for o in ajuste + prueba), corte)
        # Una que no cerró, una que el filtro de BTC no dejaba entrar y una sin resultado no son casos
        colados = [*ops, dict(ops[0], motivo="sin_cerrar", neto=None), dict(ops[0], permitida=False),
                   dict(ops[0], neto=None)]
        self.assertEqual(len(lib_calibracion.pools(colados, vs)[0]), len(ajuste))

    def test_el_puntaje_con_otros_pesos_es_el_mismo_que_mirando_las_velas(self):
        pesos = {**lib_puntaje.PESOS_BASE, "tendencia": 2.0, "costo": 0.0}
        p = lib_puntaje.puntaje_de(VALORES, pesos)
        notas = lib_calibracion.notas_de(p["familias"])
        self.assertAlmostEqual(lib_calibracion.puntaje_con(notas, pesos), p["puntaje"], places=12)
        self.assertAlmostEqual(lib_calibracion.puntaje_con(notas, lib_puntaje.PESOS_BASE),
                               lib_puntaje.puntaje_de(VALORES)["puntaje"], places=12)
        # Las mismas reglas: sin una familia clave no hay puntaje y sin una de las otras cuatro se renormaliza
        sin_clave = {**notas, "contexto": None}
        self.assertIsNone(lib_calibracion.puntaje_con(sin_clave, lib_puntaje.PESOS_BASE))
        sin_volumen = {**notas, "volumen": None}
        esperado = lib_puntaje.puntaje_de({**VALORES, "volumen_relativo": None})["puntaje"]
        self.assertAlmostEqual(lib_calibracion.puntaje_con(sin_volumen, lib_puntaje.PESOS_BASE), esperado, places=12)
        self.assertIsNone(lib_calibracion.puntaje_con(notas, {f: 0.0 for f in lib_puntaje.FAMILIAS}))
        self.assertIsNone(lib_calibracion.puntaje_con({}, lib_puntaje.PESOS_BASE))

    def test_un_peso_se_mueve_solo_si_mejora_y_las_vueltas_se_cuentan(self):
        ops = ops_calibracion(self.DESDE, self.HASTA, cada_dias=4)
        # El corte va en un índice par (las operaciones vienen en orden de tiempo): así cada mitad queda con tantas que
        # ganan como que pierden y el promedio de los pesos de partida se sabe de memoria.
        corte = 2 * (len(ops) // 4)
        ajuste_ops, prueba_ops = ops[:corte], ops[corte:]
        # Con los pesos de partida las dos puntúan igual: ninguna exigencia separa lo bueno de lo malo
        base = lib_calibracion.mejor_exigencia(ajuste_ops, lib_puntaje.PESOS_BASE)
        self.assertAlmostEqual(base["neto_medio"], 0.005, places=12)
        d = lib_calibracion.ajustar(ajuste_ops, prueba_ops)
        self.assertGreater(d["pesos"]["tendencia"], lib_puntaje.PESOS_BASE["tendencia"])
        self.assertEqual(d["pesos"]["impulso"], lib_puntaje.PESOS_BASE["impulso"])   # moverlo no mejoraba nada
        self.assertEqual(d["maximas"], lib_calibracion.VUELTAS_MAXIMAS)
        self.assertLessEqual(d["cuantas"], lib_calibracion.VUELTAS_MAXIMAS)
        self.assertEqual(d["casos"], len(ajuste_ops))
        self.assertIn(d["exigencia"], lib_calibracion.EXIGENCIAS)
        # Con los pesos ajustados solo pasan las que ganan: eso es lo que la calibración tenía que encontrar
        elegida = next(v for v in d["vueltas"] if v["n"] == d["elegida"])
        self.assertAlmostEqual(elegida["ajuste"]["neto_medio"], 0.02, places=12)
        self.assertAlmostEqual(elegida["prueba"]["neto_medio"], 0.02, places=12)
        self.assertGreater(elegida["ajuste"]["objetivo"], base["objetivo"])
        self.assertEqual([c["familia"] for c in d["vueltas"][0]["cambios"]][0], "tendencia")

    def test_sin_casos_en_las_ventanas_no_se_ajusta_ningun_peso(self):
        pocas = lib_calibracion.evaluar(ops_calibracion(self.DESDE, self.DESDE + 20 * lib_datos.DIA_MS),
                                        lib_puntaje.PESOS_BASE, 50.0)
        self.assertIsNone(pocas["objetivo"])              # con 10 operaciones no hay nada que medir
        self.assertEqual((pocas["pocos"], pocas["casos_minimos"]), (True, lib_calibracion.CASOS_VENTANA))
        d = self.calibrada(ops=ops_calibracion(self.DESDE, self.DESDE + 20 * lib_datos.DIA_MS))
        self.assertEqual((d["estado"], d["motivo"], d["calibrado"]), ("sin_calibrar", "pocos_casos", False))
        self.assertEqual((d["exigencia"], d["tope"], d["topado"]),
                         (lib_calibracion.EXIGENCIA_NO_VALIDADO, lib_calibracion.TOPE_NO_VALIDADO, True))
        self.assertEqual(d["pesos"], dict(lib_puntaje.PESOS_BASE))
        self.assertFalse(d["prueba_final"]["hecha"])      # la prueba final no se gasta cuando no se ajustó nada
        self.assertIn("pocos_casos", {m["codigo"] for m in d["motivos"]})

    def test_sin_el_backtest_de_senales_crudas_no_se_calibra_nada(self):
        d = self.calibrada(plan="normal")
        self.assertTrue(d["calibrado"])
        sin = lib_calibracion.calibrar(AHORA, recorrida=recorrido_falso(
            ops_calibracion(self.DESDE, self.HASTA), self.DESDE, self.HASTA), reporte={},
            anterior=lib_calibracion.sin_calibrar())
        self.assertEqual((sin["estado"], sin["motivo"], sin["calibrado"]), ("sin_calibrar", "sin_backtest", False))
        self.assertFalse(sin["compuerta"]["corrido"])
        self.assertFalse(sin["prueba_final"]["hecha"])
        self.assertIn("sin_backtest", {m["codigo"] for m in sin["motivos"]})

    def test_el_criterio_esta_escrito_antes_y_se_revisa_entero(self):
        self.assertEqual(lib_calibracion.criterio(),
                         {"casos": lib_calibracion.CRITERIO_CASOS, "neto_medio": lib_calibracion.CRITERIO_NETO,
                          "rendimiento": lib_calibracion.CRITERIO_USDT, "caida_maxima": lib_calibracion.CRITERIO_CAIDA,
                          "plan": "normal", "una_vez": True})
        bien = lib_calibracion.aprobar(medida_falsa(), "normal", True)
        self.assertTrue(bien["aprobado"])
        self.assertEqual(bien["motivo"], "")
        self.assertEqual([x["que"] for x in bien["revisiones"]],
                         ["casos", "neto", "usdt", "caida", "plan", "nueva"])
        self.assertTrue(all(x["pasa"] for x in bien["revisiones"]))
        self.assertEqual(bien["criterio"], lib_calibracion.criterio())
        # Cada forma de no aprobar dice cuál fue, y las revisiones que pasaron se muestran igual
        self.assertEqual(lib_calibracion.aprobar(medida_falsa(casos=10), "normal", True)["motivo"], "pocos_casos")
        self.assertEqual(lib_calibracion.aprobar(medida_falsa(neto=-0.001), "normal", True)["motivo"],
                         "no_deja_nada")
        self.assertEqual(lib_calibracion.aprobar(medida_falsa(rendimiento=-0.2), "normal", True)["motivo"],
                         "no_gana_a_usdt")
        self.assertEqual(lib_calibracion.aprobar(medida_falsa(caida=0.4), "normal", True)["motivo"], "caida_grande")
        self.assertEqual(lib_calibracion.aprobar(medida_falsa(), "unico", True)["motivo"], "plan_b")
        self.assertEqual(lib_calibracion.aprobar(medida_falsa(), "normal", False)["motivo"], "prueba_repetida")
        self.assertEqual(lib_calibracion.aprobar(None)["motivo"], "pocos_casos")

    def test_si_la_compuerta_uso_el_plan_b_el_modelo_no_queda_validado(self):
        d = self.calibrada(plan="unico")
        self.assertEqual((d["estado"], d["motivo"]), ("no_validado", "plan_b"))
        self.assertTrue(d["calibrado"])                   # los pesos se ajustaron, pero nada está probado
        self.assertEqual((d["exigencia"], d["tope"], d["topado"]),
                         (lib_calibracion.EXIGENCIA_NO_VALIDADO, lib_calibracion.TOPE_NO_VALIDADO, True))
        self.assertGreater(d["pesos"]["tendencia"], lib_puntaje.PESOS_BASE["tendencia"])
        self.assertFalse(d["aprobacion"]["aprobado"])
        self.assertFalse(next(x for x in d["aprobacion"]["revisiones"] if x["que"] == "plan")["pasa"])
        self.assertTrue(next(x for x in d["aprobacion"]["revisiones"] if x["que"] == "casos")["pasa"])
        self.assertFalse(lib_calibracion.modelo(d)["validado"])
        self.assertEqual(lib_calibracion.modelo(d)["tope"], lib_calibracion.TOPE_NO_VALIDADO)

    def test_con_la_compuerta_pasada_y_la_prueba_final_aprobada_queda_validado(self):
        d = self.calibrada(plan="normal")
        self.assertEqual((d["estado"], d["motivo"], d["calibrado"]), ("validado", "", True))
        self.assertEqual(d["exigencia"], d["ajuste"]["exigencia"])
        self.assertEqual((d["tope"], d["topado"]), (None, False))
        self.assertTrue(d["aprobacion"]["aprobado"])
        self.assertTrue(d["prueba_final"]["hecha"])
        self.assertEqual(d["prueba_final"]["ventana"]["dias"], lib_calibracion.DIAS_APARTADOS)
        self.assertGreaterEqual(d["prueba_final"]["medida"]["casos"], lib_calibracion.CRITERIO_CASOS)
        self.assertGreater(d["prueba_final"]["medida"]["neto_medio"], 0)
        # El reporte compara siempre con quedarse en USDT y con comprar BTC y esperar
        self.assertEqual(d["referencias"]["de"], "prueba_final")
        self.assertEqual(d["referencias"]["usdt"]["rendimiento"], 0.0)
        self.assertEqual(d["referencias"]["btc"]["que"], "comprar_y_esperar")
        self.assertTrue(d["rebacktest"]["corrido"])
        self.assertLessEqual(d["rebacktest"]["ventana"]["hasta"], d["apartado"]["desde"])
        self.assertEqual(lib_calibracion.modelo(d)["estado"], "validado")
        self.assertIsNone(lib_calibracion.modelo(d)["tope"])
        # Y el supuesto de las velas sin 1 m sigue marcado: esto ya no es sin exigencia
        self.assertEqual(d["supuestos"]["sin_1m"], backtest.SUPUESTO_AMBIGUO)
        self.assertFalse(d["supuestos"]["sin_exigencia"])

    def test_calibrar_de_nuevo_no_vuelve_a_gastar_la_prueba_final(self):
        antes = self.calibrada(plan="normal")
        self.assertTrue(antes["prueba_final"]["hecha"])
        otra = self.calibrada(plan="normal", anterior=antes)
        self.assertEqual((otra["estado"], otra["motivo"]), ("no_validado", "prueba_repetida"))
        self.assertFalse(otra["prueba_final"]["hecha"])
        self.assertTrue(otra["apartado"]["repetida"])
        self.assertEqual(otra["exigencia"], lib_calibracion.EXIGENCIA_NO_VALIDADO)
        self.assertEqual(otra["referencias"]["de"], "rebacktest")
        # Lo mismo leyendo la calibración guardada: de la prueba final anterior se mira **su ventana** (hasta dónde
        # llegaron los datos que el modelo ya vio), no la prueba entera, que no tiene fecha de hasta cuándo llegó
        lib_calibracion.escribir(antes)
        r = recorrido_falso(ops_calibracion(self.DESDE, self.HASTA), self.DESDE, self.HASTA)
        de_disco = lib_calibracion.calibrar(AHORA, recorrida=r, reporte=backtest_falso("normal"))
        self.assertEqual((de_disco["estado"], de_disco["motivo"]), ("no_validado", "prueba_repetida"))
        self.assertFalse(de_disco["prueba_final"]["hecha"])
        self.assertEqual(de_disco["apartado"]["hasta"], antes["prueba_final"]["ventana"]["hasta"])
        self.assertEqual(de_disco["apartado"]["dias_minimos"], lib_calibracion.DIAS_PRUEBA_NUEVA)

    def test_la_calibracion_queda_escrita_y_el_puntaje_la_encuentra(self):
        self.assertFalse(lib_calibracion.guardada()["corrido"])     # antes de calibrar no se inventa nada
        self.assertEqual(lib_calibracion.guardada()["estado"], "sin_calibrar")
        self.assertEqual(lib_calibracion.modelo()["exigencia"], lib_puntaje.EXIGENCIA_SIN_CALIBRAR)
        d = lib_calibracion.escribir(self.calibrada(plan="normal"))
        with open(lib_calibracion.ruta_calibracion(), encoding="utf-8") as f:
            escrito = json.load(f)
        self.assertEqual((escrito["cuando"], escrito["estado"]), (d["cuando"], "validado"))
        guardada = lib_calibracion.guardada()
        self.assertEqual(guardada["pesos"], d["pesos"])
        # Es lo que el puntaje lee para saber con qué pesos y con qué exigencia se mira una oportunidad
        m = lib_puntaje.modelo(guardada)
        self.assertEqual((m["estado"], m["calibrado"]), ("validado", True))
        self.assertEqual((m["pesos"], m["exigencia"]), (d["pesos"], d["exigencia"]))
        self.assertEqual(lib_puntaje.estado(AHORA, calibracion=guardada)["exigencia"], d["exigencia"])

    def test_la_exigencia_entra_por_el_gancho_y_da_lo_mismo_que_filtrar_despues(self):
        self.guardar_todo()
        lib_datos.guardar_serie("BTCFDUSD", "4h", serie_con_una_operacion("4h")[0])
        r = lib_calibracion.recorrido(AHORA)
        self.assertTrue(r["listo"])
        fila = next(s for s in r["series"] if (s["par"], s["temporalidad"]) == ("BTCFDUSD", "4h"))
        self.assertEqual((fila["senales"], fila["puntuadas"], fila["operaciones"]), (1, 1, 1))
        suya = next(o for o in r["ops"] if not o["motivo"])
        self.assertEqual(sorted(suya["notas"]), sorted(lib_puntaje.FAMILIAS))
        self.assertIn(lib_calibracion.clave_de({"estrategia": "ruptura", "par": "BTCFDUSD", "temporalidad": "4h",
                                                "vela": suya["senal_ms"]}), r["tabla"])
        # Por el gancho de `backtest.correr` sale lo mismo que filtrando las operaciones después: no es una cartera
        t = lib_calibracion.tramo(r["ventana"]["desde"], r["ventana"]["hasta"] + 1)
        todo = lib_calibracion.correr_con(lib_puntaje.PESOS_BASE, 0.0, t, r, AHORA)
        self.assertEqual(todo["resumen"]["operaciones"], todo["medida"]["operaciones"])
        self.assertEqual(todo["medida"]["operaciones"], 1)
        self.assertFalse(todo["supuestos"]["sin_exigencia"])
        nada = lib_calibracion.correr_con(lib_puntaje.PESOS_BASE, 100.0, t, r, AHORA)
        self.assertEqual((nada["resumen"]["operaciones"], nada["medida"]["operaciones"]), (0, 0))

    def test_sin_historial_suficiente_se_dice_que_falta_en_vez_de_calibrar(self):
        self.guardar_todo()
        backtest.escribir(backtest.correr(AHORA))
        d = lib_calibracion.calibrar(AHORA)
        self.assertEqual((d["estado"], d["motivo"], d["calibrado"]), ("sin_calibrar", "falta_historia", False))
        self.assertEqual(d["ventanas"], [])
        self.assertEqual(d["exigencia"], lib_calibracion.EXIGENCIA_NO_VALIDADO)
        self.assertEqual(d["tope"], lib_calibracion.TOPE_NO_VALIDADO)
        self.assertFalse(d["prueba_final"]["hecha"])
        self.assertIn("falta_historia", {m["codigo"] for m in d["motivos"]})
        self.assertEqual(d["parametros"]["criterio"], lib_calibracion.criterio())


class AccionCalibracion(unittest.TestCase):
    def test_sin_calibrar_la_pantalla_lo_dice_y_no_inventa_ningun_peso(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            r = correr("calibrar.py", "estado", entrada={}, datos=datos)
            self.assertTrue(r["ok"])
            self.assertFalse(r["datos"]["corrido"])
            self.assertEqual(r["datos"]["estado"], "sin_calibrar")
            self.assertEqual(r["datos"]["exigencia"], 85.0)
            self.assertEqual(r["datos"]["tope"], 15.0)
            self.assertEqual(set(r["datos"]["pesos"].values()), {1.0})
            r = correr("calibrar.py", "correr", entrada={}, datos=datos)
            self.assertTrue(r["ok"])
            self.assertFalse(r["datos"]["listo"])
            self.assertEqual(r["datos"]["motivo"], "sin_backtest")   # la compuerta de casos va antes
            self.assertFalse(r["datos"]["prueba_final"]["hecha"])
            with open(os.path.join(datos, "mercado", "calibracion.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["motivos"], r["datos"]["motivos"])


class RegistroQueNoSeBorra(ConCarpeta):
    def test_cada_linea_lleva_siempre_los_mismos_campos(self):
        fila = lib_registro.anotar("prueba", "entrada_ruptura", par="BTCFDUSD", puntaje=84.0,
                                   orden={"lado": "compra", "monto": 60.0, "precio": 94830.0, "stop": 93869.7},
                                   resultado={}, ms=AHORA)
        self.assertEqual(tuple(fila), lib_registro.CAMPOS)
        self.assertEqual(fila["fecha"], lib_datos.iso(AHORA))      # la fecha sale del ms, no se escribe aparte
        self.assertEqual(fila["orden"]["monto"], 60.0)
        self.assertEqual(fila["resultado"], {})
        # Una línea sin par ni puntaje (un arranque, un freno) trae los campos igual, vacíos.
        suelta = lib_registro.anotar("prueba", "arranque_frenado", resultado={"motivo": "huella_no_cuadra"}, ms=AHORA)
        self.assertEqual(tuple(suelta), lib_registro.CAMPOS)
        self.assertEqual((suelta["par"], suelta["puntaje"], suelta["orden"]), ("", None, {}))

    def test_solo_se_agrega_al_final_y_nada_se_reescribe(self):
        primera = lib_registro.anotar("prueba", "quedarse_en_usdt", puntaje=50.0, ms=AHORA)
        with open(lib_registro.ruta("prueba", AHORA), encoding="utf-8") as f:
            antes = f.readline()
        for i in range(3):
            lib_registro.anotar("prueba", "propuesta", par="ETHFDUSD", puntaje=62.0, ms=AHORA + 1000 * (i + 1))
        with open(lib_registro.ruta("prueba", AHORA), encoding="utf-8") as f:
            lineas = f.readlines()
        self.assertEqual(len(lineas), 4)
        self.assertEqual(lineas[0], antes, "la primera línea quedó igual: el registro solo agrega")
        recientes, danadas = lib_registro.ultimas("prueba")
        self.assertEqual([l["razon"] for l in recientes][-1], primera["razon"], "la más vieja queda al final")
        self.assertEqual((len(recientes), danadas), (4, 0))
        self.assertEqual(lib_registro.cuantas("prueba"), 4)
        self.assertEqual(lib_registro.primera("prueba")["ms"], AHORA)

    def test_nada_de_texto_de_afuera_entra_al_registro(self):
        with self.assertRaises(ValueError):
            lib_registro.anotar("prueba", "lo_que_sea", ms=AHORA)                       # una razón inventada
        with self.assertRaises(ValueError):
            lib_registro.anotar("prueba", "rechazo", par="DOGEFDUSD", ms=AHORA)          # un par que no operamos
        with self.assertRaises(ValueError):
            lib_registro.anotar("prueba", "rechazo", puntaje=120.0, ms=AHORA)            # fuera de la escala
        with self.assertRaises(ValueError):
            lib_registro.anotar("prueba", "rechazo", orden={"comentario": "hola"}, ms=AHORA)   # una clave que no existe
        with self.assertRaises(ValueError):
            # Lo que respondería Binance, tal cual: eso nunca llega a la pantalla convertido en texto.
            lib_registro.anotar("prueba", "rechazo", resultado={"motivo": "Error 400: Filter failure\n"}, ms=AHORA)
        self.assertEqual(lib_registro.cuantas("prueba"), 0, "nada de eso quedó escrito")

    def test_prueba_y_real_llevan_registros_separados(self):
        lib_registro.anotar("prueba", "saldo_reiniciado", resultado={"saldo": 200.0}, ms=AHORA)
        self.assertEqual(lib_registro.cuantas("prueba"), 1)
        self.assertEqual(lib_registro.cuantas("real"), 0)
        self.assertEqual(lib_registro.ultimas("real")[0], [])
        with self.assertRaises(ValueError):
            lib_registro.anotar("otro", "propuesta", ms=AHORA)

    def test_una_linea_a_medias_no_tapa_ni_borra_las_otras(self):
        lib_registro.anotar("prueba", "objetivo", par="BTCFDUSD", puntaje=84.0,
                            resultado={"por": "objetivo", "neto": 0.52}, ms=AHORA)
        with open(lib_registro.ruta("prueba", AHORA), "a", encoding="utf-8") as f:
            f.write('{"ms": 1770732300000, "razon": "obje\n')      # un corte de luz a la mitad de la línea
        lib_registro.anotar("prueba", "stop", par="ETHFDUSD", puntaje=73.0, resultado={"por": "stop"}, ms=AHORA + 60_000)
        recientes, danadas = lib_registro.ultimas("prueba")
        self.assertEqual([l["razon"] for l in recientes], ["stop", "objetivo"])
        self.assertEqual(danadas, 1, "la que quedó a medias se cuenta y se dice")
        self.assertEqual(lib_registro.cuantas("prueba"), 3, "pero no se borra: en el archivo sigue estando")

    def test_una_fecha_editada_a_mano_no_engana(self):
        linea = lib_registro.linea("propuesta", par="BTCFDUSD", puntaje=70.0, ms=AHORA)
        revisada = lib_registro.revisar({**linea, "fecha": "2001-01-01T00:00:00Z"})
        self.assertEqual(revisada["fecha"], lib_datos.iso(AHORA), "la fecha se vuelve a sacar del ms")
        with self.assertRaises(ValueError):
            lib_registro.revisar({"razon": "propuesta"})          # sin ms no es una línea del registro

    def test_cada_anio_en_su_archivo(self):
        un_anio = 366 * 24 * 60 * 60 * 1000
        lib_registro.anotar("prueba", "propuesta", par="BTCFDUSD", puntaje=70.0, ms=AHORA)
        lib_registro.anotar("prueba", "objetivo", par="BTCFDUSD", puntaje=70.0, ms=AHORA + un_anio)
        self.assertEqual(lib_registro.anios("prueba"), ["2026", "2027"])
        recientes, _ = lib_registro.ultimas("prueba")
        self.assertEqual([l["razon"] for l in recientes], ["objetivo", "propuesta"], "las últimas cruzan los dos años")

    def test_el_resumen_dice_cuantas_lleva_y_desde_cuando(self):
        self.assertEqual(lib_registro.resumen("prueba", ahora_ms=AHORA)["lineas"], 0)
        lib_registro.anotar("prueba", "arranque_frenado", resultado={"motivo": "sin_estado"},
                            ms=AHORA - 9 * 86_400_000)
        lib_registro.anotar("prueba", "quedarse_en_usdt", puntaje=50.0, ms=AHORA)
        r = lib_registro.resumen("prueba", ahora_ms=AHORA)
        self.assertEqual((r["lineas"], r["dias"], r["anios"]), (2, 9, ["2026"]))
        self.assertEqual(r["campos"], list(lib_registro.CAMPOS))
        self.assertEqual(r["ultimas"][0]["razon"], "quedarse_en_usdt")

    def test_la_escala_del_puntaje_es_la_misma_del_puntaje(self):
        self.assertEqual(lib_registro.PUNTAJE_MAXIMO, lib_puntaje.PUNTAJE_MAXIMO)


class EstadoFirmado(ConCarpeta):
    def test_la_primera_vez_no_es_un_freno(self):
        e = lib_estado.cargar("prueba", ahora_ms=AHORA)
        self.assertFalse(e["frenado"])
        self.assertTrue(e["arranque"]["nuevo"])
        self.assertEqual(e["arranque"]["motivo"], "primera_vez")
        self.assertEqual((e["saldo"], e["referencia"], e["modo"]), (0.0, 0.0, "manual"))

    def test_lo_guardado_vuelve_igual(self):
        cuerpo = lib_estado.nuevo("prueba", 200.0, ahora_ms=AHORA)
        lib_estado.guardar("prueba", cuerpo)
        e = lib_estado.cargar("prueba", ahora_ms=AHORA + 60_000)
        self.assertFalse(e["frenado"])
        self.assertFalse(e["arranque"]["nuevo"])
        self.assertEqual((e["saldo"], e["referencia"], e["aportado"]), (200.0, 200.0, 200.0))
        self.assertEqual([(a["que"], a["monto"]) for a in e["aportes"]], [("deposito", 200.0)])

    def test_sin_archivo_pero_con_registro_arranca_frenado(self):
        lib_registro.anotar("prueba", "entrada_ruptura", par="BTCFDUSD", puntaje=84.0, ms=AHORA)
        e = lib_estado.cargar("prueba", ahora_ms=AHORA)
        self.assertEqual((e["frenado"], e["motivo"], e["modo"]), (True, "sin_estado", "manual"))
        self.assertFalse(e["arranque"]["nuevo"], "esta cuenta ya vivió algo: el estado se perdió")

    def test_la_huella_que_no_cuadra_arranca_frenado_y_no_se_cree_los_numeros(self):
        lib_estado.guardar("prueba", lib_estado.nuevo("prueba", 200.0, ahora_ms=AHORA))
        archivo = lib_estado.ruta("prueba")
        with open(archivo, encoding="utf-8") as f:
            d = json.load(f)
        d["estado"]["saldo"] = 99999.0                       # alguien o algo cambió el archivo por fuera
        with open(archivo, "w", encoding="utf-8") as f:
            json.dump(d, f)
        with open(archivo, encoding="utf-8") as f:
            antes = f.read()
        e = lib_estado.cargar("prueba", ahora_ms=AHORA)
        self.assertEqual((e["frenado"], e["motivo"], e["modo"]), (True, "huella_no_cuadra", "manual"))
        self.assertEqual(e["saldo"], 0.0, "de un número del que no se puede fiar nadie no sale un tamaño")
        self.assertEqual(e["leido"]["saldo"], 99999.0, "lo que decía el archivo se muestra, marcado")
        with open(archivo, encoding="utf-8") as f:
            self.assertEqual(f.read(), antes, "el archivo sospechoso no se pisa")

    def test_la_fecha_futura_arranca_frenado(self):
        lib_estado.guardar("prueba", lib_estado.nuevo("prueba", 200.0, ahora_ms=AHORA))
        e = lib_estado.cargar("prueba", ahora_ms=AHORA - 2 * 60 * 1000)
        self.assertFalse(e["frenado"], "unos minutos son el reloj del computador, no un archivo de otro día")
        e = lib_estado.cargar("prueba", ahora_ms=AHORA - 86_400_000)
        self.assertEqual((e["frenado"], e["motivo"]), (True, "fecha_futura"))

    def test_un_archivo_a_medias_arranca_frenado(self):
        with open(lib_estado.ruta("prueba"), "w", encoding="utf-8") as f:
            f.write('{"formato": 1, "huella": "abc", "est')
        e = lib_estado.cargar("prueba", ahora_ms=AHORA)
        self.assertEqual((e["frenado"], e["motivo"]), (True, "formato_desconocido"))

    def test_el_estado_de_prueba_no_sirve_para_la_cuenta_real(self):
        lib_estado.guardar("prueba", lib_estado.nuevo("prueba", 200.0, ahora_ms=AHORA))
        with open(lib_estado.ruta("prueba"), encoding="utf-8") as f:
            copia = f.read()
        with open(lib_estado.ruta("real"), "w", encoding="utf-8") as f:
            f.write(copia)
        e = lib_estado.cargar("real", ahora_ms=AHORA)
        self.assertTrue(e["frenado"], "el ambiente va dentro de la huella: dos cuentas no se confunden")
        self.assertIn(e["motivo"], ("huella_no_cuadra", "otro_ambiente"))
        self.assertEqual(e["saldo"], 0.0)

    def test_el_modo_vuelve_a_manual_cuando_arranca_frenado(self):
        cuerpo = lib_estado.con_modo(lib_estado.nuevo("prueba", 200.0, ahora_ms=AHORA), "automatico", ahora_ms=AHORA)
        lib_estado.guardar("prueba", cuerpo)
        self.assertEqual(lib_estado.cargar("prueba", ahora_ms=AHORA)["modo"], "automatico")
        with open(lib_estado.ruta("prueba"), encoding="utf-8") as f:
            d = json.load(f)
        with open(lib_estado.ruta("prueba"), "w", encoding="utf-8") as f:
            json.dump({**d, "huella": "0" * 64}, f)
        self.assertEqual(lib_estado.cargar("prueba", ahora_ms=AHORA)["modo"], "manual")
        with self.assertRaises(ValueError):
            lib_estado.con_modo(cuerpo, "turbo")

    def test_la_referencia_sube_con_las_ganancias_y_nunca_baja(self):
        cuerpo = lib_estado.nuevo("prueba", 200.0, ahora_ms=AHORA)
        cuerpo = lib_estado.con_saldo(cuerpo, 214.8, ahora_ms=AHORA)
        self.assertEqual((cuerpo["saldo"], cuerpo["referencia"]), (214.8, 214.8))
        cuerpo = lib_estado.con_saldo(cuerpo, 205.0, ahora_ms=AHORA)
        self.assertEqual((cuerpo["saldo"], cuerpo["referencia"]), (205.0, 214.8))

    def test_un_deposito_no_es_una_ganancia_ni_un_retiro_una_perdida(self):
        cuerpo = lib_estado.con_saldo(lib_estado.nuevo("prueba", 200.0, ahora_ms=AHORA), 214.8, ahora_ms=AHORA)
        cuerpo = lib_estado.con_aporte(cuerpo, 100.0, ahora_ms=AHORA)
        self.assertEqual((cuerpo["saldo"], cuerpo["referencia"], cuerpo["aportado"]), (314.8, 314.8, 300.0))
        cuerpo = lib_estado.con_aporte(cuerpo, -50.0, ahora_ms=AHORA)
        self.assertEqual((cuerpo["saldo"], cuerpo["referencia"], cuerpo["aportado"]), (264.8, 264.8, 250.0))
        self.assertEqual([(a["que"], a["monto"]) for a in cuerpo["aportes"]],
                         [("deposito", 200.0), ("deposito", 100.0), ("retiro", 50.0)])
        with self.assertRaises(ValueError):
            lib_estado.con_aporte(cuerpo, -1000.0, ahora_ms=AHORA)
        with self.assertRaises(ValueError):
            lib_estado.nuevo("prueba", float("inf"), ahora_ms=AHORA)

    def test_arrancar_deja_cada_arranque_frenado_en_el_registro(self):
        lib_registro.anotar("prueba", "entrada_rebote", par="ETHFDUSD", puntaje=72.0, ms=AHORA)
        d = lib_estado.arrancar(AHORA)
        prueba = next(c for c in d["cuentas"] if c["ambiente"] == "prueba")
        self.assertTrue(d["frenado"])
        self.assertEqual(d["activo"], "prueba")
        self.assertEqual(prueba["registro"]["ultimas"][0]["razon"], "arranque_frenado")
        self.assertEqual(prueba["registro"]["ultimas"][0]["resultado"]["motivo"], "sin_estado")
        lib_estado.arrancar(AHORA)
        self.assertEqual(lib_registro.cuantas("prueba"), 3, "una línea por arranque, ni una más")
        self.assertEqual(lib_registro.cuantas("real"), 0, "la cuenta real nunca arrancó: no hay nada que perder")

    def test_reiniciar_el_saldo_de_prueba_es_al_tiro_y_queda_en_el_registro(self):
        d = lib_estado.reiniciar(200.0, AHORA)
        prueba = next(c for c in d["cuentas"] if c["ambiente"] == "prueba")
        self.assertEqual((prueba["saldo"], prueba["referencia"], prueba["reinicios"]), (200.0, 200.0, 1))
        self.assertFalse(prueba["frenado"], "queda listo al tiro: no hay que esperar 24 h en prueba")
        ultima = prueba["registro"]["ultimas"][0]
        self.assertEqual((ultima["razon"], ultima["resultado"]["saldo"], ultima["resultado"]["n"]),
                         ("saldo_reiniciado", 200.0, 1))
        d = lib_estado.reiniciar(50.0, AHORA + 60_000)
        prueba = next(c for c in d["cuentas"] if c["ambiente"] == "prueba")
        self.assertEqual((prueba["saldo"], prueba["reinicios"]), (50.0, 2))
        self.assertEqual(lib_registro.cuantas("prueba"), 2)
        real = next(c for c in d["cuentas"] if c["ambiente"] == "real")
        self.assertTrue(real["arranque"]["nuevo"], "prueba y real van por separado")
        self.assertEqual(real["registro"]["lineas"], 0)

    def test_el_estado_dice_con_que_dinero_se_juega_y_que_campos_tiene_el_registro(self):
        d = lib_estado.estado(AHORA)
        self.assertEqual([c["ambiente"] for c in d["cuentas"]], ["prueba", "real"])
        self.assertEqual(d["activo"], "prueba")
        self.assertEqual(d["parametros"]["campos"], list(lib_registro.CAMPOS))
        self.assertEqual(d["parametros"]["modo_frenado"], "manual")
        self.assertEqual(d["parametros"]["motivos"], list(lib_estado.MOTIVOS_FRENADO))

    def test_la_accion_revisa_el_monto_antes_de_tocar_nada(self):
        r = accion_estado.arrancar({}, AHORA)
        self.assertTrue(r["ok"])
        self.assertEqual(r["datos"]["activo"], lib_estado.activo())
        mal = accion_estado.reiniciar({"saldo": lib_estado.SALDO_MAXIMO + 1}, AHORA)
        self.assertEqual((mal["ok"], mal["error"]), (False, "monto"))
        self.assertFalse(os.path.exists(lib_estado.ruta("prueba")))


class AccionEstado(unittest.TestCase):
    def test_arranca_sin_nada_y_el_reinicio_queda_escrito_con_su_huella(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            r = correr("estado.py", "arrancar", entrada={}, datos=datos)
            self.assertTrue(r["ok"])
            self.assertFalse(r["datos"]["frenado"])
            self.assertEqual(r["datos"]["activo"], "prueba")
            self.assertEqual(len(r["datos"]["cuentas"]), 2)
            self.assertTrue(all(c["arranque"]["nuevo"] for c in r["datos"]["cuentas"]))
            r = correr("estado.py", "reiniciar", entrada={"saldo": 200}, datos=datos)
            self.assertTrue(r["ok"])
            prueba = next(c for c in r["datos"]["cuentas"] if c["ambiente"] == "prueba")
            self.assertEqual(prueba["saldo"], 200.0)
            with open(os.path.join(datos, "estado", "prueba.json"), encoding="utf-8") as f:
                guardado = json.load(f)
            self.assertEqual(len(guardado["huella"]), 64)
            self.assertEqual(guardado["estado"]["saldo"], 200.0)
            anio = prueba["registro"]["anios"][0]
            with open(os.path.join(datos, "registro", "prueba", f"{anio}.jsonl"), encoding="utf-8") as f:
                lineas = [json.loads(l) for l in f if l.strip()]
            self.assertEqual([l["razon"] for l in lineas], ["saldo_reiniciado"])
            # Y con el estado escrito, un arranque siguiente lo encuentra: nada de frenos inventados.
            r = correr("estado.py", "arrancar", entrada={}, datos=datos)
            self.assertFalse(r["datos"]["frenado"])

    def test_un_monto_que_no_es_un_monto_no_reinicia_nada(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            r = correr("estado.py", "reiniciar", entrada={"saldo": "mucho"}, datos=datos)
            self.assertFalse(r["ok"])
            self.assertEqual(r["error"], "monto")
            self.assertFalse(os.path.exists(os.path.join(datos, "estado", "prueba.json")))
            r = correr("estado.py", "reiniciar", entrada={"saldo": -5}, datos=datos)
            self.assertFalse(r["ok"])

    def test_el_archivo_perdido_deja_la_app_frenada_en_manual(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            correr("estado.py", "reiniciar", entrada={"saldo": 200}, datos=datos)
            os.remove(os.path.join(datos, "estado", "prueba.json"))
            r = correr("estado.py", "arrancar", entrada={}, datos=datos)
            self.assertTrue(r["datos"]["frenado"])
            self.assertEqual(r["datos"]["motivo"], "sin_estado")
            self.assertEqual(r["datos"]["modo"], "manual")


def filtros_falsos(par="BTCFDUSD", **cambios):
    """Los filtros de un par como los deja el capital mínimo viable, con los mínimos de la API de juguete."""
    f = FILTROS[par]
    return {"par": par, "moneda": par[:3], "tick": float(f["tick"]), "paso": float(f["paso"]),
            "cantidad_minima": float(f["cantidad"]), "nocional_minimo": float(f["nocional"]),
            "proteccion": True, "operando": True, "motivo": "", **cambios}


class TamanoDeLaOperacion(unittest.TestCase):
    """El monto de una operación en el orden fijo: los mínimos de Binance, la reserva, las dos posiciones y el 2 %."""

    def test_el_orden_es_el_mismo_del_capital_minimo_viable(self):
        self.assertEqual((lib_tamano.RESERVA, lib_tamano.POSICIONES, lib_tamano.RIESGO),
                         (minimo_viable.RESERVA, minimo_viable.POSICIONES, minimo_viable.RIESGO))
        self.assertEqual(lib_tamano.parametros()["tope_no_validado"], lib_calibracion.TOPE_NO_VALIDADO)

    def test_la_reserva_se_queda_en_usdt_y_caben_dos_posiciones(self):
        r = lib_tamano.reparto(200.0)
        self.assertEqual((r["en_usdt"], r["operable"], r["por_posicion"]), (80.0, 120.0, 60.0))
        self.assertEqual((r["disponible"], r["abiertas"], r["quedan"]), (60.0, 0, 2))
        self.assertEqual(r["riesgo_maximo"], 4.0)
        # Lo que ya está puesto en una posición abierta no se reparte de nuevo
        con_una = lib_tamano.reparto(200.0, abiertas=1, comprometido=60.0)
        self.assertEqual((con_una["libre"], con_una["disponible"], con_una["quedan"]), (60.0, 60.0, 1))
        llena = lib_tamano.reparto(200.0, abiertas=2, comprometido=120.0)
        self.assertEqual((llena["quedan"], llena["libre"]), (0, 0.0))

    def test_el_monto_es_el_menor_de_los_tres_limites(self):
        f = filtros_falsos()
        # Con un stop a 1 %, el que corta es lo disponible para esa posición (60 USDT), no el riesgo (347 USDT)
        t = lib_tamano.tamano(200.0, 95000.0, 94050.0, f)
        self.assertEqual((t["puede"], t["manda"], t["motivo"]), (True, "disponible", ""))
        self.assertEqual(t["cantidad"], 0.00063)                   # al paso de Binance, siempre hacia abajo
        self.assertAlmostEqual(t["monto"], 59.939775, places=9)
        self.assertLessEqual(t["monto"], t["disponible"], "nunca más de lo disponible para esa posición")
        self.assertLessEqual(t["arriesgado"], t["riesgo_maximo"], "ni más riesgo que el 2 % del capital")
        self.assertAlmostEqual(t["arriesgado"], 0.00063 * 950 + t["costos"], places=9)
        self.assertIsNone(t["tope"])
        self.assertFalse(t["topado"])
        # Con un stop lejos, el que corta es el riesgo del 2 % (y la pata del stop sigue pasando el nocional mínimo)
        lejos = lib_tamano.tamano(200.0, 95000.0, 88000.0, f)
        self.assertEqual((lejos["puede"], lejos["manda"]), (True, "riesgo"))
        self.assertEqual(lejos["cantidad"], 0.00056)
        self.assertLessEqual(lejos["arriesgado"], lejos["riesgo_maximo"])
        self.assertLess(lejos["monto"], t["monto"])

    def test_el_tope_del_modelo_sin_validar_corta_el_monto(self):
        f = filtros_falsos()
        t = lib_tamano.tamano(200.0, 95000.0, 94050.0, f, tope=lib_calibracion.TOPE_NO_VALIDADO)
        self.assertEqual((t["puede"], t["manda"], t["topado"]), (True, "tope", True))
        self.assertEqual(t["cantidad"], 0.00015)
        self.assertLessEqual(t["monto"], lib_calibracion.TOPE_NO_VALIDADO, "con el tope puesto, el monto no lo pasa")
        self.assertAlmostEqual(t["monto"], 14.271375, places=9)
        self.assertEqual([l["que"] for l in t["limites"]], ["riesgo", "disponible", "tope"])

    def test_bajo_el_minimo_de_binance_se_rechaza_con_el_motivo_y_con_cuanto_falta(self):
        t = lib_tamano.tamano(10.0, 95000.0, 94050.0, filtros_falsos())
        self.assertEqual((t["puede"], t["motivo"]), (False, "bajo_minimo"))
        self.assertEqual((t["cantidad"], t["monto"]), (0.0, 0.0), "una orden que Binance rechaza no se manda")
        self.assertEqual(t["minimo"]["cantidad"], 0.00006, "la pata del stop es la que manda, no la compra")
        self.assertAlmostEqual(t["minimo"]["posicion"], 5.70855, places=9)
        self.assertEqual(t["minimo"]["capital"], 20, "y se dice desde cuánto capital sí se podría")
        # Un stop tan lejos que la cantidad que deja el riesgo no alcanza para el nocional mínimo de la pata del stop
        lejisimo = lib_tamano.tamano(200.0, 95000.0, 47500.0, filtros_falsos())
        self.assertEqual((lejisimo["puede"], lejisimo["motivo"], lejisimo["manda"]), (False, "bajo_minimo", "riesgo"))
        self.assertEqual(lejisimo["minimo"]["cantidad"], 0.00011, "cuanto más abajo el stop, más cantidad pide")

    def test_sin_los_minimos_de_binance_no_se_inventa_ningun_tamano(self):
        sin = lib_tamano.tamano(200.0, 95000.0, 94050.0, None)
        self.assertEqual((sin["puede"], sin["motivo"], sin["monto"]), (False, "sin_minimos", 0.0))
        detenido = lib_tamano.tamano(200.0, 95000.0, 94050.0, filtros_falsos(motivo="sin_operar"))
        self.assertEqual((detenido["puede"], detenido["motivo"]), (False, "sin_operar"))
        sin_oco = lib_tamano.tamano(200.0, 95000.0, 94050.0, filtros_falsos(motivo="sin_proteccion"))
        self.assertEqual((sin_oco["puede"], sin_oco["motivo"]), (False, "sin_proteccion"))

    def test_lo_que_falta_se_dice_en_el_orden_en_que_se_revisa(self):
        f = filtros_falsos()
        frenada = lib_tamano.tamano(200.0, 95000.0, 94050.0, f, frenado=True)
        self.assertEqual((frenada["puede"], frenada["motivo"]), (False, "frenado"))
        sin_stop = lib_tamano.tamano(200.0, 95000.0, 95000.0, f)
        self.assertEqual((sin_stop["puede"], sin_stop["motivo"]), (False, "sin_stop"))
        sin_precio = lib_tamano.tamano(200.0, None, 94050.0, f)
        self.assertEqual((sin_precio["puede"], sin_precio["motivo"]), (False, "sin_precio"))
        llenas = lib_tamano.tamano(200.0, 95000.0, 94050.0, f, abiertas=2, comprometido=120.0)
        self.assertEqual((llenas["puede"], llenas["motivo"]), (False, "posiciones_llenas"))
        sin_capital = lib_tamano.tamano(0.0, 95000.0, 94050.0, f)
        self.assertEqual((sin_capital["puede"], sin_capital["motivo"]), (False, "sin_capital"))
        ocupado = lib_tamano.tamano(200.0, 95000.0, 94050.0, f, abiertas=1, comprometido=120.0)
        self.assertEqual((ocupado["puede"], ocupado["motivo"]), (False, "sin_disponible"))

    def test_el_precio_el_stop_y_la_cantidad_van_como_los_acepta_binance(self):
        f = filtros_falsos()
        t = lib_tamano.tamano(200.0, 95000.0123, 94050.0456, f, tope=15.0)
        self.assertEqual((t["precio"], t["stop"]), (95000.01, 94050.04), "al tick, siempre hacia abajo")
        self.assertEqual((t["precio_pedido"], t["stop_pedido"]), (95000.0123, 94050.0456))
        pasos = t["cantidad"] / f["paso"]
        self.assertAlmostEqual(pasos, round(pasos), places=6, msg="la cantidad va al paso de Binance")
        self.assertLessEqual(t["monto"], 15.0, "y redondeada hacia abajo: nunca se pasa del límite")
        self.assertEqual(lib_tamano.bajar_al_paso(0.000199, 0.00001), 0.00019)
        self.assertEqual(lib_tamano.bajar_al_paso(-5.0, 0.00001), 0.0)

    def test_los_costos_de_los_dos_lados_entran_en_el_riesgo(self):
        f = filtros_falsos()
        com = {"maker": 0.0, "taker": 0.001, "conversion": 0.0005, "origen": "api"}
        t = lib_tamano.tamano(200.0, 95000.0, 94050.0, f, com=com)
        self.assertEqual(t["comisiones"]["origen"], "api")
        self.assertAlmostEqual(t["costo_relativo"], 0.0015, places=12)
        self.assertAlmostEqual(t["costos"], t["entrada"] * 0.0015, places=12)
        self.assertAlmostEqual(t["monto"], t["entrada"] + t["costos"], places=12)
        # Una comisión que no se entiende no se cree: se vuelve a las supuestas y se dice
        rara = lib_tamano.comisiones({"maker": "gratis", "taker": 0.001, "conversion": 0.0005, "origen": "api"})
        self.assertEqual(rara["origen"], "supuesto")
        self.assertEqual(rara["maker"], minimo_viable.COMISIONES_SUPUESTAS["maker"])


class TamanoDeAhora(ConCarpeta):
    """El tamaño de ahora sobre lo guardado: el puntaje, el estado firmado y los mínimos de Binance."""

    def preparar(self, saldo=200.0):
        for par in lib_datos.PARES:
            for temporalidad in lib_datos.TEMPORALIDADES:
                lib_datos.guardar_serie(par, temporalidad, velas_que_suben(lib_indicadores.VENTANA, temporalidad))
        velas = lib_datos.leer_serie("BTCFDUSD", "4h")
        ultima = velas[-1]
        techo = max(v[2] for v in velas[-1 - lib_indicadores_mercado.RUPTURA_VELAS:-1])
        velas[-1] = [ultima[0], techo, techo + 11.0, techo - 1.0, techo + 10.0, ultima[5] * 4]
        lib_datos.guardar_serie("BTCFDUSD", "4h", velas)
        muestra_guardada(AHORA)
        nucleo.escribir_json(minimo_viable.ruta_minimo(), minimo_viable.medir(ApiFalsa().cliente(), saldo))
        if saldo:
            lib_estado.guardar("prueba", lib_estado.nuevo("prueba", saldo, ahora_ms=AHORA))

    def test_sin_minimos_ni_capital_no_hay_tamano_y_se_dice_que_falta(self):
        d = lib_tamano.estado(AHORA)
        self.assertFalse(d["listo"])
        self.assertEqual({m["codigo"] for m in d["motivos"]}, {"sin_minimos", "sin_capital"})
        self.assertEqual(d["oportunidades"], [])
        self.assertIsNone(d["mejor"])
        self.assertEqual(d["ambiente"], lib_estado.activo())
        self.assertEqual(d["reparto"]["capital"], 0.0)
        self.assertTrue(d["modelo"]["topado"], "sin calibración, el monto por posición queda topado")
        self.assertEqual(d["modelo"]["tope"], lib_calibracion.TOPE_NO_VALIDADO)

    def test_cada_oportunidad_de_ahora_trae_su_monto_en_usdt(self):
        self.preparar()
        d = lib_tamano.estado(AHORA)
        self.assertTrue(d["listo"], d["motivos"])
        self.assertEqual(d["reparto"]["capital"], 200.0)
        self.assertEqual((d["reparto"]["por_posicion"], d["reparto"]["riesgo_maximo"]), (60.0, 4.0))
        self.assertEqual(len(d["oportunidades"]), 1)
        o = d["oportunidades"][0]
        t = o["tamano"]
        self.assertEqual((o["estrategia"], o["par"], o["puede"], o["motivo"]), ("ruptura", "BTCFDUSD", True, ""))
        self.assertEqual(o["entrada"], t["precio"])
        self.assertGreater(t["monto"], 0.0)
        self.assertLessEqual(t["monto"], lib_calibracion.TOPE_NO_VALIDADO, "el modelo todavía no está validado")
        self.assertEqual(t["manda"], "tope")
        self.assertLessEqual(t["arriesgado"], t["riesgo_maximo"])
        self.assertGreaterEqual(t["cantidad"], t["minimo"]["cantidad"])
        self.assertEqual(d["mejor"]["par"], "BTCFDUSD")
        self.assertEqual(d["minimos"]["calculado"], True)

    def test_con_el_modelo_validado_el_monto_ya_no_queda_topado(self):
        self.preparar()
        cal = {"corrido": True, "calibrado": True, "estado": "validado", "exigencia": 70.0,
               "cuando": lib_datos.iso(AHORA), "pesos": dict(lib_puntaje.PESOS_BASE)}
        d = lib_tamano.estado(AHORA, calibracion=cal)
        self.assertEqual((d["modelo"]["estado"], d["modelo"]["topado"], d["modelo"]["tope"]),
                         ("validado", False, None))
        t = d["oportunidades"][0]["tamano"]
        self.assertFalse(t["topado"])
        self.assertIn(t["manda"], ("riesgo", "disponible"))
        self.assertGreater(t["monto"], lib_calibracion.TOPE_NO_VALIDADO)
        self.assertLessEqual(t["monto"], d["reparto"]["disponible"])

    def test_la_cuenta_frenada_no_da_ningun_monto(self):
        self.preparar()
        with open(lib_estado.ruta("prueba"), encoding="utf-8") as f:
            d = json.load(f)
        with open(lib_estado.ruta("prueba"), "w", encoding="utf-8") as f:
            json.dump({**d, "huella": "0" * 64}, f)      # el archivo ya no es el que se firmó
        e = lib_tamano.estado(AHORA)
        self.assertTrue(e["frenado"])
        self.assertEqual(e["motivo"], "huella_no_cuadra")
        self.assertIn("frenado", {m["codigo"] for m in e["motivos"]})
        o = e["oportunidades"][0]
        self.assertEqual((o["puede"], o["motivo"], o["tamano"]["monto"]), (False, "frenado", 0.0))

    def test_con_una_posicion_abierta_queda_la_mitad_y_con_dos_ninguna(self):
        self.preparar()
        cuerpo = lib_estado.nuevo("prueba", 200.0, ahora_ms=AHORA)
        cuerpo["posiciones"] = [{"par": "ETHFDUSD", "cantidad": 0.02, "precio": 3000.0, "monto": 60.0}]
        lib_estado.guardar("prueba", cuerpo)
        d = lib_tamano.estado(AHORA)
        self.assertEqual((d["reparto"]["abiertas"], d["reparto"]["comprometido"]), (1, 60.0))
        self.assertEqual(d["reparto"]["disponible"], 60.0)
        self.assertTrue(d["oportunidades"][0]["puede"])
        cuerpo["posiciones"] = [*cuerpo["posiciones"], {"par": "BTCFDUSD", "monto": 60.0}]
        lib_estado.guardar("prueba", cuerpo)
        llena = lib_tamano.estado(AHORA)
        self.assertIn("posiciones_llenas", {m["codigo"] for m in llena["motivos"]})
        self.assertEqual(llena["oportunidades"][0]["motivo"], "posiciones_llenas")
        self.assertIsNone(llena["mejor"])

    def test_el_tamano_puede_salir_de_lo_ya_calculado_y_queda_escrito(self):
        self.preparar()
        ya = lib_puntaje.estado(AHORA)     # el motor, en su paso, lo tiene a mano: no se recorre dos veces
        self.assertEqual(lib_tamano.estado(AHORA, puntaje=ya), lib_tamano.estado(AHORA))
        d = tamano.estado({}, AHORA)["datos"]
        with open(lib_tamano.ruta_tamano(), encoding="utf-8") as f:
            escrito = json.load(f)
        self.assertEqual((escrito["cuando"], escrito["motivos"]), (d["cuando"], d["motivos"]))
        self.assertEqual(escrito["parametros"]["rechazos"], list(lib_tamano.RECHAZOS))
        self.assertEqual(lib_tamano.guardado()["cuando"], d["cuando"])


class AccionTamano(unittest.TestCase):
    def test_sin_nada_guardado_dice_que_falta_en_vez_de_un_monto_inventado(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            r = correr("tamano.py", "estado", entrada={}, datos=datos)
            self.assertTrue(r["ok"])
            self.assertFalse(r["datos"]["listo"])
            self.assertEqual(r["datos"]["oportunidades"], [])
            self.assertEqual(r["datos"]["parametros"]["reserva"], 0.4)
            self.assertEqual(r["datos"]["parametros"]["riesgo"], 0.02)
            self.assertEqual(r["datos"]["modelo"]["tope"], 15.0)
            self.assertIn("sin_minimos", {m["codigo"] for m in r["datos"]["motivos"]})
            with open(os.path.join(datos, "mercado", "tamano.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["motivos"], r["datos"]["motivos"])


#: Un mercado tranquilo para las pruebas de los frenos: la comisión no subió y FDUSD vale lo que tiene que valer.
MERCADO_OK = {"comision": {"maker": 0.0, "taker": 0.001, "supuesto": 0.0, "origen": "supuesto", "de": "supuesto",
                           "subio": False},
              "fdusd": {"minimo": 0.995, "valor": 0.9999, "listo": True, "bajo": False, "pares": [], "motivos": []}}
#: Y el mismo mercado en mal rato: la maker subió sobre lo que supuso el backtest y FDUSD se despegó del dólar.
MERCADO_MALO = {"comision": {**MERCADO_OK["comision"], "maker": 0.0002, "subio": True},
                "fdusd": {**MERCADO_OK["fdusd"], "valor": 0.9904, "bajo": True}}


def vela_de_cierre(apertura_ms, cierra):
    """Una vela plana en ese precio: para medir FDUSD solo importa el cierre de la última vela cerrada."""
    return [apertura_ms, cierra, cierra, cierra, cierra, 1.0]


def velas_de_fdusd(fdusd=0.9999, ahora_ms=AHORA, hora=None):
    """La última vela cerrada de 1 h de los cuatro pares, con el par contra USDT marcando ese cambio: el mismo BTC vale
    `precio` FDUSD y `precio * fdusd` USDT."""
    paso = lib_datos.PASO_MS["1h"]
    apertura = (ahora_ms // paso - 1) * paso
    otra = apertura if hora is None else hora
    return {"BTCFDUSD": [vela_de_cierre(apertura, 95000.0)], "BTCUSDT": [vela_de_cierre(otra, 95000.0 * fdusd)],
            "ETHFDUSD": [vela_de_cierre(apertura, 3200.0)], "ETHUSDT": [vela_de_cierre(otra, 3200.0 * fdusd)]}


class FrenosDeLaCuenta(ConCarpeta):
    """Los frenos sobre una cuenta ficticia: el saldo de prueba que eligió Ana Pérez."""

    def cuenta(self, ambiente="prueba", saldo=200.0, **extra):
        return {**lib_estado.nuevo(ambiente, saldo, ahora_ms=AHORA), **extra}

    def hoy(self, inicio, aportado=0.0):
        return {"fecha": lib_frenos.fecha_de(AHORA), "inicio": inicio, "aportado": aportado}

    def frenos(self, cuenta, ambiente="prueba", ahora_ms=AHORA, mercado=None):
        return lib_frenos.de_cuenta(cuenta, ambiente, ahora_ms, mercado or MERCADO_OK)

    def orden(self, **extra):
        return {"lado": "compra", "tipo": "limite", "precio": 94830.0, "stop": 93869.7, "cantidad": 0.0006,
                "monto": 57.0, **extra}

    def tamano(self, **extra):
        return {"puede": True, "motivo": "", "cantidad": 0.0006, "monto": 57.0, **extra}

    def test_sin_apalancamiento_y_solo_compras_con_limite(self):
        f = self.frenos(self.cuenta())
        self.assertTrue(lib_frenos.revisar_orden(self.orden(), f, self.tamano())["puede"])
        for orden, motivo in ((self.orden(apalancamiento=3), "apalancamiento"),
                              (self.orden(lado="venta"), "lado"),
                              (self.orden(tipo="mercado"), "tipo"),
                              (self.orden(stop=0.0), "sin_proteccion"),
                              (self.orden(stop=99000.0), "sin_proteccion"),
                              (self.orden(cantidad=0.0007), "monto_mayor"),
                              (self.orden(monto=58.0), "monto_mayor")):
            r = lib_frenos.revisar_orden(orden, f, self.tamano())
            self.assertEqual((r["puede"], r["motivo"]), (False, motivo), motivo)
        sin = lib_frenos.revisar_orden(self.orden(), f, None)
        self.assertEqual((sin["puede"], sin["motivo"]), (False, "sin_tamano"),
                         "una orden que no pasó por el tamaño no pasa por los frenos")
        rechazado = lib_frenos.revisar_orden(self.orden(), f, self.tamano(puede=False, motivo="bajo_minimo"))
        self.assertEqual(rechazado["motivo"], "sin_tamano")
        self.assertEqual(f["apalancamiento"], 1)

    def test_nunca_mas_de_dos_posiciones(self):
        una = self.cuenta(posiciones=[{"par": "BTCFDUSD", "monto": 60.0}])
        f = self.frenos(una)
        self.assertEqual((f["posiciones"]["abiertas"], f["entradas"]["quedan"]), (1, 1))
        self.assertTrue(f["entradas"]["puede"])
        dos = self.cuenta(posiciones=[{"par": "BTCFDUSD", "monto": 60.0}, {"par": "ETHFDUSD", "monto": 60.0}])
        f = self.frenos(dos)
        self.assertEqual((f["entradas"]["puede"], f["entradas"]["motivo"]), (False, "posiciones_llenas"))
        self.assertEqual(lib_frenos.revisar_orden(self.orden(), f, self.tamano())["motivo"], "posiciones_llenas")
        self.assertEqual(f["posiciones"]["maximas"], lib_tamano.POSICIONES)

    def test_el_freno_del_dia_se_mide_contra_el_saldo_del_dia_y_se_levanta_al_cambiar_el_dia(self):
        cuenta = self.cuenta(saldo=190.0, dia=self.hoy(200.0), modo="automatico")
        f = self.frenos(cuenta)
        diario = next(x for x in f["frenos"] if x["codigo"] == "diario")
        self.assertTrue(diario["activo"])
        self.assertEqual((f["estado"], f["entradas"]["motivo"], f["modo"]), ("frenado", "diario", "manual"))
        self.assertEqual(diario["hasta_ms"], lib_frenos.fin_del_dia_ms(AHORA))
        self.assertEqual(f["dia"]["monto"], 10.0)
        manana = self.frenos(cuenta, ahora_ms=AHORA + lib_datos.DIA_MS)
        self.assertFalse(next(x for x in manana["frenos"] if x["codigo"] == "diario")["activo"],
                         "el día cambió: el freno se levantó solo y el día parte desde el saldo de ahora")
        self.assertEqual((manana["estado"], manana["dia"]["inicio"]), ("operando", 190.0))

    def test_un_deposito_no_es_una_ganancia_del_dia_ni_un_retiro_una_perdida(self):
        cuerpo = self.cuenta(dia=self.hoy(200.0))
        cuerpo = lib_frenos.con_aporte(cuerpo, 100.0, ahora_ms=AHORA)
        self.assertEqual((cuerpo["saldo"], cuerpo["referencia"], cuerpo["dia"]["aportado"]), (300.0, 300.0, 100.0))
        self.assertEqual(self.frenos(cuerpo)["dia"]["perdida"], 0.0, "el depósito no es una ganancia del día")
        cuerpo = lib_frenos.con_cierre(cuerpo, -11.0, ahora_ms=AHORA)
        f = self.frenos(cuerpo)
        self.assertEqual((cuerpo["saldo"], cuerpo["racha"], cuerpo["operaciones"]), (289.0, 1, 1))
        self.assertAlmostEqual(f["dia"]["perdida"], 0.055)
        self.assertTrue(next(x for x in f["frenos"] if x["codigo"] == "diario")["activo"],
                        "perder el 5,5 % del día es perder el 5 % del día, con depósito o sin él")

    def test_cuatro_perdidas_seguidas_vuelven_a_manual_y_no_bloquean(self):
        cuerpo = self.cuenta(racha=3, modo="automatico", dia=self.hoy(200.0))
        cuerpo = lib_frenos.con_cierre(cuerpo, -0.5, ahora_ms=AHORA)
        f = self.frenos(cuerpo)
        self.assertEqual(cuerpo["racha"], lib_frenos.RACHA_MAXIMA)
        self.assertTrue(next(x for x in f["frenos"] if x["codigo"] == "racha")["activo"])
        self.assertEqual((f["modo"], f["manual"]), ("manual", True))
        self.assertEqual((f["estado"], f["entradas"]["puede"]), ("operando", True),
                         "la racha vuelve a manual: no bloquea las entradas, las propone")
        gana = lib_frenos.con_cierre(cuerpo, 0.8, ahora_ms=AHORA)
        self.assertEqual(gana["racha"], 0, "una ganada corta la racha")

    def test_el_piso_bloquea_y_no_toca_las_protecciones(self):
        cuerpo = self.cuenta(saldo=150.0, referencia=200.0, aportado=200.0, dia=self.hoy(150.0),
                             posiciones=[{"par": "BTCFDUSD", "monto": 60.0}])
        f = self.frenos(cuerpo)
        piso = next(x for x in f["frenos"] if x["codigo"] == "piso")
        self.assertEqual((piso["activo"], piso["limite"]), (True, 150.0))
        self.assertEqual((f["estado"], f["bloquean"], f["entradas"]["motivo"]), ("frenado", ["piso"], "piso"))
        self.assertFalse(f["reduce"]["hay"], "el piso no cierra nada: lo abierto se queda con su protección")
        self.assertEqual(f["protegidas"], 1)

    def test_el_piso_absoluto_cierra_la_exposicion_a_la_fuerza(self):
        cuerpo = self.cuenta(saldo=120.0, referencia=200.0, aportado=200.0, dia=self.hoy(120.0),
                             posiciones=[{"par": "BTCFDUSD", "monto": 60.0}])
        f = self.frenos(cuerpo)
        absoluto = next(x for x in f["frenos"] if x["codigo"] == "piso_absoluto")
        self.assertEqual((absoluto["activo"], absoluto["limite"]), (True, 130.0))
        self.assertEqual(f["estado"], "reduciendo")
        self.assertEqual((f["reduce"]["hay"], f["reduce"]["por"], f["reduce"]["monto"]), (True, "piso_absoluto", 60.0))
        self.assertEqual(f["entradas"]["motivo"], "piso_absoluto")
        self.assertEqual(f["desbloqueo"]["motivo"], "piso_absoluto", "el piso absoluto no se desbloquea")
        self.assertFalse(f["desbloqueo"]["puede"])

    def test_los_frenos_del_mercado_no_corren_en_prueba_pero_se_avisan(self):
        f = self.frenos(self.cuenta(dia=self.hoy(200.0)), mercado=MERCADO_MALO)
        for codigo in lib_frenos.SOLO_REAL:
            suyo = next(x for x in f["frenos"] if x["codigo"] == codigo)
            self.assertEqual((suyo["activo"], suyo["avisa"], suyo["aplica"]), (False, True, False), codigo)
        self.assertTrue(f["entradas"]["puede"], "en prueba no hay dinero de verdad que cuidar")
        self.assertEqual(f["avisos"], list(lib_frenos.SOLO_REAL))
        real = self.frenos(self.cuenta("real", dia=self.hoy(200.0)), "real", mercado=MERCADO_MALO)
        self.assertEqual(real["bloquean"], ["comision", "fdusd"])
        self.assertEqual((real["entradas"]["puede"], real["entradas"]["motivo"]), (False, "comision"))
        self.assertEqual(real["estado"], "frenado")

    def test_fdusd_sale_de_los_dos_pares_del_mismo_activo(self):
        d = lib_frenos.fdusd_de(AHORA, velas_de_fdusd(0.9999))
        self.assertAlmostEqual(d["valor"], 0.9999)
        self.assertEqual((d["listo"], d["bajo"], d["motivos"]), (True, False, []))
        bajo = lib_frenos.fdusd_de(AHORA, velas_de_fdusd(0.9904))
        self.assertTrue(bajo["bajo"], "bajo 0,995 FDUSD ya no es un dólar")
        for par, temporalidad, velas in [(p, "1h", v) for p, v in velas_de_fdusd(0.99).items()]:
            lib_datos.guardar_serie(par, temporalidad, velas)
        self.assertTrue(lib_frenos.fdusd_de(AHORA)["bajo"], "las velas también se leen del disco")
        distinta = lib_frenos.fdusd_de(AHORA, velas_de_fdusd(0.99, hora=AHORA // 3_600_000 * 3_600_000))
        self.assertEqual({m["codigo"] for m in distinta["motivos"]}, {"sin_hora"})
        self.assertIsNone(distinta["valor"], "dos velas de distinta hora no dan un cambio")
        viejas = lib_frenos.fdusd_de(AHORA + 2 * lib_datos.DIA_MS, velas_de_fdusd(0.99))
        self.assertEqual({m["codigo"] for m in viejas["motivos"]}, {"velas_viejas"})
        sin = lib_frenos.fdusd_de(AHORA, {p: [] for p in lib_datos.PARES})
        self.assertEqual({m["codigo"] for m in sin["motivos"]}, {"sin_velas"})
        self.assertFalse(sin["bajo"], "lo que no se puede medir no frena por su cuenta: queda dicho")

    def test_con_un_freno_a_ciegas_la_cuenta_real_no_abre_nada(self):
        sin_fdusd = {**MERCADO_OK, "fdusd": {**MERCADO_OK["fdusd"], "valor": None, "listo": False,
                                             "motivos": [{"codigo": "sin_velas", "par": "BTCFDUSD"}]}}
        prueba = self.frenos(self.cuenta(dia=self.hoy(200.0)), mercado=sin_fdusd)
        self.assertTrue(prueba["listo"], "en prueba ese freno no corre, así que no falta nada")
        real = self.frenos(self.cuenta("real", dia=self.hoy(200.0)), "real", mercado=sin_fdusd)
        self.assertFalse(real["listo"])
        self.assertEqual((real["entradas"]["puede"], real["entradas"]["motivo"]), (False, "sin_medir"))

    def test_pausar_cancela_las_entradas_y_no_toca_ninguna_proteccion(self):
        posiciones = [{"par": "BTCFDUSD", "monto": 60.0, "proteccion": "oco-1"}]
        lib_estado.guardar("prueba", self.cuenta(posiciones=posiciones, dia=self.hoy(200.0)))
        d = lib_frenos.pausar(True, "prueba", AHORA)
        self.assertEqual((d["pausado"], d["estado"], d["motivo"]), (True, "pausado", "pausado"))
        self.assertEqual((d["entradas"]["puede"], d["protegidas"]), (False, 1))
        guardado = lib_estado.cargar("prueba", ahora_ms=AHORA)
        self.assertTrue(guardado["pausado"])
        self.assertEqual(guardado["posiciones"], posiciones, "«Pausar» no toca ninguna protección automática")
        self.assertEqual(lib_registro.ultimas("prueba")[0][0]["razon"], "pausa")
        d = lib_frenos.pausar(False, "prueba", AHORA)
        self.assertEqual((d["pausado"], d["estado"]), (False, "operando"))
        self.assertEqual(lib_registro.ultimas("prueba")[0][0]["razon"], "reanudar")
        self.assertEqual(lib_registro.cuantas("prueba"), 2, "una línea por vez, ni una más")

    def test_el_desbloqueo_del_piso_en_real_espera_24_h_y_es_como_maximo_dos_veces(self):
        lib_estado.guardar("real", self.cuenta("real", saldo=150.0, referencia=200.0, aportado=100.0,
                                               dia=self.hoy(150.0)))
        pedido = lib_frenos.desbloquear("real", AHORA)
        self.assertEqual((pedido["hecho"], pedido["motivo"]), (False, "esperando"))
        guardado = lib_estado.cargar("real", ahora_ms=AHORA)
        self.assertEqual(guardado["desbloqueo"]["hasta_ms"], AHORA + lib_frenos.ESPERA_DESBLOQUEO_MS)
        self.assertEqual(guardado["desbloqueos"], 0, "pedirlo no lo gasta: aplicarlo sí")
        antes = lib_frenos.desbloquear("real", AHORA + 60 * 60 * 1000)
        self.assertEqual((antes["hecho"], antes["motivo"]), (False, "esperando"), "las 24 h no se saltan")
        listo = AHORA + lib_frenos.ESPERA_DESBLOQUEO_MS
        hecho = lib_frenos.desbloquear("real", listo)
        self.assertTrue(hecho["hecho"])
        guardado = lib_estado.cargar("real", ahora_ms=listo)
        self.assertEqual((guardado["referencia"], guardado["desbloqueos"], guardado["desbloqueo"]), (150.0, 1, {}))
        f = self.frenos(guardado, "real", ahora_ms=listo)
        self.assertFalse(next(x for x in f["frenos"] if x["codigo"] == "piso")["activo"])
        ultima = lib_registro.ultimas("real")[0][0]
        self.assertEqual((ultima["razon"], ultima["resultado"]["referencia"]), ("referencia_reiniciada", 150.0))
        # La segunda vez igual, y la tercera ya no: el piso se desbloquea dos veces y no más.
        segundo = listo + lib_frenos.ESPERA_DESBLOQUEO_MS
        lib_estado.guardar("real", {**lib_estado.cuerpo_de(guardado), "saldo": 100.0, "dia": self.hoy(100.0)})
        lib_frenos.desbloquear("real", listo)
        lib_frenos.desbloquear("real", segundo)
        guardado = lib_estado.cargar("real", ahora_ms=segundo)
        self.assertEqual((guardado["desbloqueos"], guardado["referencia"]), (2, 100.0))
        lib_estado.guardar("real", {**lib_estado.cuerpo_de(guardado), "saldo": 70.0, "dia": self.hoy(70.0)})
        no = lib_frenos.desbloquear("real", segundo)
        self.assertEqual((no["hecho"], no["motivo"]), (False, "sin_desbloqueos"))
        self.assertEqual(lib_estado.cargar("real", ahora_ms=segundo)["referencia"], 100.0,
                         "sin desbloqueos, el capital de referencia se queda donde está")

    def test_en_prueba_el_desbloqueo_del_piso_es_al_tiro(self):
        lib_estado.guardar("prueba", self.cuenta(saldo=150.0, referencia=200.0, aportado=100.0, dia=self.hoy(150.0)))
        d = lib_frenos.desbloquear("prueba", AHORA)
        self.assertTrue(d["hecho"], "la espera de 24 h es solo para el piso en real")
        guardado = lib_estado.cargar("prueba", ahora_ms=AHORA)
        self.assertEqual((guardado["referencia"], guardado["desbloqueos"]), (150.0, 1))
        self.assertEqual(lib_registro.ultimas("prueba")[0][0]["razon"], "referencia_reiniciada")

    def test_revisar_vuelve_a_manual_y_anota_cada_freno_una_sola_vez(self):
        lib_estado.guardar("prueba", self.cuenta(saldo=150.0, referencia=200.0, aportado=200.0, dia=self.hoy(150.0),
                                                 modo="automatico"))
        d = lib_frenos.revisar(AHORA, MERCADO_OK)
        self.assertEqual((d["estado"], d["modo"], d["motivo"]), ("frenado", "manual", "piso"))
        self.assertEqual(lib_estado.cargar("prueba", ahora_ms=AHORA)["modo"], "manual",
                         "tras cualquier freno se vuelve a manual, y queda escrito")
        self.assertEqual(lib_estado.cargar("prueba", ahora_ms=AHORA)["frenos"], ["piso"])
        razones = [l["razon"] for l in lib_registro.ultimas("prueba")[0]]
        self.assertEqual(sorted(razones), ["cambio_modo", "freno_piso"])
        linea = next(l for l in lib_registro.ultimas("prueba")[0] if l["razon"] == "freno_piso")
        self.assertEqual((linea["resultado"]["motivo"], linea["resultado"]["saldo"]), ("piso", 150.0))
        lib_frenos.revisar(AHORA + 60_000, MERCADO_OK)
        self.assertEqual(lib_registro.cuantas("prueba"), 2, "el freno ya estaba anotado: no se anota de nuevo")

    def test_del_archivo_de_estado_que_no_es_de_fiar_no_se_escribe_nada(self):
        lib_estado.guardar("prueba", self.cuenta(dia=self.hoy(200.0)))
        archivo = lib_estado.ruta("prueba")
        with open(archivo, encoding="utf-8") as f:
            d = json.load(f)
        with open(archivo, "w", encoding="utf-8") as f:
            json.dump({**d, "huella": "0" * 64}, f)
        with open(archivo, encoding="utf-8") as f:
            antes = f.read()
        r = lib_frenos.aplicar("prueba", AHORA, MERCADO_OK)
        self.assertEqual((r["arranque"], r["estado"], r["entradas"]["motivo"]), (True, "frenado", "frenado"))
        with open(archivo, encoding="utf-8") as f:
            self.assertEqual(f.read(), antes, "el archivo sospechoso no se pisa")
        self.assertEqual(lib_registro.cuantas("prueba"), 0, "ni se anota un freno que no se midió")

    def test_una_cuenta_que_todavia_no_existe_no_se_inventa(self):
        d = lib_frenos.revisar(AHORA, MERCADO_OK)
        self.assertFalse(os.path.exists(lib_estado.ruta("prueba")))
        self.assertFalse(os.path.exists(lib_estado.ruta("real")))
        self.assertEqual(d["estado"], "operando")
        self.assertEqual(lib_registro.cuantas("prueba"), 0)

    def test_los_numeros_y_las_razones_son_los_mismos_de_los_otros_pasos(self):
        self.assertEqual(lib_frenos.POSICIONES, minimo_viable.POSICIONES)
        self.assertEqual(lib_frenos.POSICIONES, lib_tamano.POSICIONES)
        for codigo, razon in lib_frenos.RAZON.items():
            self.assertIn(razon, lib_registro.RAZONES, codigo)
        for razon in ("pausa", "reanudar", "referencia_reiniciada", "desbloqueo", "cambio_modo"):
            self.assertIn(razon, lib_registro.RAZONES)
        self.assertLess(1 - lib_frenos.PISO_ABSOLUTO, 1 - lib_frenos.PISO,
                        "el piso absoluto va más abajo que el del capital de referencia")
        self.assertEqual(lib_frenos.parametros()["rechazos"], list(lib_frenos.RECHAZOS))

    def test_la_accion_revisa_los_frenos_y_los_deja_escritos(self):
        lib_estado.guardar("prueba", self.cuenta(dia=self.hoy(200.0)))
        r = frenos.estado({}, AHORA)
        self.assertTrue(r["ok"])
        self.assertEqual(r["datos"]["activo"], lib_estado.activo())
        self.assertEqual(r["datos"]["estado"], "operando")
        self.assertEqual(lib_frenos.guardado()["cuando"], r["datos"]["cuando"])
        mal = frenos.pausar({"pausar": 7}, AHORA)
        self.assertEqual((mal["ok"], mal["error"]), (False, "pausa"))
        self.assertFalse(lib_estado.cargar("prueba", ahora_ms=AHORA)["pausado"])
        bien = frenos.pausar({"pausar": 1}, AHORA)
        self.assertEqual((bien["ok"], bien["datos"]["pausado"]), (True, True))
        nada = frenos.desbloquear({}, AHORA)
        self.assertEqual((nada["ok"], nada["datos"]["hecho"], nada["datos"]["motivo_desbloqueo"]),
                         (True, False, "sin_freno"))


class AccionFrenos(unittest.TestCase):
    def test_sin_nada_guardado_los_frenos_no_frenan_ni_inventan_un_estado(self):
        with tempfile.TemporaryDirectory() as tmp:
            datos = os.path.join(tmp, "datos")
            r = correr("frenos.py", "estado", entrada={}, datos=datos)
            self.assertTrue(r["ok"])
            self.assertEqual(r["datos"]["estado"], "operando")
            self.assertEqual(r["datos"]["parametros"]["posiciones"], 2)
            self.assertEqual(r["datos"]["parametros"]["piso"], 0.25)
            self.assertEqual(r["datos"]["parametros"]["perdida_diaria"], 0.05)
            self.assertEqual(r["datos"]["parametros"]["racha_maxima"], 4)
            self.assertEqual(r["datos"]["parametros"]["fdusd_minimo"], 0.995)
            self.assertEqual(len(r["datos"]["cuentas"]), 2)
            self.assertFalse(os.path.exists(os.path.join(datos, "estado", "prueba.json")))
            with open(os.path.join(datos, "mercado", "frenos.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["cuando"], r["datos"]["cuando"])


if __name__ == "__main__":
    unittest.main()
