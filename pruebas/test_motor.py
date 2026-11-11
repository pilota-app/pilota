"""Pruebas del motor: la revisión cada 5 minutos y la reconciliación al arrancar o al despertar.

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

import lib_datos  # noqa: E402  (después de sys.path: bin/ no es un paquete instalado)
import lib_ejecutor_prueba as ejecutor  # noqa: E402
import lib_estado  # noqa: E402
import lib_reconciliar as reconciliar  # noqa: E402
import lib_registro  # noqa: E402
import lib_trabajo  # noqa: E402
import minimo_viable  # noqa: E402
import motor  # noqa: E402
import nucleo  # noqa: E402

#: El mismo lunes a las 14:05 UTC de las otras pruebas: las cuentas no dependen de cuándo se corren.
AHORA = 1_770_732_300_000
MINUTO = lib_datos.PASO_MS[lib_datos.MINUTO]
HORA = lib_datos.PASO_MS["1h"]
#: Los niveles de la posición, redondos: entrada 100.000, stop un 1 % abajo y objetivo un 1,5 % arriba.
PRECIO, STOP, OBJETIVO = 100_000.0, 99_000.0, 101_500.0
#: Los filtros de Binance del par que se opera, del mismo orden de magnitud que los de verdad pero inventados.
FILTROS = {"par": "BTCFDUSD", "moneda": "BTC", "tick": 0.01, "paso": 0.00001, "cantidad_minima": 0.00001,
           "nocional_minimo": 5.0, "proteccion": True, "operando": True, "motivo": ""}
CANTIDAD = 0.00014


def con_minimos():
    """El cálculo del capital mínimo viable, ya guardado: sin él no hay filtros y no hay tamaño."""
    otro = {**FILTROS, "par": "ETHFDUSD", "moneda": "ETH", "paso": 0.0001, "cantidad_minima": 0.0001, "capital": 40}
    nucleo.escribir_json(minimo_viable.ruta_minimo(), {
        "formato": 1, "calculado": True, "cuando": lib_datos.iso(AHORA), "moneda": "USDT", "capital_minimo": 40,
        "pares": [{**FILTROS, "capital": 40}, otro], "motivos": [], "listo": True})


def velas(n, bajo, alto, desde_ms=AHORA, par="BTCFDUSD"):
    """Velas de 1 m ficticias, todas con el mismo máximo y el mismo mínimo: lo que importa es qué nivel tocaron."""
    inicio = (desde_ms // MINUTO) * MINUTO
    medio = (alto + bajo) / 2
    filas = [[inicio + i * MINUTO, medio, alto, bajo, medio, 1.0] for i in range(n)]
    lib_datos.guardar_serie(par, lib_datos.MINUTO, filas)
    return filas


def velas_de_los_dos(n, bajo, alto, desde_ms=AHORA):
    """Lo mismo en los dos pares que se operan: la cobertura se mide con los dos, así que con uno solo no está cubierta."""
    return [velas(n, bajo, alto, desde_ms=desde_ms, par=p) for p in lib_datos.PARES_OPERADOS]


def posicion(estado=ejecutor.ABIERTA, par="BTCFDUSD", ms=AHORA, revisado_ms=AHORA, vence_ms=0, protegida=True):
    """Una posición como la deja el ejecutor: puesta en el nivel o ya llenada con su protección simulada."""
    c = ejecutor.cabe(FILTROS, PRECIO, STOP, OBJETIVO, CANTIDAD, True)
    o = {"estrategia": "ruptura", "par": par, "temporalidad": "4h", "vela": ms - 4 * HORA, "entrada": PRECIO,
         "stop": STOP, "objetivo": OBJETIVO, "puntaje": 84.0, "permitida": True,
         "vence": vence_ms or (ms + 3 * HORA)}
    t = {"precio": PRECIO, "stop": STOP, "cantidad": CANTIDAD, "monto": CANTIDAD * PRECIO * 1.0015}
    p = ejecutor.nueva_posicion(o, t, c, OBJETIVO, ms)
    p["revisado_ms"] = revisado_ms
    if estado == ejecutor.ABIERTA:
        p.update(estado=ejecutor.ABIERTA, llenada_ms=ms, maximo=PRECIO, protegida=protegida)
        p["ordenes"] = ejecutor.ordenes_de(p)
    return p


def cuenta(saldo=200.0, posiciones=(), **cambios):
    """La cuenta de prueba con su saldo ficticio, firmada como la deja `lib_estado`."""
    cuerpo = lib_estado.nuevo(lib_estado.PRUEBA, saldo, ahora_ms=AHORA)
    return lib_estado.guardar(lib_estado.PRUEBA, {**cuerpo, "posiciones": list(posiciones), **cambios})


def razones(ambiente=lib_estado.PRUEBA):
    """Las razones del registro, de la más vieja a la más nueva: es lo que quedó escrito."""
    filas, _ = lib_registro.leer(ambiente, lib_registro.anio_de(AHORA))
    return [f["razon"] for f in filas]


def plan_con(**cambios):
    """Un plan del motor ya guardado: con él se simula el rato en que nadie miró."""
    plan = reconciliar.armar(AHORA, {**{"formato": 1}, **cambios})
    plan.update(cambios)
    return lib_trabajo.guardar_plan(reconciliar.TIPO, plan)


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
    """Cada prueba con su carpeta de datos: lo que escriba el motor se va con ella."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.antes = os.environ.get("PILOTA_DATOS")
        self.datos = os.path.join(self.tmp.name, "datos")
        os.environ["PILOTA_DATOS"] = self.datos
        con_minimos()

    def tearDown(self):
        if self.antes is None:
            os.environ.pop("PILOTA_DATOS", None)
        else:
            os.environ["PILOTA_DATOS"] = self.antes
        self.tmp.cleanup()


class LaVentanaQueNadieMiro(ConCarpeta):
    """Desde cuándo nadie miró y qué pasó en ese rato."""

    def test_la_primera_revision_mira_un_ciclo_hacia_atras(self):
        cuenta()
        velas(5, 99_500.0, 100_500.0, desde_ms=AHORA - 5 * MINUTO)
        d = reconciliar.reconciliar(AHORA)
        r = d["resumen"]
        self.assertTrue(r["primera"])                              # sin plan no se cuenta la historia entera
        self.assertEqual(r["dormido_min"], reconciliar.CICLO_SEGUNDOS // 60)
        self.assertEqual((d["ultima_ms"], d["hace_min"], d["vueltas"]), (AHORA, 0, 1))

    def test_dormir_nueve_horas_queda_en_el_resumen_con_lo_que_paso(self):
        # Nueve horas sin mirar: en ese rato se cruzó un stop y vencieron dos entradas que nadie alcanzó a cancelar.
        plan_con(ultima_ms=AHORA - 9 * HORA, vueltas=37)
        velas(9 * 60, 98_000.0, 100_200.0, desde_ms=AHORA - 9 * HORA)
        cuenta(posiciones=[posicion(revisado_ms=AHORA - 9 * HORA, ms=AHORA - 9 * HORA),
                           posicion(estado=ejecutor.PUESTA, ms=AHORA - 9 * HORA - MINUTO,
                                    revisado_ms=AHORA, vence_ms=AHORA - 2 * HORA),
                           posicion(estado=ejecutor.PUESTA, par="ETHFDUSD", ms=AHORA - 9 * HORA - 2 * MINUTO,
                                    revisado_ms=AHORA, vence_ms=AHORA - 3 * HORA)])
        r = reconciliar.reconciliar(AHORA)["resumen"]
        self.assertEqual((r["dormido_h"], r["stops"], r["vencidas"]), (9.0, 1, 2))
        self.assertTrue(r["dormido"] and r["hubo"])
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"], [])

    def test_el_stop_que_se_cruzo_mientras_nadie_miraba_queda_cobrado(self):
        plan_con(ultima_ms=AHORA - 2 * HORA)
        velas(120, 98_000.0, 100_200.0, desde_ms=AHORA - 2 * HORA)
        cuenta(posiciones=[posicion(revisado_ms=AHORA - 2 * HORA, ms=AHORA - 2 * HORA)])
        d = reconciliar.reconciliar(AHORA)
        self.assertEqual(d["resumen"]["stops"], 1)
        self.assertIn("stop", razones())
        después = lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)
        self.assertEqual(después["posiciones"], [])                # lo cruzado no queda abierto
        self.assertLess(después["saldo"], 200.0)                   # el saldo se mueve al cerrar, con sus costos
        self.assertEqual(después["operaciones"], 1)

    def test_revisar_dos_veces_no_aplica_ni_anota_nada_dos_veces(self):
        plan_con(ultima_ms=AHORA - 2 * HORA)
        velas(120, 98_000.0, 100_200.0, desde_ms=AHORA - 2 * HORA)
        cuenta(posiciones=[posicion(revisado_ms=AHORA - 2 * HORA, ms=AHORA - 2 * HORA)])
        reconciliar.reconciliar(AHORA)
        primeras = razones()
        d = reconciliar.reconciliar(AHORA + MINUTO)
        self.assertEqual(razones(), primeras)                      # ninguna línea nueva: ya estaba todo aplicado
        self.assertEqual(d["resumen"]["stops"], 0)


class LoHuerfano(ConCarpeta):
    """Lo que no puede quedar así después de reconciliar."""

    def test_la_entrada_que_vencio_se_cancela_aunque_no_haya_velas_que_la_cancelen(self):
        velas(5, 99_500.0, 100_500.0, desde_ms=AHORA - 5 * MINUTO)
        cuenta(posiciones=[posicion(estado=ejecutor.PUESTA, ms=AHORA - 4 * HORA, revisado_ms=AHORA,
                                    vence_ms=AHORA - HORA)])
        r = reconciliar.reconciliar(AHORA)["resumen"]
        self.assertEqual((r["vencidas"], r["huerfanas"], r["cerradas"]), (1, 1, 1))
        self.assertIn("propuesta_vencida", razones())
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"], [])

    def test_la_posicion_abierta_sin_proteccion_se_cierra_a_mercado(self):
        velas(5, 99_500.0, 100_500.0, desde_ms=AHORA - 5 * MINUTO)
        cuenta(posiciones=[posicion(revisado_ms=AHORA, protegida=False)])
        r = reconciliar.reconciliar(AHORA)["resumen"]
        self.assertEqual((r["desnudas"], r["cerradas"], r["cierres"]), (1, 1, 1))
        self.assertIn("cierre_manual", razones())
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"], [])

    def test_lo_que_no_es_de_pilota_no_se_toca_nunca(self):
        velas(5, 99_500.0, 100_500.0, desde_ms=AHORA - 5 * MINUTO)
        ajena = {"id": "otra-cosa-42", "par": "BTCFDUSD", "estado": ejecutor.ABIERTA, "protegida": False}
        cuenta(posiciones=[ajena])
        r = reconciliar.reconciliar(AHORA)["resumen"]
        self.assertEqual((r["desnudas"], r["cerradas"]), (0, 0))
        self.assertEqual(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"], [ajena])

    def test_de_una_cuenta_que_no_es_de_fiar_no_se_toca_nada(self):
        velas(5, 99_500.0, 100_500.0, desde_ms=AHORA - 5 * MINUTO)
        cuenta(posiciones=[posicion(revisado_ms=AHORA, protegida=False)])
        ruta = lib_estado.ruta(lib_estado.PRUEBA)
        d = nucleo.leer_json(ruta, {})
        d["estado"]["saldo"] = 999.0                               # la huella ya no cuadra: nada de esto es de fiar
        nucleo.escribir_json(ruta, d)
        v = reconciliar.reconciliar(AHORA)
        self.assertTrue(v["frenado"])
        self.assertIn("frenado", [m["codigo"] for m in v["motivos"]])
        self.assertEqual(nucleo.leer_json(ruta, {})["estado"]["saldo"], 999.0)   # el archivo no se pisa


class LaCobertura(ConCarpeta):
    """El rato sin velas de 1 m que cuiden las posiciones: se dice, nunca se tapa."""

    def test_sin_velas_de_un_minuto_la_ventana_queda_abierta_y_despues_se_cierra(self):
        cuenta(posiciones=[posicion(revisado_ms=AHORA - HORA, ms=AHORA - HORA)])
        v = reconciliar.reconciliar(AHORA)
        ventana = v["sin_cobertura"][-1]
        self.assertEqual((ventana["motivo"], ventana["abierto"]), (reconciliar.VENTANA_SIN_1M, True))
        self.assertTrue(v["abierta"])
        self.assertIn("sin_1m", [m["codigo"] for m in v["motivos"]])
        velas_de_los_dos(60, 99_500.0, 100_500.0, desde_ms=AHORA - HORA)   # el muestreo trajo los minutos que faltaban
        otra = reconciliar.reconciliar(AHORA + MINUTO)
        self.assertEqual(len(otra["sin_cobertura"]), 1)             # la misma ventana, no una nueva
        self.assertFalse(otra["sin_cobertura"][-1]["abierto"])
        self.assertFalse(otra["abierta"])

    def test_el_rato_dormido_queda_escrito_aunque_las_velas_esten_al_dia(self):
        plan_con(ultima_ms=AHORA - 9 * HORA)
        velas_de_los_dos(9 * 60, 99_500.0, 100_500.0, desde_ms=AHORA - 9 * HORA)
        cuenta()
        v = reconciliar.reconciliar(AHORA)
        ventana = v["sin_cobertura"][-1]
        self.assertEqual((ventana["motivo"], ventana["abierto"], ventana["min"]),
                         (reconciliar.VENTANA_DORMIDO, False, 9 * 60))

    def test_una_revision_al_dia_no_anota_ninguna_ventana(self):
        plan_con(ultima_ms=AHORA - reconciliar.CICLO_SEGUNDOS * 1000)
        velas_de_los_dos(10, 99_500.0, 100_500.0, desde_ms=AHORA - 10 * MINUTO)
        cuenta()
        self.assertEqual(reconciliar.reconciliar(AHORA)["sin_cobertura"], [])


class ComoEstaElMotor(ConCarpeta):
    """«Última revisión hace N min» y si está activo o dormido."""

    def test_apagado_lo_dice_y_no_reconcilia_nada(self):
        plan_con(ultima_ms=AHORA - 30 * 60_000, vueltas=3)
        d = reconciliar.estado(AHORA)
        self.assertEqual((d["hace_min"], d["corriendo"], d["activo"]), (30, False, False))
        self.assertEqual([m["codigo"] for m in d["motivos"]][0], reconciliar.APAGADO)
        self.assertEqual(d["vueltas"], 3)                          # mirar no es revisar: la cuenta no sube

    def test_encendido_pero_sin_revisar_hace_rato_esta_dormido(self):
        plan = {**reconciliar.armar(AHORA, {"ultima_ms": AHORA - 30 * 60_000}), "corriendo": True}
        d = reconciliar.vista(plan, AHORA)
        self.assertEqual((d["activo"], d["dormido"], d["hace_min"]), (False, True, 30))
        self.assertEqual([m["codigo"] for m in d["motivos"]][0], reconciliar.DORMIDO)

    def test_recien_revisado_y_encendido_esta_activo(self):
        plan = {**reconciliar.armar(AHORA, {"ultima_ms": AHORA - 60_000}), "corriendo": True}
        d = reconciliar.vista(plan, AHORA)
        self.assertEqual((d["activo"], d["dormido"], d["hace_min"]), (True, False, 1))

    def test_sin_ninguna_revision_todavia_no_hay_hace_cuanto(self):
        d = reconciliar.estado(AHORA)
        self.assertIsNone(d["hace_min"])
        self.assertEqual((d["estado"], d["vueltas"]), ("nunca", 0))


class LasAcciones(ConCarpeta):
    """Las cuatro acciones, como las corre el host."""

    def test_estado_no_reconcilia_y_revisar_si(self):
        cuenta()
        velas(5, 99_500.0, 100_500.0, desde_ms=AHORA - 5 * MINUTO)
        r = correr("motor.py", "estado", entrada={}, datos=self.datos)
        self.assertTrue(r["ok"])
        self.assertEqual(r["datos"]["ultima_ms"], 0)
        otra = correr("motor.py", "revisar", entrada={}, datos=self.datos)
        self.assertTrue(otra["ok"])
        self.assertGreater(otra["datos"]["ultima_ms"], 0)
        self.assertEqual(otra["datos"]["vueltas"], 1)
        self.assertEqual(otra["datos"]["parametros"]["ciclo_segundos"], reconciliar.CICLO_SEGUNDOS)

    def test_el_trabajo_revisa_cada_cinco_minutos_hasta_que_lo_detienen(self):
        cuenta()
        velas(10, 99_500.0, 100_500.0, desde_ms=AHORA - 10 * MINUTO)
        esperas = []
        r = motor.encender({}, ahora_ms=AHORA, dormir=esperas.append, ciclos=2, latir=False)
        self.assertEqual((r["ok"], r["error"]), (True, ""))
        self.assertEqual(r["datos"]["vueltas"], 2)
        self.assertEqual(r["datos"]["estado"], "listo")
        self.assertEqual(r["datos"]["etapa"], reconciliar.ETAPAS[1])   # la primera vuelta despierta; después vigila
        self.assertEqual(sum(esperas), reconciliar.CICLO_SEGUNDOS)      # una espera entre las dos vueltas
        self.assertEqual(lib_trabajo.leer_plan(reconciliar.TIPO)["vueltas"], 2)

    def test_apagar_no_toca_ninguna_proteccion(self):
        velas(10, 99_500.0, 100_500.0, desde_ms=AHORA - 10 * MINUTO)
        cuenta(posiciones=[posicion(revisado_ms=AHORA)])
        r = motor.apagar({}, ahora_ms=AHORA)
        self.assertTrue(r["ok"])
        self.assertFalse(r["datos"]["corriendo"])
        guardadas = lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)["posiciones"]
        self.assertEqual([p["protegida"] for p in guardadas], [True])


class ElGanchoDeLosModos(ConCarpeta):
    """Cuándo entrar no se decide acá: el motor deja el mundo al día y le pasa el contexto a quien decide."""

    def test_el_gancho_recibe_el_contexto_al_dia_y_puede_sumar_al_resumen(self):
        cuenta()
        velas(10, 99_500.0, 100_500.0, desde_ms=AHORA - 10 * MINUTO)
        visto = {}

        def decidir(ctx):
            visto.update(ctx)
            return {"propuestas": 2}

        d = reconciliar.reconciliar(AHORA, decidir=decidir)
        self.assertEqual(visto["ahora_ms"], AHORA)
        self.assertEqual(visto["ambiente"], lib_estado.PRUEBA)
        self.assertFalse(visto["frenos"]["frenado"])
        self.assertEqual(visto["ejecutor"]["saldo"], 200.0)
        self.assertEqual(d["resumen"]["propuestas"], 2)

    def test_sin_gancho_no_se_abre_ninguna_posicion(self):
        cuenta()
        velas(10, 99_000.0, 101_600.0, desde_ms=AHORA - 10 * MINUTO)   # precios que cruzarían cualquier nivel
        d = reconciliar.reconciliar(AHORA)
        self.assertEqual((d["abiertas"], d["puestas"]), (0, 0))
        self.assertEqual(razones(), [])


if __name__ == "__main__":
    unittest.main()
