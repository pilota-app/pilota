#!/usr/bin/env python3
"""lib_calibracion — la calibración del puntaje: el año apartado, los pesos por ventanas y la prueba final. Solo
biblioteca estándar.

Es el cuarto y el quinto paso del orden de la calibración (los tres primeros son el backtest de señales crudas, la
compuerta de casos y los tramos de puntaje). No toca la red: recorre el historial que ya está guardado.

Lo que hace, y el orden importa:

1. **Se aparta el último año** (`apartar`). Antes de mover un solo peso, los últimos `DIAS_APARTADOS` días quedan
   afuera y nadie los toca: son los que después van a decir si esto sirve o no.
2. **Una sola pasada por el historial** (`recorrido`): las mismas cuatro series de entrada del backtest, con el mismo
   empalme, el mismo modelo de spread, el mismo no llenado condicionado y los mismos costos de cada lado, puntuando
   cada señal cruda **antes** de seguirla (`lib_puntaje.de_velas` + `lib_puntaje.seguir`). Las **notas** de las siete
   familias viajan con cada operación, así que probar otros pesos no vuelve a recorrer nada: el puntaje es un promedio
   pesado de notas que ya están calculadas (`puntaje_con`).
3. **Los pesos, por ventanas** (`ventanas_de`, `ajustar`): `MESES_AJUSTAR` meses para ajustar y los `MESES_PROBAR`
   siguientes para probar, corriéndose de `MESES_PROBAR` en `MESES_PROBAR` meses y siempre antes del año apartado. Un
   peso se mueve solo si de verdad mejora, y se dan como máximo `VUELTAS_MAXIMAS` vueltas: el reporte dice cuántas.
4. **El backtest de nuevo, con puntaje y exigencia** (`correr_con`), por el gancho de siempre
   (`backtest.correr(filtrar=…)`): el recorrido no se escribe dos veces.
5. **La prueba final, una sola vez** (`aprobar`), con el año apartado y el criterio escrito **antes** (`criterio`).

Lo que no se negocia:
- **El año apartado no se mira hasta la prueba final.** Los pesos y la exigencia salen de las ventanas de antes del
  corte; una operación cuenta en la ventana en que se **decidió** (`senal_ms`), aunque haya cerrado después.
- **La prueba final se gasta una sola vez.** Queda escrita con su ventana (`prueba_final.ventana`) y no se repite: para
  volver a probar hace falta un tramo intacto de al menos `DIAS_PRUEBA_NUEVA` días **después** del que ya se usó. Si no
  lo hay, el modelo queda «No validado» con el motivo `prueba_repetida`: una prueba final sobre datos ya vistos no es
  una prueba final.
- **Si no aprueba, el modelo queda «No validado»**: exigencia `EXIGENCIA_NO_VALIDADO` (85) y los montos topados en
  `TOPE_NO_VALIDADO` USDT (lo lee el tamaño de la operación, en su paso). Los pesos ajustados se quedan —el reporte
  dice con cuáles quedó—, pero nada de lo que prometen está probado.
- **El plan B de la compuerta manda.** Si el backtest de señales crudas tuvo que ensanchar sus tramos, el modelo no
  puede quedar validado, pase lo que pase en la prueba final.
- **El criterio está escrito antes de ver un resultado** (`criterio`, `CRITERIO_*`), y se revisa entero en el reporte
  (`aprobacion.revisiones`): cuántos casos pide, que deje algo después de costos, que le gane a quedarse en USDT y que
  su caída máxima no llegue al piso de los frenos.
- **Ganarle a comprar BTC y esperar no es el criterio.** El reporte lo compara siempre (`referencias.btc`), pero una
  posición larga en BTC tiene caídas que los frenos de Pilota no dejarían pasar: la vara es quedarse en USDT.
- **Sin backtest de señales crudas no se calibra nada** (`sin_backtest`): la compuerta de casos va antes.
- **Nunca se mira el futuro.** El recorrido es el del backtest: la señal se decide con la vela cerrada, la orden se
  puede llenar recién en la siguiente y una vela que tocó el stop y el objetivo se cuenta como stop
  (`lib_resolucion.SUPUESTO_SIN_1M`, validado contra los días que sí tienen velas de 1 m).

Dónde queda: `<datos>/mercado/calibracion.json` (lo que devuelve `calibrar()`). Es lo que leen el puntaje
(`lib_puntaje.estado(calibracion=…)`), y el tamaño y los frenos en sus pasos (`modelo()`).
"""
import math
import os

import backtest
import lib_costos
import lib_datos
import lib_estrategias
import lib_indicadores
import lib_indicadores_mercado
import lib_puntaje
import nucleo

#: El año que se aparta antes de calibrar: nadie lo mira hasta la prueba final.
DIAS_APARTADOS = 365
#: Cuántos días intactos hacen falta, después de la ventana que ya se usó, para que una prueba final sea otra prueba
#: final y no la misma dos veces.
DIAS_PRUEBA_NUEVA = 90
#: Las ventanas de la calibración: 12 meses para ajustar los pesos y los 3 siguientes para probarlos. Un mes acá son
#: `DIAS_MES` días: los meses de calendario no existen en milisegundos y la ventana tiene que ser siempre la misma.
MESES_AJUSTAR, MESES_PROBAR, DIAS_MES = 12, 3, 30
MES_MS = DIAS_MES * lib_datos.DIA_MS
#: Cuántas vueltas de ajuste como máximo. Más vueltas sobre las mismas ventanas no es aprender: es memorizarlas.
VUELTAS_MAXIMAS = 3
#: Cuántas ventanas se usan como máximo, las más nuevas: lo de hace tres años pesa menos que lo del año pasado.
VENTANAS_MAXIMAS = 6
#: Los pesos que se le prueban a cada familia, escritos antes de ver un resultado (el de partida, 1,0, está entre
#: ellos: así un peso se queda quieto cuando moverlo no mejora nada).
PESOS_CANDIDATOS = (0.0, 0.5, 1.0, 1.5, 2.0)
#: Las exigencias que se prueban: el corte de puntaje para entrar, de 5 en 5 puntos.
EXIGENCIAS = (50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0, 85.0, 90.0)
#: Menos casos que estos en una ventana no son una medición: con cuatro operaciones, el mejor peso es el que tuvo
#: suerte. Es el mismo mínimo con el que el puntaje se atreve a mostrar una probabilidad.
CASOS_VENTANA = lib_puntaje.CASOS_PROBABILIDAD
#: Cuánto tiene que mejorar algo para que cuente como mejora (y no como ruido de la última cifra).
MEJORA_MINIMA = 1e-9
#: Los dos estados que puede dejar la calibración. Sin calibración, el del puntaje (`lib_puntaje.MODELO_SIN_CALIBRAR`).
VALIDADO, NO_VALIDADO = "validado", "no_validado"
#: Mientras el modelo no esté validado: la exigencia alta del puntaje y el monto por posición topado en estos USDT (lo
#: lee el tamaño de la operación, en su paso). Nada de lo que el modelo promete está probado todavía.
EXIGENCIA_NO_VALIDADO = lib_puntaje.EXIGENCIA_SIN_CALIBRAR
TOPE_NO_VALIDADO = 15.0
#: El criterio de aprobación de la prueba final, escrito **antes** de correrla: casos que no se pisen, que deje algo
#: después de costos, que le gane a quedarse en USDT y que su caída máxima no llegue al piso de los frenos (−25 %).
CRITERIO_CASOS = CASOS_VENTANA
CRITERIO_NETO = 0.0
CRITERIO_USDT = 0.0
CRITERIO_CAIDA = 0.25
#: Qué código se muestra cuando una revisión del criterio no pasa.
MOTIVOS_CRITERIO = {"casos": "pocos_casos", "neto": "no_deja_nada", "usdt": "no_gana_a_usdt",
                    "caida": "caida_grande", "plan": "plan_b", "nueva": "prueba_repetida"}


def ruta_calibracion():
    return os.path.join(lib_datos.carpeta_mercado(), "calibracion.json")


def criterio():
    """El criterio de aprobación de la prueba final, escrito antes de verla. Se guarda con el reporte para que se pueda
    revisar que es el mismo con el que se aprobó (o no)."""
    return {"casos": CRITERIO_CASOS, "neto_medio": CRITERIO_NETO, "rendimiento": CRITERIO_USDT,
            "caida_maxima": CRITERIO_CAIDA, "plan": "normal", "una_vez": True}


def parametros():
    """Con qué números se calibra: los lee la pantalla y quedan en el reporte."""
    return {"dias_apartados": DIAS_APARTADOS, "dias_prueba_nueva": DIAS_PRUEBA_NUEVA,
            "meses_ajustar": MESES_AJUSTAR, "meses_probar": MESES_PROBAR, "dias_mes": DIAS_MES,
            "vueltas_maximas": VUELTAS_MAXIMAS, "ventanas_maximas": VENTANAS_MAXIMAS,
            "pesos_candidatos": list(PESOS_CANDIDATOS), "exigencias": list(EXIGENCIAS),
            "casos_ventana": CASOS_VENTANA, "exigencia_no_validado": EXIGENCIA_NO_VALIDADO,
            "tope_no_validado": TOPE_NO_VALIDADO, "pesos_base": dict(lib_puntaje.PESOS_BASE),
            "criterio": criterio()}


# ── 1. El año apartado y las ventanas ───────────────────────────────────────────────────────────────────────────────────────

def tramo(desde, hasta):
    """Un trozo de tiempo, con sus fechas en palabras y cuántos días son. El borde de abajo entra y el de arriba no,
    igual que en los tramos de puntaje."""
    dias = ((int(hasta) - int(desde)) // lib_datos.DIA_MS) if (desde is not None and hasta is not None) else 0
    return {"desde": desde, "hasta": hasta, "iso_desde": lib_datos.iso(desde) if desde is not None else "",
            "iso_hasta": lib_datos.iso(hasta) if hasta is not None else "", "dias": max(0, dias)}


def apartar(ventana, usada=None):
    """El tramo que nadie toca hasta la prueba final.

    La primera vez son los últimos `DIAS_APARTADOS` días del historial, y para eso el historial tiene que alcanzar
    también para las ventanas de ajustar y probar (si no, `falta_historia` y no se calibra nada).

    Si ya se hizo una prueba final (`usada`, con su `hasta`), el tramo apartado es lo que vino **después**: una prueba
    final sobre datos que el modelo ya vio no prueba nada. Mientras ese tramo nuevo no llegue a `DIAS_PRUEBA_NUEVA`
    días, no hay prueba final que hacer (`prueba_repetida`) y el modelo no puede quedar validado."""
    inicio, fin = (ventana or {}).get("desde"), (ventana or {}).get("hasta")
    minimo = DIAS_APARTADOS + (MESES_AJUSTAR + MESES_PROBAR) * DIAS_MES
    if inicio is None or fin is None:
        return {**tramo(None, None), "nueva": False, "repetida": False, "dias_minimos": minimo,
                "faltan_dias": minimo, "motivo": "falta_historia"}
    antes = (usada or {}).get("hasta")
    if antes:
        desde = max(int(antes), int(inicio))
        t = tramo(desde, fin)
        if t["dias"] >= DIAS_PRUEBA_NUEVA:
            return {**t, "nueva": True, "repetida": False, "dias_minimos": DIAS_PRUEBA_NUEVA, "faltan_dias": 0,
                    "motivo": ""}
        return {**t, "nueva": False, "repetida": True, "dias_minimos": DIAS_PRUEBA_NUEVA,
                "faltan_dias": DIAS_PRUEBA_NUEVA - t["dias"], "motivo": "prueba_repetida"}
    todos = (int(fin) - int(inicio)) // lib_datos.DIA_MS
    t = tramo(int(fin) - DIAS_APARTADOS * lib_datos.DIA_MS, fin)
    if todos < minimo:
        return {**t, "nueva": False, "repetida": False, "dias_minimos": minimo, "faltan_dias": minimo - todos,
                "motivo": "falta_historia"}
    return {**t, "nueva": True, "repetida": False, "dias_minimos": minimo, "faltan_dias": 0, "motivo": ""}


def ventanas_de(desde, corte):
    """Las ventanas con las que se ajustan los pesos, de la más vieja a la más nueva: `MESES_AJUSTAR` meses para
    ajustar y los `MESES_PROBAR` siguientes para probar, corriéndose de `MESES_PROBAR` en `MESES_PROBAR` meses y
    siempre enteras antes de `corte` (el día en que empieza el tramo apartado). De las que salgan se usan las últimas
    `VENTANAS_MAXIMAS`."""
    if desde is None or corte is None:
        return []
    largo_a, largo_p = MESES_AJUSTAR * MES_MS, MESES_PROBAR * MES_MS
    salida, ini = [], int(desde)
    while ini + largo_a + largo_p <= int(corte):
        salida.append({"n": 0, "ajustar": tramo(ini, ini + largo_a),
                       "probar": tramo(ini + largo_a, ini + largo_a + largo_p)})
        ini += largo_p
    salida = salida[-VENTANAS_MAXIMAS:]
    for i, v in enumerate(salida):
        v["n"] = i + 1
    return salida


def pools(ops, ventanas):
    """Las operaciones que ve el ajuste y las que ve la prueba de cada vuelta, repartidas por la ventana en que se
    **decidió** la señal (`senal_ms`): una operación decidida en los meses de ajustar es de ajustar, aunque haya
    cerrado después. Las del tramo apartado no están en ninguna de las dos: ese tramo no se toca."""
    cerradas = [o for o in ops or [] if not o.get("motivo") and o.get("permitida") and o.get("neto") is not None]

    def dentro(o, cual):
        return any(v[cual]["desde"] <= o["senal_ms"] < v[cual]["hasta"] for v in ventanas or [])

    return [o for o in cerradas if dentro(o, "ajustar")], [o for o in cerradas if dentro(o, "probar")]


# ── 2. El puntaje con otros pesos, sin volver a mirar las velas ─────────────────────────────────────────────────────────────

def notas_de(familias):
    """Las siete notas de una señal ya puntuada, sueltas: `{familia: nota}` (con `None` donde la familia no tenía su
    número). Es lo único que la calibración necesita de una señal para volver a puntuarla con otros pesos."""
    return {f.get("familia"): f.get("nota") for f in familias or [] if f.get("familia")}


def puntaje_con(notas, pesos):
    """El puntaje de 0 a 100 de una oportunidad con estos pesos, sobre notas **ya calculadas**.

    Es la misma regla de `lib_puntaje.puntaje_de` —sin una familia clave no hay puntaje, y sin una de las otras cuatro
    los pesos se renormalizan entre las que sí tienen dato— aplicada a las notas que dejó el recorrido, sin volver a
    mirar un solo indicador: así probar cientos de combinaciones de pesos no cuesta cientos de recorridos."""
    if not notas:
        return None
    if any(notas.get(f) is None for f in lib_puntaje.FAMILIAS_CLAVE):
        return None
    presentes = [(f, notas[f], float((pesos or {}).get(f, 0.0) or 0.0))
                 for f in lib_puntaje.FAMILIAS if notas.get(f) is not None]
    total = math.fsum(p for _, _, p in presentes)
    if total <= 0:
        return None
    return math.fsum(nota * (peso / total) for _, nota, peso in presentes)


def clave_de(senal):
    """Con qué se encuentra una señal en la tabla de notas del recorrido: su estrategia, su par, su temporalidad y la
    vela en que se decidió. En una vela, una estrategia da una señal o ninguna."""
    return (senal.get("estrategia"), senal.get("par"), senal.get("temporalidad"), senal.get("vela"))


# ── 3. Una sola pasada por el historial ─────────────────────────────────────────────────────────────────────────────────────

def recorrido(ahora_ms=None, factor=None):
    """El historial recorrido una sola vez, con las notas de cada señal pegadas a su operación.

    Es el mismo recorrido de `lib_puntaje.medir` (las cuatro series de entrada empalmadas, el mismo modelo de costos y
    la regla de las velas sin 1 m en `lib_resolucion`), con lo que la calibración necesita además: la tabla de notas
    (`tabla`, por `clave_de`) para volver a puntuar cualquier señal con otros pesos y las operaciones con sus notas.

    Las operaciones **no** se guardan en disco: lo que queda escrito son los números del reporte."""
    ahora = ahora_ms or lib_datos.ahora_local_ms()
    com, costos = lib_costos.comisiones(), lib_costos.modelo()
    principal = lib_costos.PENETRACION_SPREADS if factor is None else float(factor)
    motivos, empalmes, filas, ops, tabla = [], [], [], [], {}
    btc = lib_datos.leer_serie(lib_indicadores_mercado.CONTEXTO_PAR, lib_estrategias.TEMPORALIDAD_DIARIA)
    hay_btc = len(btc) >= backtest.VELAS_MINIMAS
    filtro = lib_estrategias.filtro_en(btc) if hay_btc else None
    contexto_btc = lib_estrategias.contexto_en(btc) if hay_btc else None
    if not hay_btc:   # sin el contexto de BTC ninguna señal queda puntuada: no hay nada que calibrar
        motivos.append({"codigo": "sin_contexto", "par": lib_indicadores_mercado.CONTEXTO_PAR,
                        "temporalidad": lib_estrategias.TEMPORALIDAD_DIARIA, "n": backtest.VELAS_MINIMAS - len(btc)})
    for par in lib_datos.PARES_OPERADOS:
        diario = lib_estrategias.PAR_DIARIO[par]
        velas_dia = lib_datos.leer_serie(diario, lib_estrategias.TEMPORALIDAD_DIARIA)
        al_alza = lib_estrategias.al_alza_en(velas_dia) if len(velas_dia) >= backtest.VELAS_MINIMAS else None
        if al_alza is None:
            motivos.append({"codigo": "sin_tendencia_diaria", "par": diario,
                            "temporalidad": lib_estrategias.TEMPORALIDAD_DIARIA,
                            "n": backtest.VELAS_MINIMAS - len(velas_dia)})
        for temporalidad in lib_estrategias.TEMPORALIDADES_SENAL:
            velas, empalme = backtest.empalmar(par, temporalidad)
            empalmes.append(empalme)
            fila = {"par": par, "temporalidad": temporalidad, "velas": empalme["velas"], "motivo": empalme["motivo"],
                    "faltan": empalme["faltan"], "empalmada": empalme["empalmada"], "prestadas": empalme["prestadas"],
                    "senales": 0, "puntuadas": 0, "operaciones": 0}
            if empalme["motivo"]:
                motivos.append({"codigo": empalme["motivo"], "par": par, "temporalidad": temporalidad,
                                "n": empalme["faltan"]})
                filas.append(fila)
                continue
            spread = lib_costos.spread_de(costos, par)
            puntuadas = lib_puntaje.de_velas(par, temporalidad, velas, al_alza=al_alza, filtro=filtro,
                                             contexto_btc=contexto_btc, spread=spread, com=com)
            # El calentamiento no da operaciones, igual que en el backtest: ahí el ATR y el ADX todavía arrastran.
            suyas = [(i, s) for i, fila_i in enumerate(puntuadas) for s in fila_i
                     if i >= lib_indicadores.VELAS_CALENTAMIENTO]
            cuantas = 0
            for i, s in suyas:
                notas = notas_de(s.get("familias"))
                tabla[clave_de(s)] = notas
                o = lib_puntaje.seguir(velas, i, s, spread, com, principal)
                ops.append({**o, "notas": notas})
                cuantas += 0 if o["motivo"] else 1
            fila.update(senales=len(suyas), operaciones=cuantas,
                        puntuadas=sum(1 for _, s in suyas if s.get("puntaje") is not None))
            filas.append(fila)
    return {"ahora": ahora, "cuando": lib_datos.iso(ahora), "ops": ops, "tabla": tabla,
            "ventana": backtest.ventana_de(empalmes), "series": filas, "empalmes": empalmes, "comisiones": com,
            "modelo": costos, "penetracion": principal, "motivos": motivos, "listo": not motivos}


# ── 4. Qué dio un puntaje con una exigencia ─────────────────────────────────────────────────────────────────────────────────

def puntuar(ops, pesos):
    """Las operaciones con el puntaje que tendrían con estos pesos. Se calcula una vez y sirve para todas las
    exigencias: la exigencia solo saca señales, no cambia lo que les pasó a las que quedan."""
    return [(puntaje_con(o.get("notas"), pesos), o) for o in ops or []]


def medida_vacia(exigencia=EXIGENCIA_NO_VALIDADO):
    """Lo que se ve cuando no hay ninguna operación: ceros y ningún promedio inventado."""
    return {"exigencia": float(exigencia), "operaciones": 0, "casos": 0, "aciertos": None, "neto_medio": None,
            "rendimiento": 0.0, "caida_maxima": 0.0, "objetivo": None, "pocos": True,
            "casos_minimos": CASOS_VENTANA}


def medir_puntuadas(puntuadas, exigencia):
    """Qué dieron las operaciones que llegan a esta exigencia: cuántas son, cuántos **casos** (las que no se pisan
    entre sí, `backtest.sin_solapar`), con qué frecuencia ganaron, lo que dejaron después de costos y la curva.

    `objetivo` es con lo que se elige, y es la ganancia media por operación después de costos —no el rendimiento
    compuesto, que premia operar mucho—: sin `CASOS_VENTANA` casos no hay objetivo, porque no hay medición."""
    suyas = [o for p, o in puntuadas if p is not None and p >= exigencia]
    r = backtest.resumen(suyas)
    casos = backtest.sin_solapar(suyas)
    bastan = casos >= CASOS_VENTANA and bool(r["operaciones"])
    return {"exigencia": float(exigencia), "operaciones": r["operaciones"], "casos": casos,
            "aciertos": r["aciertos"], "neto_medio": r["neto_medio"], "rendimiento": r["rendimiento"],
            "caida_maxima": r["caida_maxima"], "objetivo": r["neto_medio"] if bastan else None,
            "pocos": not bastan, "casos_minimos": CASOS_VENTANA}


def evaluar(ops, pesos, exigencia):
    """Qué dieron estas operaciones con estos pesos y esta exigencia."""
    return medir_puntuadas(puntuar(ops, pesos), exigencia)


def valor(medida):
    """Con qué se comparan dos medidas. Una sin casos no compite: no es peor, es que no se midió."""
    return medida["objetivo"] if (medida or {}).get("objetivo") is not None else float("-inf")


def mejor(opciones):
    """La mejor de varias medidas: la que más deja por operación después de costos entre las que tienen casos de sobra
    y, a igualdad, la que tiene más casos (más evidencia). Si ninguna tiene casos, la de más casos: así se elige algo
    deterministamente en vez de la primera que pasó por ahí."""
    con_casos = [d for d in opciones if d["objetivo"] is not None]
    if con_casos:
        return max(con_casos, key=lambda d: (d["objetivo"], d["casos"]))
    return max(opciones, key=lambda d: (d["casos"], -d["exigencia"]))


def mejor_exigencia(ops, pesos):
    """La exigencia que más deja con estos pesos, de las de `EXIGENCIAS`. El puntaje de cada operación se calcula una
    sola vez para todas."""
    puntuadas = puntuar(ops, pesos)
    return mejor([medir_puntuadas(puntuadas, e) for e in EXIGENCIAS])


# ── 5. Los pesos, ajustados por ventanas y con las vueltas contadas ─────────────────────────────────────────────────────────

def sin_ajuste(motivo="sin_calibracion"):
    """Lo que se ve cuando no se ajustó nada: los pesos de partida y la exigencia alta, con su motivo."""
    return {"cuantas": 0, "maximas": VUELTAS_MAXIMAS, "pesos": dict(lib_puntaje.PESOS_BASE),
            "exigencia": EXIGENCIA_NO_VALIDADO, "operaciones": 0, "casos": 0, "vueltas": [], "motivo": motivo}


def ajustar(ajuste_ops, prueba_ops, pesos=None):
    """Los pesos de las siete familias y la exigencia, ajustados sobre las ventanas de ajustar y elegidos con las de
    probar.

    Cada vuelta recorre las familias en su orden y a cada una le prueba los pesos de `PESOS_CANDIDATOS` (con el que
    tiene puesto entre ellos), quedándose con la exigencia que más deja en cada caso. Un peso se mueve **solo si
    mejora de verdad** (`MEJORA_MINIMA`): si moverlo no cambia nada, se queda donde estaba, y así no se elige un peso
    al azar entre empates. Después la vuelta se mide en las ventanas de probar, que son las que eligen: de las
    `VUELTAS_MAXIMAS` vueltas queda la que mejor le fue ahí, y si una vuelta no mejora a la anterior no se da otra
    —más vueltas sobre las mismas ventanas no es aprender, es memorizarlas—."""
    actuales = dict(pesos or lib_puntaje.PESOS_BASE)
    vueltas = []
    for n in range(1, VUELTAS_MAXIMAS + 1):
        cambios = []
        for f in lib_puntaje.FAMILIAS:
            candidatos = sorted({*PESOS_CANDIDATOS, float(actuales.get(f, 0.0) or 0.0)})
            opciones = [{**mejor_exigencia(ajuste_ops, {**actuales, f: peso}), "peso": peso} for peso in candidatos]
            elegida = mejor(opciones)
            puesta = next(d for d in opciones if d["peso"] == float(actuales.get(f, 0.0) or 0.0))
            if valor(elegida) <= valor(puesta) + MEJORA_MINIMA:
                continue                      # moverlo no mejora nada: el peso se queda como estaba
            cambios.append({"familia": f, "antes": float(actuales.get(f, 0.0) or 0.0), "ahora": elegida["peso"]})
            actuales[f] = elegida["peso"]
        en_ajuste = mejor_exigencia(ajuste_ops, actuales)
        en_prueba = evaluar(prueba_ops, actuales, en_ajuste["exigencia"])
        vueltas.append({"n": n, "pesos": dict(actuales), "exigencia": en_ajuste["exigencia"], "cambios": cambios,
                        "ajuste": en_ajuste, "prueba": en_prueba})
        if not cambios:
            break                             # nada se movió: otra vuelta daría exactamente lo mismo
        if len(vueltas) > 1 and valor(en_prueba) <= valor(vueltas[-2]["prueba"]) + MEJORA_MINIMA:
            break                             # esta vuelta no mejoró en las ventanas de probar
    elegida = max(vueltas, key=lambda v: (valor(v["prueba"]), v["prueba"]["casos"], -v["n"]))
    return {"cuantas": len(vueltas), "maximas": VUELTAS_MAXIMAS, "pesos": dict(elegida["pesos"]),
            "exigencia": elegida["exigencia"], "elegida": elegida["n"], "operaciones": len(ajuste_ops),
            "casos": backtest.sin_solapar(ajuste_ops), "vueltas": vueltas, "motivo": ""}


# ── 6. El backtest de nuevo, con puntaje y exigencia, por el gancho de siempre ──────────────────────────────────────────────

def gancho(tabla, pesos, exigencia, desde, hasta):
    """El `filtrar` de `backtest.correr`: deja pasar solo las señales de este tramo que llegan a la exigencia. Una
    señal sin puntaje (le faltaba una familia clave) no llega a ninguna exigencia: no se entra a ciegas."""
    def filtrar(senal):
        cuando = senal.get("vela")
        if cuando is None or not (desde <= cuando < hasta):
            return False
        p = puntaje_con(tabla.get(clave_de(senal)), pesos)
        return p is not None and p >= exigencia
    return filtrar


def compuerta_corta(reporte):
    """La compuerta de un reporte, sin los tres niveles enteros: el plan que salió y si fue plan B."""
    c = (reporte or {}).get("compuerta") or {}
    return {"casos_minimos": c.get("casos_minimos") or backtest.CASOS_MINIMOS,
            "operaciones": c.get("operaciones") or 0, "plan": c.get("plan") or "insuficiente",
            "plan_b": bool(c.get("plan_b", True)), "no_validado": bool(c.get("no_validado", True)),
            "tramos": c.get("tramos") or [], "listo": bool(c.get("listo"))}


def compuerta_de(reporte):
    """La compuerta del backtest de señales crudas guardado: la que manda. Si tuvo que ensanchar sus tramos (plan B),
    el modelo no puede quedar validado, y si no se corrió todavía no hay nada que calibrar."""
    return {"corrido": bool((reporte or {}).get("corrido")), "cuando": (reporte or {}).get("cuando") or "",
            **compuerta_corta(reporte)}


def comprar_btc(t, costos, com):
    """Comprar BTC al principio de este tramo y esperar hasta el final, con los costos de entrar y salir. Es la otra
    comparación que el reporte no puede esconder, al lado de quedarse en USDT."""
    velas, _ = backtest.empalmar(lib_datos.PARES_OPERADOS[0], lib_estrategias.TEMPORALIDAD_DIARIA)
    suyas = [v for v in velas if t["desde"] is not None and t["desde"] <= v[0] < t["hasta"]]
    return backtest.comprar_y_esperar(suyas, lib_costos.spread_de(costos, lib_datos.PARES_OPERADOS[0]), com)


def sin_reporte(exigencia=EXIGENCIA_NO_VALIDADO, motivo="sin_calibracion"):
    """Un reporte que no se corrió: los ceros y las dos comparaciones, sin ningún número inventado."""
    return {"corrido": False, "cuando": "", "ventana": tramo(None, None), "exigencia": float(exigencia),
            "resumen": backtest.resumen([]), "medida": medida_vacia(exigencia), "compuerta": compuerta_corta({}),
            "referencias": {"usdt": backtest.quedarse_en_usdt(),
                            "btc": backtest.comprar_y_esperar([], lib_costos.SPREAD_SUPUESTO,
                                                              lib_costos.comisiones())},
            "series": [], "motivos": [], "motivo": motivo}


def sin_prueba(motivo="sin_calibracion"):
    """La prueba final que no se hizo —todavía, o porque sería la misma dos veces—: sin ningún número y con su
    motivo."""
    return {**sin_reporte(motivo=motivo), "hecha": False}


def correr_con(pesos, exigencia, t, r, ahora_ms=None):
    """El backtest de nuevo, con el puntaje y la exigencia puestos, sobre el tramo `t`.

    La exigencia entra por el gancho de siempre (`backtest.correr(filtrar=…)`): el recorrido no se escribe dos veces.
    La prueba de sensibilidad no se repite acá (ya la hizo el backtest de señales crudas) y las dos comparaciones se
    miden en **este** tramo, no en todo el historial.

    `medida` es lo mismo, mirado desde las operaciones del recorrido (`r["ops"]`): filtrar por la exigencia después es
    igual que filtrar antes, porque el backtest no es una cartera —una operación no depende de las otras—, y de ahí
    salen los casos que no se pisan, que el reporte del backtest no cuenta en total."""
    filtrar = gancho(r["tabla"], pesos, exigencia, t["desde"], t["hasta"])
    d = backtest.correr(ahora_ms or r.get("ahora"), factor=r.get("penetracion"), filtrar=filtrar, sensibilidad=False)
    suyas = [o for o in r["ops"] if not o["motivo"] and o["permitida"] and o["neto"] is not None
             and t["desde"] <= o["senal_ms"] < t["hasta"]]
    return {"corrido": True, "cuando": d["cuando"], "ventana": t, "exigencia": float(exigencia),
            "resumen": d["resumen"], "medida": evaluar(suyas, pesos, exigencia),
            "compuerta": compuerta_corta(d),
            "referencias": {"usdt": backtest.quedarse_en_usdt(),
                            "btc": comprar_btc(t, r["modelo"], r["comisiones"])},
            "series": d["series"], "supuestos": d["supuestos"], "motivos": d["motivos"], "motivo": ""}


# ── 7. La prueba final: una sola vez, con el criterio escrito antes ─────────────────────────────────────────────────────────

def aprobar(medida, plan="insuficiente", nueva=False):
    """Si la prueba final aprueba, revisión por revisión y contra el criterio escrito **antes** de correrla
    (`criterio`): casos que no se pisen, que deje algo después de costos, que le gane a quedarse en USDT, que su caída
    máxima no llegue al piso de los frenos, que la compuerta no haya tenido que usar el plan B y que esta prueba sea de
    verdad la primera sobre este tramo.

    Todas las revisiones quedan en el reporte, también las que pasaron: una aprobación que no se puede revisar no es
    una aprobación."""
    m = medida or medida_vacia()
    revisiones = [
        {"que": "casos", "pide": CRITERIO_CASOS, "hay": m["casos"], "pasa": m["casos"] >= CRITERIO_CASOS},
        {"que": "neto", "pide": CRITERIO_NETO, "hay": m["neto_medio"],
         "pasa": (m["neto_medio"] or 0.0) > CRITERIO_NETO},
        {"que": "usdt", "pide": CRITERIO_USDT, "hay": m["rendimiento"],
         "pasa": (m["rendimiento"] or 0.0) > CRITERIO_USDT},
        {"que": "caida", "pide": CRITERIO_CAIDA, "hay": m["caida_maxima"],
         "pasa": (m["caida_maxima"] or 0.0) <= CRITERIO_CAIDA},
        {"que": "plan", "pide": "normal", "hay": plan, "pasa": plan == "normal"},
        {"que": "nueva", "pide": True, "hay": bool(nueva), "pasa": bool(nueva)},
    ]
    falla = next((x["que"] for x in revisiones if not x["pasa"]), "")
    return {"criterio": criterio(), "revisiones": revisiones, "aprobado": not falla,
            "motivo": MOTIVOS_CRITERIO.get(falla, "") if falla else ""}


# ── 8. La calibración completa ──────────────────────────────────────────────────────────────────────────────────────────────

def supuestos(r, reporte=None):
    """Los supuestos que arrastra la calibración, marcados: la regla de las velas sin 1 m con su validación, de dónde
    salió el spread, si hubo empalme y que esto ya **no** es sin exigencia (es el backtest con puntaje y con corte)."""
    s = (reporte or {}).get("supuestos") or {}
    return {"sin_1m": backtest.SUPUESTO_AMBIGUO, "dias_1m": lib_datos.DIAS_MINUTOS,
            "ambiguas": s.get("ambiguas") or backtest.validar_ambiguas([], {}),
            "spread": ((r or {}).get("modelo") or {}).get("origen") or "",
            "empalme": any(e["empalmada"] for e in (r or {}).get("empalmes") or []),
            "sin_exigencia": False, "calentamiento": lib_indicadores.VELAS_CALENTAMIENTO}


def calibrar(ahora_ms=None, factor=None, recorrida=None, reporte=None, anterior=None):
    """La calibración entera, en el orden que manda: apartar el tramo que nadie toca, recorrer el historial una vez,
    ajustar los pesos por ventanas con sus vueltas contadas, volver a correr el backtest con puntaje y exigencia y
    hacer la prueba final una sola vez con el tramo apartado.

    Lo que devuelve es el estado del modelo («Validado», o «No validado» con la exigencia alta y los montos topados) y
    el reporte con el que se llegó a él, incluido el criterio con el que se aprobó o no. `recorrida`, `reporte` y
    `anterior` se pueden pasar ya listos (el recorrido del historial, el backtest de señales crudas guardado y la
    calibración anterior): es por donde entran las pruebas, sin recorrer nada dos veces."""
    r = recorrido(ahora_ms, factor) if recorrida is None else recorrida
    ahora = r.get("ahora") or (ahora_ms or lib_datos.ahora_local_ms())
    bt = backtest.guardado() if reporte is None else reporte
    previa = guardada() if anterior is None else anterior
    puerta = compuerta_de(bt)
    usada = previa.get("prueba_final") or {}
    # Lo que `apartar` necesita de la prueba final anterior es **su ventana**: hasta dónde llegaron los datos que el
    # modelo ya vio. Pasarle la prueba entera sería no mirar nada (no tiene `hasta`) y gastarla de nuevo con el mismo año.
    apartado = apartar(r["ventana"], (usada.get("ventana") or {}) if usada.get("hecha") else None)
    ventanas = ventanas_de((r["ventana"] or {}).get("desde"), apartado["desde"]) if apartado["desde"] else []
    ajuste_ops, prueba_ops = pools(r["ops"], ventanas)
    casos = backtest.sin_solapar(ajuste_ops)
    motivos = list(r["motivos"])
    estorbo = ""
    if not puerta["corrido"]:
        estorbo = "sin_backtest"              # la compuerta de casos va antes de calibrar
    elif not ventanas:
        estorbo = "falta_historia"
    elif casos < CASOS_VENTANA:
        estorbo = "pocos_casos"
    if estorbo:
        motivos.append({"codigo": estorbo, "par": "", "temporalidad": "",
                        "n": (CASOS_VENTANA - casos) if estorbo == "pocos_casos" else apartado["faltan_dias"]})
    ajuste, rebacktest = sin_ajuste(estorbo or "sin_calibracion"), sin_reporte()
    final, ap = sin_prueba(estorbo or "sin_calibracion"), aprobar(None, puerta["plan"], apartado["nueva"])
    if not estorbo:
        ajuste = ajustar(ajuste_ops, prueba_ops)
        pesos_ajustados, exigencia_ajustada = ajuste["pesos"], ajuste["exigencia"]
        antes = tramo((r["ventana"] or {}).get("desde"), apartado["desde"])
        rebacktest = correr_con(pesos_ajustados, exigencia_ajustada, antes, r, ahora)
        if apartado["nueva"]:
            final = {**correr_con(pesos_ajustados, exigencia_ajustada, tramo(apartado["desde"], apartado["hasta"]),
                                  r, ahora), "hecha": True}
        else:
            final = sin_prueba(apartado["motivo"] or "prueba_repetida")
        ap = aprobar(final.get("medida"), puerta["plan"], apartado["nueva"])
    calibrado = not estorbo and math.fsum(ajuste["pesos"].values()) > 0
    aprobado = calibrado and ap["aprobado"]
    # Cuando no hubo prueba final que hacer, el motivo es ese y no el de la medida vacía («pocos casos»): lo que falta no
    # son casos, es un tramo que el modelo todavía no haya visto.
    razon = apartado["motivo"] if (not apartado["nueva"] and apartado["motivo"]) else ap["motivo"]
    de = "prueba_final" if final.get("corrido") else ("rebacktest" if rebacktest["corrido"] else "")
    fuente = final if de == "prueba_final" else rebacktest
    return {"formato": 1, "corrido": True, "cuando": lib_datos.iso(ahora),
            # El modelo: lo que leen el puntaje, el tamaño y los frenos
            "calibrado": calibrado,
            "estado": VALIDADO if aprobado else (NO_VALIDADO if calibrado else lib_puntaje.MODELO_SIN_CALIBRAR),
            "exigencia": ajuste["exigencia"] if aprobado else EXIGENCIA_NO_VALIDADO,
            "pesos": dict(ajuste["pesos"]) if calibrado else dict(lib_puntaje.PESOS_BASE),
            "tope": None if aprobado else TOPE_NO_VALIDADO, "topado": not aprobado,
            "motivo": "" if aprobado else (estorbo or razon or NO_VALIDADO),
            "familias": list(lib_puntaje.FAMILIAS),
            # Cómo se llegó a eso
            "ventana": r["ventana"], "apartado": apartado, "ventanas": ventanas, "compuerta": puerta,
            "ajuste": ajuste, "rebacktest": rebacktest, "prueba_final": final, "aprobacion": ap,
            "referencias": {"de": de, **fuente["referencias"]},
            "series": r["series"], "comisiones": r["comisiones"], "modelo_costos": r["modelo"],
            "supuestos": supuestos(r, final if final.get("corrido") else rebacktest),
            "parametros": parametros(), "motivos": motivos, "listo": not motivos}


def sin_calibrar():
    """Lo que se ve antes de calibrar: el modelo sin calibrar, con la exigencia alta y los montos topados, y ningún
    número inventado. Tiene la misma forma que lo que devuelve `calibrar`: la pantalla no adivina."""
    return {"formato": 1, "corrido": False, "cuando": "", "calibrado": False,
            "estado": lib_puntaje.MODELO_SIN_CALIBRAR, "exigencia": EXIGENCIA_NO_VALIDADO,
            "pesos": dict(lib_puntaje.PESOS_BASE), "tope": TOPE_NO_VALIDADO, "topado": True,
            "motivo": "sin_calibracion", "familias": list(lib_puntaje.FAMILIAS),
            "ventana": backtest.ventana_de([]), "apartado": apartar({}),
            "ventanas": [], "compuerta": compuerta_de({}), "ajuste": sin_ajuste(), "rebacktest": sin_reporte(),
            "prueba_final": sin_prueba(), "aprobacion": aprobar(None),
            "referencias": {"de": "", **sin_reporte()["referencias"]},
            "series": [], "comisiones": lib_costos.comisiones(), "modelo_costos": lib_costos.modelo(),
            "supuestos": supuestos({}), "parametros": parametros(), "motivos": [], "listo": False}


def guardada():
    """La última calibración o, si no hay ninguna, el modelo sin calibrar. Sin red y sin recorrer nada."""
    d = nucleo.leer_json(ruta_calibracion(), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    if isinstance(d, dict) and d.get("formato") == 1 and d.get("corrido") and isinstance(d.get("pesos"), dict):
        return d
    return sin_calibrar()


def escribir(d):
    """Deja escrita la calibración: la leen el puntaje, el tamaño y los frenos sin volver a calibrar nada."""
    nucleo.escribir_json(ruta_calibracion(), d)
    return d


def modelo(calibracion=None):
    """El modelo con el que se puntúa, para el puntaje, el tamaño y los frenos: lo que dice `lib_puntaje.modelo`
    (estado, pesos y exigencia) más el tope de monto mientras no esté validado."""
    c = guardada() if calibracion is None else (calibracion or {})
    m = lib_puntaje.modelo(c)
    validado = bool(m["calibrado"] and m["estado"] == VALIDADO)
    return {**m, "validado": validado, "tope": None if validado else TOPE_NO_VALIDADO, "topado": not validado,
            "corrido": bool(c.get("corrido"))}
