#!/usr/bin/env python3
"""lib_perfiles — las cinco formas de operar de Pilota. Solo biblioteca estándar. No es una acción.

Un perfil es un juego de reglas, no una opinión. Los mismos números se usan en las dos partes:
- en **Comparar** (el pasado, `lib_simulacion`), y
- en la **prueba en vivo** (`lib_piloto`).
Así lo que se ve en vivo es coherente con lo que mostró la comparación.

| perfil | qué hace | velas | ganancia/riesgo mínima | riesgo por operación | posiciones |
|---|---|---|---|---|---|
| holding | compra BTC y ETH por partes, una por semana, y mantiene | 1 d | — | — | — |
| conservador | pocas operaciones, solo las muy claras | 4 h | 2 | 1 % | 1 |
| equilibrado | operaciones medianas, más selectivas | 1 h y 4 h | 1,5 | 1,5 % | 2 |
| trader | muchas operaciones chicas | 1 h | 1 | 2 % | 2 |
| scalper | el más rápido: entra y sale en minutos | 5 m | 1 | 1 % | 2 |
| rotacion | tiene las 2 monedas más fuertes de las 8 y cambia cuando otra las pasa | 1 d | — | — | 2 |

Cada perfil de señales mira sus propias monedas, contra USDT (`pares`): el conservador solo las tres más grandes, el trader
las ocho. Las monedas son las de `lib_datos.UNIVERSO`.

Lo que no se negocia aquí:
- **Los frenos de siempre valen para todos** (pérdida diaria, racha, piso y piso absoluto) y la reserva del 40 % en USDT.
- **El riesgo de un perfil nunca pasa el 2 %** (`lib_tamano.RIESGO`): un perfil solo puede achicar, nunca agrandar.
- **Las velas de 5 m salen de las de 1 m** que guarda el muestreo (30 días): el scalper no se puede mirar más atrás.
"""
import lib_datos
import lib_tamano
import minimo_viable

DIA_MS = lib_datos.DIA_MS
PERFILES = {
    "holding": {"tipo": "acumular", "partes": 12, "cada_ms": 7 * DIA_MS,
                "reparto": {"BTCFDUSD": 0.6, "ETHFDUSD": 0.4}},
    "conservador": {"tipo": "senales", "temporalidades": ("4h",), "rr": 2.0, "riesgo": 0.01, "posiciones": 1,
                    "pares": ("BTCUSDT", "ETHUSDT", "BNBUSDT")},
    "equilibrado": {"tipo": "senales", "temporalidades": ("1h", "4h"), "rr": 1.5, "riesgo": 0.015, "posiciones": 2,
                    "pares": ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")},
    "trader": {"tipo": "senales", "temporalidades": ("1h",), "rr": 1.0, "riesgo": 0.02, "posiciones": 2,
               "pares": lib_datos.UNIVERSO},
    "scalper": {"tipo": "senales", "temporalidades": ("5m",), "rr": 1.0, "riesgo": 0.01, "posiciones": 2,
                "dias_max": lib_datos.DIAS_MINUTOS, "pares": ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT")},
    # Rotación: cada día, las 2 monedas más fuertes de las 8 (fuerza = cuánto subieron en 30 días contra cuánto se movieron),
    # solo las que están sobre su media de 50 días y solo si BTC está sobre su media de 200. Cambia una cuando otra la pasa
    # con margen (`margen`), para no ir y venir por nada. Ver `lib_rotacion`.
    "rotacion": {"tipo": "rotar", "temporalidades": ("1d",), "posiciones": 2, "pares": lib_datos.UNIVERSO,
                 "dias_fuerza": 30, "media": 50, "margen": 1},
}
ORDEN = ("holding", "conservador", "equilibrado", "trader", "scalper", "rotacion")
SUGERIDO = "equilibrado"
#: Las velas que no se guardan tal cual: se arman juntando velas de 1 m.
AGRUPADAS = {"5m": 5}


def de(perfil):
    """Las reglas de un perfil, o `None` si no existe."""
    p = PERFILES.get(perfil)
    return {"id": perfil, **p} if p else None


def pares_de(perfil):
    """Las monedas que mira un perfil (contra USDT). El holding compra las suyas aparte (`reparto`)."""
    p = PERFILES.get(perfil) or {}
    return tuple(x for x in p.get("pares", ()) if x in lib_datos.UNIVERSO)


def relacion(s):
    """Cuánto se gana si sale por el objetivo por cada unidad que se pierde si sale por el stop."""
    riesgo = s["entrada"] - s["stop"]
    return (s["objetivo"] - s["entrada"]) / riesgo if riesgo > 0 else 0.0


def acepta(perfil, s):
    """Si una señal entra en las reglas del perfil: su moneda, su temporalidad y su relación ganancia/riesgo.
    BTCFDUSD cuenta como BTC: la moneda es la misma, solo cambia contra qué se paga."""
    p = PERFILES.get(perfil) or {}
    return (p.get("tipo") == "senales" and s.get("temporalidad") in p.get("temporalidades", ())
            and (not s.get("par") or s["par"].replace("FDUSD", "USDT") in p.get("pares", ()))
            and relacion(s) >= p.get("rr", 99) - 1e-9)


def agrupar(velas, n):
    """Arma velas de `n` minutos con las de 1 m. Solo las completas y seguidas: una vela a medias no se usa."""
    paso = lib_datos.PASO_MS[lib_datos.MINUTO] * n
    grupos, salida = {}, []
    for v in velas:
        grupos.setdefault(v[0] // paso * paso, []).append(v)
    for inicio in sorted(grupos):
        g = sorted(grupos[inicio])
        if len(g) != n or g[0][0] != inicio:
            continue
        salida.append([inicio, g[0][1], max(x[2] for x in g), min(x[3] for x in g), g[-1][4], sum(x[5] for x in g)])
    return salida


def serie(par, temporalidad):
    """Las velas cerradas de un par en una temporalidad, guardadas o armadas desde las de 1 m."""
    if temporalidad in AGRUPADAS:
        return agrupar(lib_datos.leer_serie(par, lib_datos.MINUTO), AGRUPADAS[temporalidad])
    return lib_datos.leer_serie(par, temporalidad)


def tamano(perfil, capital, precio, stop, filtros, com=None, abiertas=0, comprometido=0.0, tope=None):
    """El tamaño de una operación con las reglas del perfil: el de siempre (`lib_tamano.tamano`), achicado al riesgo del
    perfil y con su máximo de posiciones."""
    p = PERFILES.get(perfil) or {}
    if abiertas >= p.get("posiciones", lib_tamano.POSICIONES):
        return {"puede": False, "motivo": "posiciones_llenas"}
    t = lib_tamano.tamano(capital, precio, stop, filtros, com, tope, abiertas, comprometido)
    if not t.get("puede"):
        return t
    factor = min(1.0, p.get("riesgo", lib_tamano.RIESGO) / lib_tamano.RIESGO)
    if factor >= 1.0 or t.get("manda") != "riesgo":
        return t
    cantidad = lib_tamano.bajar_al_paso(t["cantidad"] * factor, t["paso"])
    if cantidad < ((t.get("minimo") or {}).get("cantidad") or 0):
        return {**t, "puede": False, "motivo": "bajo_minimo"}
    nocional = cantidad * t["precio"]
    costos = nocional * t["costo_relativo"]
    return {**t, "cantidad": cantidad, "entrada": nocional, "costos": costos, "monto": nocional + costos,
            "arriesgado": cantidad * (t["precio"] - t["stop"]) + costos}


def parametros():
    return {"perfiles": [{"id": k, **{c: (list(v) if isinstance(v, tuple) else v) for c, v in PERFILES[k].items()}}
                         for k in ORDEN], "sugerido": SUGERIDO}


assert all(p.get("riesgo", 0) <= lib_tamano.RIESGO for p in PERFILES.values())
assert minimo_viable.RIESGO == lib_tamano.RIESGO
