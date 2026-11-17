#!/usr/bin/env python3
"""lib_holding — las formas de holdear: comprar por partes y quedarse, con variantes. Solo biblioteca estándar. No es una acción.

Un holding compra monedas por partes, una vez por semana, y las guarda. Las variantes cambian una sola cosa cada una:

| regla | qué hace |
|---|---|
| `reparto` | qué monedas y en qué proporción (contra USDT) |
| `partes`, `cada_ms` | en cuántas compras se reparte el monto y cada cuánto |
| `descuento` | cada compra se deja como orden **un poco más abajo** del cierre; si el día siguiente el precio no llega, se compra a ese cierre igual (nunca se salta una semana) |
| `rebalanceo` | `{"cripto", "banda"}`: qué parte del dinero va en monedas; si sube de la banda se vende el sobrante, si baja se compra lo que falta |
| `cosecha` | `{"sube", "vende", "recompra"}`: cuando una moneda sube `sube` sobre lo que costó, se vende la parte `vende` y se espera; si después cae `recompra` desde esa venta, se vuelve a comprar con esa plata |

`paso` es **un día**: lo usan igual la comparación con el pasado (`simular`) y el robot en vivo (`lib_piloto`), así lo que se ve en
vivo es lo mismo que se midió. Recibe el cierre y el mínimo de ese día de cada moneda y mueve el libro `h` (efectivo, cantidades,
costo, compras esperando y plata guardada de la cosecha).

Lo que no se negocia aquí:
- **Nunca se mira el futuro**: la orden más abajo se pone con el cierre de hoy y solo se llena con el mínimo de **mañana**.
- **Cada compra y cada venta paga** la comisión taker y la diferencia de puntas (`spread`).
- **Es puro**: no lee el disco ni la red.
"""
import lib_rotacion

DIA_MS = lib_rotacion.DIA_MS
SEMANA_MS = 7 * DIA_MS
SPREAD = 0.0005


def nuevo(monto):
    return {"efectivo": float(monto), "monto": float(monto), "tenencias": {}, "costo": {}, "partes": 0, "ultima_ms": 0,
            "revision_ms": 0, "pendiente": {}, "guardado": {}}


def _libre(h):
    """La plata que se puede usar: el efectivo menos lo comprometido en órdenes y lo guardado de la cosecha."""
    return h["efectivo"] - sum(x["monto"] for x in h["pendiente"].values()) - sum(x["monto"] for x in h["guardado"].values())


def valor(h, precios):
    return h["efectivo"] + sum(q * precios.get(par, 0.0) for par, q in h["tenencias"].items())


def _comprar(h, par, gasto, precio, ms, taker, spread, por):
    gasto = min(gasto, h["efectivo"])
    if gasto <= 1e-9 or not precio:
        return None
    pagado = precio * (1 + spread)
    cantidad = gasto * (1 - taker) / pagado
    h["efectivo"] -= gasto
    h["tenencias"][par] = h["tenencias"].get(par, 0.0) + cantidad
    h["costo"][par] = h["costo"].get(par, 0.0) + gasto
    return {"ms": ms, "que": "compra", "par": par, "precio": pagado, "cantidad": cantidad, "monto": gasto, "por": por,
            "comision": gasto * taker}


def _vender(h, par, cantidad, precio, ms, taker, spread, por):
    tiene = h["tenencias"].get(par, 0.0)
    cantidad = min(cantidad, tiene)
    if cantidad <= 1e-12 or not precio:
        return None
    cobrado = precio * (1 - spread)
    recibe = cantidad * cobrado * (1 - taker)
    base = h["costo"].get(par, 0.0) * cantidad / tiene
    h["tenencias"][par] = tiene - cantidad
    h["costo"][par] = h["costo"].get(par, 0.0) - base
    if h["tenencias"][par] <= 1e-12:
        h["tenencias"].pop(par)
        h["costo"].pop(par, None)
    h["efectivo"] += recibe
    return {"ms": ms, "que": "venta", "par": par, "precio": cobrado, "cantidad": cantidad, "monto": recibe,
            "ganancia": recibe - base, "por": por, "comision": cantidad * cobrado * taker}


def paso(h, ms, cierre, bajo, reglas, taker=0.001, spread=SPREAD):
    """Un día del holding, con el cierre (`cierre[par]`) y el mínimo (`bajo[par]`) de ese día. Devuelve los movimientos."""
    movs = []
    reparto = reglas["reparto"]
    # 1. Las órdenes puestas más abajo: se llenan si hoy el precio llegó; si no, al cierre de hoy (no se salta la semana).
    for par, o in list(h["pendiente"].items()):
        if ms <= o["desde_ms"] or par not in cierre:
            continue
        del h["pendiente"][par]
        llena = bajo.get(par) is not None and bajo[par] <= o["limite"]
        m = _comprar(h, par, o["monto"], o["limite"] if llena else cierre[par], ms, taker, 0.0 if llena else spread,
                     "limite" if llena else "cierre")
        if m:
            movs.append(m)
    # 2. La compra de la semana.
    if h["partes"] < reglas["partes"] and (not h["ultima_ms"] or ms - h["ultima_ms"] >= reglas.get("cada_ms", SEMANA_MS)):
        if all(par in cierre for par in reparto):
            quedan = reglas["partes"] - h["partes"]
            meta = h["monto"] * (reglas.get("rebalanceo") or {}).get("cripto", 1.0)
            puesto = sum(h["costo"].values()) + sum(x["monto"] for x in h["pendiente"].values())
            parte = max(0.0, min(_libre(h), (meta - puesto) / quedan))
            for par, peso in reparto.items():
                if reglas.get("descuento"):
                    h["pendiente"][par] = {"monto": parte * peso, "limite": cierre[par] * (1 - reglas["descuento"]),
                                           "desde_ms": ms}
                else:
                    m = _comprar(h, par, parte * peso, cierre[par], ms, taker, spread, "semana")
                    if m:
                        movs.append(m)
            h["partes"] += 1
            h["ultima_ms"] = ms
    terminado = h["partes"] >= reglas["partes"] and not h["pendiente"]
    # 3. El rebalanceo, una vez por semana y recién con todas las partes compradas.
    rb = reglas.get("rebalanceo")
    if rb and terminado and ms - h.get("revision_ms", 0) >= reglas.get("cada_ms", SEMANA_MS):
        h["revision_ms"] = ms
        total = valor(h, cierre)
        en_cripto = total - h["efectivo"]
        parte = en_cripto / total if total > 0 else 0.0
        if parte > rb["cripto"] + rb["banda"]:
            sobra = en_cripto - rb["cripto"] * total
            for par, q in list(h["tenencias"].items()):
                vale = q * cierre.get(par, 0.0)
                m = _vender(h, par, q * (sobra * vale / en_cripto) / vale if vale else 0, cierre.get(par), ms, taker,
                            spread, "rebalanceo")
                if m:
                    movs.append(m)
        elif parte < rb["cripto"] - rb["banda"]:
            falta = min(rb["cripto"] * total - en_cripto, _libre(h))
            for par, peso in reparto.items():
                m = _comprar(h, par, falta * peso, cierre.get(par), ms, taker, spread, "rebalanceo")
                if m:
                    movs.append(m)
    # 4. La cosecha: vender una parte cuando subió harto, y recomprar con esa plata si después cae.
    co = reglas.get("cosecha")
    if co:
        for par in list(reparto):
            p = cierre.get(par)
            if not p:
                continue
            g = h["guardado"].get(par)
            if g:
                if p <= g["precio"] * (1 - co["recompra"]):
                    del h["guardado"][par]
                    m = _comprar(h, par, g["monto"], p, ms, taker, spread, "recompra")
                    if m:
                        movs.append(m)
                continue
            q = h["tenencias"].get(par, 0.0)
            if q > 0 and p >= h["costo"][par] / q * (1 + co["sube"]):
                m = _vender(h, par, q * co["vende"], p, ms, taker, spread, "cosecha")
                if m:
                    h["guardado"][par] = {"monto": m["monto"], "precio": p}
                    movs.append(m)
    return movs


def simular(monto, diarias, desde_ms, hasta_ms, reglas, com=None, spread=SPREAD):
    """El holding sobre el pasado, día por día. `diarias`: {par: velas 1d}. Devuelve lo mismo que las demás simulaciones."""
    taker = (com or {}).get("taker", 0.001)
    cierres = {par: {v[0]: v[4] for v in velas} for par, velas in diarias.items()}
    minimos = {par: {v[0]: v[3] for v in velas} for par, velas in diarias.items()}
    dias = sorted({t for par in reglas["reparto"] for t in cierres.get(par, {}) if desde_ms <= t <= hasta_ms})
    if len(dias) < 2 or any(par not in cierres for par in reglas["reparto"]):
        return {"listo": False, "motivo": "sin_historial"}
    h = nuevo(monto)
    curva, movimientos, techo, caida, ultimo = [], [], float(monto), 0.0, {}
    for d in dias:
        hoy = {par: c[d] for par, c in cierres.items() if d in c}
        ultimo.update(hoy)
        movs = paso(h, d, hoy, {par: m[d] for par, m in minimos.items() if d in m}, reglas, taker, spread)
        v = valor(h, ultimo)
        for m in movs:
            m["saldo"] = v
            m.setdefault("estrategia", "holding")
            m.setdefault("temporalidad", "1d")
        movimientos += movs
        techo = max(techo, v)
        caida = max(caida, (techo - v) / techo if techo > 0 else 0.0)
        curva.append([int(d), round(v, 6)])
    saldo = curva[-1][1]
    ventas = [m for m in movimientos if m["que"] == "venta"]
    return {"listo": True, "motivo": "", "saldo": saldo, "ganancia": saldo - monto, "rendimiento": saldo / monto - 1,
            "caida_maxima": caida, "curva": curva, "operaciones": len(movimientos),
            "ganadas": sum(1 for m in ventas if m["ganancia"] > 0), "perdidas": sum(1 for m in ventas if m["ganancia"] <= 0),
            "movimientos": movimientos, "movimientos_total": len(movimientos), "libro": h}
