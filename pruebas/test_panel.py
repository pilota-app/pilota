"""Pruebas de la pantalla principal: la banda, el saldo con su línea del piso, los medidores, las posiciones, las
propuestas, el motor, el registro, la línea diaria y la mascota.

Cada prueba corre con su carpeta temporal y con datos ficticios (Ana Pérez, Matías Soto): ninguna sale a la red ni toca
datos reales. Los precios son redondos a propósito: así las cuentas se saben de memoria.
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
import lib_frenos  # noqa: E402
import lib_modos  # noqa: E402
import lib_panel  # noqa: E402
import lib_registro  # noqa: E402
import lib_tamano  # noqa: E402
import minimo_viable  # noqa: E402
import nucleo  # noqa: E402
import panel  # noqa: E402

#: El mismo lunes a las 14:05 UTC de las otras pruebas: las cuentas no dependen de cuándo se corren.
AHORA = 1_770_732_300_000
MINUTO = lib_datos.PASO_MS[lib_datos.MINUTO]
HORA = lib_datos.PASO_MS["1h"]
#: Los niveles de la oportunidad, redondos: entrada 100.000, stop un 1 % abajo y objetivo un 1,5 % arriba.
PRECIO, STOP, OBJETIVO = 100_000.0, 99_000.0, 101_500.0
FILTROS = {"par": "BTCFDUSD", "moneda": "BTC", "tick": 0.01, "paso": 0.00001, "cantidad_minima": 0.00001,
           "nocional_minimo": 5.0, "proteccion": True, "operando": True, "motivo": ""}
CANTIDAD = 0.00014


def con_minimos():
    """El cálculo del capital mínimo viable, ya guardado: sin él no hay filtros y no hay tamaño."""
    otro = {**FILTROS, "par": "ETHFDUSD", "moneda": "ETH", "paso": 0.0001, "cantidad_minima": 0.0001, "capital": 40}
    nucleo.escribir_json(minimo_viable.ruta_minimo(), {
        "formato": 1, "calculado": True, "cuando": lib_datos.iso(AHORA), "moneda": "USDT", "capital_minimo": 40,
        "pares": [{**FILTROS, "capital": 40}, otro], "motivos": [], "listo": True})


def cuenta(saldo=200.0, posiciones=(), **cambios):
    """La cuenta de prueba con su saldo ficticio, firmada como la deja `lib_estado`."""
    cuerpo = lib_estado.nuevo(lib_estado.PRUEBA, saldo, ahora_ms=AHORA)
    return lib_estado.guardar(lib_estado.PRUEBA, {**cuerpo, "posiciones": list(posiciones), **cambios})


def oportunidad(par="BTCFDUSD", puntaje=84.0, monto=14.0, puede=True, motivo=""):
    """Una oportunidad puntuada con su tamaño al lado, como la deja escrita `lib_tamano.estado`."""
    return {"estrategia": "ruptura", "par": par, "temporalidad": "4h", "razon": "ruptura_con_volumen",
            "vela": AHORA - 4 * HORA, "puntaje": puntaje, "permitida": True, "filtro": "",
            "entrada": PRECIO, "stop": STOP, "objetivo": OBJETIVO, "vence": AHORA + 3 * HORA,
            "puede": puede, "motivo": motivo,
            "tamano": {"par": par, "moneda": par[:3], "precio": PRECIO, "stop": STOP, "cantidad": CANTIDAD,
                       "monto": monto, "arriesgado": 0.16, "puede": puede, "motivo": motivo}}


def con_tamano(oportunidades=None, exigencia=85.0):
    """El último tamaño escrito: es de ahí de donde salen los medidores de la pantalla."""
    lista = list(oportunidades) if oportunidades is not None else [oportunidad()]
    return lib_tamano.escribir({
        "formato": 1, "cuando": lib_datos.iso(AHORA), "moneda": "USDT", "ambiente": lib_estado.PRUEBA,
        "frenado": False, "motivo": "", "modo": "manual", "saldo": 200.0, "referencia": 200.0,
        "modelo": {"estado": "sin_calibrar", "calibrado": False, "validado": False, "exigencia": exigencia,
                   "tope": 15.0, "topado": True, "cuando": "", "motivo": "sin_calibracion"},
        "oportunidades": lista, "mejor": lib_tamano.mejor_de(lista), "motivos": [], "listo": True})


def posicion(estado=ejecutor.ABIERTA, par="BTCFDUSD", ms=AHORA, protegida=True):
    """Una posición como la deja el ejecutor: puesta en el nivel o ya llenada con su protección simulada."""
    c = ejecutor.cabe(FILTROS, PRECIO, STOP, OBJETIVO, CANTIDAD, True)
    o = {"estrategia": "ruptura", "par": par, "temporalidad": "4h", "vela": ms - 4 * HORA, "entrada": PRECIO,
         "stop": STOP, "objetivo": OBJETIVO, "puntaje": 84.0, "permitida": True, "vence": ms + 3 * HORA}
    t = {"precio": PRECIO, "stop": STOP, "cantidad": CANTIDAD, "monto": CANTIDAD * PRECIO}
    p = ejecutor.nueva_posicion(o, t, c, OBJETIVO, ms)
    p["revisado_ms"] = ms
    if estado == ejecutor.ABIERTA:
        p.update(estado=ejecutor.ABIERTA, llenada_ms=ms, maximo=PRECIO, protegida=protegida)
        p["ordenes"] = ejecutor.ordenes_de(p)
    return p


def con_ejecutor(precio=PRECIO):
    """Lo último que escribió el ejecutor de prueba (las posiciones salen de la cuenta, que ya está guardada): es de ahí
    de donde la pantalla saca lo que está abierto y lo que lleva ganado. Sin precio no hay velas de 1 m, y entonces
    tampoco hay ganancia: no se supone ninguna."""
    series = ({par: [[AHORA - MINUTO, precio, precio, precio, precio, 1.0]] for par in lib_datos.PARES_OPERADOS}
              if precio is not None else {par: [] for par in lib_datos.PARES_OPERADOS})
    return ejecutor.escribir(ejecutor.estado(AHORA, minutos=series))


def con_propuesta(puntaje=86.0, minutos=15):
    """Una propuesta esperando el «Sí», con su cuenta atrás corriendo."""
    o = {**oportunidad(puntaje=puntaje), "vela": AHORA - 4 * HORA}
    archivo, p = lib_modos.proponer(o, AHORA, vencimiento_min=minutos, exigencia=85.0)
    lib_modos.guardar(archivo)
    return p


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
    """Cada prueba con su carpeta de datos: lo que se escriba se va con ella."""

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


class LaBandaYElSaldo(ConCarpeta):
    """Con qué dinero se juega y dónde está la línea del piso."""

    def test_la_banda_dice_el_ambiente_y_que_es_ficticio(self):
        cuenta()
        d = lib_panel.estado(AHORA)
        self.assertEqual((d["ambiente"], d["ficticio"], d["moneda"]), (lib_estado.PRUEBA, True, "USDT"))

    def test_el_saldo_trae_los_dos_pisos_y_en_que_parte_del_tramo_va(self):
        cuenta(saldo=200.0)
        s = lib_panel.estado(AHORA)["saldo"]
        self.assertEqual((s["saldo"], s["referencia"], s["aportado"]), (200.0, 200.0, 200.0))
        self.assertEqual(s["piso"], 200.0 * (1 - lib_frenos.PISO))               # 150: el 25 % bajo la referencia
        self.assertEqual(s["piso_absoluto"], 200.0 * (1 - lib_frenos.PISO_ABSOLUTO))
        self.assertEqual(s["sobre_piso"], 1.0)                                   # el saldo es el más alto alcanzado
        self.assertFalse(s["toco_piso"] or s["toco_piso_absoluto"])

    def test_el_saldo_a_medio_camino_del_piso_queda_a_medio_camino_de_la_barra(self):
        # Referencia 200 y piso 150: con 175 el saldo va justo a la mitad del tramo que dibuja la barra.
        cuenta(saldo=200.0)
        lib_estado.guardar(lib_estado.PRUEBA,
                           {**lib_estado.cuerpo_de(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)),
                            "saldo": 175.0})
        s = lib_panel.estado(AHORA)["saldo"]
        self.assertAlmostEqual(s["sobre_piso"], 0.5)

    def test_con_el_piso_tocado_la_pantalla_lo_dice(self):
        cuenta(saldo=200.0)
        lib_estado.guardar(lib_estado.PRUEBA,
                           {**lib_estado.cuerpo_de(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)),
                            "saldo": 140.0})
        s = lib_panel.estado(AHORA)["saldo"]
        self.assertTrue(s["toco_piso"])
        self.assertEqual(s["sobre_piso"], 0.0)


class LaMonedaLocal(ConCarpeta):
    """La referencia en la moneda de la persona: solo para mirar, y nunca inventada."""

    def test_sin_tasa_no_hay_ninguna_equivalencia(self):
        cuenta()
        l = lib_panel.estado(AHORA)["local"]
        self.assertEqual((l["moneda"], l["tasa"], l["listo"]), (lib_panel.MONEDA_LOCAL, 0.0, False))

    def test_la_tasa_que_escribe_la_persona_queda_guardada(self):
        cuenta()
        r = lib_panel.guardar_local("clp", 950, ahora_ms=AHORA)
        self.assertTrue(r["hecho"])
        self.assertEqual((r["datos"]["moneda"], r["datos"]["tasa"], r["datos"]["listo"]), ("CLP", 950.0, True))
        self.assertEqual(lib_panel.estado(AHORA)["local"]["tasa"], 950.0)

    def test_una_moneda_que_no_es_un_codigo_no_se_guarda(self):
        r = lib_panel.guardar_local("peso chileno <b>", 950, ahora_ms=AHORA)
        self.assertEqual((r["hecho"], r["motivo"]), (False, "moneda"))
        self.assertFalse(lib_panel.local()["listo"])

    def test_una_tasa_imposible_no_se_guarda_y_el_cero_borra_la_referencia(self):
        self.assertEqual(lib_panel.guardar_local("CLP", lib_panel.TASA_MAXIMA + 1, ahora_ms=AHORA)["motivo"], "tasa")
        lib_panel.guardar_local("CLP", 950, ahora_ms=AHORA)
        r = lib_panel.guardar_local(None, 0, ahora_ms=AHORA)
        self.assertTrue(r["hecho"])
        self.assertEqual((r["datos"]["moneda"], r["datos"]["listo"]), ("CLP", False))


class LosMedidores(ConCarpeta):
    """El puntaje de cada par contra la exigencia."""

    def test_cada_par_operado_tiene_su_medidor_con_su_exigencia(self):
        cuenta()
        con_tamano([oportunidad("BTCFDUSD", 84.0), oportunidad("ETHFDUSD", 61.0)])
        d = lib_panel.estado(AHORA)
        self.assertEqual([m["par"] for m in d["medidores"]], list(lib_datos.PARES_OPERADOS))
        btc, eth = d["medidores"]
        self.assertEqual((btc["puntaje"], eth["puntaje"]), (84.0, 61.0))
        self.assertEqual(d["mejor_puntaje"], 84.0)
        self.assertTrue(all(m["exigencia"] == d["exigencia"] for m in d["medidores"]))

    def test_el_medidor_dice_si_pasa_la_exigencia(self):
        cuenta()
        con_tamano([oportunidad("BTCFDUSD", 90.0), oportunidad("ETHFDUSD", 61.0)], exigencia=85.0)
        btc, eth = lib_panel.estado(AHORA)["medidores"]
        self.assertTrue(btc["pasa"])
        self.assertFalse(eth["pasa"])
        self.assertAlmostEqual(btc["parte"], 0.9)

    def test_un_puntaje_que_no_esta_no_se_inventa(self):
        cuenta()
        d = lib_panel.estado(AHORA)                      # sin tamaño escrito todavía
        self.assertEqual([m["puntaje"] for m in d["medidores"]], [None, None])
        self.assertEqual([m["motivo"] for m in d["medidores"]], ["sin_oportunidad"] * 2)
        self.assertIn("sin_medida", [m["codigo"] for m in d["motivos"]])
        self.assertFalse(d["listo"])

    def test_de_un_par_manda_la_que_mas_puntua(self):
        cuenta()
        con_tamano([oportunidad("BTCFDUSD", 51.0), oportunidad("BTCFDUSD", 77.0)])
        btc = lib_panel.estado(AHORA)["medidores"][0]
        self.assertEqual(btc["puntaje"], 77.0)


class LasPosicionesYLasPropuestas(ConCarpeta):
    """Lo que está abierto, lo que espera y cuánto le queda."""

    def test_una_posicion_abierta_viene_con_su_ganancia_su_stop_y_su_objetivo(self):
        p = posicion()
        cuenta(posiciones=[p])
        con_ejecutor(precio=101_000.0)
        d = lib_panel.estado(AHORA)
        self.assertEqual(d["abiertas"], 1)
        suya = d["posiciones"][0]
        self.assertEqual((suya["par"], suya["estado"]), ("BTCFDUSD", ejecutor.ABIERTA))
        self.assertEqual((suya["stop"], suya["objetivo"]), (STOP, OBJETIVO))
        self.assertAlmostEqual(suya["ganancia"], CANTIDAD * (101_000.0 - PRECIO))
        self.assertTrue(suya["protegida"])

    def test_sin_precio_de_ahora_la_ganancia_no_se_supone(self):
        p = posicion()
        cuenta(posiciones=[p])
        con_ejecutor(precio=None)
        d = lib_panel.estado(AHORA)
        self.assertIsNone(d["posiciones"][0]["ganancia"])
        self.assertIn("sin_1m", [m["codigo"] for m in d["motivos"]])   # y se dice el rato sin velas de 1 m

    def test_la_propuesta_que_espera_trae_su_cuenta_atras(self):
        cuenta()
        con_tamano()
        con_propuesta(minutos=15)
        d = lib_panel.estado(AHORA + 5 * 60_000)
        self.assertEqual(d["esperando"], 1)
        self.assertEqual(d["propuestas"][0]["queda_min"], 10)
        self.assertTrue(d["propuestas"][0]["espera"])

    def test_la_propuesta_que_se_paso_de_su_hora_ya_no_espera(self):
        cuenta()
        con_tamano()
        con_propuesta(minutos=5)
        d = lib_panel.estado(AHORA + 6 * 60_000)
        self.assertEqual((d["esperando"], d["propuestas"]), (0, []))
        self.assertIn("propuesta_vencida", [f["razon"] for f in
                                           lib_registro.ultimas(lib_estado.PRUEBA, 5)[0]])


class LaLineaDiariaYLaMascota(ConCarpeta):
    """Lo que la mascota cuenta de la decisión de ahora."""

    def test_si_hoy_no_se_opero_la_linea_dice_el_mejor_puntaje_y_la_exigencia(self):
        cuenta()
        con_tamano([oportunidad("BTCFDUSD", 62.0)])
        d = lib_panel.estado(AHORA)
        # La exigencia es la del modelo (sin calibrar, la alta), la misma de los medidores y de la línea diaria.
        self.assertEqual((d["dia"]["opero"], d["dia"]["mejor_puntaje"]), (False, 62.0))
        self.assertEqual(d["dia"]["exigencia"], d["exigencia"])
        self.assertGreater(d["exigencia"], 62.0)
        self.assertEqual(d["mascota"]["animo"], "atento")
        self.assertEqual(d["mascota"]["cuento"], "bajo_exigencia")
        self.assertEqual(d["mascota"]["datos"]["puntaje"], 62.0)

    def test_lo_que_se_opero_hoy_queda_contado_en_la_linea_diaria(self):
        cuenta()
        con_tamano()
        lib_registro.anotar(lib_estado.PRUEBA, "entrada_ruptura", par="BTCFDUSD", puntaje=84.0, ms=AHORA - 3 * HORA)
        lib_registro.anotar(lib_estado.PRUEBA, "objetivo", par="BTCFDUSD", puntaje=84.0, ms=AHORA - 2 * HORA,
                            resultado={"por": "objetivo", "neto": 0.5})
        d = lib_panel.estado(AHORA)
        self.assertTrue(d["dia"]["opero"])
        self.assertEqual((d["dia"]["entradas"], d["dia"]["cerradas"]), (1, 1))

    def test_lo_de_ayer_no_cuenta_como_de_hoy(self):
        cuenta()
        con_tamano()
        lib_registro.anotar(lib_estado.PRUEBA, "objetivo", par="BTCFDUSD", puntaje=84.0, ms=AHORA - 24 * HORA,
                            resultado={"por": "objetivo", "neto": 0.5})
        d = lib_panel.estado(AHORA)
        self.assertFalse(d["dia"]["opero"])
        self.assertEqual(d["dia"]["cerradas"], 0)

    def test_al_cerrar_la_mascota_queda_neutral_sin_celebrar(self):
        cuenta()
        con_tamano()
        lib_registro.anotar(lib_estado.PRUEBA, "objetivo", par="BTCFDUSD", puntaje=84.0, ms=AHORA - 5 * 60_000,
                            resultado={"por": "objetivo", "neto": 0.52})
        m = lib_panel.estado(AHORA)["mascota"]
        self.assertEqual((m["animo"], m["cuento"]), ("neutral", "cerrada"))
        self.assertEqual((m["datos"]["par"], m["datos"]["neto"]), ("BTCFDUSD", 0.52))

    def test_con_una_propuesta_esperando_la_mascota_duda(self):
        cuenta()
        con_tamano()
        con_propuesta(puntaje=86.0)
        m = lib_panel.estado(AHORA)["mascota"]
        self.assertEqual((m["animo"], m["cuento"]), ("dudando", "esperando"))
        self.assertEqual(m["datos"]["puntaje"], 86.0)

    def test_con_una_posicion_abierta_la_mascota_esta_operando(self):
        p = posicion()
        cuenta(posiciones=[p])
        con_tamano()
        con_ejecutor(precio=101_000.0)
        m = lib_panel.estado(AHORA)["mascota"]
        self.assertEqual((m["animo"], m["cuento"], m["datos"]["n"]), ("operando", "abierta", 1))

    def test_un_freno_puesto_manda_sobre_todo_lo_demas(self):
        # Con el piso tocado, la mascota cuenta el freno aunque haya una propuesta esperando y una posición abierta.
        p = posicion()
        cuenta(saldo=200.0, posiciones=[p])
        lib_estado.guardar(lib_estado.PRUEBA,
                           {**lib_estado.cuerpo_de(lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=AHORA)),
                            "saldo": 140.0, "posiciones": [p]})
        con_tamano()
        con_propuesta()
        con_ejecutor()
        lib_frenos.escribir(lib_frenos.estado(AHORA))
        d = lib_panel.estado(AHORA)
        self.assertEqual(d["mascota"]["animo"], "frenado")
        self.assertEqual(d["mascota"]["datos"]["freno"], "piso")
        self.assertTrue(d["frenos"]["frenado"])
        self.assertIn("frenado", [m["codigo"] for m in d["motivos"]])

    def test_un_aviso_del_mercado_se_cuenta_aunque_en_prueba_no_frene(self):
        # La comisión maker por sobre la que supuso el backtest: en prueba no frena, pero la mascota lo dice igual.
        cuenta()
        con_tamano()
        mercado = {"comision": lib_frenos.comision_de(com={"maker": 0.001, "taker": 0.001, "origen": "api"}),
                   "fdusd": lib_frenos.fdusd_de(AHORA)}
        lib_frenos.escribir(lib_frenos.estado(AHORA, mercado=mercado))
        d = lib_panel.estado(AHORA)
        self.assertFalse(d["frenos"]["frenado"])                      # en prueba no frena: avisa
        self.assertEqual((d["mascota"]["animo"], d["mascota"]["cuento"]), ("dudando", "aviso"))
        self.assertEqual(d["mascota"]["datos"]["aviso"], "comision")

    def test_con_todas_las_posiciones_que_caben_abiertas_la_mascota_lo_dice(self):
        cuenta(posiciones=[posicion(), posicion(par="ETHFDUSD")])
        con_tamano()
        con_ejecutor(precio=101_000.0)
        m = lib_panel.estado(AHORA)["mascota"]
        self.assertEqual((m["animo"], m["cuento"]), ("operando", "llenas"))
        self.assertEqual((m["datos"]["n"], m["datos"]["maximas"], m["datos"]["quedan"]),
                         (lib_tamano.POSICIONES, lib_tamano.POSICIONES, 0))

    def test_lo_que_pasa_la_exigencia_y_no_deja_monto_se_cuenta_con_su_motivo(self):
        cuenta()
        con_tamano([oportunidad("BTCFDUSD", 95.0, puede=False, motivo="sin_disponible")])
        m = lib_panel.estado(AHORA)["mascota"]
        self.assertEqual((m["animo"], m["cuento"]), ("atento", "rechazada"))
        self.assertEqual((m["datos"]["par"], m["datos"]["motivo"]), ("BTCFDUSD", "sin_disponible"))

    def test_con_el_motor_apagado_lo_que_pasa_la_exigencia_igual_se_explica(self):
        cuenta()
        con_tamano([oportunidad("BTCFDUSD", 95.0)])
        d = lib_panel.estado(AHORA)
        self.assertFalse(d["motor"]["corriendo"])
        self.assertEqual((d["mascota"]["animo"], d["mascota"]["cuento"]), ("atento", "apagado"))
        # Con el motor mirando, lo mismo se cuenta como la decisión de la próxima revisión.
        m = lib_panel.mascota_de(d["frenos"], [], [], d["medidores"], d["dia"], {"ultimas": []},
                                 d["exigencia"], AHORA, motor={"corriendo": True})
        self.assertEqual((m["animo"], m["cuento"]), ("atento", "sobre_exigencia"))
        self.assertEqual(m["datos"]["puntaje"], 95.0)

    def test_la_linea_diaria_cuenta_las_propuestas_que_vencieron_sin_respuesta(self):
        # Mirar también es aplicar: la propuesta que vence al mirar ya cuenta en el día de esta misma vuelta.
        cuenta()
        con_tamano()
        con_propuesta(minutos=5)
        d = lib_panel.estado(AHORA + 6 * 60_000)
        self.assertEqual((d["dia"]["opero"], d["dia"]["vencidas"]), (False, 1))
        self.assertEqual(d["historial"]["ultimas"][0]["razon"], "propuesta_vencida")


class LoQueFaltaYElRegistro(ConCarpeta):
    """Lo que la pantalla dice cuando falta algo, y lo último que hizo Pilota."""

    def test_el_motor_apagado_se_dice_siempre(self):
        cuenta()
        con_tamano()
        d = lib_panel.estado(AHORA)
        self.assertFalse(d["motor"]["corriendo"])
        self.assertIn("motor_apagado", [m["codigo"] for m in d["motivos"]])

    def test_el_registro_viene_con_las_ultimas_lineas_y_desde_cuando(self):
        cuenta()
        for i in range(3):
            lib_registro.anotar(lib_estado.PRUEBA, "quedarse_en_usdt", puntaje=50.0, ms=AHORA - (i + 1) * HORA)
        h = lib_panel.estado(AHORA)["historial"]
        self.assertEqual(h["lineas"], 3)
        self.assertEqual(h["campos"], list(lib_registro.CAMPOS))
        self.assertLessEqual(len(h["ultimas"]), lib_panel.LINEAS)
        self.assertEqual(h["ultimas"][0]["razon"], "quedarse_en_usdt")

    def test_una_cuenta_que_arranco_frenada_no_muestra_numeros_de_fiar(self):
        cuenta()
        with open(lib_estado.ruta(lib_estado.PRUEBA), "r+", encoding="utf-8") as f:
            d = json.load(f)
            d["estado"]["saldo"] = 999.0            # el archivo tocado a mano: la huella ya no cuadra
            f.seek(0)
            json.dump(d, f)
            f.truncate()
        p = lib_panel.estado(AHORA)
        self.assertTrue(p["frenos"]["arranque"])
        self.assertEqual(p["mascota"]["animo"], "frenado")
        self.assertEqual(p["mascota"]["cuento"], "arranque")
        self.assertEqual(p["saldo"]["saldo"], 0.0)
        self.assertIn("sin_cuenta", [m["codigo"] for m in p["motivos"]])


class LasAcciones(ConCarpeta):
    """Las dos acciones, corridas como las corre la app."""

    def test_panel_estado_responde_la_pantalla_entera(self):
        r = correr("panel.py", "estado", entrada={}, datos=self.datos)
        self.assertTrue(r["ok"])
        d = r["datos"]
        for clave in ("ambiente", "saldo", "local", "medidores", "posiciones", "propuestas", "motor", "historial",
                      "dia", "mascota", "parametros", "motivos"):
            self.assertIn(clave, d)
        self.assertEqual(d["mascota"]["animo"] in lib_panel.ANIMOS, True)

    def test_panel_local_guarda_la_referencia_y_la_devuelve_con_la_pantalla(self):
        r = correr("panel.py", "local", entrada={"moneda": "CLP", "tasa": 950}, datos=self.datos)
        self.assertTrue(r["ok"])
        self.assertEqual((r["datos"]["local"]["moneda"], r["datos"]["local"]["tasa"]), ("CLP", 950.0))
        self.assertIn("medidores", r["datos"])

    def test_panel_local_rechaza_lo_que_no_es_una_moneda(self):
        r = correr("panel.py", "local", entrada={"moneda": "no es una moneda", "tasa": 950}, datos=self.datos)
        self.assertEqual((r["ok"], r["error"]), (False, "moneda"))

    def test_panel_local_rechaza_una_tasa_que_no_es_un_numero(self):
        r = panel.local({"tasa": "mil"}, ahora_ms=AHORA)
        self.assertEqual((r["ok"], r["error"]), (False, "tasa"))


if __name__ == "__main__":
    unittest.main()
