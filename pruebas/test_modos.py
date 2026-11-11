"""Pruebas de los tres modos y de las propuestas que vencen.

Cada prueba corre con su carpeta temporal y con datos ficticios (Ana Pérez, Matías Soto): ninguna sale a la red ni toca
datos reales. La oportunidad y su tamaño se le pasan a `decidir` ya calculados —es el mismo gancho que usa el motor—, así
que acá no se recorre ninguna vela: lo que se prueba es quién dice «sí» y qué pasa cuando nadie responde.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "bin"))

import lib_calibracion  # noqa: E402  (después de sys.path: bin/ no es un paquete instalado)
import lib_datos  # noqa: E402
import lib_ejecutor_prueba as ejecutor  # noqa: E402
import lib_estado  # noqa: E402
import lib_frenos  # noqa: E402
import lib_modos as modos  # noqa: E402
import lib_puntaje  # noqa: E402
import lib_registro  # noqa: E402
import lib_tamano  # noqa: E402
import minimo_viable  # noqa: E402
import nucleo  # noqa: E402
import propuestas  # noqa: E402

#: El mismo lunes a las 14:05 UTC de las otras pruebas: las cuentas no dependen de cuándo se corren.
AHORA = 1_770_732_300_000
MINUTO = lib_datos.PASO_MS[lib_datos.MINUTO]
HORA = lib_datos.PASO_MS["1h"]
#: Los niveles de la oportunidad, redondos: entrada 100.000, stop un 1 % abajo y objetivo un 1,5 % arriba.
PRECIO, STOP, OBJETIVO = 100_000.0, 99_000.0, 101_500.0
#: Los filtros de Binance del par que se opera, del mismo orden de magnitud que los de verdad pero inventados.
FILTROS = {"par": "BTCFDUSD", "moneda": "BTC", "tick": 0.01, "paso": 0.00001, "cantidad_minima": 0.00001,
           "nocional_minimo": 5.0, "proteccion": True, "operando": True, "motivo": ""}
#: Una calibración ya corrida y validada: con ella el semiautomático y el automático se pueden usar.
CALIBRADA = {"formato": 1, "corrido": True, "calibrado": True, "estado": lib_calibracion.VALIDADO,
             "exigencia": 72.0, "pesos": dict(lib_puntaje.PESOS_BASE), "cuando": lib_datos.iso(AHORA), "motivo": ""}


def con_minimos():
    """El cálculo del capital mínimo viable, ya guardado: sin él no hay filtros y no hay tamaño."""
    otro = {**FILTROS, "par": "ETHFDUSD", "moneda": "ETH", "paso": 0.0001, "cantidad_minima": 0.0001, "capital": 40}
    nucleo.escribir_json(minimo_viable.ruta_minimo(), {
        "formato": 1, "calculado": True, "cuando": lib_datos.iso(AHORA), "moneda": "USDT", "capital_minimo": 40,
        "pares": [{**FILTROS, "capital": 40}, otro], "motivos": [], "listo": True})


def cuenta(saldo=200.0, **cambios):
    """La cuenta de prueba con su saldo ficticio, firmada como la deja `lib_estado`."""
    cuerpo = lib_estado.nuevo(lib_estado.PRUEBA, saldo, ahora_ms=AHORA)
    return lib_estado.guardar(lib_estado.PRUEBA, {**cuerpo, **cambios})


def velas(n=5, par="BTCFDUSD", desde_ms=AHORA - 5 * MINUTO):
    """Velas de 1 m ficticias que no cruzan ningún nivel: solo para que haya precio de ahora."""
    inicio = (desde_ms // MINUTO) * MINUTO
    filas = [[inicio + i * MINUTO, 99_500.0, 99_600.0, 99_400.0, 99_500.0, 1.0] for i in range(n)]
    lib_datos.guardar_serie(par, lib_datos.MINUTO, filas)
    return filas


def tamano_de(tope=None):
    """El tamaño de la oportunidad, calculado como lo calcula `lib_tamano`: con 200 USDT de capital."""
    return lib_tamano.tamano(200.0, PRECIO, STOP, FILTROS, None, tope, 0, 0.0, False)


def oportunidad(puntaje=86.0, vela_ms=AHORA - 4 * HORA, tope=None):
    """Una oportunidad puntuada con su tamaño al lado, como la deja `lib_tamano.de_opcion`."""
    t = tamano_de(tope)
    return {"estrategia": "ruptura", "par": "BTCFDUSD", "temporalidad": "4h", "razon": "ruptura_con_volumen",
            "vela": vela_ms, "entrada": PRECIO, "stop": STOP, "objetivo": OBJETIVO, "vence": AHORA + 3 * HORA,
            "puntaje": puntaje, "permitida": True, "filtro": "", "tamano": t, "puede": t["puede"],
            "motivo": t["motivo"]}


def medido(mejor=None, exigencia=72.0, usdt_puntaje=50.0, sola=False):
    """Lo que el motor ya tiene a mano cuando llama a los modos: el puntaje y el tamaño de ahora."""
    p = {"formato": 1, "usdt": {"estrategia": "usdt", "puntaje": usdt_puntaje, "sola": sola,
                               "razon": "hay_oportunidades" if not sola else "sin_oportunidad"}}
    t = {"formato": 1, "cuando": lib_datos.iso(AHORA), "modelo": {"exigencia": exigencia}, "mejor": mejor,
         "motivos": []}
    return {"puntaje": p, "tamano": t}


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
    """Cada prueba con su carpeta de datos: lo que escriban los modos se va con ella."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.antes = os.environ.get("PILOTA_DATOS")
        self.datos = os.path.join(self.tmp.name, "datos")
        os.environ["PILOTA_DATOS"] = self.datos
        con_minimos()
        velas()
        velas(par="ETHFDUSD")

    def tearDown(self):
        if self.antes is None:
            os.environ.pop("PILOTA_DATOS", None)
        else:
            os.environ["PILOTA_DATOS"] = self.antes
        self.tmp.cleanup()


class ElManualPropone(ConCarpeta):
    """Manual: Pilota propone con todo lo que hace falta para decidir, y no abre nada."""

    def test_propone_con_puntaje_razon_monto_y_stop_y_no_abre_nada(self):
        cuenta()
        r = modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad()))
        d = r["modos"]
        self.assertEqual((d["decision"], d["propuestas"], d["entradas"]), (modos.PROPUESTA, 1, 0))
        p = modos.vigentes(modos.guardado(), AHORA)[0]
        self.assertEqual((p["par"], p["estrategia"], p["puntaje"]), ("BTCFDUSD", "ruptura", 86.0))
        self.assertGreater(p["monto"], 0)
        self.assertEqual(p["stop"], STOP)
        self.assertEqual(p["vence_ms"], AHORA + modos.VENCIMIENTO * 60_000)
        self.assertEqual(razones(), ["propuesta"])
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"], [])

    def test_una_propuesta_no_vive_mas_que_su_senal(self):
        cuenta()
        corta = {**oportunidad(), "vence": AHORA + 2 * 60_000}     # la señal vence antes que los 15 min elegidos
        modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(corta))
        p = modos.vigentes(modos.guardado(), AHORA)[0]
        self.assertEqual(p["vence_ms"], AHORA + 2 * 60_000)

    def test_la_misma_senal_no_se_propone_dos_veces(self):
        cuenta()
        o = oportunidad()
        modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(o))
        otra = modos.decidir(ahora_ms=AHORA + MINUTO, calibracion=CALIBRADA, **medido(o))
        self.assertEqual(otra["modos"]["decision"], modos.ESPERANDO)
        self.assertEqual(len(modos.vigentes(modos.guardado(), AHORA + MINUTO)), 1)
        self.assertEqual(razones(), ["propuesta"])

    def test_bajo_la_exigencia_no_propone_nada(self):
        cuenta()
        r = modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad(puntaje=60.0)))
        self.assertEqual(r["modos"]["decision"], modos.BAJO_EXIGENCIA)
        self.assertEqual(razones(), [])

    def test_si_quedarse_en_usdt_puntua_mas_no_propone_nada(self):
        cuenta()
        r = modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA,
                          **medido(oportunidad(puntaje=86.0), usdt_puntaje=100.0, sola=True))
        self.assertEqual(r["modos"]["decision"], modos.EN_USDT)
        self.assertEqual(razones(), [])

    def test_sin_oportunidad_no_hay_nada_que_proponer(self):
        cuenta()
        r = modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(None))
        self.assertEqual(r["modos"]["decision"], modos.SIN_OPORTUNIDAD)
        self.assertEqual(razones(), [])


class LaPropuestaVence(ConCarpeta):
    """Si nadie responde, la propuesta vence. Siempre: no hay un camino donde el silencio opere."""

    def test_pasada_la_hora_vence_y_queda_en_el_registro(self):
        cuenta()
        modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad()))
        despues = AHORA + (modos.VENCIMIENTO + 1) * 60_000
        d = modos.estado(despues)
        self.assertEqual(d["esperando"], 0)
        self.assertEqual([p["estado"] for p in d["propuestas"]], [modos.VENCIDA])
        self.assertEqual(razones(), ["propuesta", "propuesta_vencida"])
        self.assertEqual(d["vencidas_hoy"], 1)
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=despues)["posiciones"], [])

    def test_mirar_dos_veces_no_la_hace_vencer_dos_veces(self):
        cuenta()
        modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad()))
        despues = AHORA + (modos.VENCIMIENTO + 1) * 60_000
        modos.estado(despues)
        modos.estado(despues + MINUTO)
        self.assertEqual(razones(), ["propuesta", "propuesta_vencida"])

    def test_responder_una_vencida_no_abre_nada(self):
        cuenta()
        modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad()))
        p = modos.propuestas_de(modos.guardado())[0]
        despues = AHORA + (modos.VENCIMIENTO + 1) * 60_000
        r = modos.responder(p["id"], True, ahora_ms=despues)
        self.assertEqual((r["hecho"], r["motivo"]), (False, modos.VENCIDA))
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=despues)["posiciones"], [])

    def test_el_vencimiento_lo_elige_la_persona(self):
        cuenta()
        self.assertTrue(modos.ajustar(vencimiento_min=5, ahora_ms=AHORA)["hecho"])
        modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad()))
        p = modos.vigentes(modos.guardado(), AHORA)[0]
        self.assertEqual((p["minutos"], p["vence_ms"]), (5, AHORA + 5 * 60_000))

    def test_un_vencimiento_que_no_ofrezco_no_se_guarda(self):
        cuenta()
        r = modos.ajustar(vencimiento_min=7, ahora_ms=AHORA)
        self.assertEqual((r["hecho"], r["motivo"]), (False, "vencimiento"))
        self.assertEqual(modos.ajustes()["vencimiento_min"], modos.VENCIMIENTO)


class LaRespuesta(ConCarpeta):
    """El «Sí» pone la orden con el tamaño y los frenos de ahora; el «No» es quedarse en USDT."""

    def test_el_si_pone_la_compra_con_su_proteccion(self):
        cuenta()
        modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad()))
        p = modos.vigentes(modos.guardado(), AHORA)[0]
        r = modos.responder(p["id"], True, ahora_ms=AHORA + MINUTO, calibracion=CALIBRADA)
        self.assertEqual((r["hecho"], r["motivo"]), (True, ""))
        self.assertEqual(r["propuesta"]["estado"], modos.ACEPTADA)
        puestas = lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"]
        self.assertEqual([x["estado"] for x in puestas], [ejecutor.PUESTA])
        self.assertEqual((puestas[0]["precio"], puestas[0]["stop"]), (PRECIO, STOP))
        self.assertEqual(razones(), ["propuesta", "entrada_ruptura"])
        self.assertEqual(modos.vigentes(modos.guardado(), AHORA + MINUTO), [])

    def test_el_no_queda_como_quedarse_en_usdt_y_no_abre_nada(self):
        cuenta()
        modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad()))
        p = modos.vigentes(modos.guardado(), AHORA)[0]
        r = modos.responder(p["id"], False, ahora_ms=AHORA + MINUTO)
        self.assertTrue(r["hecho"])
        self.assertEqual(r["propuesta"]["estado"], modos.RECHAZADA)
        self.assertEqual(razones(), ["propuesta", "quedarse_en_usdt"])
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"], [])

    def test_sin_propuesta_no_hay_nada_que_responder(self):
        cuenta()
        r = modos.responder(None, True, ahora_ms=AHORA)
        self.assertEqual((r["hecho"], r["motivo"]), (False, modos.SIN_PROPUESTA))

    def test_el_si_se_mide_con_los_frenos_de_ahora(self):
        # La propuesta es una foto: si cuando respondes hay un freno que bloquea, la orden no se pone.
        cuenta()
        modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad()))
        p = modos.vigentes(modos.guardado(), AHORA)[0]
        lib_frenos.pausar(True, ahora_ms=AHORA)
        r = modos.responder(p["id"], True, ahora_ms=AHORA + MINUTO, calibracion=CALIBRADA)
        self.assertEqual((r["hecho"], r["motivo"]), (False, "pausado"))
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"], [])
        # Y sigue esperando mientras le quede hora: la respuesta no se perdió.
        self.assertEqual(len(modos.vigentes(modos.guardado(), AHORA + MINUTO)), 1)


class ElSemiautomatico(ConCarpeta):
    """Opera solo cuando el puntaje es claramente alto y el monto cabe en el que se eligió; si no, pregunta."""

    def setUp(self):
        super().setUp()
        cuenta()
        self.assertTrue(modos.elegir(modos.SEMI, ahora_ms=AHORA, calibracion=CALIBRADA)["hecho"])

    def test_con_el_puntaje_claramente_alto_y_el_monto_que_cabe_opera_solo(self):
        modos.ajustar(monto=100, ahora_ms=AHORA)
        r = modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad(puntaje=90.0)))
        self.assertEqual((r["modos"]["decision"], r["modos"]["entradas"]), (modos.ENTRADA, 1))
        puestas = lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"]
        self.assertEqual([x["estado"] for x in puestas], [ejecutor.PUESTA])
        self.assertIn("entrada_ruptura", razones())

    def test_si_el_puntaje_no_es_claramente_alto_pregunta(self):
        modos.ajustar(monto=100, ahora_ms=AHORA)
        r = modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad(puntaje=75.0)))
        self.assertEqual((r["modos"]["decision"], r["modos"]["motivo"]), (modos.PROPUESTA, modos.NO_CLARO))
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"], [])

    def test_si_el_monto_pasa_el_que_elegi_pregunta(self):
        modos.ajustar(monto=10, ahora_ms=AHORA)     # la oportunidad pide más que esto
        r = modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad(puntaje=95.0)))
        self.assertEqual((r["modos"]["decision"], r["modos"]["motivo"]), (modos.PROPUESTA, modos.MONTO_MAYOR))
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"], [])

    def test_el_monto_es_visible_y_editable(self):
        self.assertEqual(modos.estado(AHORA)["monto"], modos.MONTO)
        self.assertTrue(modos.ajustar(monto=25, ahora_ms=AHORA)["hecho"])
        self.assertEqual(modos.estado(AHORA)["monto"], 25.0)
        self.assertEqual(modos.ajustar(monto=0, ahora_ms=AHORA)["motivo"], "monto")


class ElAutomatico(ConCarpeta):
    """Opera solo, y activarlo pide dos confirmaciones."""

    def test_activarlo_pide_dos_confirmaciones(self):
        cuenta()
        una = modos.elegir(modos.AUTO, confirmaciones=1, ahora_ms=AHORA, calibracion=CALIBRADA)
        self.assertEqual((una["hecho"], una["motivo"], una["faltan"]), (False, modos.FALTAN_CONFIRMACIONES, 1))
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["modo"], modos.MANUAL)
        dos = modos.elegir(modos.AUTO, confirmaciones=2, ahora_ms=AHORA, calibracion=CALIBRADA)
        self.assertTrue(dos["hecho"])
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["modo"], modos.AUTO)
        self.assertIn("cambio_modo", razones())

    def test_opera_solo_sin_mirar_ningun_monto_elegido(self):
        cuenta()
        modos.elegir(modos.AUTO, confirmaciones=2, ahora_ms=AHORA, calibracion=CALIBRADA)
        modos.ajustar(monto=10, ahora_ms=AHORA)     # el tope del semiautomático no manda en automático
        r = modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad(puntaje=73.0)))
        self.assertEqual(r["modos"]["decision"], modos.ENTRADA)
        self.assertEqual(len(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"]), 1)


class SinCalibracion(ConCarpeta):
    """Sin calibración, el semiautomático y el automático quedan deshabilitados con el motivo visible."""

    def test_los_dos_modos_quedan_apagados_con_su_motivo(self):
        cuenta()
        d = modos.estado(AHORA)
        apagados = {m["modo"]: m["motivo"] for m in d["modos"] if not m["puede"]}
        self.assertEqual(apagados, {modos.SEMI: modos.SIN_CALIBRACION, modos.AUTO: modos.SIN_CALIBRACION})
        self.assertTrue(next(m["puede"] for m in d["modos"] if m["modo"] == modos.MANUAL))

    def test_elegirlos_no_cambia_el_modo(self):
        cuenta()
        for modo in (modos.SEMI, modos.AUTO):
            r = modos.elegir(modo, confirmaciones=2, ahora_ms=AHORA)
            self.assertEqual((r["hecho"], r["motivo"]), (False, modos.SIN_CALIBRACION))
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["modo"], modos.MANUAL)
        self.assertEqual(razones(), [])

    def test_si_el_estado_dice_otro_modo_la_vuelta_se_decide_como_manual(self):
        # Un modo que quedó escrito cuando había calibración: sin ella, Pilota propone y la persona decide.
        cuerpo = lib_estado.cuerpo_de(cuenta())
        lib_estado.guardar(lib_estado.PRUEBA, {**cuerpo, "modo": modos.AUTO})
        r = modos.decidir(ahora_ms=AHORA, **medido(oportunidad(puntaje=99.0)))
        d = r["modos"]
        self.assertEqual((d["modo"], d["efectivo"]), (modos.AUTO, modos.MANUAL))
        self.assertEqual((d["decision"], d["motivo_modo"]), (modos.PROPUESTA, modos.SIN_CALIBRACION))
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"], [])


class TrasUnFreno(ConCarpeta):
    """Tras cualquier freno se vuelve a manual, y los otros dos modos no se pueden elegir."""

    def test_con_la_racha_puesta_el_modo_vuelve_a_manual_y_no_se_puede_cambiar(self):
        cuerpo = lib_estado.cuerpo_de(cuenta())
        lib_estado.guardar(lib_estado.PRUEBA, {**cuerpo, "modo": modos.SEMI, "racha": lib_frenos.RACHA_MAXIMA})
        r = modos.elegir(modos.SEMI, ahora_ms=AHORA, calibracion=CALIBRADA)
        self.assertEqual((r["hecho"], r["motivo"]), (False, "racha"))
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["modo"], modos.MANUAL)

    def test_un_freno_que_bloquea_no_propone_ni_abre_nada(self):
        cuenta()
        lib_frenos.pausar(True, ahora_ms=AHORA)
        r = modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad(puntaje=99.0)))
        self.assertEqual((r["modos"]["decision"], r["modos"]["motivo"]), (modos.FRENADO, "pausado"))
        self.assertEqual(razones(), ["pausa"])


class LasAcciones(ConCarpeta):
    """Las cinco acciones, como las corre el host."""

    def test_estado_dice_en_que_modo_esta_y_que_espera(self):
        cuenta()
        r = correr("propuestas.py", "estado", entrada={}, datos=self.datos)
        self.assertTrue(r["ok"])
        self.assertEqual(r["datos"]["modo"], modos.MANUAL)
        self.assertEqual(r["datos"]["esperando"], 0)
        self.assertEqual(r["datos"]["parametros"]["vencimientos"], list(modos.VENCIMIENTOS))

    def test_decidir_sin_velas_no_inventa_ninguna_oportunidad(self):
        cuenta()
        r = correr("propuestas.py", "decidir", entrada={}, datos=self.datos)
        self.assertTrue(r["ok"])
        self.assertIn(r["datos"]["decision"]["decision"], (modos.SIN_OPORTUNIDAD, modos.EN_USDT, modos.FRENADO))
        self.assertEqual(r["datos"]["esperando"], 0)

    def test_un_modo_que_no_existe_se_rechaza(self):
        cuenta()
        r = correr("propuestas.py", "modo", entrada={"modo": "piloto"}, datos=self.datos)
        self.assertEqual((r["ok"], r["error"]), (False, "modo"))

    def test_responder_necesita_un_si_o_un_no(self):
        cuenta()
        r = correr("propuestas.py", "responder", entrada={"id": "pil-p-prop-x", "si": 2}, datos=self.datos)
        self.assertEqual((r["ok"], r["error"]), (False, "pausa"))

    def test_ajustar_guarda_el_vencimiento_y_el_monto(self):
        cuenta()
        r = correr("propuestas.py", "ajustar", entrada={"vencimiento": 60, "monto": 25}, datos=self.datos)
        self.assertTrue(r["ok"])
        self.assertEqual((r["datos"]["vencimiento_min"], r["datos"]["monto"]), (60, 25.0))
        otra = correr("propuestas.py", "estado", entrada={}, datos=self.datos)
        self.assertEqual(otra["datos"]["vencimiento_min"], 60)

    def test_responder_desde_la_accion_pone_la_orden(self):
        cuenta()
        modos.decidir(ahora_ms=AHORA, calibracion=CALIBRADA, **medido(oportunidad()))
        lib_calibracion.escribir(CALIBRADA)
        p = modos.vigentes(modos.guardado(), AHORA)[0]
        r = propuestas.responder({"id": p["id"], "si": 1}, ahora_ms=AHORA + MINUTO)
        self.assertTrue(r["ok"])
        self.assertTrue(r["datos"]["hecho"])
        self.assertEqual(len(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"]), 1)


if __name__ == "__main__":
    unittest.main()
