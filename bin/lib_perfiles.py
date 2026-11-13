#!/usr/bin/env python3
"""lib_perfiles — las formas de operar de Pilota. Solo biblioteca estándar. No es una acción.

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

**Se ofrecen** (`ORDEN`) la familia holding —holding, holding_ocho, compra_semanal, rebalanceo y cosecha, cada una con
una sola variante de comprar por partes y guardar (`lib_holding`)— y la rotacion. Los cuatro perfiles de señales (conservador, equilibrado, trader y
scalper) quedan **retirados**: perdieron contra quedarse en USDT con datos reales (nov 2026) y la pantalla ya no los ofrece.
Sus reglas siguen aquí porque la máquina de señales es la misma que usan los tres modos del dinero real, y sus pruebas la
cuidan. Un perfil retirado que estaba andando se detiene solo (`vivo.retirar`).

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
    # La familia holding: comprar por partes y guardar, con una variante cada uno (`lib_holding`). Todas contra USDT.
    "holding_ocho": {"tipo": "acumular", "variante": True, "partes": 12, "cada_ms": 7 * DIA_MS,
                     "reparto": {p: 1 / len(lib_datos.UNIVERSO) for p in lib_datos.UNIVERSO}, "pares": lib_datos.UNIVERSO},
    "compra_semanal": {"tipo": "acumular", "variante": True, "partes": 52, "cada_ms": 7 * DIA_MS, "descuento": 0.01,
                       "reparto": {"BTCUSDT": 0.6, "ETHUSDT": 0.4}, "pares": ("BTCUSDT", "ETHUSDT")},
    "rebalanceo": {"tipo": "acumular", "variante": True, "partes": 12, "cada_ms": 7 * DIA_MS,
                   "rebalanceo": {"cripto": 0.5, "banda": 0.1},
                   "reparto": {"BTCUSDT": 0.6, "ETHUSDT": 0.4}, "pares": ("BTCUSDT", "ETHUSDT")},
    "cosecha": {"tipo": "acumular", "variante": True, "partes": 12, "cada_ms": 7 * DIA_MS,
                "cosecha": {"sube": 0.3, "vende": 0.25, "recompra": 0.15},
                "reparto": {"BTCUSDT": 0.6, "ETHUSDT": 0.4}, "pares": ("BTCUSDT", "ETHUSDT")},
    # El holding de BTC y ETH contra USDT: no se ofrece solo (para eso está «holding»), es la parte de una mezcla.
    "holding_usdt": {"tipo": "acumular", "variante": True, "partes": 12, "cada_ms": 7 * DIA_MS,
                     "reparto": {"BTCUSDT": 0.6, "ETHUSDT": 0.4}, "pares": ("BTCUSDT", "ETHUSDT")},
    # Acciones de EE. UU. (bStocks de Binance, `lib_datos.ACCIONES`): SPY es el S&P 500 y QQQ el Nasdaq 100.
    "indice_eeuu": {"tipo": "acumular", "variante": True, "partes": 12, "cada_ms": 7 * DIA_MS,
                    "reparto": {"SPYBUSDT": 0.6, "QQQBUSDT": 0.4}, "pares": ("SPYBUSDT", "QQQBUSDT")},
    "indice_semanal": {"tipo": "acumular", "variante": True, "partes": 52, "cada_ms": 7 * DIA_MS, "descuento": 0.01,
                       "reparto": {"SPYBUSDT": 0.6, "QQQBUSDT": 0.4}, "pares": ("SPYBUSDT", "QQQBUSDT")},
    "acciones_ocho": {"tipo": "acumular", "variante": True, "partes": 12, "cada_ms": 7 * DIA_MS,
                      "reparto": {p: 1 / 8 for p in lib_datos.ACCIONES[2:]}, "pares": lib_datos.ACCIONES[2:]},
    # Las mezclas: el monto repartido entre perfiles, cada parte con su propio libro (`lib_piloto`, `lib_simulacion.mezcla`).
    "semanal_rotacion": {"tipo": "mezcla", "componentes": (("compra_semanal", 0.5), ("rotacion", 0.5))},
    "nucleo_satelite": {"tipo": "mezcla", "componentes": (("holding_usdt", 0.7), ("rotacion", 0.3))},
    "cripto_acciones": {"tipo": "mezcla", "componentes": (("compra_semanal", 0.5), ("indice_semanal", 0.5))},
    # Rotación: cada día, las 2 monedas más fuertes de las 8 (fuerza = cuánto subieron en 30 días contra cuánto se movieron),
    # solo las que están sobre su media de 50 días y solo si BTC está sobre su media de 200. Cambia una cuando otra la pasa
    # con margen (`margen`), para no ir y venir por nada. Ver `lib_rotacion`.
    "rotacion": {"tipo": "rotar", "temporalidades": ("1d",), "posiciones": 2, "pares": lib_datos.UNIVERSO,
                 "dias_fuerza": 30, "media": 50, "margen": 1},
}
#: Los que se ofrecen, en el orden de la pantalla. El resto está retirado (ver arriba).
ORDEN = ("holding", "holding_ocho", "compra_semanal", "rebalanceo", "cosecha",
         "indice_eeuu", "indice_semanal", "acciones_ocho",
         "semanal_rotacion", "nucleo_satelite", "cripto_acciones", "rotacion")
RETIRADOS = ("conservador", "equilibrado", "trader", "scalper")
SUGERIDO = "holding"
#: Las velas que no se guardan tal cual: se arman juntando velas de 1 m.
AGRUPADAS = {"5m": 5}


def de(perfil):
    """Las reglas de un perfil, o `None` si no existe."""
    p = PERFILES.get(perfil)
    return {"id": perfil, **p} if p else None


def pares_de(perfil):
    """Lo que mira un perfil (contra USDT): sus monedas y acciones, o las de sus partes si es una mezcla. El holding
    clásico compra las suyas aparte (`reparto`, contra FDUSD)."""
    p = PERFILES.get(perfil) or {}
    if p.get("tipo") == "mezcla":
        return tuple(dict.fromkeys(x for c, _ in p["componentes"] for x in pares_de(c)))
    return tuple(x for x in p.get("pares", ()) if x in lib_datos.ACTIVOS)


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
