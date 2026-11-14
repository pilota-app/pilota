#!/usr/bin/env python3
"""lib_tendencia — seguir la tendencia y ajustar el tamaño a cuánto se mueve el mercado. Solo biblioteca estándar.
No es una acción.

Lo que hacen hace décadas los fondos que operan con reglas, en tres ideas:
1. **Seguir la tendencia** (`pesos_tendencia`): una moneda se tiene mientras su cierre está sobre su media de `media` días y
   esa media sube. Cuando lo pierde, se vende. No se adivina el techo ni el piso.
2. **Rotar a lo más fuerte** (`pesos_rotacion`): la regla de `lib_rotacion`, con el tamaño de abajo.
3. **El tamaño según cuánto se mueve** (`tamano`): cada cupo tiene su parte del capital cuando la moneda se mueve como
   `objetivo` (volatilidad anual); si se mueve más, se pone menos y el resto queda en USDT. Así una moneda nerviosa no
   decide sola cuánto se pierde.

Todo sale de velas diarias cerradas. `simular` recorre el pasado día por día con la misma regla que se usaría en vivo:
decide con el cierre de ayer, compra y vende a ese precio con la diferencia de puntas y la comisión taker, y solo
reajusta una posición si el cambio pasa de `umbral` (para no pagar comisiones por centavos).

`pesos_cruce` es la regla del perfil «tendencia» (`lib_perfiles`): cada moneda con su parte mientras cierra sobre su media
de 50 días. `paso` es un día, y lo usan igual `simular` y el robot en vivo (`lib_piloto._vuelta_tendencia`).

Lo que no se negocia aquí:
- **Nunca se mira el futuro**: cada decisión usa solo las velas que ya cerraron antes de ese día.
- **Cada movimiento paga lo que cuesta.**
- **Es puro**: no lee el disco ni la red. Recibe las velas y devuelve números.
"""
import bisect
import inspect
import math

import lib_rotacion

DIA_MS = lib_rotacion.DIA_MS
#: Cuántos días de volatilidad se miran para el tamaño.
DIAS_VOLATILIDAD = 30
#: Cuántos días atrás se compara la media para saber si sube.
PENDIENTE = 20
ANUAL = math.sqrt(365)
#: Lo que se pierde entre la punta de compra y la de venta en cada movimiento.
SPREAD = 0.0005


def _media(xs):
    return sum(xs) / len(xs) if xs else 0.0


def volatilidad(cierres, dias=DIAS_VOLATILIDAD):
    """Cuánto se mueve una moneda: la desviación de sus cambios diarios en `dias`, llevada a un año. `None` sin datos."""
    tramo = cierres[-dias - 1:]
    if len(tramo) < dias + 1:
        return None
    cambios = [tramo[i] / tramo[i - 1] - 1 for i in range(1, len(tramo)) if tramo[i - 1] > 0]
    m = _media(cambios)
    return math.sqrt(_media([(c - m) ** 2 for c in cambios])) * ANUAL if cambios else None


def tamano(cupos, vol, objetivo=None):
    """La parte del capital de un cupo: 1/cupos, achicada si la moneda se mueve más que `objetivo`. Sin objetivo, entera."""
    if cupos <= 0:
        return 0.0
    if not objetivo or not vol:
        return 1.0 / cupos
    return min(1.0, objetivo / vol) / cupos


def en_tendencia(cierres, media):
    """Si una moneda está en tendencia: cierre sobre su media de `media` días y esa media más alta que hace `PENDIENTE`."""
    if len(cierres) < media + PENDIENTE:
        return False
    ahora = _media(cierres[-media:])
    antes = _media(cierres[-media - PENDIENTE:-PENDIENTE])
    return cierres[-1] > ahora and ahora > antes


def pesos_tendencia(tramos, media=100, objetivo=None, cupos=None):
    """La parte del capital en cada moneda: las que están en tendencia, cada una con su cupo. `tramos`: {par: cierres}."""
    cupos = cupos or len(tramos)
    salida = {}
    for par, c in tramos.items():
        if en_tendencia(c, media):
            salida[par] = tamano(cupos, volatilidad(c), objetivo)
    return salida


def sobre_media(cierres, media):
    """El cierre de hoy y su media de `media` días, o `None` si todavía no hay tantos días."""
    if len(cierres) < media:
        return None
    return {"precio": cierres[-1], "media": _media(cierres[-media:]), "sobre": cierres[-1] > _media(cierres[-media:])}


golpe_en = lib_rotacion.golpe_en


def filas_cruce(tramos, reparto, media=50, actuales=(), golpe=None, dias_freno=5, noticias=None):
    """Cada moneda del reparto con su precio, su media y la parte que le toca: la suya si cierra sobre la media y nada si
    cierra bajo. Dos frenos más, medidos en el estudio de nov 2026 (ver AGENTS.md):
    - `golpe`: si en los últimos `dias_freno` días hubo un día que cayó `golpe` o más, no compra (lo que ya tiene, lo
      mantiene). Es la huella de una mala noticia en el precio.
    - `noticias`: {par: noticia} de personas influyentes que bajaron el precio en los últimos días: esa parte espera en USDT.
    `motivo` dice por qué una parte quedó en cero. `None` si a alguna le falta historia (no se decide con media regla)."""
    filas = []
    for par, peso in reparto.items():
        m = sobre_media(tramos.get(par) or [], media)
        if m is None:
            return None
        caida = golpe_en(tramos.get(par) or [], golpe, dias_freno)
        noticia = (noticias or {}).get(par)
        if not m["sobre"]:
            parte, motivo = 0.0, "bajo_media"
        elif noticia:
            parte, motivo = 0.0, "noticia"
        elif caida is not None and par not in actuales:
            parte, motivo = 0.0, "golpe"
        else:
            parte, motivo = peso, None
        filas.append({"par": par, **m, "parte": parte, "reparto": peso, "motivo": motivo, "golpe": caida,
                      "noticia": noticia})
    return filas


def historia_cruce(cierres, media=50, horizonte=20, caida=0.10):
    """Lo que pasó antes cuando la moneda estaba del mismo lado de su media que hoy: en cuántos de esos días el precio
    subió `horizonte` días después, cuánto en promedio y en cuántos cayó más de `caida` en el camino. `cierres` son los
    cierres diarios de toda la historia guardada, el último es hoy. `None` si hay menos de 100 días comparables."""
    if len(cierres) < media + horizonte + 100:
        return None
    sumas = [0.0]
    for x in cierres:
        sumas.append(sumas[-1] + x)
    lado_hoy = cierres[-1] > (sumas[-1] - sumas[-1 - media]) / media
    n = sube = cae = 0
    total = 0.0
    for i in range(media - 1, len(cierres) - horizonte):
        if (cierres[i] > (sumas[i + 1] - sumas[i + 1 - media]) / media) != lado_hoy:
            continue
        futuro = cierres[i + horizonte] / cierres[i] - 1
        peor = min(cierres[i + 1:i + horizonte + 1]) / cierres[i] - 1
        n += 1
        sube += futuro > 0
        cae += peor < -caida
        total += futuro
    if n < 100:
        return None
    return {"sobre": lado_hoy, "dias": n, "horizonte": horizonte, "sube": sube / n, "medio": total / n,
            "cae": cae / n, "caida": caida}


def pesos_cruce(tramos, reparto, media=50, actuales=(), golpe=None, dias_freno=5, noticias=None):
    """La regla del perfil tendencia: cada moneda con su parte del reparto mientras cierra sobre su media de `media` días;
    bajo la media, tras un golpe o tras una mala noticia, esa parte espera en USDT (ver `filas_cruce`)."""
    filas = filas_cruce(tramos, reparto, media, actuales, golpe, dias_freno, noticias)
    return {f["par"]: f["parte"] for f in filas or [] if f["parte"] > 0}


def pesos_rotacion(tramos, actuales, posiciones=2, margen=1, dias=30, media=50, objetivo=None, filtro_pasa=True):
    """Las `posiciones` más fuertes (`lib_rotacion`), cada una con su cupo achicado por la volatilidad."""
    filas = []
    for par, c in tramos.items():
        f = lib_rotacion.fuerza(c, dias, media)
        if f is not None:
            filas.append({"par": par, **f})
    filas.sort(key=lambda x: (-x["fuerza"], x["par"]))
    for i, f in enumerate(filas):
        f["puesto"] = i + 1
    elegidas = lib_rotacion.elegir(filas, list(actuales), posiciones, margen, filtro_pasa)
    return {par: tamano(posiciones, volatilidad(tramos[par]), objetivo) for par in elegidas}


def nuevo(monto):
    """Un libro vacío: todo en USDT."""
    return {"efectivo": float(monto), "cantidad": {}, "costo": {}}


def valor(libro, hoy):
    return libro["efectivo"] + sum(q * hoy.get(par, 0) for par, q in libro["cantidad"].items())


def paso(libro, ms, hoy, objetivo, taker, spread=SPREAD, umbral=0.02):
    """Un día: lleva el libro a la parte de cada moneda que pide `objetivo` ({par: parte del valor}), con los precios de
    `hoy`. Primero vende (lo que sale y lo que sobra) y después compra con lo que quedó. Solo reajusta lo que ya tiene si
    el cambio pasa de `umbral`. Lo usan igual `simular` y el robot en vivo. Devuelve los movimientos."""
    efectivo, cantidad, costo = libro["efectivo"], libro["cantidad"], libro["costo"]
    total = efectivo + sum(q * hoy.get(par, 0) for par, q in cantidad.items())
    movimientos = []
    # Primero se vende (lo que sale y lo que sobra) y después se compra con lo que quedó.
    for par in sorted(set(cantidad) | set(objetivo), key=lambda x: objetivo.get(x, 0)):
        p = hoy.get(par)
        if not p:
            continue
        ahora = cantidad.get(par, 0.0) * p
        quiero = objetivo.get(par, 0.0) * total
        diferencia = quiero - ahora
        sale, entra = quiero == 0 and ahora > 0, ahora == 0 and quiero > 0
        if not (sale or entra) and abs(diferencia) < umbral * total:
            continue
        if diferencia < 0:
            vende = min(cantidad.get(par, 0.0), -diferencia / p)
            recibe = vende * p * (1 - spread) * (1 - taker)
            base = costo.get(par, 0.0) * (vende / cantidad[par]) if cantidad.get(par) else 0.0
            cantidad[par] -= vende
            costo[par] = costo.get(par, 0.0) - base
            efectivo += recibe
            movimientos.append({"ms": ms, "que": "venta", "par": par, "precio": p * (1 - spread), "monto": recibe,
                                "ganancia": recibe - base, "saldo": None, "por": "tendencia", "cantidad": vende,
                                "comision": vende * p * (1 - spread) * taker})
            if cantidad[par] <= 1e-12:
                cantidad.pop(par)
                costo.pop(par, None)
    for par in sorted(objetivo, key=lambda x: -objetivo[x]):
        p = hoy.get(par)
        if not p:
            continue
        diferencia = objetivo[par] * total - cantidad.get(par, 0.0) * p
        entra = cantidad.get(par, 0.0) == 0
        if diferencia <= 0 or (not entra and diferencia < umbral * total):
            continue
        gasto = min(diferencia, efectivo)
        if gasto <= 0:
            continue
        cantidad[par] = cantidad.get(par, 0.0) + gasto * (1 - taker) / (p * (1 + spread))
        costo[par] = costo.get(par, 0.0) + gasto
        efectivo -= gasto
        movimientos.append({"ms": ms, "que": "compra", "par": par, "precio": p * (1 + spread), "monto": gasto,
                            "cantidad": gasto * (1 - taker) / (p * (1 + spread)), "comision": gasto * taker})
    libro["efectivo"] = efectivo
    return movimientos


# ── El pasado, día por día ───────────────────────────────────────────────────────────────────────────────────────────

def _series(diarias):
    return {par: ([v[0] for v in velas], [v[4] for v in velas]) for par, velas in diarias.items() if velas}


def tramos_en(series, ms, largo):
    """Los últimos `largo` cierres de cada moneda que cerraron antes de `ms`."""
    salida = {}
    for par, (ts, cierres) in series.items():
        i = bisect.bisect_right(ts, ms - DIA_MS)
        if i > 0:
            salida[par] = cierres[max(0, i - largo):i]
    return salida


def simular(monto, diarias, desde_ms, hasta_ms, com, regla, spread=SPREAD, umbral=0.02, largo=260, filtro=None):
    """Recorre el pasado con una regla de pesos. `regla(tramos, actuales, filtro_pasa) -> {par: parte}`.
    Devuelve el saldo, la curva, la peor caída, los movimientos y cuánto estuvo invertido en promedio."""
    taker = (com or {}).get("taker", 0.001)
    series = _series(diarias)
    precio = {par: dict(zip(ts, cierres)) for par, (ts, cierres) in series.items()}
    dias_ms = sorted({t for ts, _ in series.values() for t in ts if desde_ms <= t <= hasta_ms})
    usa_ms = "ms" in inspect.signature(regla).parameters     # la regla puede pedir el día (las noticias tienen fecha)
    libro = nuevo(monto)
    movimientos, curva, techo, caida, invertido = [], [], float(monto), 0.0, []
    for d in dias_ms:
        ms = d + DIA_MS
        hoy = {par: p[d] for par, p in precio.items() if d in p}
        pasa = filtro(ms).get("pasa") if filtro else True
        tramos = tramos_en(series, ms, largo)
        actuales = [p for p, q in libro["cantidad"].items() if q > 0]
        objetivo = (regla(tramos, actuales, pasa, ms=ms) if usa_ms else regla(tramos, actuales, pasa)) if valor(libro, hoy) > 0 else {}
        movimientos += paso(libro, ms, hoy, objetivo, taker, spread, umbral)
        v = valor(libro, hoy)
        for m in movimientos:
            if m["que"] == "venta" and m["saldo"] is None:
                m["saldo"] = v
        invertido.append(1 - libro["efectivo"] / v if v > 0 else 0.0)
        techo = max(techo, v)
        caida = max(caida, (techo - v) / techo if techo > 0 else 0.0)
        curva.append([int(d), round(v, 6)])
    if not curva:
        return {"listo": False, "motivo": "sin_historial"}
    saldo = curva[-1][1]
    ventas = [m for m in movimientos if m["que"] == "venta"]
    return {"listo": True, "motivo": "", "saldo": saldo, "ganancia": saldo - monto, "rendimiento": saldo / monto - 1,
            "caida_maxima": caida, "curva": curva, "operaciones": len(ventas),
            "ganadas": sum(1 for m in ventas if m["ganancia"] > 0), "perdidas": sum(1 for m in ventas if m["ganancia"] <= 0),
            "movimientos": movimientos, "movimientos_total": len(movimientos),
            "invertido_medio": _media(invertido)}
