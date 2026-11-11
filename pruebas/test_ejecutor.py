"""Pruebas del ejecutor de prueba: la protección simulada, los cruces con velas de 1 m y el saldo ficticio.

Cada prueba corre con su carpeta temporal y con datos ficticios (Ana Pérez, Matías Soto): ninguna sale a la red ni toca
datos reales. Las velas de 1 m son inventadas y los precios, redondos a propósito: así las cuentas se saben de memoria.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "bin"))

import lib_costos  # noqa: E402
import lib_datos  # noqa: E402  (después de sys.path: bin/ no es un paquete instalado)
import lib_ejecutor_prueba as ejecutor  # noqa: E402
import lib_estado  # noqa: E402
import lib_frenos  # noqa: E402
import lib_registro  # noqa: E402
import lib_resolucion  # noqa: E402
import minimo_viable  # noqa: E402
import nucleo  # noqa: E402

#: El mismo lunes a las 14:05 UTC de las otras pruebas: las cuentas no dependen de cuándo se corren.
AHORA = 1_770_732_300_000
MINUTO = lib_datos.PASO_MS[lib_datos.MINUTO]
HORA = lib_datos.PASO_MS["1h"]
#: Los niveles de la oportunidad, redondos: entrada 100.000, stop un 1 % abajo y objetivo un 1,5 % arriba.
PRECIO, STOP, OBJETIVO = 100_000.0, 99_000.0, 101_500.0
#: Los filtros de Binance del par que se opera, del mismo orden de magnitud que los de verdad pero inventados.
FILTROS = {"par": "BTCFDUSD", "moneda": "BTC", "tick": 0.01, "paso": 0.00001, "cantidad_minima": 0.00001,
           "nocional_minimo": 5.0, "proteccion": True, "operando": True, "motivo": ""}
#: Lo que deja el tamaño con 200 USDT de capital de prueba: lo corta el tope del modelo sin validar (15 USDT).
CANTIDAD, MITAD = 0.00014, 0.00007


def con_minimos(**cambios):
    """El cálculo del capital mínimo viable, ya guardado: sin él no hay filtros y no hay tamaño."""
    uno = {**FILTROS, **cambios, "capital": 40}
    otro = {**FILTROS, "par": "ETHFDUSD", "moneda": "ETH", "paso": 0.0001, "cantidad_minima": 0.0001, "capital": 40}
    nucleo.escribir_json(minimo_viable.ruta_minimo(), {
        "formato": 1, "calculado": True, "cuando": lib_datos.iso(AHORA), "moneda": "USDT", "capital_minimo": 40,
        "pares": [uno, otro], "motivos": [], "listo": True})


def cuenta(saldo=200.0, **cambios):
    """La cuenta de prueba con su saldo ficticio, firmada como la deja `lib_estado`."""
    return lib_estado.guardar(lib_estado.PRUEBA, {**lib_estado.nuevo(lib_estado.PRUEBA, saldo, ahora_ms=AHORA),
                                                  **cambios})


def oportunidad(**cambios):
    """Una ruptura de BTCFDUSD en 4 h, ya puntuada, como la deja el puntaje con su tamaño al lado."""
    return {"estrategia": "ruptura", "par": "BTCFDUSD", "temporalidad": "4h", "vela": AHORA - 4 * HORA,
            "razon": "ruptura_con_volumen", "entrada": PRECIO, "stop": STOP, "objetivo": OBJETIVO,
            "puntaje": 84.0, "permitida": True, "vence": AHORA + 3 * HORA, **cambios}


def velas(n, bajo, alto, desde_ms=AHORA, par="BTCFDUSD", guardar=True):
    """Velas de 1 m ficticias, todas con el mismo máximo y el mismo mínimo: lo que importa es qué nivel tocaron."""
    inicio = (desde_ms // MINUTO) * MINUTO
    medio = (alto + bajo) / 2
    filas = [[inicio + i * MINUTO, medio, alto, bajo, medio, 1.0] for i in range(n)]
    if guardar:
        lib_datos.guardar_serie(par, lib_datos.MINUTO, filas)
    return filas


def posicion(estado=ejecutor.PUESTA, cantidad=CANTIDAD, **cambios):
    """Una posición como la deja `entrar`, sin pasar por el disco: puesta o ya llenada y protegida."""
    t = {"precio": PRECIO, "stop": STOP, "cantidad": cantidad, "monto": cantidad * PRECIO * 1.0015}
    c = ejecutor.cabe(FILTROS, PRECIO, STOP, OBJETIVO, cantidad, True)
    p = ejecutor.nueva_posicion(oportunidad(), t, c, OBJETIVO, AHORA)
    if estado == ejecutor.ABIERTA:
        p.update(estado=ejecutor.ABIERTA, llenada_ms=AHORA, maximo=PRECIO, protegida=True)
        p["ordenes"] = ejecutor.ordenes_de(p)
    return {**p, **cambios}


def razones(ambiente=lib_estado.PRUEBA):
    """Las razones del registro, de la más vieja a la más nueva: es lo que quedó escrito."""
    filas, _ = lib_registro.leer(ambiente, lib_registro.anio_de(AHORA))
    return [f["razon"] for f in filas]


def correr(script, *args, entrada=None, datos=None):
    """Corre bin/<script> como lo corre el host: lo de la persona en un archivo y el último argumento es la salida."""
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


class ConCarpeta(unittest.TestCase):
    """Cada prueba con su carpeta de datos: lo que escriba el ejecutor se va con ella."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.antes = os.environ.get("PILOTA_DATOS")
        self.datos = os.path.join(self.tmp.name, "datos")
        os.environ["PILOTA_DATOS"] = self.datos

    def tearDown(self):
        if self.antes is None:
            os.environ.pop("PILOTA_DATOS", None)
        else:
            os.environ["PILOTA_DATOS"] = self.antes
        self.tmp.cleanup()


class LaProteccionCabe(ConCarpeta):
    def test_la_proteccion_cabe_con_los_tres_lados_sobre_el_minimo(self):
        c = ejecutor.cabe(FILTROS, PRECIO, STOP, OBJETIVO, CANTIDAD, True)
        self.assertTrue(c["cabe"], c["motivo"])
        self.assertEqual([p["que"] for p in c["patas"]], ["compra", "stop", "objetivo"])
        self.assertAlmostEqual(c["mitad"], MITAD)       # la ruptura sale mitad en el objetivo y mitad con el stop móvil
        self.assertFalse(c["entera"])

    def test_la_pata_del_stop_es_la_que_manda(self):
        # La pata del stop vale menos USDT que la compra: con el mínimo justo en medio, es la que no pasa.
        c = ejecutor.cabe({**FILTROS, "nocional_minimo": 13.9}, PRECIO, STOP, OBJETIVO, CANTIDAD, True)
        self.assertFalse(c["cabe"])
        self.assertEqual(c["motivo"], "nocional_stop")

    def test_la_mitad_bajo_el_minimo_sale_entera(self):
        c = ejecutor.cabe(FILTROS, PRECIO, STOP, OBJETIVO, 0.00008, True)
        self.assertTrue(c["cabe"])
        self.assertTrue(c["entera"])                    # la mitad no pasaría el nocional mínimo: no se parte
        self.assertEqual(c["mitad"], 0.0)

    def test_un_precio_fuera_del_tick_no_se_pone(self):
        self.assertEqual(ejecutor.cabe(FILTROS, 100_000.005, STOP, OBJETIVO, CANTIDAD)["motivo"], "tick")
        self.assertEqual(ejecutor.cabe(FILTROS, PRECIO, STOP, OBJETIVO, 0.000145)["motivo"], "paso")

    def test_sin_los_minimos_de_binance_no_se_revisa_nada(self):
        self.assertEqual(ejecutor.cabe({}, PRECIO, STOP, OBJETIVO, CANTIDAD)["motivo"], "sin_filtros")
        self.assertEqual(ejecutor.cabe(FILTROS, PRECIO, PRECIO, OBJETIVO, CANTIDAD)["motivo"], "sin_niveles")


class LosIdsSonNuestros(ConCarpeta):
    def test_el_id_es_determinista_y_lleva_el_prefijo(self):
        uno = ejecutor.id_de("BTCFDUSD", AHORA, ejecutor.ENTRADA)
        self.assertEqual(uno, ejecutor.id_de("BTCFDUSD", AHORA, ejecutor.ENTRADA))
        self.assertTrue(uno.startswith(ejecutor.PREFIJO + "-"))
        self.assertTrue(ejecutor.es_nuestro(uno))
        self.assertTrue(lib_registro.CODIGO.fullmatch(uno))        # entra en el registro sin texto libre
        # Cada reposición de la protección son órdenes nuevas, con otro id.
        self.assertNotEqual(ejecutor.id_de("BTCFDUSD", AHORA, ejecutor.STOP, 1),
                            ejecutor.id_de("BTCFDUSD", AHORA, ejecutor.STOP, 2))

    def test_lo_que_no_lleva_el_prefijo_es_de_otro(self):
        self.assertFalse(ejecutor.es_nuestro("web_1234"))
        self.assertFalse(ejecutor.es_nuestro(None))

    def test_una_posicion_ajena_no_se_cierra_nunca(self):
        con_minimos()
        ajena = {"id": "web_1234", "par": "BTCFDUSD", "estado": "abierta", "precio": PRECIO, "stop": STOP,
                 "cantidad": 0.001, "monto": 100.0}
        cuenta(posiciones=[ajena])
        velas(3, 90_000.0, 91_000.0)                               # un desplome que cruzaría cualquier stop
        d = ejecutor.revisar(AHORA + 3 * MINUTO)
        guardado = lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA + 3 * MINUTO)
        self.assertEqual(guardado["posiciones"], [ajena])          # ni se tocó ni se cerró
        self.assertEqual(d["ajenas"], 1)
        self.assertEqual(d["posiciones"], [])
        self.assertEqual(razones(), [])                            # tampoco se anotó nada suyo


class Entrar(ConCarpeta):
    def test_una_orden_que_paso_el_tamano_y_los_frenos_queda_puesta(self):
        con_minimos()
        cuenta()
        r = ejecutor.entrar(oportunidad(), AHORA)
        self.assertTrue(r["puesta"], r["motivo"])
        p = r["posicion"]
        self.assertEqual(p["estado"], ejecutor.PUESTA)              # puesta no es llenada
        self.assertAlmostEqual(p["cantidad"], CANTIDAD)
        self.assertAlmostEqual(p["monto"], CANTIDAD * PRECIO * 1.0015)
        self.assertEqual(p["objetivo"], OBJETIVO)
        self.assertFalse(p["protegida"])                            # la protección va cuando la compra se llena
        self.assertEqual([o["que"] for o in p["ordenes"]], [ejecutor.ENTRADA])
        self.assertEqual(razones(), ["entrada_ruptura"])
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"][0]["id"], p["id"])

    def test_sin_el_calculo_de_los_minimos_no_hay_orden(self):
        cuenta()
        r = ejecutor.entrar(oportunidad(), AHORA)
        self.assertFalse(r["puesta"])
        self.assertEqual(r["motivo"], "sin_minimos")
        self.assertEqual(razones(), ["rechazo"])                    # y el motivo queda en el registro

    def test_la_que_el_filtro_de_btc_no_permite_no_se_pone(self):
        con_minimos()
        cuenta()
        self.assertEqual(ejecutor.entrar(oportunidad(permitida=False), AHORA)["motivo"], "no_permitida")
        self.assertEqual(ejecutor.entrar(oportunidad(estrategia="usdt"), AHORA)["motivo"], "sin_opcion")

    def test_la_misma_senal_dos_veces_no_abre_dos_posiciones(self):
        con_minimos()
        cuenta()
        self.assertTrue(ejecutor.entrar(oportunidad(), AHORA)["puesta"])
        self.assertEqual(ejecutor.entrar(oportunidad(), AHORA + MINUTO)["motivo"], "repetida")
        self.assertEqual(len(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"]), 1)

    def test_una_tercera_posicion_no_se_abre(self):
        con_minimos()
        cuenta()
        for atras in (4 * HORA, 8 * HORA):
            self.assertTrue(ejecutor.entrar(oportunidad(vela=AHORA - atras), AHORA)["puesta"])
        r = ejecutor.entrar(oportunidad(vela=AHORA - 12 * HORA), AHORA)
        self.assertEqual(r["motivo"], "posiciones_llenas")          # el mismo máximo del tamaño y de los frenos

    def test_una_cuenta_que_arranco_frenada_no_pone_nada(self):
        con_minimos()
        cuenta()
        with open(lib_estado.ruta(lib_estado.PRUEBA), "r+", encoding="utf-8") as f:
            d = json.load(f)
            d["huella"] = "0" * 64                                  # el archivo ya no es el que se firmó
            f.seek(0)
            f.truncate()
            json.dump(d, f)
        r = ejecutor.entrar(oportunidad(), AHORA)
        self.assertFalse(r["puesta"])
        self.assertEqual(r["motivo"], "frenado")

    def test_una_cuenta_que_todavia_no_existe_no_se_inventa(self):
        con_minimos()
        r = ejecutor.entrar(oportunidad(), AHORA)
        self.assertEqual(r["motivo"], "sin_cuenta")
        self.assertEqual(razones(), [])                             # y el registro no se estrena con un rechazo
        self.assertFalse(os.path.exists(lib_estado.ruta(lib_estado.PRUEBA)))

    def test_una_orden_que_no_paso_por_el_tamano_no_se_pone(self):
        con_minimos()
        cuenta()
        # El ejecutor no calcula montos: si el tamaño no dijo que se puede, acá no hay orden.
        r = ejecutor.entrar(oportunidad(), AHORA, tamano_={"puede": False, "motivo": ""})
        self.assertEqual(r["motivo"], "sin_tamano")
        self.assertEqual(razones(), ["rechazo"])

    def test_lo_que_queda_bajo_el_minimo_de_binance_se_rechaza_con_su_motivo(self):
        con_minimos(nocional_minimo=50.0)                           # con el tope de 15 USDT no alcanza para la pata
        cuenta()
        self.assertEqual(ejecutor.entrar(oportunidad(), AHORA)["motivo"], "bajo_minimo")


class CrucesConVelasDeUnMinuto(ConCarpeta):
    def test_una_limite_se_llena_solo_cuando_el_precio_sigue_en_contra(self):
        # Tocar el nivel no alcanza: la cola de órdenes en ese precio se come a la nuestra (`lib_costos.llena`).
        toca = ejecutor.seguir(posicion(), velas(1, 99_960.0, 100_050.0, guardar=False), FILTROS)
        self.assertEqual(toca["eventos"], [])
        self.assertEqual(toca["posicion"]["estado"], ejecutor.PUESTA)
        pasa = ejecutor.seguir(posicion(), velas(1, 99_900.0, 100_050.0, guardar=False), FILTROS)
        self.assertEqual([e["que"] for e in pasa["eventos"]], [ejecutor.LLENADA])
        p = pasa["posicion"]
        self.assertEqual(p["estado"], ejecutor.ABIERTA)
        self.assertTrue(p["protegida"])                              # llenada, con su protección simulada al tiro
        self.assertEqual([o["que"] for o in p["ordenes"]], [ejecutor.STOP, ejecutor.OBJETIVO])
        self.assertAlmostEqual([o for o in p["ordenes"] if o["que"] == ejecutor.OBJETIVO][0]["cantidad"], MITAD)

    def test_el_minuto_que_toco_los_dos_cuenta_el_stop(self):
        r = ejecutor.seguir(posicion(ejecutor.ABIERTA), velas(1, 98_000.0, 101_600.0, guardar=False), FILTROS)
        ev = r["eventos"][0]
        self.assertIsNone(r["posicion"])
        self.assertEqual(ev["por"], lib_resolucion.POR_STOP)         # del minuto no se baja más: manda el supuesto
        self.assertEqual(ev["etiqueta"], lib_resolucion.SIN_1M)
        self.assertEqual(ev["precio"], STOP)

    def test_el_stop_movil_sube_y_repone_la_proteccion(self):
        sube = velas(1, 100_500.0, 101_000.0, guardar=False)
        r = ejecutor.seguir(posicion(ejecutor.ABIERTA), sube, FILTROS)
        p = r["posicion"]
        self.assertEqual(r["eventos"], [])
        self.assertEqual(p["reposiciones"], 1)                       # mover el stop es cancelar la OCO y poner otra
        self.assertAlmostEqual(p["stop"], 99_990.0)                  # el máximo visto menos la misma distancia
        self.assertGreater(p["stop"], p["stop_inicial"])
        self.assertNotEqual(p["ordenes"][0]["id"], ejecutor.ordenes_de({**p, "reposiciones": 0})[0]["id"])
        cae = velas(1, 99_900.0, 100_100.0, desde_ms=AHORA + MINUTO, guardar=False)
        fin = ejecutor.seguir(p, cae, FILTROS)
        self.assertIsNone(fin["posicion"])
        self.assertEqual(fin["eventos"][0]["razon"], "stop_movil")   # salió por el stop, pero por el que se movió

    def test_la_mitad_sale_en_el_objetivo_y_el_resto_queda_con_el_stop_movil(self):
        r = ejecutor.seguir(posicion(ejecutor.ABIERTA), velas(1, 101_000.0, 101_600.0, guardar=False), FILTROS)
        ev = r["eventos"][0]
        self.assertEqual(ev["por"], ejecutor.OBJETIVO)
        self.assertFalse(ev["entera"])
        self.assertAlmostEqual(ev["cantidad"], MITAD)
        p = r["posicion"]
        self.assertAlmostEqual(p["cantidad"], CANTIDAD - MITAD)      # lo que queda sigue abierto
        self.assertEqual(p["objetivo"], 0.0)
        self.assertEqual([o["que"] for o in p["ordenes"]], [ejecutor.STOP])
        self.assertGreater(p["stop"], STOP)

    def test_la_posicion_que_sale_entera_cierra_entera_en_el_objetivo(self):
        entera = posicion(ejecutor.ABIERTA, cantidad=0.00008)
        self.assertTrue(entera["entera"])
        r = ejecutor.seguir(entera, velas(1, 101_000.0, 101_600.0, guardar=False), FILTROS)
        self.assertIsNone(r["posicion"])
        self.assertTrue(r["eventos"][0]["entera"])
        self.assertAlmostEqual(r["eventos"][0]["cantidad"], 0.00008)

    def test_la_entrada_que_nadie_llena_se_cancela_al_vencer(self):
        tarde = velas(1, 100_100.0, 100_200.0, desde_ms=AHORA + 3 * HORA, guardar=False)
        r = ejecutor.seguir(posicion(), tarde, FILTROS)
        self.assertIsNone(r["posicion"])
        self.assertEqual(r["eventos"][0]["que"], ejecutor.VENCIDA)


class RevisarAplica(ConCarpeta):
    def setUp(self):
        super().setUp()
        con_minimos()
        cuenta()
        self.puesta = ejecutor.entrar(oportunidad(), AHORA)["posicion"]

    def test_el_stop_cruzado_mueve_el_saldo_y_queda_en_el_registro(self):
        velas(2, 98_000.0, 100_000.0)                                # se llena y, en el siguiente minuto, se para
        d = ejecutor.revisar(AHORA + 2 * MINUTO)
        self.assertEqual(d["posiciones"], [])
        self.assertEqual(razones(), ["entrada_ruptura", "entrada_ruptura", "stop"])
        c = lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA + 2 * MINUTO)
        esperado = ejecutor.neto_de(PRECIO, STOP, CANTIDAD, "stop", lib_costos.SPREAD_SUPUESTO)["neto"]
        self.assertLess(esperado, 0)
        self.assertAlmostEqual(c["saldo"], 200.0 + esperado)
        self.assertEqual(c["racha"], 1)                              # una pérdida seguida
        self.assertEqual(c["operaciones"], 1)
        self.assertEqual(c["referencia"], 200.0)                     # el capital de referencia nunca baja

    def test_la_mitad_en_el_objetivo_sube_el_saldo_y_deja_la_otra_abierta(self):
        velas(1, 99_900.0, 101_600.0)
        d = ejecutor.revisar(AHORA + MINUTO)
        self.assertEqual(razones(), ["entrada_ruptura", "entrada_ruptura", "objetivo"])
        c = lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA + MINUTO)
        self.assertGreater(c["saldo"], 200.0)
        self.assertEqual(c["racha"], 0)
        self.assertEqual(len(c["posiciones"]), 1)
        self.assertAlmostEqual(c["posiciones"][0]["cantidad"], CANTIDAD - MITAD)
        self.assertEqual(d["protegidas"], 1)

    def test_mirar_dos_veces_no_cobra_dos_veces(self):
        velas(1, 99_900.0, 101_600.0)                                # se llena y la mitad sale en el objetivo
        ejecutor.revisar(AHORA + MINUTO)
        saldo = lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA + MINUTO)["saldo"]
        lineas = razones()
        ejecutor.revisar(AHORA + 2 * MINUTO)
        self.assertEqual(razones(), lineas)                          # la vela ya revisada no se vuelve a cobrar
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA + 2 * MINUTO)["saldo"], saldo)

    def test_sin_velas_de_un_minuto_no_pasa_nada_y_se_dice(self):
        d = ejecutor.revisar(AHORA + 2 * MINUTO)
        self.assertEqual([m["codigo"] for m in d["motivos"]], ["sin_1m", "sin_1m"])
        self.assertFalse(d["listo"])
        self.assertEqual(d["puestas"], 1)                            # la orden sigue puesta, nadie la llenó
        self.assertEqual(razones(), ["entrada_ruptura"])

    def test_el_rato_sin_cobertura_se_dice(self):
        velas(1, 100_100.0, 100_200.0)
        velas(1, 3_000.0, 3_010.0, par="ETHFDUSD")
        d = ejecutor.revisar(AHORA + 30 * MINUTO)
        self.assertEqual(d["cobertura"]["sin_cobertura_min"], 29)    # en prueba nadie cuida esto sin el motor
        self.assertFalse(d["cobertura"]["cubierto"])

    def test_cerrar_a_mano_sale_a_mercado_y_queda_en_el_registro(self):
        velas(2, 99_900.0, 100_100.0)
        ejecutor.revisar(AHORA + 2 * MINUTO)
        r = ejecutor.cerrar(ahora_ms=AHORA + 3 * MINUTO)
        self.assertTrue(r["hecho"])
        self.assertEqual(r["cerradas"], 1)
        self.assertEqual(razones()[-1], "cierre_manual")
        self.assertEqual(r["estado"]["posiciones"], [])

    def test_la_accion_deja_el_estado_escrito(self):
        velas(2, 98_000.0, 100_000.0)
        r = correr("operar_prueba.py", "estado", entrada={}, datos=self.datos)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["datos"]["ambiente"], lib_estado.PRUEBA)
        self.assertTrue(r["datos"]["ficticio"])
        self.assertEqual(ejecutor.guardado()["formato"], 1)
        self.assertEqual(razones()[-1], "stop")                      # mirar es revisar: el cruce quedó aplicado


class ReiniciarElSaldo(ConCarpeta):
    def test_reiniciar_borra_las_posiciones_y_queda_en_el_registro(self):
        con_minimos()
        cuenta()
        ejecutor.entrar(oportunidad(), AHORA)
        lib_estado.reiniciar(200.0, ahora_ms=AHORA + MINUTO)         # una sola confirmación y al tiro
        c = lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA + MINUTO)
        self.assertEqual(c["posiciones"], [])
        self.assertEqual(c["saldo"], 200.0)
        self.assertEqual(c["reinicios"], 1)
        self.assertEqual(razones(), ["entrada_ruptura", "saldo_reiniciado"])
        self.assertEqual(ejecutor.estado(AHORA + MINUTO)["puestas"], 0)


class ElEjecutorYLosFrenos(ConCarpeta):
    def test_una_orden_no_pasa_si_los_frenos_no_dejan_entrar(self):
        con_minimos()
        cuenta()
        f = lib_frenos.de_cuenta(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA), lib_estado.PRUEBA, AHORA)
        pausado = {**f, "entradas": {"puede": False, "motivo": "pausado", "quedan": 2}}
        self.assertEqual(ejecutor.entrar(oportunidad(), AHORA, frenos=pausado)["motivo"], "pausado")
        self.assertEqual(razones(), ["rechazo"])

    def test_el_tope_del_modelo_sin_validar_tambien_corta_al_ejecutor(self):
        con_minimos()
        cuenta()
        r = ejecutor.entrar(oportunidad(), AHORA)
        self.assertEqual(r["tamano"]["manda"], "tope")               # el mismo tope que muestra el tamaño
        self.assertLessEqual(r["posicion"]["monto"], 15.0)


if __name__ == "__main__":
    unittest.main()
