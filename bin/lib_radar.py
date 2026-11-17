#!/usr/bin/env python3
"""lib_radar — qué está esperando el robot, en números. Solo biblioteca estándar. No es una acción.

El robot no compra «cuando le parece»: compra cuando una vela cerrada cumple las reglas de una estrategia. El radar mira la
última vela cerrada de cada par en las temporalidades del perfil y dice, para cada estrategia:
- **si aplica ahora** y, si no, **por qué** (`motivo`: el día no viene al alza, el precio tiene rumbo, BTC frena todo…);
- **el gatillo**: a qué precio tendría que cerrar la vela para que la regla se cumpla, y **cuánto falta** (`distancia`);
- **cómo sería la operación** si se cumpliera: entrada, stop, objetivo y cuánto gana por cada 1 que arriesga (`rr`), y si el
  perfil la aceptaría (`sirve`);
- **qué pasó en el pasado** con esa misma jugada (`historia`): cuántas veces, cuántas ganó y cuánto dejó en promedio después
  de costos. Es el pasado, no una promesa, y la pantalla lo dice.

Las reglas son las de `lib_estrategias` con los mismos números: el radar no decide nada, solo explica a qué distancia está la
decisión. La historia sale del mismo recorrido del backtest (`estadisticas`), guardada en `mercado/radar.json`.
"""
import os

import backtest
import lib_costos
import lib_datos
import lib_estrategias
import lib_indicadores
import lib_indicadores_mercado
import lib_perfiles
import lib_piloto
import lib_simulacion
import lib_tamano
import nucleo

#: Desde qué distancia al gatillo se dice «casi casi».
CERCA = 0.0025
#: Cada cuánto se vuelve a medir la historia (es una pasada por 3 años de velas).
HISTORIA_CADA_MS = 6 * 3600 * 1000
MOTIVOS = ("btc_frena", "sin_contexto", "dia_no_al_alza", "con_rumbo", "sin_datos", "sin_volumen", "listo", "lejos")


def ruta():
    return os.path.join(lib_datos.carpeta_mercado(), "radar.json")


def guardado():
    d = nucleo.leer_json(ruta(), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    return d if isinstance(d, dict) else {}


# ── La historia de cada jugada ───────────────────────────────────────────────────────────────────────────────────────

def agrupar(ops):
    """Las operaciones cerradas y permitidas, juntadas por estrategia, par y temporalidad."""
    salida = {}
    for o in ops:
        if o.get("motivo") or not o.get("llenada") or not o.get("permitida") or o.get("neto") is None:
            continue
        k = f"{o['estrategia']}|{o['par']}|{o['temporalidad']}"
        g = salida.setdefault(k, {"n": 0, "ganadas": 0, "suma": 0.0, "por_objetivo": 0})
        g["n"] += 1
        g["ganadas"] += 1 if o["neto"] > 0 else 0
        g["por_objetivo"] += 1 if o.get("por") == "objetivo" else 0
        g["suma"] += o["neto"]
    return {k: {"n": g["n"], "ganadas": g["ganadas"], "gana": g["ganadas"] / g["n"], "neto_medio": g["suma"] / g["n"],
                "por_objetivo": g["por_objetivo"]} for k, g in salida.items()}


def estadisticas(ahora_ms=None, recorrido=None, rapidas=None):
    """La historia de cada jugada: 3 años en 1 h y 4 h y los últimos 30 días en 5 m (las velas de 1 m), en las ocho monedas
    contra USDT (y las dos contra FDUSD del backtest, si se le pasa su recorrido)."""
    ms = ahora_ms or lib_datos.ahora_local_ms()
    com = lib_tamano.comisiones(lib_costos.comisiones())
    if recorrido is not None:
        ops = list((recorrido or {}).get("todas") or [])
    else:
        ops = [o for t in ("1h", "4h") for o in lib_simulacion.ops_de(lib_datos.UNIVERSO, t, com)]
    ops += rapidas if rapidas is not None else lib_simulacion.ops_rapidas("5m", com)
    return {"formato": 1, "cuando_ms": ms, "jugadas": agrupar(ops)}


def al_dia(ahora_ms=None, forzar=False):
    """La historia guardada, medida de nuevo si tiene más de `HISTORIA_CADA_MS`. La corre el flujo en vivo, que no tiene apuro."""
    ms = ahora_ms or lib_datos.ahora_local_ms()
    d = guardado()
    h = d.get("historia") or {}
    if forzar or not h.get("cuando_ms") or ms - int(h["cuando_ms"]) > HISTORIA_CADA_MS:
        h = estadisticas(ms)
        nucleo.escribir_json(ruta(), {**d, "historia": h})
    return h


# ── El radar de ahora ────────────────────────────────────────────────────────────────────────────────────────────────

def _ultimo(serie):
    return serie[-1] if serie else None


def mirar_serie(par, temporalidad, velas, al_alza, filtro, perfil, historia):
    """Una serie: las dos estrategias con su gatillo, su operación posible y su historia. Pura (no lee el disco)."""
    p = lib_perfiles.de(perfil) or {}
    pide = p.get("rr", 0)
    item = {"par": par, "temporalidad": temporalidad, "precio": None, "vela_ms": None, "estrategias": []}
    if len(velas) < 60:
        item["motivo"] = "sin_datos"
        return item
    altos, bajos, cierres, volumenes = ([v[i] for v in velas] for i in (2, 3, 4, 5))
    banda = lib_indicadores_mercado.bollinger(cierres)
    medio = _ultimo(lib_indicadores_mercado.atr(altos, bajos, cierres))
    niveles = lib_indicadores_mercado.rupturas(altos, bajos, cierres)
    relativo = _ultimo(lib_indicadores_mercado.volumen_relativo(volumenes))
    fuerza = _ultimo(lib_indicadores.adx(altos, bajos, cierres)["adx"])
    cierre = cierres[-1]
    item.update(precio=cierre, vela_ms=velas[-1][0], adx=fuerza, volumen_relativo=relativo,
                banda_baja=_ultimo(banda["baja"]), banda_media=_ultimo(banda["media"]), banda_alta=_ultimo(banda["alta"]))
    btc = filtro or {"pasa": False, "motivo": "sin_contexto"}

    def con_historia(e):
        h = (historia or {}).get(f"{e['estrategia']}|{par}|{temporalidad}")
        e["historia"] = h
        return e

    # Rebote: el cierre pegado a la banda de abajo con el precio sin rumbo.
    baja, alta, media = item["banda_baja"], item["banda_alta"], item["banda_media"]
    r = {"estrategia": "rebote", "aplica": False, "motivo": "", "gatillo": None, "distancia": None}
    if None in (baja, alta, media, medio, fuerza):
        r["motivo"] = "sin_datos"
    else:
        gatillo = baja + lib_estrategias.POSICION_REBOTE * (alta - baja)
        entrada = min(baja, gatillo)
        stop, objetivo = entrada - lib_estrategias.STOP_ATR_REBOTE * medio, media
        rr = (objetivo - entrada) / (entrada - stop) if entrada > stop else 0.0
        r.update(gatillo=gatillo, distancia=(cierre - gatillo) / cierre, entrada=entrada, stop=stop, objetivo=objetivo,
                 rr=rr, rr_pide=pide, sirve=rr >= pide - 1e-9, adx_maximo=lib_estrategias.ADX_RANGO)
        if not btc.get("pasa"):
            r["motivo"] = btc.get("motivo") or "btc_frena"
        elif fuerza > lib_estrategias.ADX_RANGO:
            r["motivo"] = "con_rumbo"
        elif cierre <= gatillo:
            r.update(aplica=True, motivo="listo")
        else:
            r["motivo"] = "lejos"
    item["estrategias"].append(con_historia(r))

    # Ruptura: el cierre pasa el techo de las velas anteriores, con volumen y el día al alza.
    techo = _ultimo(niveles["maximo"])
    u = {"estrategia": "ruptura", "aplica": False, "motivo": "", "gatillo": techo, "distancia": None}
    if techo is None or medio is None:
        u["motivo"] = "sin_datos"
    else:
        stop, objetivo = techo - lib_estrategias.STOP_ATR_RUPTURA * medio, techo * (1 + lib_estrategias.OBJETIVO_RUPTURA)
        rr = (objetivo - techo) / (techo - stop) if techo > stop else 0.0
        u.update(distancia=(techo - cierre) / cierre, entrada=techo, stop=stop, objetivo=objetivo, rr=rr, rr_pide=pide,
                 sirve=rr >= pide - 1e-9, volumen_pide=lib_estrategias.VOLUMEN_RUPTURA)
        if not btc.get("pasa"):
            u["motivo"] = btc.get("motivo") or "btc_frena"
        elif not al_alza:
            u["motivo"] = "dia_no_al_alza"
        elif _ultimo(niveles["rompio_maximo"]) and (relativo or 0) >= lib_estrategias.VOLUMEN_RUPTURA:
            u.update(aplica=True, motivo="listo")
        elif _ultimo(niveles["rompio_maximo"]):
            u["motivo"] = "sin_volumen"
        else:
            u["motivo"] = "lejos"
    item["estrategias"].append(con_historia(u))

    # Lo más cercano que sí serviría: eso es lo que «está esperando».
    posibles = [e for e in item["estrategias"] if e.get("distancia") is not None and e.get("sirve")
                and e["motivo"] in ("lejos", "listo", "sin_volumen")]
    mejor = min(posibles, key=lambda e: max(0.0, e["distancia"]), default=None)
    item["espera"] = mejor["estrategia"] if mejor else ""
    item["cerca"] = bool(mejor and 0 <= mejor["distancia"] <= CERCA)
    item["condicion"] = ""
    if not mejor and r.get("motivo") == "con_rumbo" and r.get("sirve"):
        # Ninguna aplica, pero el rebote solo espera que el precio se calme: eso también es «estar esperando».
        item.update(espera="rebote", condicion="con_rumbo")
    return item


def radar(perfil, ahora_ms=None, series=None, ctx=None, historia=None):
    """El radar del perfil: una fila por par y temporalidad que el perfil mira."""
    ms = ahora_ms or lib_datos.ahora_local_ms()
    p = lib_perfiles.de(perfil)
    if p is None or p.get("tipo") != "senales":
        return {"perfil": perfil or "", "cuando_ms": ms, "filas": [], "filtro": None}
    pares = lib_perfiles.pares_de(perfil)
    filtro_en, alzas = ctx if ctx is not None else lib_piloto.contexto(ms, pares)
    filtro = filtro_en(ms) if filtro_en else {"pasa": False, "motivo": "sin_contexto"}
    hist = historia if historia is not None else (guardado().get("historia") or {}).get("jugadas") or {}
    filas = []
    for par in pares:
        al = alzas.get(par)
        for t in p["temporalidades"]:
            paso = lib_datos.PASO_MS[t]
            velas = (series or {}).get((par, t)) if series is not None else lib_perfiles.serie(par, t)
            cerradas = [v for v in (velas or []) if v[0] + paso <= ms][-lib_piloto.VELAS_MIRADAS:]
            filas.append(mirar_serie(par, t, cerradas, al(ms) if al else None, filtro, perfil, hist))
    # Lo más cerca de comprar va primero: la pantalla muestra las primeras y abre sus gráficos.
    filas.sort(key=lambda f: (0 if f.get("cerca") else (1 if f.get("espera") else 2), _distancia(f)))
    return {"perfil": perfil, "cuando_ms": ms, "filtro": {"pasa": bool(filtro.get("pasa")), "motivo": filtro.get("motivo") or ""},
            "filas": filas}


def _distancia(f):
    e = next((x for x in f.get("estrategias") or [] if x.get("estrategia") == f.get("espera")), None)
    return abs(e.get("distancia") or 0) if e else 9.0


def escribir(r):
    d = guardado()
    nucleo.escribir_json(ruta(), {**d, "radar": r})
    return r
