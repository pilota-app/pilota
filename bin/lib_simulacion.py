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
import backtest
import lib_calibracion
import lib_costos
import lib_datos
import lib_estrategias
import lib_frenos
import lib_indicadores_mercado
import lib_perfiles
import lib_rotacion
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


def rotacion(monto, desde, hasta, com, diarias=None, btc=None):
    """La rotación (`lib_rotacion`) sobre el pasado, con las 8 monedas del robot."""
    p = lib_perfiles.de("rotacion")
    pares = lib_perfiles.pares_de("rotacion")
    diarias = diarias if diarias is not None else {par: lib_datos.leer_serie(par, "1d") for par in pares}
    btc = btc if btc is not None else lib_datos.leer_serie(lib_indicadores_mercado.CONTEXTO_PAR, "1d")
    r = lib_rotacion.simular(monto, {k: v for k, v in diarias.items() if v}, btc, desde, hasta,
                             lib_universo.comisiones_de("USDT", com), posiciones=p["posiciones"], dias=p["dias_fuerza"],
                             media=p["media"], margen=p["margen"])
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
        if p["tipo"] == "acumular":
            r = holding(monto, desde, hasta, com)
            salida.append({"perfil": perfil, "desde_ms": desde, "hasta_ms": hasta, "recortado": False, **r})
            continue
        if p["tipo"] == "rotar":
            r = rotacion(monto, desde, hasta, com)
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
