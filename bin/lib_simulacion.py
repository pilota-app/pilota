#!/usr/bin/env python3
"""lib_simulacion — «si hubiera puesto X USDT»: el historial recorrido como una cartera de verdad. Solo biblioteca estándar.
No es una acción (la corre `bin/simular.py`).

El backtest (`bin/backtest.py`) mide las señales crudas, sin tamaño ni frenos. Esto es el paso siguiente: las mismas
operaciones, pero con **las reglas que Pilota usa hoy en vivo**, sobre el monto que la persona elige.

Lo que hace, en orden:

1. Toma las operaciones del recorrido del backtest (`backtest.correr(con_todas=True)`), solo las **permitidas** (el filtro de
   BTC dejaba entrar) y que se llenaron y cerraron. Con los costos de los dos lados ya adentro (`neto`).
2. Las recorre por la hora de entrada, como una cartera: cierra primero lo que ya terminó, mira los frenos y calcula el
   tamaño con `lib_tamano.tamano` (la reserva del 40 %, dos posiciones, 2 % de riesgo, los mínimos de Binance y el tope
   mientras el modelo no esté validado).
3. Los frenos son los de `lib_frenos`: el día se cierra al perder el 5 %, cuatro pérdidas seguidas paran el resto del
   día, bajo el piso (25 % bajo el capital de referencia) no se abre nada y en el piso absoluto (35 % bajo lo que se puso)
   se termina la simulación.
4. Devuelve el saldo final, la curva, la caída máxima, cuántas operaciones y cuántas ganó, cuántas se saltó cada freno,
   y al lado lo que habría pasado con **quedarse en USDT** y con **comprar BTC y esperar**, con el mismo monto.

Lo que no se negocia aquí:
- **Es el pasado, no una promesa.** El resultado dice siempre desde cuándo hasta cuándo y con cuántas operaciones.
- **Las reglas son las de hoy.** Los filtros de Binance son los del último cálculo del capital mínimo viable; sin ese
  cálculo no se simula (`sin_minimos`): un mínimo inventado da un resultado inventado.
- **Sin exigencia todavía.** Mientras el modelo no esté calibrado, el puntaje no filtra: se simulan todas las señales
  permitidas, y el resultado lo dice (`sin_exigencia`).
- **Nada se escribe en la cuenta.** Es una cuenta aparte, en memoria: el saldo de prueba y el real no se tocan.
"""
import bisect
import backtest
import lib_calibracion
import lib_costos
import lib_datos
import lib_estrategias
import lib_frenos
import lib_holding
import lib_indicadores_mercado
import lib_perfiles
import lib_rotacion
import lib_influencia
import lib_tendencia
import lib_tamano
import lib_universo

#: Los períodos que se pueden elegir, en días.
PERIODOS = (30, 90, 180, 365, 1095)
PERIODO_SUGERIDO = 90
MONTO_SUGERIDO = 100.0
MONTO_MINIMO = 10.0
MONTO_MAXIMO = 1_000_000.0
#: La curva se entrega con a lo más estos puntos (la pantalla la dibuja; más no se ve).
PUNTOS_CURVA = 160
#: Cuántos movimientos se entregan por perfil (los últimos): la película de lo que hizo.
MOVIMIENTOS = 400
MOTIVOS = ("sin_monto", "sin_periodo", "sin_minimos", "sin_operaciones", "sin_historial")


def _numero(valor, defecto=0.0):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return defecto
    return v if v == v and v not in (float("inf"), float("-inf")) else defecto


def _dia(ms):
    return int(ms) // lib_datos.DIA_MS


def ralear(puntos, maximo=PUNTOS_CURVA):
    """Deja a lo más `maximo` puntos, siempre con el primero y el último."""
    if len(puntos) <= maximo:
        return puntos
    paso = (len(puntos) - 1) / (maximo - 1)
    return [puntos[round(i * paso)] for i in range(maximo)]


def _de_op(o):
    """Una operación del backtest con la forma de una señal: lo que mira el perfil."""
    return {"temporalidad": o.get("temporalidad"), "entrada": o["nivel"], "stop": o["stop"], "objetivo": o["objetivo"]}


def cartera(ops, monto, filtros, com=None, tope=None, desde_ms=None, hasta_ms=None, perfil=None):
    """Recorre `ops` (las del backtest) como una cartera que parte con `monto` USDT. Pura: no lee ni escribe nada.

    Con `perfil`, solo entran las operaciones que ese perfil acepta y con su tamaño (`lib_perfiles`). Devuelve el saldo
    final, la curva `[[ms, saldo], …]`, la cuenta de lo que pasó y los movimientos (cada compra y cada venta)."""
    capital = float(monto)
    saldo, referencia, techo, caida = capital, capital, capital, 0.0
    piso_absoluto = capital * (1 - lib_frenos.PISO_ABSOLUTO)
    abiertas = []                     # [(salida_ms, nocional, neto, movimiento de salida)]
    movimientos = []
    maximo = (lib_perfiles.de(perfil) or {}).get("posiciones", lib_frenos.POSICIONES)
    curva = [[int(desde_ms or 0), round(saldo, 6)]] if desde_ms else []
    c = {"operaciones": 0, "ganadas": 0, "perdidas": 0, "saltadas": {"diario": 0, "racha": 0, "piso": 0,
         "posiciones": 0, "tamano": 0}, "terminada": False, "mejor": None, "peor": None}
    dia, inicio_dia, racha, pausa_dia = None, saldo, 0, None

    def cerrar_hasta(ms):
        nonlocal saldo, referencia, techo, caida, racha, abiertas
        quedan = []
        for salida, nocional, neto, mov in sorted(abiertas, key=lambda x: x[0]):
            if salida > ms:
                quedan.append((salida, nocional, neto, mov))
                continue
            ganancia = nocional * neto
            saldo += ganancia
            movimientos.append({**mov, "ganancia": ganancia, "saldo": saldo})
            referencia = max(referencia, saldo)
            techo = max(techo, saldo)
            caida = max(caida, (techo - saldo) / techo if techo > 0 else 0.0)
            c["ganadas" if ganancia > 0 else "perdidas"] += 1
            c["mejor"] = ganancia if c["mejor"] is None else max(c["mejor"], ganancia)
            c["peor"] = ganancia if c["peor"] is None else min(c["peor"], ganancia)
            racha = 0 if ganancia > 0 else racha + 1
            curva.append([int(salida), round(saldo, 6)])
        abiertas = quedan

    for o in sorted(ops, key=lambda x: (x["entrada_ms"], x["salida_ms"])):
        ms = int(o["entrada_ms"])
        if perfil and not lib_perfiles.acepta(perfil, _de_op(o)):
            continue
        if desde_ms is not None and ms < desde_ms:
            continue
        if hasta_ms is not None and ms > hasta_ms:
            continue
        cerrar_hasta(ms)
        if saldo <= piso_absoluto:
            c["terminada"] = True
            break
        if _dia(ms) != dia:
            dia, inicio_dia = _dia(ms), saldo
            if pausa_dia is not None and pausa_dia != dia:
                pausa_dia, racha = None, 0
        if inicio_dia > 0 and (inicio_dia - saldo) / inicio_dia >= lib_frenos.PERDIDA_DIARIA:
            c["saltadas"]["diario"] += 1
            continue
        if racha >= lib_frenos.RACHA_MAXIMA:
            pausa_dia = dia
            c["saltadas"]["racha"] += 1
            continue
        if saldo < referencia * (1 - lib_frenos.PISO):
            c["saltadas"]["piso"] += 1
            continue
        if len(abiertas) >= maximo:
            c["saltadas"]["posiciones"] += 1
            continue
        comprometido = sum(x[1] for x in abiertas)
        f = filtros.get(o["par"]) or {}
        if perfil:
            t = lib_perfiles.tamano(perfil, saldo, o["nivel"], o["stop"], f, com, len(abiertas), comprometido, tope)
        else:
            t = lib_tamano.tamano(saldo, o["nivel"], o["stop"], f, com, tope, len(abiertas), comprometido)
        if not t.get("puede"):
            c["saltadas"]["tamano"] += 1
            continue
        comun = {"par": o["par"], "estrategia": o.get("estrategia") or "", "temporalidad": o.get("temporalidad") or ""}
        movimientos.append({**comun, "ms": ms, "que": "compra", "precio": o["nivel"], "monto": t["entrada"],
                            "stop": o["stop"], "objetivo": o["objetivo"]})
        salida = o["objetivo"] if o.get("por") == "objetivo" else o["stop"]
        abiertas.append((int(o["salida_ms"]), t["entrada"], o["neto"],
                         {**comun, "ms": int(o["salida_ms"]), "que": "venta", "precio": salida,
                          "monto": t["entrada"], "por": o.get("por") or "", "entrada": o["nivel"]}))
        c["operaciones"] += 1
    if not c["terminada"]:
        cerrar_hasta(float("inf"))
    return {"saldo": saldo, "ganancia": saldo - capital, "rendimiento": (saldo - capital) / capital if capital else 0,
            "caida_maxima": caida, "curva": ralear(curva), "movimientos": movimientos[-MOVIMIENTOS:],
            "movimientos_total": len(movimientos), **c}


def comprar_y_esperar(velas, monto, desde_ms, hasta_ms, spread, com):
    """Comprar BTC con todo el monto al principio y venderlo al final, con su curva diaria."""
    tramo = [v for v in velas if desde_ms <= v[0] <= hasta_ms]
    if len(tramo) < 2:
        return {"saldo": None, "rendimiento": None, "caida_maxima": None, "curva": []}
    r = lib_costos.resultado(tramo[0][4], tramo[-1][4], "objetivo", spread, com)
    base, techo, caida = tramo[0][4], tramo[0][4], 0.0
    for v in tramo:
        techo = max(techo, v[4])
        caida = max(caida, (techo - v[3]) / techo)
    curva = ralear([[int(v[0]), round(monto * v[4] / base, 6)] for v in tramo])
    return {"saldo": monto * (1 + r["neto"]), "rendimiento": r["neto"], "caida_maxima": caida, "curva": curva}


def simular(monto, dias, recorrido, minimo=None, calibracion=None):
    """La simulación completa sobre un recorrido del backtest ya hecho (`backtest.correr(con_todas=True)`)."""
    monto = _numero(monto, None)
    dias = int(_numero(dias, 0))
    base = {"formato": 1, "monto": monto, "dias": dias, "periodos": list(PERIODOS), "listo": False, "motivo": ""}
    if monto is None or not (MONTO_MINIMO <= monto <= MONTO_MAXIMO):
        return {**base, "motivo": "sin_monto"}
    if dias not in PERIODOS:
        return {**base, "motivo": "sin_periodo"}
    pares, md = lib_tamano.filtros_de(minimo)
    if not md.get("calculado") or not pares:
        return {**base, "motivo": "sin_minimos"}
    ventana = (recorrido or {}).get("ventana") or {}
    hasta = ventana.get("hasta")
    if not hasta:
        return {**base, "motivo": "sin_historial"}
    desde = max(int(ventana.get("desde") or 0), int(hasta) - dias * lib_datos.DIA_MS)
    ops = [o for o in ((recorrido or {}).get("todas") or [])
           if not o.get("motivo") and o.get("llenada") and o.get("permitida") and o.get("neto") is not None]
    modelo = lib_calibracion.modelo(lib_calibracion.guardada() if calibracion is None else calibracion)
    com = lib_tamano.comisiones(lib_costos.comisiones())
    tope = modelo["tope"] if modelo["topado"] else None
    r = cartera(ops, monto, pares, com, tope, desde, int(hasta))
    m = lib_costos.modelo()
    btc = comprar_y_esperar(lib_datos.leer_serie(lib_estrategias.PAR_DIARIO[lib_datos.PARES_OPERADOS[0]],
                                                 lib_estrategias.TEMPORALIDAD_DIARIA),
                            monto, desde, int(hasta), lib_costos.spread_de(m, lib_datos.PARES_OPERADOS[0]), com)
    dias_reales = (int(hasta) - desde) // lib_datos.DIA_MS
    return {**base, "listo": r["operaciones"] > 0, "motivo": "" if r["operaciones"] > 0 else "sin_operaciones",
            "desde": lib_datos.iso(desde), "hasta": lib_datos.iso(int(hasta)), "desde_ms": desde, "hasta_ms": int(hasta),
            "dias_reales": dias_reales, "pilota": r, "usdt": {"saldo": monto, "rendimiento": 0.0},
            "btc": btc, "sin_exigencia": not modelo["calibrado"], "topado": modelo["topado"], "tope": tope,
            "comisiones": com}


def holding(monto, desde_ms, hasta_ms, com, series=None):
    """El perfil holding: compra BTC y ETH por partes (`lib_perfiles.PERFILES["holding"]`), una vez por semana, al cierre
    diario, y mantiene. La curva es lo que vale lo comprado más lo que queda en USDT, día por día."""
    p = lib_perfiles.PERFILES["holding"]
    taker = (com or {}).get("taker", 0.0)
    diarias = {}
    for par in p["reparto"]:
        velas = (series.get(par) or []) if series is not None else lib_datos.leer_serie(
            lib_estrategias.PAR_DIARIO[par], lib_estrategias.TEMPORALIDAD_DIARIA)
        diarias[par] = {v[0]: v[4] for v in velas if desde_ms <= v[0] <= hasta_ms}
    dias = sorted(set.intersection(*(set(d) for d in diarias.values()))) if diarias else []
    if len(dias) < 2:
        return {"listo": False, "motivo": "sin_historial"}
    efectivo, tenencias, partes, ultima = float(monto), {par: 0.0 for par in p["reparto"]}, 0, None
    curva, movimientos, techo, caida = [], [], float(monto), 0.0
    for ms in dias:
        if partes < p["partes"] and (ultima is None or ms - ultima >= p["cada_ms"]):
            parte = efectivo / (p["partes"] - partes)
            for par, peso in p["reparto"].items():
                gasto = parte * peso
                cantidad = gasto * (1 - taker) / diarias[par][ms]
                tenencias[par] += cantidad
                efectivo -= gasto
                movimientos.append({"ms": ms, "que": "compra", "par": par, "precio": diarias[par][ms], "monto": gasto,
                                    "estrategia": "holding", "temporalidad": "1d"})
            partes, ultima = partes + 1, ms
        valor = efectivo + sum(tenencias[par] * diarias[par][ms] for par in tenencias)
        techo = max(techo, valor)
        caida = max(caida, (techo - valor) / techo if techo > 0 else 0.0)
        curva.append([int(ms), round(valor, 6)])
    saldo = curva[-1][1]
    return {"listo": True, "motivo": "", "saldo": saldo, "ganancia": saldo - monto,
            "rendimiento": (saldo - monto) / monto, "caida_maxima": caida, "curva": ralear(curva),
            "operaciones": len(movimientos), "ganadas": 0, "perdidas": 0, "movimientos": movimientos[-MOVIMIENTOS:],
            "movimientos_total": len(movimientos), "tenencias": tenencias, "efectivo": efectivo}


def _diarias_de(pares):
    return {par: lib_datos.leer_serie(par, "1d") for par in pares}


def inicio_posible(perfil, desde_ms, diarias=None):
    """Desde cuándo se puede mirar un perfil: las acciones están en Binance desde junio de 2026, así que un perfil con
    acciones empieza el día en que todas sus partes ya tienen velas. Devuelve el inicio y si hubo que correrlo."""
    pares = lib_perfiles.pares_de(perfil)
    d = diarias if diarias is not None else _diarias_de(pares)
    primeros = [d[par][0][0] for par in pares if d.get(par)]
    if len(primeros) < len(pares):
        return desde_ms, False
    inicio = max([desde_ms] + primeros)
    return inicio, inicio > desde_ms


def _regla_tendencia(p):
    """La regla del perfil tendencia con sus frenos (golpe y noticias), la misma que usa el robot en vivo."""
    datos = lib_influencia.cargar() if p.get("noticias") else None

    def regla(tramos, actuales, pasa, ms):
        noticias = lib_influencia.negativas(ms, p["reparto"], p["dias_freno"], datos) if datos else None
        return lib_tendencia.pesos_cruce(tramos, p["reparto"], p["media"], actuales, p.get("golpe"), p["dias_freno"], noticias)
    return regla


def _tendencia(perfil, monto, desde_ms, hasta_ms, com, diarias):
    """El perfil tendencia (`lib_tendencia.pesos_cruce`) sobre el pasado, con el mismo paso que usa el robot en vivo."""
    p = lib_perfiles.de(perfil)
    return lib_tendencia.simular(monto, {k: diarias.get(k) or [] for k in p["reparto"]}, desde_ms, hasta_ms,
                                 lib_universo.comisiones_de("USDT", com),
                                 _regla_tendencia(p),
                                 spread=lib_tendencia.SPREAD, umbral=p["umbral"])


def tendencia(perfil, monto, desde, hasta, com, diarias=None):
    p = lib_perfiles.de(perfil)
    r = _tendencia(perfil, monto, desde, hasta, com, diarias if diarias is not None else _diarias_de(p["reparto"]))
    if r.get("listo"):
        r["curva"] = ralear(r["curva"])
        r["movimientos"] = r["movimientos"][-MOVIMIENTOS:]
    return r


def _curva_de(perfil, monto, desde_ms, hasta_ms, com, diarias):
    """La simulación cruda de un perfil holding o de la rotación (sin ralear), para sumarla en una mezcla."""
    p = lib_perfiles.de(perfil)
    if p["tipo"] == "tendencia":
        return _tendencia(perfil, monto, desde_ms, hasta_ms, com, diarias)
    if p["tipo"] == "rotar":
        btc = diarias.get(lib_indicadores_mercado.CONTEXTO_PAR) or lib_datos.leer_serie(lib_indicadores_mercado.CONTEXTO_PAR, "1d")
        return lib_rotacion.simular(monto, {k: diarias[k] for k in p["pares"] if diarias.get(k)}, btc, desde_ms, hasta_ms,
                                    lib_universo.comisiones_de("USDT", com), posiciones=p["posiciones"],
                                    dias=p["dias_fuerza"], media=p["media"], margen=p["margen"], golpe=p.get("golpe"),
                                    dias_freno=p.get("dias_freno", 5), noticia=_noticia_btc(p))
    return lib_holding.simular(monto, {k: diarias.get(k) or [] for k in p["reparto"]}, desde_ms, hasta_ms, p, com)


def mezcla(perfil, monto, desde_ms, hasta_ms, com, diarias=None):
    """Una mezcla: el monto repartido entre sus partes, cada una con su libro. La curva es la suma, día por día."""
    p = lib_perfiles.de(perfil)
    pares = lib_perfiles.pares_de(perfil) + (lib_indicadores_mercado.CONTEXTO_PAR,)
    diarias = diarias if diarias is not None else _diarias_de(dict.fromkeys(pares))
    inicio, recortado = inicio_posible(perfil, desde_ms, diarias)
    partes = []
    for comp, peso in p["componentes"]:
        r = _curva_de(comp, monto * peso, inicio, hasta_ms, com, diarias)
        if not r.get("listo"):
            return {"listo": False, "motivo": r.get("motivo") or "sin_historial"}
        partes.append((comp, r))
    dias = sorted({t for _, r in partes for t, _ in r["curva"]})
    valores = []
    for _, r in partes:
        punto, ultimo, serie = dict(r["curva"]), r["curva"][0][1], []
        for t in dias:
            ultimo = punto.get(t, ultimo)
            serie.append(ultimo)
        valores.append(serie)
    curva = [[t, round(sum(v[i] for v in valores), 6)] for i, t in enumerate(dias)]
    techo, caida = float(monto), 0.0
    for _, v in curva:
        techo = max(techo, v)
        caida = max(caida, (techo - v) / techo if techo > 0 else 0.0)
    # El saldo de cada movimiento es el de la mezcla entera ese día, no el de su parte.
    valor_de = dict(curva)
    movimientos = sorted((dict(m, componente=c, saldo=valor_de.get(m["ms"] // lib_datos.DIA_MS * lib_datos.DIA_MS,
                                                                   m.get("saldo")))
                          for c, r in partes for m in r["movimientos"]), key=lambda m: m["ms"])
    saldo = curva[-1][1]
    return {"listo": True, "motivo": "", "saldo": saldo, "ganancia": saldo - monto, "rendimiento": saldo / monto - 1,
            "caida_maxima": caida, "curva": ralear(curva), "operaciones": len(movimientos), "ganadas": 0, "perdidas": 0,
            "movimientos": movimientos[-MOVIMIENTOS:], "movimientos_total": len(movimientos),
            "partes": [{"perfil": c, "peso": w, "saldo": r["saldo"]} for (c, w), (_, r) in zip(p["componentes"], partes)],
            **({"desde_ms": inicio, "recorte": "acciones"} if recortado else {})}


#: El mapa de inicios: desde cuándo y cada cuántos meses se prueba empezar, y el último inicio (que deje al menos medio año).
MAPA_DESDE = (2018, 6)
MAPA_CADA_MESES = 6
MAPA_MINIMO_DIAS = 180


def inicios_mapa(hasta_ms):
    """Los inicios del mapa: el 1 de cada `MAPA_CADA_MESES` meses desde `MAPA_DESDE`, hasta medio año antes de hoy."""
    import datetime
    a, m, salida = MAPA_DESDE[0], MAPA_DESDE[1], []
    while True:
        ms = int(datetime.datetime(a, m, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
        if ms > hasta_ms - MAPA_MINIMO_DIAS * lib_datos.DIA_MS:
            return salida
        salida.append(ms)
        m += MAPA_CADA_MESES
        a, m = a + (m - 1) // 12, (m - 1) % 12 + 1


def _proporcion(curva, desde_ms):
    """Cuánto multiplicó una curva desde `desde_ms` hasta el final (para lo que no depende del día en que se empezó)."""
    inicio = next((v for t, v in curva if t >= desde_ms), None)
    return curva[-1][1] / inicio if inicio else None


def mapa(monto, com, hasta_ms, diarias=None, perfiles=None):
    """El mapa de inicios: si hubieras empezado en cada fecha de `inicios_mapa`, cuánto tendrías hoy con cada perfil
    (rendimiento hasta hoy). Los holding se corren de nuevo desde cada inicio (sus compras dependen de cuándo empiezan); la
    rotación y comprar BTC se corren una vez y se miden desde cada inicio (sus reglas no dependen del día en que partiste).
    Un perfil con acciones no tiene casillas antes de junio de 2026: ahí no existían en Binance."""
    perfiles = perfiles or [p for p in lib_perfiles.ORDEN if p != "holding"]
    inicios = inicios_mapa(hasta_ms)
    pares = dict.fromkeys(x for p in perfiles for x in lib_perfiles.pares_de(p))
    pares[lib_indicadores_mercado.CONTEXTO_PAR] = None
    diarias = diarias if diarias is not None else _diarias_de(pares)
    btc = diarias.get(lib_indicadores_mercado.CONTEXTO_PAR) or []
    referencia = [[v[0], v[4]] for v in btc if v[0] <= hasta_ms]
    # Las de reglas que no dependen del día en que partiste se corren una vez y se miden desde cada inicio.
    unicas = {perfil: (_curva_de(perfil, 100.0, inicios[0], hasta_ms, com, diarias).get("curva") or []) if inicios else []
              for perfil in ("rotacion", "tendencia")}

    def parte(perfil, peso, desde):
        p = lib_perfiles.de(perfil)
        if p["tipo"] in ("rotar", "tendencia"):
            f = _proporcion(unicas[perfil], desde)
            return None if f is None else peso * f
        inicio, recortado = inicio_posible(perfil, desde, diarias)
        if recortado:
            return None
        r = lib_holding.simular(1.0, {k: diarias.get(k) or [] for k in p["reparto"]}, desde, hasta_ms, p, com)
        return peso * r["saldo"] if r.get("listo") else None

    filas = []
    for perfil in perfiles:
        p = lib_perfiles.de(perfil)
        valores = []
        for desde in inicios:
            comps = p["componentes"] if p["tipo"] == "mezcla" else ((perfil, 1.0),)
            trozos = [parte(c, w, desde) for c, w in comps]
            valores.append(None if any(x is None for x in trozos) else round(sum(trozos) - 1, 4))
        filas.append({"perfil": perfil, "valores": valores})
    btc_fila = [None if _proporcion(referencia, d) is None else round(_proporcion(referencia, d) - 1, 4) for d in inicios]
    return {"formato": 1, "hasta_ms": hasta_ms, "inicios": inicios, "filas": filas, "btc": btc_fila, "monto": monto}


# ── Qué tan seguido sale bien: todas las ventanas del pasado del mismo largo ──────────────────────────────────────────
#: Cada cuántos días empieza una ventana. Dos semanas: muchas ventanas sin correr cada día de nuevo.
PROB_CADA_DIAS = 14
#: Una pérdida «grande» en la ventana.
PROB_PERDIDA_GRANDE = 0.2
#: Lo que se cuenta como empate con BTC (las curvas se guardan redondeadas).
EMPATE = 1e-4
#: Con menos ventanas que esto no se da ningún porcentaje.
PROB_MINIMO = 20


def _valor_en(curva, ms):
    """El valor de una curva el último día que no pasa de `ms` (o `None` si todavía no empezaba)."""
    i = bisect.bisect_right([t for t, _ in curva], ms)
    return curva[i - 1][1] if i > 0 else None


def _percentil(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))]


def probabilidades(dias, com, hasta_ms, diarias=None, perfiles=None, desde_ms=None):
    """Si empezabas cualquier día desde junio de 2018 (cada `PROB_CADA_DIAS`) y esperabas `dias`, qué tan seguido terminabas
    ganando, perdiendo más de `PROB_PERDIDA_GRANDE` o ganándole a comprar BTC, con el caso malo, el típico y el bueno (los
    percentiles 10, 50 y 90). Los holding se corren de nuevo desde cada inicio; la rotación, la tendencia y BTC se corren
    una vez y se miden en cada ventana. Es el pasado: la misma cuenta de «Comparar» repetida en cientos de inicios."""
    import datetime
    perfiles = perfiles or [p for p in lib_perfiles.ORDEN if p != "holding"]
    largo = int(dias) * lib_datos.DIA_MS
    desde = desde_ms or int(datetime.datetime(*MAPA_DESDE, 1, tzinfo=datetime.timezone.utc).timestamp() * 1000)
    inicios = list(range(desde, hasta_ms - largo + 1, PROB_CADA_DIAS * lib_datos.DIA_MS))
    pares = dict.fromkeys(x for p in perfiles for x in lib_perfiles.pares_de(p))
    pares[lib_indicadores_mercado.CONTEXTO_PAR] = None
    diarias = diarias if diarias is not None else _diarias_de(pares)
    btc = [[v[0], v[4]] for v in diarias.get(lib_indicadores_mercado.CONTEXTO_PAR) or [] if v[0] <= hasta_ms]
    unicas = {perfil: (_curva_de(perfil, 100.0, inicios[0], hasta_ms, com, diarias).get("curva") or []) if inicios else []
              for perfil in ("rotacion", "tendencia")}

    def multiplico(perfil, i):
        p = lib_perfiles.de(perfil)
        if p["tipo"] in ("rotar", "tendencia"):
            a, b = _valor_en(unicas[perfil], i), _valor_en(unicas[perfil], i + largo)
            return b / a if a and b else None
        _, recortado = inicio_posible(perfil, i, diarias)
        if recortado:
            return None
        r = lib_holding.simular(1.0, {k: diarias.get(k) or [] for k in p["reparto"]}, i, i + largo, p, com)
        return r["saldo"] if r.get("listo") else None

    def resumen(veces, contra):
        if len(veces) < PROB_MINIMO:
            return {"n": len(veces), "listo": False}
        return {"n": len(veces), "listo": True,
                "gana": sum(1 for x in veces if x > 1) / len(veces),
                "pierde_grande": sum(1 for x in veces if x < 1 - PROB_PERDIDA_GRANDE) / len(veces),
                "gana_btc": (sum(1 for x, b in zip(veces, contra) if b is not None and x > b * (1 + EMPATE)) / len(veces)) if contra else None,
                "malo": _percentil(veces, 0.1) - 1, "tipico": _percentil(veces, 0.5) - 1, "bueno": _percentil(veces, 0.9) - 1}

    ref = {}
    for i in inicios:
        a, b = _valor_en(btc, i), _valor_en(btc, i + largo)
        ref[i] = b / a if a and b else None
    filas = []
    for perfil in perfiles:
        p = lib_perfiles.de(perfil)
        comps = p["componentes"] if p["tipo"] == "mezcla" else ((perfil, 1.0),)
        veces, contra = [], []
        for i in inicios:
            trozos = [multiplico(c, i) for c, _ in comps]
            if any(x is None for x in trozos):
                continue
            veces.append(sum(w * x for (_, w), x in zip(comps, trozos)))
            contra.append(ref[i])
        filas.append({"perfil": perfil, **resumen(veces, contra)})
    veces_btc = [x for x in ref.values() if x is not None]
    return {"formato": 1, "dias": int(dias), "hasta_ms": hasta_ms, "cada_dias": PROB_CADA_DIAS,
            "perdida_grande": PROB_PERDIDA_GRANDE, "filas": filas, "btc": resumen(veces_btc, None)}


def holding_variante(perfil, monto, desde_ms, hasta_ms, com, diarias=None):
    """Una variante de holding (`lib_holding`) sobre el pasado, con las velas diarias de sus monedas contra USDT. Si sus
    acciones todavía no estaban en Binance al inicio, empieza cuando llegan y lo dice (`recorte`)."""
    p = lib_perfiles.de(perfil)
    diarias = diarias if diarias is not None else _diarias_de(p["reparto"])
    inicio, recortado = inicio_posible(perfil, desde_ms, diarias)
    r = lib_holding.simular(monto, diarias, inicio, hasta_ms, p, com)
    if r.get("listo") and recortado:
        r.update(desde_ms=inicio, recorte="acciones")
    if r.get("listo"):
        r["curva"] = ralear(r["curva"])
        r["movimientos"] = r["movimientos"][-MOVIMIENTOS:]
        r.pop("libro", None)
    return r


def ops_de(pares, temporalidad, com=None, minutos=None, desde_ms=None):
    """Las operaciones que habrían dado las reglas de siempre en esas monedas y esa vela, con los costos de cada una (contra
    USDT no hay conversión). Las de 5 m se arman con las de 1 m (solo hay los últimos `lib_datos.DIAS_MINUTOS` días)."""
    btc = lib_datos.leer_serie(lib_indicadores_mercado.CONTEXTO_PAR, lib_estrategias.TEMPORALIDAD_DIARIA)
    filtro = lib_estrategias.filtro_en(btc) if len(btc) >= backtest.VELAS_MINIMAS else None
    modelo = lib_costos.modelo()
    paso = lib_datos.PASO_MS[temporalidad]
    ops = []
    for par in pares:
        dia = lib_datos.leer_serie(lib_estrategias.PAR_DIARIO.get(par, par), lib_estrategias.TEMPORALIDAD_DIARIA)
        al_alza = lib_estrategias.al_alza_en(dia) if len(dia) >= backtest.VELAS_MINIMAS else None
        if temporalidad in lib_perfiles.AGRUPADAS:
            uno = (minutos or {}).get(par) if minutos is not None else lib_datos.leer_serie(par, lib_datos.MINUTO)
            velas = lib_perfiles.agrupar(uno or [], lib_perfiles.AGRUPADAS[temporalidad])
        else:
            velas = lib_datos.leer_serie(par, temporalidad)
        if desde_ms:                         # lo justo para que los indicadores lleguen calientes al período
            velas = [v for v in velas if v[0] >= desde_ms - 400 * paso]
        if len(velas) < backtest.VELAS_MINIMAS:
            continue
        senales = backtest.senales_de(par, temporalidad, velas, al_alza=al_alza, filtro=filtro)
        c = lib_universo.comisiones_de(par, com)
        ops.extend(backtest.recorrer(velas, senales, lib_costos.spread_de(modelo, par), c))
    return [o for o in ops if not o.get("motivo") and o.get("llenada") and o.get("permitida")
            and o.get("neto") is not None]


def ops_rapidas(temporalidad="5m", com=None, minutos=None, pares=None):
    """Las operaciones del perfil más rápido (velas de 5 m armadas con las de 1 m)."""
    return ops_de(pares or lib_perfiles.pares_de("scalper"), temporalidad, com, minutos)


def _noticia_btc(p):
    """Si el perfil frena con noticias: una función que dice si hubo una mala noticia de BTC en los últimos días."""
    if not p.get("noticias"):
        return None
    datos = lib_influencia.cargar()
    return lambda ms: bool(lib_influencia.negativas(ms, ["BTCUSDT"], p.get("dias_freno", 5), datos))


def rotacion(monto, desde, hasta, com, diarias=None, btc=None):
    """La rotación (`lib_rotacion`) sobre el pasado, con las 8 monedas del robot."""
    p = lib_perfiles.de("rotacion")
    pares = lib_perfiles.pares_de("rotacion")
    diarias = diarias if diarias is not None else {par: lib_datos.leer_serie(par, "1d") for par in pares}
    btc = btc if btc is not None else lib_datos.leer_serie(lib_indicadores_mercado.CONTEXTO_PAR, "1d")
    r = lib_rotacion.simular(monto, {k: v for k, v in diarias.items() if v}, btc, desde, hasta,
                             lib_universo.comisiones_de("USDT", com), posiciones=p["posiciones"], dias=p["dias_fuerza"],
                             media=p["media"], margen=p["margen"], golpe=p.get("golpe"), dias_freno=p.get("dias_freno", 5),
                             noticia=_noticia_btc(p))
    if r.get("listo"):
        r["curva"] = ralear(r["curva"])
        r["movimientos"] = r["movimientos"][-MOVIMIENTOS:]
        r.pop("tenencias", None)
    return r


def comparar(monto, dias, recorrido, minimo=None, rapidas=None):
    """Los cinco perfiles con el mismo monto y el mismo período, lado a lado, cada uno con su película de movimientos.
    Sin tope de monto: es para ver cómo opera cada uno, y la pantalla lo dice."""
    base = simular(monto, dias, recorrido, minimo)
    if base.get("motivo") in ("sin_monto", "sin_periodo", "sin_minimos", "sin_historial"):
        return {**base, "perfiles": []}
    monto, desde, hasta = base["monto"], base["desde_ms"], base["hasta_ms"]
    pares, _ = lib_tamano.filtros_de(minimo)
    com = base["comisiones"]
    salida = []
    for perfil in lib_perfiles.ORDEN:
        p = lib_perfiles.de(perfil)
        if p["tipo"] in ("acumular", "mezcla"):
            if p["tipo"] == "mezcla":
                r = mezcla(perfil, monto, desde, hasta, com)
            else:
                r = holding_variante(perfil, monto, desde, hasta, com) if p.get("variante") else holding(monto, desde, hasta, com)
            salida.append({"perfil": perfil, "desde_ms": desde, "hasta_ms": hasta, **r,
                           "recortado": bool(r.get("recorte"))})
            continue
        if p["tipo"] in ("rotar", "tendencia"):
            r = rotacion(monto, desde, hasta, com) if p["tipo"] == "rotar" else tendencia(perfil, monto, desde, hasta, com)
            salida.append({"perfil": perfil, "desde_ms": desde, "hasta_ms": hasta, "recortado": False, **r})
            continue
        d, recortado = desde, False
        if p.get("dias_max"):
            d = max(desde, hasta - p["dias_max"] * lib_datos.DIA_MS)
            recortado = d > desde
            propias = rapidas if rapidas is not None else ops_rapidas(p["temporalidades"][0], com)
        else:
            propias = [o for t in p["temporalidades"] for o in ops_de(lib_perfiles.pares_de(perfil), t, com, desde_ms=d)]
        r = cartera(propias, monto, pares, com, None, d, hasta, perfil=perfil)
        salida.append({"perfil": perfil, "desde_ms": d, "hasta_ms": hasta, "recortado": recortado,
                       "listo": r["operaciones"] > 0, "motivo": "" if r["operaciones"] > 0 else "sin_operaciones", **r})
    return {**base, "perfiles": salida, "sugerido": lib_perfiles.SUGERIDO}


def parametros():
    return {"periodos": list(PERIODOS), "periodo_sugerido": PERIODO_SUGERIDO, "monto_sugerido": MONTO_SUGERIDO,
            "monto_minimo": MONTO_MINIMO, "monto_maximo": MONTO_MAXIMO, "motivos": list(MOTIVOS)}
