#!/usr/bin/env python3
"""lib_rotacion — tener las monedas más fuertes y cambiarlas cuando otra las pasa. Solo biblioteca estándar. No es una acción.

Es la forma de «cambiar BTC por SOL si SOL viene mejor» sin adivinar: una regla escrita, la misma en el pasado (Comparar) y
en vivo (`lib_piloto`), que se puede medir.

Cada día, al cerrar la vela diaria:
1. **La fuerza de cada moneda** (`fuerza`): cuánto subió en los últimos `dias_fuerza` días, dividido por cuánto se movió
   (la desviación de sus subidas y bajadas diarias). Una moneda que subió parejo vale más que una que subió a saltos.
2. **Solo las que están en forma** (`elegible`): sobre su media de `media` días y con fuerza positiva. Una moneda que cae no
   se compra aunque caiga menos que las otras.
3. **BTC manda** (`lib_estrategias.filtro_en`, el mismo filtro de siempre): si BTC viene cayendo, todo a USDT.
4. **Las `posiciones` más fuertes** (`elegir`). Una que ya se tiene se queda mientras siga en forma y entre las
   `posiciones + margen` primeras: así no se cambia por una diferencia mínima y no se pagan comisiones de más.

Lo que no se negocia aquí:
- **Nunca se mira el futuro**: la fuerza y el filtro salen de velas diarias ya cerradas, y se compra al precio de después.
- **Cada cambio paga lo que cuesta** (`comisiones` taker de los dos lados y la diferencia entre compra y venta).
- **No hay stop por operación**: lo que la saca es salir del ranking, caer bajo su media o el filtro de BTC. Por eso puede
  caer más que los perfiles de señales antes de salir, y la pantalla lo dice.
"""
import bisect
import math

import lib_estrategias

DIA_MS = 86_400_000


def _media(xs):
    return sum(xs) / len(xs) if xs else 0.0


def fuerza(cierres, dias=30, media=50):
    """La fuerza de una moneda con sus cierres diarios (el último es el de hoy, cerrado). `None` si no hay velas suficientes."""
    if len(cierres) < max(dias, media) + 1:
        return None
    tramo = cierres[-dias - 1:]
    cambios = [tramo[i] / tramo[i - 1] - 1 for i in range(1, len(tramo)) if tramo[i - 1] > 0]
    retorno = tramo[-1] / tramo[0] - 1 if tramo[0] > 0 else 0.0
    m = _media(cambios)
    desvio = math.sqrt(_media([(c - m) ** 2 for c in cambios])) if cambios else 0.0
    sobre = cierres[-1] > _media(cierres[-media:])
    valor = retorno / (desvio * math.sqrt(dias)) if desvio > 0 else 0.0
    return {"fuerza": valor, "retorno": retorno, "volatilidad": desvio, "sobre_media": sobre,
            "elegible": sobre and retorno > 0}


def cerradas_antes(velas, ms):
    """Las velas diarias que ya cerraron antes de `ms`."""
    i = bisect.bisect_right([v[0] for v in velas], ms - DIA_MS) if len(velas) < 64 else _corte(velas, ms - DIA_MS)
    return velas[:i]


def _corte(velas, hasta):
    """Cuántas velas empiezan en `hasta` o antes (búsqueda binaria: las velas vienen ordenadas)."""
    lo, hi = 0, len(velas)
    while lo < hi:
        m = (lo + hi) // 2
        if velas[m][0] <= hasta:
            lo = m + 1
        else:
            hi = m
    return lo


def ranking(diarias, ms, dias=30, media=50):
    """Las monedas ordenadas de la más fuerte a la más débil, con lo que se miró de cada una. `diarias`: {par: velas 1d}."""
    filas = []
    for par, velas in diarias.items():
        f = fuerza([v[4] for v in cerradas_antes(velas, ms)], dias, media)
        if f is not None:
            filas.append({"par": par, **f})
    filas.sort(key=lambda x: (-x["fuerza"], x["par"]))
    for i, f in enumerate(filas):
        f["puesto"] = i + 1
    return filas


def golpe_en(cierres, golpe, dias):
    """La peor caída de un día en los últimos `dias` cierres si fue de `golpe` o más (por ejemplo −0,07), o `None`."""
    if not golpe or len(cierres) < 2:
        return None
    peor = min(cierres[i] / cierres[i - 1] - 1 for i in range(max(1, len(cierres) - dias), len(cierres)))
    return peor if peor <= -golpe else None


def golpeadas(diarias, ms, golpe, dias):
    """Las monedas que tuvieron un día de `golpe` o peor en los últimos `dias` días cerrados antes de `ms`."""
    if not golpe:
        return {}
    salida = {}
    for par, velas in diarias.items():
        cerradas = cerradas_antes(velas, ms)[-dias - 1:]
        caida = golpe_en([v[4] for v in cerradas], golpe, dias)
        if caida is not None:
            salida[par] = caida
    return salida


def elegir(filas, actuales, posiciones=2, margen=1, filtro_pasa=True, bloqueadas=()):
    """Qué monedas tener ahora. Sin el permiso de BTC, ninguna. Las `bloqueadas` (un golpe reciente) no entran, pero si ya
    se tienen, se mantienen."""
    if not filtro_pasa:
        return []
    puesto = {f["par"]: f for f in filas}
    quedan = [p for p in actuales if p in puesto and puesto[p]["elegible"] and puesto[p]["puesto"] <= posiciones + margen]
    for f in filas:
        if len(quedan) >= posiciones:
            break
        if f["elegible"] and f["par"] not in quedan and f["par"] not in bloqueadas:
            quedan.append(f["par"])
    return quedan[:posiciones]


def simular(monto, diarias, btc, desde_ms, hasta_ms, com, spread=0.0005, posiciones=2, dias=30, media=50, margen=1,
            golpe=None, dias_freno=5, noticia=None):
    """La rotación sobre el pasado, día por día: el saldo, la curva y cada compra y venta. Pura (no lee el disco).
    Los frenos de la tendencia (estudio de nov 2026): no entra a una moneda con un día de `golpe` o peor en los últimos
    `dias_freno`, y si `noticia(ms)` dice que hubo una mala noticia de BTC, todo a USDT (como el filtro de BTC)."""
    filtro = lib_estrategias.filtro_en(btc)
    taker = (com or {}).get("taker", 0.001)
    dias_ms = sorted({v[0] for velas in diarias.values() for v in velas if desde_ms <= v[0] <= hasta_ms})
    precio = {par: {v[0]: v[4] for v in velas} for par, velas in diarias.items()}
    efectivo, tenencias, movimientos, curva = float(monto), {}, [], []
    techo, caida = float(monto), 0.0
    for d in dias_ms:
        ms = d + DIA_MS                     # se decide con la vela de este día ya cerrada
        filas = ranking(diarias, ms, dias, media)
        pasa = filtro(ms).get("pasa") and not (noticia and noticia(ms))
        objetivo = elegir(filas, list(tenencias), posiciones, margen, pasa, golpeadas(diarias, ms, golpe, dias_freno))
        for par in [p for p in tenencias if p not in objetivo]:
            p = precio[par].get(d)
            if not p:
                continue
            venta = p * (1 - spread)
            recibido = tenencias[par]["cantidad"] * venta * (1 - taker)
            efectivo += recibido
            movimientos.append({"ms": ms, "que": "venta", "par": par, "precio": venta, "monto": recibido,
                                "ganancia": recibido - tenencias[par]["costo"], "saldo": None, "por": "rotacion",
                                "estrategia": "rotacion", "temporalidad": "1d"})
            del tenencias[par]
        libres = [p for p in objetivo if p not in tenencias]
        for i, par in enumerate(libres):
            p = precio[par].get(d)
            if not p:
                continue
            gasto = efectivo / (len(libres) - i)
            compra = p * (1 + spread)
            tenencias[par] = {"cantidad": gasto * (1 - taker) / compra, "costo": gasto}
            efectivo -= gasto
            movimientos.append({"ms": ms, "que": "compra", "par": par, "precio": compra, "monto": gasto,
                                "estrategia": "rotacion", "temporalidad": "1d"})
        valor = efectivo + sum(t["cantidad"] * (precio[par].get(d) or 0) for par, t in tenencias.items())
        for m in movimientos:
            if m["que"] == "venta" and m["saldo"] is None:
                m["saldo"] = valor
        techo = max(techo, valor)
        caida = max(caida, (techo - valor) / techo if techo > 0 else 0.0)
        curva.append([int(d), round(valor, 6)])
    if not curva:
        return {"listo": False, "motivo": "sin_historial"}
    saldo = curva[-1][1]
    ventas = [m for m in movimientos if m["que"] == "venta"]
    return {"listo": True, "motivo": "", "saldo": saldo, "ganancia": saldo - monto, "rendimiento": saldo / monto - 1,
            "caida_maxima": caida, "curva": curva, "operaciones": len(ventas),
            "ganadas": sum(1 for m in ventas if m["ganancia"] > 0), "perdidas": sum(1 for m in ventas if m["ganancia"] <= 0),
            "movimientos": movimientos, "movimientos_total": len(movimientos), "tenencias": tenencias}
