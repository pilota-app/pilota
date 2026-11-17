#!/usr/bin/env python3
"""backtest — el backtest de las señales crudas, sin exigencia. Solo biblioteca estándar.

  backtest.py estado <entrada.json {}> <salida.json>   → {ok, datos}
  backtest.py correr <entrada.json {}> <salida.json>   → {ok, datos}

No toca la red: recorre el historial que ya está guardado. Es el **primer** paso del orden de la calibración, y por eso va
sin exigencia: las señales crudas de las dos estrategias de entrada (`bin/lib_estrategias.py`), tal como salieron, con los
costos de cada lado y la conversión USDT↔FDUSD (`bin/lib_costos.py`), el no llenado condicionado y su prueba de
sensibilidad. El puntaje, la exigencia y el tamaño son de sus propios pasos: aquí se mide qué daban las reglas, no qué daría
Pilota.

Lo que hace, en orden:

1. **Empalme.** Donde el par contra FDUSD todavía no existía se usan las velas del par contra USDT del mismo activo (el que
   tiene años de historia) con los costos de FDUSD, y el reporte lo marca. Antes de recorrer, la regla de siempre:
   continuidad. Una serie vacía, corta o con hoyos no se recorre y dice qué le falta.
2. **El recorrido.** Cada señal pone su orden límite en su nivel y vive lo que dice su vigencia. Se llena cuando el precio
   **sigue en contra** (no cuando lo toca). Llenada, se la sigue vela por vela hasta el stop o el objetivo, y si una vela
   tocó los dos se supone lo malo: el stop primero (`SUPUESTO_AMBIGUO`). Ese supuesto se valida contra los 30 días que sí
   tienen velas de 1 m y queda marcado en el reporte con cuántas veces acertó.
3. **La compuerta.** Cuenta los casos por estrategia, par y temporalidad **sin contar dos veces los que se solapan** y, si
   un tramo no llega a `CASOS_MINIMOS`, aplica el plan B escrito antes de ver un resultado.
4. **El reporte.** Contra quedarse en USDT y contra comprar y esperar: rendimiento, caída máxima y operaciones.

Lo que no se negocia aquí:
- **Sin exigencia y sin tapar nada.** Este recorrido es el de las señales crudas; que la compuerta haya tenido que usar el
  plan B se dice (`compuerta.plan_b`), y la calibración, en su paso, tiene que dejar el modelo en «No validado».
- **Nunca se mira el futuro.** Las señales salen de `lib_estrategias.de_velas`, que decide con la vela cerrada, y la orden
  se puede llenar recién en la vela **siguiente**; la tendencia diaria y el filtro de BTC responden con la última vela de
  1 d cerrada antes de ese momento.
- **El calentamiento no cuenta.** Las primeras `lib_indicadores.VELAS_CALENTAMIENTO` velas de cada serie no dan
  operaciones: ahí el ATR y el ADX todavía arrastran de dónde empezó la serie.
- **Los costos se equivocan para el lado caro** (ver `bin/lib_costos.py`): spread supuesto hasta que haya datos propios,
  stop que cruza el libro y límite que solo se llena si el precio la atraviesa.
- **No es una cartera.** Las operaciones se solapan, no hay tope de posiciones ni tamaño (son sus propios pasos): la curva
  con la que se compara entra entera en cada operación y el reporte lo dice.

Dónde queda: `<datos>/mercado/backtest.json` (lo que devuelve `correr()`, con la hora del recorrido).
"""
import os

import lib_costos
import lib_datos
import lib_estrategias
import lib_indicadores
import lib_indicadores_mercado
import nucleo

#: Cuántos casos pide la compuerta en cada tramo antes de dejar calibrar (la idea completa: 300).
CASOS_MINIMOS = 300
#: Los tramos del plan B, escritos antes de ver un solo resultado: primero lo fino y, si no alcanza, más ancho.
NIVELES = (("normal", ("estrategia", "par", "temporalidad")), ("ancho", ("estrategia", "par")),
           ("unico", ("estrategia",)))
#: Las estrategias que entran (quedarse en USDT no abre ninguna operación: no tiene casos que contar).
ESTRATEGIAS_ENTRADA = tuple(e for e in lib_estrategias.ESTRATEGIAS if e != "usdt")
#: La misma ventana mínima que los indicadores: con menos velas, los suavizados todavía dependen de dónde empezó la serie.
VELAS_MINIMAS = lib_indicadores.VENTANA
#: Cuántas velas se le dan a una posición abierta antes de darla por no cerrada (no se cierra a la fuerza: no se cuenta).
VELAS_MAXIMAS = 500
#: Lo que se supone cuando una misma vela tocó el stop y el objetivo y no hay velas de 1 m para saber qué pasó primero.
SUPUESTO_AMBIGUO = "stop_primero"
#: Cuántas velas ambiguas se revisan contra las de 1 m (es una validación del supuesto, no el recorrido).
AMBIGUAS_MAXIMAS = 2000
#: Cuántas operaciones se guardan como ejemplo en el reporte: las últimas que cerraron.
OPERACIONES_GUARDADAS = 20
#: De qué par se piden prestadas las velas donde el par operado todavía no existía: el del mismo activo contra USDT.
PAR_PRESTADO = dict(lib_estrategias.PAR_DIARIO)


def ruta_backtest():
    return os.path.join(lib_datos.carpeta_mercado(), "backtest.json")


def parametros(penetracion=lib_costos.PENETRACION_SPREADS):
    """Con qué números se corrió: los de las estrategias y los del recorrido. Los mueve la calibración, en su paso."""
    return {**lib_estrategias.parametros(), "casos_minimos": CASOS_MINIMOS, "penetracion": penetracion,
            "velas_minimas": VELAS_MINIMAS, "velas_maximas": VELAS_MAXIMAS,
            "calentamiento": lib_indicadores.VELAS_CALENTAMIENTO, "supuesto_ambiguo": SUPUESTO_AMBIGUO}


# ── 1. El empalme: las velas con las que se recorre cada par ─────────────────────────────────────────────────────────────────

def empalmar(par, temporalidad):
    """Las velas de un par operado para el backtest, y de dónde salieron. Donde el par contra FDUSD todavía no existía se
    usan las del par contra USDT del mismo activo —el que tiene años de historia— con los costos de FDUSD, y eso se marca
    siempre (`empalmada`, `prestadas`, `corte`): los costos de los dos pares no son los mismos y el reporte no lo puede
    esconder.

    Y la regla de siempre antes de calcular: continuidad. Una serie vacía, con hoyos o más corta que `VELAS_MINIMAS` no se
    recorre y queda con su motivo (`sin_datos`, `huecos`, `faltan_velas`, los códigos que la pantalla ya traduce)."""
    prestado = PAR_PRESTADO.get(par, par)
    propias = lib_datos.leer_serie(par, temporalidad)
    ajenas = lib_datos.leer_serie(prestado, temporalidad) if prestado != par else []
    corte = propias[0][0] if propias else None
    prestadas = [v for v in ajenas if corte is None or v[0] < corte]
    velas = prestadas + propias
    hoyos = lib_datos.huecos(velas, temporalidad)
    motivo, faltan = "", 0
    if not velas:
        motivo, faltan = "sin_datos", VELAS_MINIMAS
    elif hoyos:
        motivo, faltan = "huecos", len(hoyos)
    elif len(velas) < VELAS_MINIMAS:
        motivo, faltan = "faltan_velas", VELAS_MINIMAS - len(velas)
    return velas, {"par": par, "temporalidad": temporalidad, "par_prestado": prestado, "empalmada": bool(prestadas),
                   "velas": len(velas), "propias": len(propias), "prestadas": len(prestadas),
                   "desde": velas[0][0] if velas else None, "hasta": velas[-1][0] if velas else None,
                   "corte": corte if prestadas else None, "huecos": len(hoyos), "motivo": motivo, "faltan": faltan}


# ── 2. El recorrido: de señal cruda a operación ──────────────────────────────────────────────────────────────────────────────

def seguir(velas, i, s, spread, com, factor=lib_costos.PENETRACION_SPREADS):
    """Qué le habría pasado a una señal de la vela `i`: si su orden límite se llenó mientras estuvo viva y, llenada, si
    terminó en el stop o en el objetivo. La orden se puede llenar recién en la vela **siguiente** (la señal se decide con la
    vela cerrada) y vive las `vigencia_velas` que dice la señal.

    Si una misma vela tocó el stop y el objetivo no se sabe qué pasó primero: se supone el stop (`SUPUESTO_AMBIGUO`), queda
    marcada (`ambigua`) y `validar_ambiguas` revisa después, con las velas de 1 m que haya, cuántas veces ese supuesto
    acertó."""
    paso = lib_datos.PASO_MS[s["temporalidad"]]
    nivel, stop, objetivo = s["entrada"], s["stop"], s["objetivo"]
    o = {"estrategia": s["estrategia"], "par": s["par"], "temporalidad": s["temporalidad"], "senal_ms": s["vela"],
         "permitida": bool(s["permitida"]), "filtro": s["filtro"], "nivel": nivel,
         "limite": nivel * (1 - lib_costos.margen_llenado(spread, factor)), "stop": stop, "objetivo": objetivo,
         "llenada": False, "entrada_ms": None, "salida_ms": None, "velas": 0, "por": "", "bruto": None, "neto": None,
         "costos": None, "ambigua": False, "motivo": "sin_llenar"}
    vigencia = int(s.get("vigencia_velas") or lib_estrategias.VIGENCIA_VELAS)
    entrada = next((j for j in range(i + 1, min(len(velas), i + 1 + vigencia))
                    if lib_costos.llena(nivel, velas[j][3], spread, factor)), None)
    if entrada is None:
        return o
    o.update(llenada=True, entrada_ms=velas[entrada][0], motivo="sin_cerrar")
    for k in range(entrada, min(len(velas), entrada + VELAS_MAXIMAS)):
        toco_stop, toco_objetivo = velas[k][3] <= stop, velas[k][2] >= objetivo
        if not (toco_stop or toco_objetivo):
            continue
        por = "stop" if toco_stop else "objetivo"
        r = lib_costos.resultado(nivel, stop if toco_stop else objetivo, por, spread, com)
        o.update(motivo="", ambigua=bool(toco_stop and toco_objetivo), salida_ms=velas[k][0] + paso,
                 velas=k - entrada + 1, por=r["por"], bruto=r["bruto"], neto=r["neto"], costos=r["costos"])
        break
    return o


def senales_de(par, temporalidad, velas, al_alza=None, filtro=None, filtrar=None):
    """Las señales crudas de cada vela de la serie, ya sin las del calentamiento. `filtrar(senal)` es el gancho que usa la
    calibración, en su paso, para dejar pasar solo las que llegan a la exigencia: aquí, sin él, no se filtra ninguna."""
    crudas = lib_estrategias.de_velas(par, temporalidad, velas, al_alza=al_alza, filtro=filtro)
    salida = []
    for i, suyas in enumerate(crudas):
        if i < lib_indicadores.VELAS_CALENTAMIENTO:
            salida.append([])
        else:
            salida.append([s for s in suyas if filtrar is None or filtrar(s)])
    return salida


def recorrer(velas, senales, spread, com, factor=lib_costos.PENETRACION_SPREADS):
    """Una pasada por la serie: una operación por señal (llenada o no). Las operaciones se solapan a propósito: aquí no hay
    tope de posiciones ni tamaño (son sus propios pasos) y la compuerta ya sabe no contar dos veces las que se pisan."""
    return [seguir(velas, i, s, spread, com, factor) for i, suyas in enumerate(senales) for s in suyas]


def curva(ops):
    """Qué habría hecho un saldo que entrara entero en cada operación, una tras otra, en el orden en que cerraron: el
    rendimiento compuesto y la caída máxima desde su punto más alto. **No es la cartera de verdad** —el tamaño, la reserva y
    los frenos son sus propios pasos—: es la única forma de poner las señales crudas al lado de quedarse en USDT y de
    comprar y esperar."""
    saldo, techo, caida = 1.0, 1.0, 0.0
    for o in sorted(ops, key=lambda x: (x["salida_ms"], x["entrada_ms"])):
        saldo *= 1 + o["neto"]
        techo = max(techo, saldo)
        caida = max(caida, (techo - saldo) / techo)
    return {"rendimiento": saldo - 1, "caida_maxima": caida}


def _medio(valores):
    return (sum(valores) / len(valores)) if valores else None


def resumen(ops):
    """Los números de un montón de operaciones: cuántas señales hubo, cuántas se llenaron, cuántas cerraron y con qué
    resultado después de costos. Lo que no se puede promediar queda en `None`: con cero operaciones no hay acierto."""
    cerradas = [o for o in ops if not o["motivo"]]
    netos = [o["neto"] for o in cerradas]
    ganadoras = [n for n in netos if n > 0]
    return {"senales": len(ops), "llenadas": sum(1 for o in ops if o["llenada"]),
            "sin_llenar": sum(1 for o in ops if o["motivo"] == "sin_llenar"),
            "sin_cerrar": sum(1 for o in ops if o["motivo"] == "sin_cerrar"),
            "permitidas": sum(1 for o in ops if o["permitida"]), "operaciones": len(cerradas),
            "por_objetivo": sum(1 for o in cerradas if o["por"] == "objetivo"),
            "por_stop": sum(1 for o in cerradas if o["por"] == "stop"),
            "ambiguas": sum(1 for o in cerradas if o["ambigua"]), "ganadoras": len(ganadoras),
            "aciertos": (len(ganadoras) / len(cerradas)) if cerradas else None,
            "neto_medio": _medio(netos), "bruto_medio": _medio([o["bruto"] for o in cerradas]),
            "costo_medio": _medio([o["costos"] for o in cerradas]),
            "velas_medias": _medio([o["velas"] for o in cerradas]),
            "mejor": max(netos) if netos else None, "peor": min(netos) if netos else None, **curva(cerradas)}


# ── El supuesto de las velas ambiguas, validado contra los 30 días con velas de 1 m ─────────────────────────────────────────

def validar_ambiguas(ops, minutos=None):
    """La regla de las velas que tocaron el stop y el objetivo. De hace años no hay velas de 1 m —Pilota guarda los últimos
    30 días—, así que el recorrido supone siempre lo malo (`SUPUESTO_AMBIGUO`): así el resultado no cambia cuando la ventana
    de 1 m se corre. Donde esas velas sí están, aquí se revisa qué pasó de verdad y el reporte deja el supuesto marcado con
    cuántas veces acertó. Una ventana de 1 m incompleta no se revisa: media ventana no dice qué se cruzó primero."""
    series = minutos if minutos is not None else {p: lib_datos.leer_serie(p, lib_datos.MINUTO)
                                                  for p in lib_datos.PARES_OPERADOS}
    guardadas = {par: {v[0]: v for v in velas} for par, velas in series.items()}
    minuto = lib_datos.PASO_MS[lib_datos.MINUTO]
    d = {"supuesto": SUPUESTO_AMBIGUO, "velas": 0, "con_1m": 0, "stop_primero": 0, "objetivo_primero": 0,
         "sin_resolver": 0, "acierto": None}
    for o in ops:
        if not o["ambigua"]:
            continue
        d["velas"] += 1
        if d["con_1m"] >= AMBIGUAS_MAXIMAS:
            continue
        paso = lib_datos.PASO_MS[o["temporalidad"]]
        apertura = o["salida_ms"] - paso
        suyas = guardadas.get(o["par"]) or {}
        trozo = [suyas.get(apertura + x * minuto) for x in range(paso // minuto)]
        if any(v is None for v in trozo):
            continue
        d["con_1m"] += 1
        for v in trozo:
            abajo, arriba = v[3] <= o["stop"], v[2] >= o["objetivo"]
            if abajo or arriba:
                d["stop_primero" if abajo and not arriba else
                  ("objetivo_primero" if arriba and not abajo else "sin_resolver")] += 1
                break
        else:
            d["sin_resolver"] += 1   # dentro del minuto tampoco se cruzó ninguno: la vela de 4 h no cuadra con las de 1 m
    resueltas = d["stop_primero"] + d["objetivo_primero"]
    d["acierto"] = (d["stop_primero"] / resueltas) if resueltas else None
    return d


# ── 3. La compuerta: los casos que de verdad hay ─────────────────────────────────────────────────────────────────────────────

def sin_solapar(ops):
    """Cuántas de esas operaciones no se pisan entre sí: ordenadas por cuándo cerraron, se cuenta una y se saltan todas las
    que habían entrado antes de que esa cerrara. Dos operaciones que viven el mismo rato son el mismo rato de mercado
    contado dos veces: contándolas las dos, la compuerta creería tener más evidencia de la que hay."""
    libre, casos = None, 0
    for o in sorted(ops, key=lambda x: (x["salida_ms"], x["entrada_ms"])):
        if libre is None or o["entrada_ms"] >= libre:
            casos += 1
            libre = o["salida_ms"]
    return casos


def tramos_de(ops, claves):
    """Los tramos de un nivel, con sus casos y sus números, en el orden en que las reglas los declaran (estrategias, pares,
    temporalidades). Están todas las combinaciones que las reglas pueden dar: un tramo sin ninguna operación es un tramo con
    cero casos, no un tramo que no existe (si no apareciera, la compuerta lo daría por bueno). Cada tramo lleva su `resumen`:
    es de ahí de donde el puntaje, en su paso, saca la probabilidad de ganar de una oportunidad de ese mismo tramo."""
    combinaciones = [{"estrategia": e, "par": p, "temporalidad": t} for e in ESTRATEGIAS_ENTRADA
                     for p in lib_datos.PARES_OPERADOS for t in lib_estrategias.TEMPORALIDADES_SENAL]
    tramos = {}
    for c in combinaciones:
        tramos.setdefault(tuple(c[k] for k in claves), [])
    for o in ops:
        clave = tuple(o[k] for k in claves)
        if clave in tramos:
            tramos[clave].append(o)
    salida = []
    for clave, suyas in tramos.items():
        d = dict(zip(claves, clave))
        casos = sin_solapar(suyas)
        salida.append({"estrategia": d.get("estrategia", ""), "par": d.get("par", ""),
                       "temporalidad": d.get("temporalidad", ""), "operaciones": len(suyas), "casos": casos,
                       "faltan": max(0, CASOS_MINIMOS - casos), "alcanza": casos >= CASOS_MINIMOS,
                       "resumen": resumen(suyas)})
    return salida


def compuerta(ops):
    """Con qué tramos se puede calibrar. Cuenta solo las operaciones que cerraron y que el filtro de BTC dejaba entrar: una
    señal que Pilota nunca habría tomado no es un caso. Si algún tramo no llega a `CASOS_MINIMOS`, aplica el plan B escrito
    antes de ver un resultado: juntar las temporalidades («ancho»), después los pares («unico») y, si todavía no alcanza,
    decirlo («insuficiente»). Haber usado el plan B no se tapa: la calibración, en su paso, tiene que dejar el modelo en
    «No validado» con la exigencia alta."""
    cerradas = [o for o in ops if not o["motivo"] and o["permitida"]]
    niveles = []
    for nombre, claves in NIVELES:
        tramos = tramos_de(cerradas, claves)
        niveles.append({"nivel": nombre, "claves": list(claves), "tramos": tramos,
                        "minimo": min((t["casos"] for t in tramos), default=0),
                        "alcanza": bool(tramos) and all(t["alcanza"] for t in tramos)})
    elegido = next((n for n in niveles if n["alcanza"]), None)
    plan = elegido["nivel"] if elegido else "insuficiente"
    return {"casos_minimos": CASOS_MINIMOS, "operaciones": len(cerradas), "plan": plan, "plan_b": plan != "normal",
            "no_validado": plan != "normal", "niveles": niveles,
            "tramos": (elegido or niveles[0])["tramos"], "listo": plan == "normal"}


# ── 4. El reporte: contra quedarse en USDT y contra comprar y esperar ────────────────────────────────────────────────────────

def quedarse_en_usdt():
    """La comparación más fácil de olvidar: no hacer nada. Ni rendimiento ni caída, y cero operaciones."""
    return {"que": "usdt", "operaciones": 0, "rendimiento": 0.0, "bruto": 0.0, "caida_maxima": 0.0}


def comprar_y_esperar(velas, spread, com):
    """Comprar al principio de la ventana y esperar hasta el final, con los costos de entrar y de salir una vez (la salida
    es una límite: maker). La caída máxima es la de verdad, medida con los mínimos de cada vela."""
    d = {"que": "comprar_y_esperar", "operaciones": 0, "rendimiento": None, "bruto": None, "caida_maxima": None,
         "desde": None, "hasta": None}
    if len(velas) < 2:
        return d
    r = lib_costos.resultado(velas[0][4], velas[-1][4], "objetivo", spread, com)
    techo, caida = velas[0][4], 0.0
    for v in velas:
        techo = max(techo, v[4])
        caida = max(caida, (techo - v[3]) / techo)
    d.update(operaciones=1, rendimiento=r["neto"], bruto=r["bruto"], caida_maxima=caida,
             desde=velas[0][0], hasta=velas[-1][0])
    return d


def ventana_de(empalmes):
    desde = [e["desde"] for e in empalmes if e["desde"] is not None]
    hasta = [e["hasta"] for e in empalmes if e["hasta"] is not None]
    inicio, fin = (min(desde) if desde else None), (max(hasta) if hasta else None)
    return {"desde": inicio, "hasta": fin, "iso_desde": lib_datos.iso(inicio) if inicio else "",
            "iso_hasta": lib_datos.iso(fin) if fin else "",
            "dias": ((fin - inicio) // lib_datos.DIA_MS) if (inicio and fin) else 0}


def correr(ahora_ms=None, factor=None, filtrar=None, sensibilidad=True, con_todas=False):
    """El recorrido completo: las cuatro series de entrada (los dos pares operados en 1 h y 4 h), la compuerta y el reporte.

    `filtrar(senal)` es el gancho de la calibración (su paso): sin él no se filtra nada y esto es el backtest de señales
    crudas **sin exigencia**, el primero del orden. `factor` cambia cuánto tiene que atravesar el precio una límite para
    contarla llenada; `sensibilidad` repite el recorrido con los factores de `lib_costos.SENSIBILIDAD` para que se vea
    cuánto del resultado es esa regla."""
    ahora = ahora_ms or lib_datos.ahora_local_ms()
    com, modelo = lib_costos.comisiones(), lib_costos.modelo()
    principal = lib_costos.PENETRACION_SPREADS if factor is None else float(factor)
    motivos, empalmes, filas, crudas, todas = [], [], [], [], []
    btc = lib_datos.leer_serie(lib_indicadores_mercado.CONTEXTO_PAR, lib_estrategias.TEMPORALIDAD_DIARIA)
    filtro = lib_estrategias.filtro_en(btc) if len(btc) >= VELAS_MINIMAS else None
    if filtro is None:   # sin el contexto de BTC no se entra a nada, así que tampoco se mide nada
        motivos.append({"codigo": "sin_contexto", "par": lib_indicadores_mercado.CONTEXTO_PAR,
                        "temporalidad": lib_estrategias.TEMPORALIDAD_DIARIA, "n": VELAS_MINIMAS - len(btc)})
    for par in lib_datos.PARES_OPERADOS:
        diario = lib_estrategias.PAR_DIARIO[par]
        velas_dia = lib_datos.leer_serie(diario, lib_estrategias.TEMPORALIDAD_DIARIA)
        al_alza = lib_estrategias.al_alza_en(velas_dia) if len(velas_dia) >= VELAS_MINIMAS else None
        if al_alza is None:
            motivos.append({"codigo": "sin_tendencia_diaria", "par": diario,
                            "temporalidad": lib_estrategias.TEMPORALIDAD_DIARIA, "n": VELAS_MINIMAS - len(velas_dia)})
        for temporalidad in lib_estrategias.TEMPORALIDADES_SENAL:
            velas, empalme = empalmar(par, temporalidad)
            empalmes.append(empalme)
            fila = {"par": par, "temporalidad": temporalidad, "velas": empalme["velas"], "motivo": empalme["motivo"],
                    "faltan": empalme["faltan"], "empalmada": empalme["empalmada"],
                    "prestadas": empalme["prestadas"], "senales": 0, "resumen": resumen([])}
            if empalme["motivo"]:
                motivos.append({"codigo": empalme["motivo"], "par": par, "temporalidad": temporalidad,
                                "n": empalme["faltan"]})
                filas.append(fila)
                continue
            senales = senales_de(par, temporalidad, velas, al_alza=al_alza, filtro=filtro, filtrar=filtrar)
            spread = lib_costos.spread_de(modelo, par)
            ops = recorrer(velas, senales, spread, com, principal)
            crudas.append((velas, senales, spread))
            todas.extend(ops)
            fila.update(senales=sum(len(s) for s in senales), resumen=resumen(ops))
            filas.append(fila)
    sensibles = []
    if sensibilidad:
        for f in lib_costos.SENSIBILIDAD:
            ops = todas if f == principal else [o for velas, senales, spread in crudas
                                                for o in recorrer(velas, senales, spread, com, f)]
            sensibles.append({"factor": f, "principal": f == principal, "resumen": resumen(ops)})
    btc_velas, _ = empalmar(lib_datos.PARES_OPERADOS[0], lib_estrategias.TEMPORALIDAD_DIARIA)
    ventana = ventana_de(empalmes)
    if ventana["desde"] is not None:
        btc_velas = [v for v in btc_velas if ventana["desde"] <= v[0] <= ventana["hasta"]]
    cerradas = sorted([o for o in todas if not o["motivo"]], key=lambda o: o["salida_ms"])
    todas_ops = list(todas)
    return {"formato": 1, "corrido": True, "cuando": lib_datos.iso(ahora), "modelo": modelo, "comisiones": com,
            "parametros": parametros(principal), "ventana": ventana, "series": filas, "empalmes": empalmes,
            "resumen": resumen(todas), "compuerta": compuerta(todas),
            "referencias": {"usdt": quedarse_en_usdt(),
                            "btc": comprar_y_esperar(btc_velas, lib_costos.spread_de(modelo, lib_datos.PARES_OPERADOS[0]),
                                                     com)},
            "sensibilidad": sensibles,
            "supuestos": {"ambiguas": validar_ambiguas(todas), "spread": modelo["origen"],
                          "empalme": any(e["empalmada"] for e in empalmes), "sin_exigencia": filtrar is None,
                          "calentamiento": lib_indicadores.VELAS_CALENTAMIENTO},
            "operaciones": cerradas[-OPERACIONES_GUARDADAS:], "motivos": motivos, "listo": not motivos,
            # Todas las operaciones, solo para la simulación con monto (`lib_simulacion`): no van al archivo.
            **({"todas": todas_ops} if con_todas else {})}


def vacio():
    """Lo que se ve antes de correr el primero: el modelo de costos y los tramos en cero, sin ningún número inventado."""
    return {"formato": 1, "corrido": False, "cuando": "", "modelo": lib_costos.modelo(),
            "comisiones": lib_costos.comisiones(), "parametros": parametros(), "ventana": ventana_de([]),
            "series": [], "empalmes": [], "resumen": resumen([]), "compuerta": compuerta([]),
            "referencias": {"usdt": quedarse_en_usdt(), "btc": comprar_y_esperar([], lib_costos.SPREAD_SUPUESTO,
                                                                                 lib_costos.comisiones())},
            "sensibilidad": [], "supuestos": {"ambiguas": validar_ambiguas([], {}), "spread": "", "empalme": False,
                                              "sin_exigencia": True,
                                              "calentamiento": lib_indicadores.VELAS_CALENTAMIENTO},
            "operaciones": [], "motivos": [], "listo": False}


def escribir(d):
    """Deja escrito el último recorrido: lo leen el puntaje y la calibración sin volver a recorrer el historial."""
    nucleo.escribir_json(ruta_backtest(), d)
    return d


def guardado():
    """El último backtest que se corrió o, si no se corrió ninguno, el esqueleto vacío. Sin red y sin recorrer nada."""
    d = nucleo.leer_json(ruta_backtest(), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    if isinstance(d, dict) and d.get("formato") == 1 and d.get("corrido") and isinstance(d.get("series"), list):
        return d
    return vacio()


# ── Las dos acciones ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def estado(d):
    return {"ok": True, "datos": guardado()}


def correr_accion(d, ahora_ms=None):
    """`ahora_ms` solo se pasa en las pruebas (una hora fija): la acción siempre recorre con la hora de ahora."""
    return {"ok": True, "datos": escribir(correr(ahora_ms))}


if __name__ == "__main__":
    nucleo.script({"estado": estado, "correr": correr_accion}, __doc__)
