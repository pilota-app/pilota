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
import lib_calibracion
import lib_costos
import lib_datos
import lib_estrategias
import lib_frenos
import lib_tamano

#: Los períodos que se pueden elegir, en días.
PERIODOS = (30, 90, 180, 365, 1095)
PERIODO_SUGERIDO = 90
MONTO_SUGERIDO = 100.0
MONTO_MINIMO = 10.0
MONTO_MAXIMO = 1_000_000.0
#: La curva se entrega con a lo más estos puntos (la pantalla la dibuja; más no se ve).
PUNTOS_CURVA = 160
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


def cartera(ops, monto, filtros, com=None, tope=None, desde_ms=None, hasta_ms=None):
    """Recorre `ops` (las del backtest) como una cartera que parte con `monto` USDT. Pura: no lee ni escribe nada.

    Devuelve el saldo final, la curva `[[ms, saldo], …]` y la cuenta de lo que pasó."""
    capital = float(monto)
    saldo, referencia, techo, caida = capital, capital, capital, 0.0
    piso_absoluto = capital * (1 - lib_frenos.PISO_ABSOLUTO)
    abiertas = []                     # [(salida_ms, nocional, neto)]
    curva = [[int(desde_ms or 0), round(saldo, 6)]] if desde_ms else []
    c = {"operaciones": 0, "ganadas": 0, "perdidas": 0, "saltadas": {"diario": 0, "racha": 0, "piso": 0,
         "posiciones": 0, "tamano": 0}, "terminada": False, "mejor": None, "peor": None}
    dia, inicio_dia, racha, pausa_dia = None, saldo, 0, None

    def cerrar_hasta(ms):
        nonlocal saldo, referencia, techo, caida, racha, abiertas
        quedan = []
        for salida, nocional, neto in sorted(abiertas):
            if salida > ms:
                quedan.append((salida, nocional, neto))
                continue
            ganancia = nocional * neto
            saldo += ganancia
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
        if len(abiertas) >= lib_frenos.POSICIONES:
            c["saltadas"]["posiciones"] += 1
            continue
        comprometido = sum(n for _, n, _ in abiertas)
        t = lib_tamano.tamano(saldo, o["nivel"], o["stop"], filtros.get(o["par"]) or {}, com, tope,
                              len(abiertas), comprometido)
        if not t.get("puede"):
            c["saltadas"]["tamano"] += 1
            continue
        abiertas.append((int(o["salida_ms"]), t["entrada"], o["neto"]))
        c["operaciones"] += 1
    if not c["terminada"]:
        cerrar_hasta(float("inf"))
    return {"saldo": saldo, "ganancia": saldo - capital, "rendimiento": (saldo - capital) / capital if capital else 0,
            "caida_maxima": caida, "curva": ralear(curva), **c}


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


def parametros():
    return {"periodos": list(PERIODOS), "periodo_sugerido": PERIODO_SUGERIDO, "monto_sugerido": MONTO_SUGERIDO,
            "monto_minimo": MONTO_MINIMO, "monto_maximo": MONTO_MAXIMO, "motivos": list(MOTIVOS)}
