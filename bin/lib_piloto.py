#!/usr/bin/env python3
"""lib_piloto — la prueba en vivo con un perfil: el robot opera solo, con dinero ficticio y precios reales de ahora.
Solo biblioteca estándar. No es una acción (la acción es `bin/vivo.py`).

La persona elige un perfil (`lib_perfiles`) y un monto («100 USDT, equilibrado») y aprieta «Empezar». Desde ahí:
- el saldo de prueba se reinicia a ese monto (`lib_estado.reiniciar`: queda en el registro);
- cada vuelta del motor (5 min) mira la **última vela cerrada** de cada par en las temporalidades del perfil, saca las
  señales con las mismas reglas del pasado (`lib_estrategias.de_velas`), se queda con las que el perfil acepta, les da el
  tamaño del perfil y las pone con el ejecutor de prueba (`lib_ejecutor_prueba.entrar`);
- el holding no opera señales: compra BTC y ETH por partes, una vez por semana, y mantiene. Esas compras viven en su propio
  archivo (`piloto.json`), con su efectivo y lo que tiene de cada moneda.

Lo que no se negocia aquí:
- **Solo en prueba.** Con el ambiente real activo, este gancho no hace nada y deciden los tres modos de siempre
  (`lib_modos.decidir`). Pasar a real sigue siendo su propio paso, con sus requisitos.
- **Los frenos y la protección son los de siempre.** La orden pasa por el tamaño del perfil, por `lib_frenos` y por el
  ejecutor de prueba, que no abre nada sin su stop y su objetivo.
- **Cada vela se mira una sola vez** (`vistas`): una señal que se rechazó no se vuelve a intentar cada 5 minutos.
- **Una vela vieja no es una señal de ahora.** Si la última vela cerrada tiene más de una vela de atraso (faltan datos),
  no se entra: se dice `sin_datos`.
"""
import json
import os

import lib_costos
import lib_datos
import lib_ejecutor_prueba
import lib_estado
import lib_estrategias
import lib_frenos
import lib_holding
import lib_indicadores_mercado
import lib_modos
import lib_perfiles
import lib_registro
import lib_rotacion
import lib_tendencia
import lib_tamano
import lib_universo
import nucleo

FORMATO = 1
AMBIENTE = lib_estado.PRUEBA
#: Cuántas velas se le pasan a las reglas: las que piden los indicadores para estar calientes, con margen.
VELAS_MIRADAS = 400
#: Cuántas velas mínimas hacen falta para el contexto diario (lo mismo que el backtest).
VELAS_MINIMAS_DIA = 200
#: Lo que puede devolver una vuelta (la pantalla lo traduce).
DECISIONES = ("apagado", "frenado", "sin_datos", "sin_senal", "entrada", "rechazo", "compra", "esperando", "completo")
TOLERANCIA = 1e-9


def ruta():
    return os.path.join(lib_estado.carpeta(), "piloto.json")


def _numero(valor, defecto=0.0):
    try:
        x = float(valor)
    except (TypeError, ValueError):
        return defecto
    return x if x == x and x not in (float("inf"), float("-inf")) else defecto


def _ms(ahora_ms=None):
    return int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())


def guardado():
    """Lo que quedó escrito, o un piloto apagado. Lo que no se entienda cuenta como apagado: nunca se opera por suposición."""
    try:
        with open(ruta(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {"formato": FORMATO, "activo": False, "perfil": "", "monto": 0.0, "desde_ms": 0, "vistas": {}}
    if not isinstance(d, dict) or lib_perfiles.de(d.get("perfil")) is None:
        return {"formato": FORMATO, "activo": False, "perfil": "", "monto": 0.0, "desde_ms": 0, "vistas": {}}
    d["vistas"] = d.get("vistas") if isinstance(d.get("vistas"), dict) else {}
    return d


def guardar(d):
    nucleo.escribir_json(ruta(), d)
    return d


def precios(minutos=None):
    """El último cierre de 1 m de cada par operado: el precio de ahora."""
    series = minutos if isinstance(minutos, dict) else lib_ejecutor_prueba.minutos_de()
    return {par: lib_ejecutor_prueba.precio_de(v) for par, v in series.items()}


# ── Empezar y detener ────────────────────────────────────────────────────────────────────────────────────────────────

def empezar(perfil, monto, ahora_ms=None):
    """Empieza la prueba en vivo: el saldo de prueba vuelve al monto elegido y el perfil queda puesto. Solo en prueba."""
    ms = _ms(ahora_ms)
    p = lib_perfiles.de(perfil)
    if p is None:
        return {"ok": False, "error": "sin_perfil"}
    if lib_estado.activo() != AMBIENTE:
        return {"ok": False, "error": "no_es_prueba"}
    monto = _numero(monto)
    if not (0 < monto <= lib_estado.SALDO_MAXIMO):
        return {"ok": False, "error": "monto"}
    lib_estado.reiniciar(monto, ahora_ms=ms)
    d = {"formato": FORMATO, "activo": True, "perfil": perfil, "monto": monto, "desde_ms": ms, "detenido_ms": 0,
         "vistas": {}}
    if p["tipo"] == "acumular" and p.get("variante"):
        d["holding_v"] = {**lib_holding.nuevo(monto), "dia_ms": 0}
    elif p["tipo"] == "acumular":
        d["holding"] = {"efectivo": monto, "tenencias": {par: 0.0 for par in p["reparto"]}, "partes": 0,
                        "ultima_ms": 0, "compras": []}
    if p["tipo"] == "rotar":
        d["rotacion"] = {"efectivo": monto, "tenencias": {}, "gastado": {}, "dia_ms": 0, "ranking": []}
    if p["tipo"] == "tendencia":
        d["tendencia"] = {**lib_tendencia.nuevo(monto), "dia_ms": 0, "filas": []}
    guardar(d)
    lib_registro.anotar(AMBIENTE, "perfil_empezado", ms=ms, resultado={"perfil": perfil, "saldo": monto})
    return {"ok": True, "datos": d}


def detener(ahora_ms=None):
    """El robot deja de entrar. Lo que está abierto sigue con su protección mientras el motor esté encendido."""
    ms = _ms(ahora_ms)
    d = guardado()
    if d.get("activo"):
        d.update({"activo": False, "detenido_ms": ms})
        guardar(d)
        lib_registro.anotar(AMBIENTE, "perfil_detenido", ms=ms, resultado={"perfil": d["perfil"]})
    return {"ok": True, "datos": d}


# ── Una vuelta ───────────────────────────────────────────────────────────────────────────────────────────────────────

def contexto(ms=None, pares=None):
    """La tendencia diaria de cada par y el filtro de BTC, como los arma el backtest. Sin ellos no hay entrada."""
    btc = lib_datos.leer_serie(lib_indicadores_mercado.CONTEXTO_PAR, lib_estrategias.TEMPORALIDAD_DIARIA)
    filtro = lib_estrategias.filtro_en(btc) if len(btc) >= VELAS_MINIMAS_DIA else None
    alzas = {}
    for par in (pares or lib_datos.PARES_OPERADOS):
        dia = _diaria(par)
        alzas[par] = lib_estrategias.al_alza_en(dia) if len(dia) >= VELAS_MINIMAS_DIA else None
    return filtro, alzas


def _diaria(par):
    """Las velas diarias de un par: las de FDUSD se miran en su par contra USDT, que tiene más historia."""
    try:
        return lib_datos.leer_serie(lib_estrategias.PAR_DIARIO.get(par, par), lib_estrategias.TEMPORALIDAD_DIARIA)
    except ValueError:
        return []


def senales_de_ahora(perfil, ms, series=None, ctx=None):
    """Las señales de la última vela cerrada de cada par en las temporalidades del perfil, ya filtradas por el perfil.
    Devuelve las señales y las series que no estaban al día (`atrasadas`)."""
    p = lib_perfiles.de(perfil) or {}
    pares = lib_perfiles.pares_de(perfil)
    filtro, alzas = ctx if ctx is not None else contexto(ms, pares)
    salida, atrasadas = [], []
    for par in pares:
        for t in p.get("temporalidades", ()):
            paso = lib_datos.PASO_MS[t]
            velas = (series or {}).get((par, t)) if series is not None else lib_perfiles.serie(par, t)
            cerradas = [v for v in (velas or []) if v[0] + paso <= ms][-VELAS_MIRADAS:]
            if not cerradas or ms - (cerradas[-1][0] + paso) > paso:
                atrasadas.append({"par": par, "temporalidad": t})
                continue
            ultima = lib_estrategias.de_velas(par, t, cerradas, al_alza=alzas.get(par), filtro=filtro)[-1]
            salida.extend(s for s in ultima if s.get("permitida") and lib_perfiles.acepta(perfil, s))
    salida.sort(key=lambda s: -lib_perfiles.relacion(s))
    return salida, atrasadas


def _vuelta_senales(d, ms, f, ex_estado):
    perfil = d["perfil"]
    senales, atrasadas = senales_de_ahora(perfil, ms)
    nuevas = [s for s in senales if d["vistas"].get(f"{s['par']}|{s['temporalidad']}|{s['estrategia']}") != s["vela"]]
    if not nuevas:
        return {"decision": "sin_datos" if atrasadas and not senales else "sin_senal", "atrasadas": atrasadas}
    cuenta = lib_estado.cargar(AMBIENTE, ahora_ms=ms)
    pares, _ = lib_tamano.filtros_de()
    com = lib_tamano.comisiones(lib_costos.comisiones())
    r, s = {"puesta": False, "motivo": ""}, nuevas[0]
    for s in nuevas:
        d["vistas"][f"{s['par']}|{s['temporalidad']}|{s['estrategia']}"] = s["vela"]
        abiertas, comprometido = lib_tamano.posiciones_de(cuenta)
        t = lib_perfiles.tamano(perfil, _numero(cuenta.get("saldo")), s["entrada"], s["stop"],
                                pares.get(s["par"]) or {}, lib_universo.comisiones_de(s["par"], com),
                                abiertas=abiertas, comprometido=comprometido)
        r = lib_ejecutor_prueba.entrar(s, ahora_ms=ms, tamano_=t, frenos=f)
        if r["puesta"]:
            anotar_jugada(d, r["posicion"], s)
            break
        cuenta = lib_estado.cargar(AMBIENTE, ahora_ms=ms)
    return {"decision": "entrada" if r["puesta"] else "rechazo", "motivo": r.get("motivo") or "",
            "par": s["par"], "temporalidad": s["temporalidad"], "estrategia": s["estrategia"]}


#: Cuántas jugadas se recuerdan (las de las últimas entradas): con qué estrategia, en qué velas y qué decía la historia.
JUGADAS = 200


def anotar_jugada(d, posicion, s):
    """Lo que el registro no guarda de una entrada: en qué velas se decidió, cuánto ganaba por cada 1 que arriesgaba y qué
    decía la historia de esa misma jugada. Lo muestra la pantalla al lado de cada compra."""
    import lib_radar           # aquí y no arriba: lib_radar usa este módulo
    h = (lib_radar.guardado().get("historia") or {}).get("jugadas") or {}
    clave = f"{s.get('estrategia')}|{s.get('par')}|{s.get('temporalidad')}"
    jugadas = d.setdefault("jugadas", {})
    jugadas[posicion["id"]] = {"estrategia": s.get("estrategia"), "temporalidad": s.get("temporalidad"),
                               "rr": lib_perfiles.relacion(s), "historia": h.get(clave)}
    if len(jugadas) > JUGADAS:
        for k in list(jugadas)[:len(jugadas) - JUGADAS]:
            del jugadas[k]


def _vuelta_holding(d, ms, minutos=None):
    p = lib_perfiles.de(d["perfil"])
    h = d.get("holding") or {}
    if int(h.get("partes") or 0) >= p["partes"]:
        return {"decision": "completo"}
    if h.get("ultima_ms") and ms - int(h["ultima_ms"]) < p["cada_ms"]:
        return {"decision": "esperando", "proxima_ms": int(h["ultima_ms"]) + p["cada_ms"]}
    ahora = precios(minutos)
    if any(not ahora.get(par) for par in p["reparto"]):
        return {"decision": "sin_datos"}
    taker = lib_tamano.comisiones(lib_costos.comisiones())["taker"]
    restantes = p["partes"] - int(h.get("partes") or 0)
    parte = _numero(h.get("efectivo")) / restantes
    for par, peso in p["reparto"].items():
        gasto = parte * peso
        cantidad = gasto * (1 - taker) / ahora[par]
        h["tenencias"][par] = _numero(h["tenencias"].get(par)) + cantidad
        h["efectivo"] = max(0.0, _numero(h.get("efectivo")) - gasto)
        h.setdefault("compras", []).append({"ms": ms, "par": par, "precio": ahora[par], "cantidad": cantidad,
                                            "monto": gasto})
        lib_registro.anotar(AMBIENTE, "compra_holding", par=par, ms=ms,
                            orden={"lado": "compra", "tipo": "mercado", "precio": ahora[par], "cantidad": cantidad,
                                   "monto": gasto, "estado": "llenada"},
                            resultado={"comision": gasto * taker, "n": int(h.get("partes") or 0) + 1})
    h["partes"] = int(h.get("partes") or 0) + 1
    h["ultima_ms"] = ms
    d["holding"] = h
    return {"decision": "compra", "parte": h["partes"]}


#: Un precio de 1 m más viejo que esto no sirve para comprar ni vender en la rotación: se espera al siguiente.
PRECIO_FRESCO_MS = 10 * 60_000
#: Lo que se pierde entre la punta de compra y la de venta en cada cambio de moneda (lo mismo que supone la comparación).
SPREAD_ROTACION = 0.0005


def precio_fresco(par, ms):
    """El último cierre de 1 m de esa moneda, si es de hace poco. Sin precio fresco no se mueve nada."""
    try:
        velas = lib_datos.leer_serie(par, lib_datos.MINUTO)
    except ValueError:
        return None
    if not velas or ms - (velas[-1][0] + 60_000) > PRECIO_FRESCO_MS:
        return None
    return _numero(velas[-1][4]) or None


def _vuelta_rotacion(d, ms, f, perfil=None):
    """Una vez por día, apenas cierra la vela diaria: ordena las ocho por fuerza, se queda con las mejores y cambia solo la
    que se cayó del grupo. Vende y compra a mercado, con la comisión taker y la diferencia de puntas."""
    p = lib_perfiles.de(perfil or d["perfil"])
    r = d.setdefault("rotacion", {"efectivo": _numero(d.get("monto")), "tenencias": {}, "gastado": {}, "dia_ms": 0})
    dia = ms // lib_rotacion.DIA_MS * lib_rotacion.DIA_MS
    if int(r.get("dia_ms") or 0) >= dia:
        return {"decision": "esperando", "proxima_ms": dia + lib_rotacion.DIA_MS}
    diarias = {par: _diaria(par) for par in p["pares"]}
    filas = lib_rotacion.ranking(diarias, ms, p["dias_fuerza"], p["media"])
    if not filas:
        return {"decision": "sin_datos"}
    filtro_en, _ = contexto(ms, ())
    pasa = bool(filtro_en(ms).get("pasa")) if filtro_en else False
    puerta = lib_frenos.permite_entrada(f)
    actuales = [par for par, q in (r.get("tenencias") or {}).items() if _numero(q) > 0]
    quiero = lib_rotacion.elegir(filas, actuales, p["posiciones"], p["margen"], pasa and puerta["puede"])
    salen = [par for par in actuales if par not in quiero]
    entran = [par for par in quiero if par not in actuales]
    precio = {par: precio_fresco(par, ms) for par in salen + entran}
    if any(not precio[par] for par in precio):
        return {"decision": "sin_datos", "faltan": [par for par in precio if not precio[par]]}
    taker = lib_tamano.comisiones(lib_costos.comisiones())["taker"]
    tenencias, gastado = r.setdefault("tenencias", {}), r.setdefault("gastado", {})
    for par in salen:
        cantidad = _numero(tenencias.pop(par, 0))
        recibe = cantidad * precio[par] * (1 - taker - SPREAD_ROTACION)
        costo = _numero(gastado.pop(par, 0))
        r["efectivo"] = _numero(r.get("efectivo")) + recibe
        lib_registro.anotar(AMBIENTE, "rotacion_venta", par=par, ms=ms,
                            orden={"lado": "venta", "tipo": "mercado", "precio": precio[par], "cantidad": cantidad,
                                   "monto": recibe, "estado": "llenada"},
                            resultado={"precio": precio[par], "neto": recibe - costo, "comision": cantidad * precio[par] * taker})
    for i, par in enumerate(entran):
        gasto = _numero(r.get("efectivo")) / (len(entran) - i)
        if gasto <= 0:
            break
        cantidad = gasto * (1 - taker - SPREAD_ROTACION) / precio[par]
        tenencias[par] = cantidad
        gastado[par] = gasto
        r["efectivo"] = max(0.0, _numero(r.get("efectivo")) - gasto)
        fila = next((x for x in filas if x["par"] == par), {})
        lib_registro.anotar(AMBIENTE, "rotacion_compra", par=par, ms=ms,
                            orden={"lado": "compra", "tipo": "mercado", "precio": precio[par], "cantidad": cantidad,
                                   "monto": gasto, "estado": "llenada"},
                            resultado={"comision": gasto * taker, "puesto": fila.get("puesto"), "fuerza": fila.get("fuerza")})
    r["dia_ms"] = dia
    r["ranking"] = [{k: x.get(k) for k in ("par", "puesto", "fuerza", "retorno", "elegible")} for x in filas]
    r["pasa_btc"] = pasa
    d["rotacion"] = r
    if salen or entran:
        return {"decision": "rotacion", "salen": salen, "entran": entran}
    return {"decision": "mantiene" if actuales else ("frenado" if not pasa else "sin_senal"), "tiene": actuales}


def _vuelta_tendencia(d, ms, f, perfil=None):
    """Una vez por día, apenas cierra la vela diaria: cada moneda del reparto con su parte si cerró sobre su media, y nada si
    cerró bajo (`lib_tendencia.pesos_cruce`). Lleva el libro ahí con `lib_tendencia.paso`, el mismo de la comparación, a
    precio de 1 m de ahora. Con un freno puesto vende todo y espera en USDT."""
    p = lib_perfiles.de(perfil or d["perfil"])
    t = d.get("tendencia") or {**lib_tendencia.nuevo(d.get("monto") or 0), "dia_ms": 0}
    dia = ms // lib_tendencia.DIA_MS * lib_tendencia.DIA_MS
    if int(t.get("dia_ms") or 0) >= dia:
        return {"decision": "esperando", "proxima_ms": dia + lib_tendencia.DIA_MS}
    tramos = {}
    for par in p["reparto"]:
        velas = [v for v in _diaria(par) if v[0] + lib_tendencia.DIA_MS <= dia]
        if not velas or velas[-1][0] != dia - lib_tendencia.DIA_MS:      # sin la vela de ayer no se decide
            return {"decision": "sin_datos", "faltan": [par]}
        tramos[par] = [v[4] for v in velas[-p["media"] - 5:]]
    filas = lib_tendencia.filas_cruce(tramos, p["reparto"], p["media"])
    if filas is None:
        return {"decision": "sin_datos"}
    puerta = lib_frenos.permite_entrada(f)
    objetivo = lib_tendencia.pesos_cruce(tramos, p["reparto"], p["media"]) if puerta["puede"] else {}
    hoy = {par: precio_fresco(par, ms) for par in set(objetivo) | set(t.get("cantidad") or {})}
    if any(not x for x in hoy.values()):
        return {"decision": "sin_datos", "faltan": [par for par, x in hoy.items() if not x]}
    taker = lib_tamano.comisiones(lib_costos.comisiones())["taker"]
    movs = lib_tendencia.paso(t, ms, hoy, objetivo, taker, lib_tendencia.SPREAD, p["umbral"])
    for m in movs:
        if m["que"] == "compra":
            lib_registro.anotar(AMBIENTE, "tendencia_compra", par=m["par"], ms=ms,
                                orden={"lado": "compra", "tipo": "mercado", "precio": m["precio"], "cantidad": m["cantidad"],
                                       "monto": m["monto"], "estado": "llenada"},
                                resultado={"comision": m["comision"]})
        else:
            lib_registro.anotar(AMBIENTE, "tendencia_venta", par=m["par"], ms=ms,
                                orden={"lado": "venta", "tipo": "mercado", "precio": m["precio"], "cantidad": m["cantidad"],
                                       "monto": m["monto"], "estado": "llenada"},
                                resultado={"precio": m["precio"], "neto": m["ganancia"], "comision": m["comision"]})
    t["dia_ms"] = dia
    t["filas"] = [{k: x[k] for k in ("par", "precio", "media", "sobre", "parte", "reparto")} for x in filas]
    t["frenado"] = not puerta["puede"]
    d["tendencia"] = t
    if movs:
        return {"decision": "tendencia", "compra": [m["par"] for m in movs if m["que"] == "compra"],
                "vende": [m["par"] for m in movs if m["que"] == "venta"]}
    tiene = [par for par, q in (t.get("cantidad") or {}).items() if q > 0]
    return {"decision": "mantiene" if tiene else ("frenado" if not puerta["puede"] else "sin_senal"), "tiene": tiene}


def _bajo_de(par, dia_ms):
    """El mínimo de la vela diaria que empezó en `dia_ms`, si ya cerró y está guardada."""
    try:
        velas = lib_datos.leer_serie(par, lib_estrategias.TEMPORALIDAD_DIARIA)
    except ValueError:
        return None
    v = next((x for x in reversed(velas[-5:]) if x[0] == dia_ms), None)
    return v[3] if v else None


def _vuelta_holding_v(d, ms, perfil=None):
    """Una variante de holding (`lib_holding.paso`): una vez por día, al cerrar la vela diaria, y la primera al empezar.
    Compra y vende con el precio de 1 m de ahora; la orden más abajo se llena con el mínimo del día que acaba de cerrar."""
    p = lib_perfiles.de(perfil or d["perfil"])
    h = d.get("holding_v") or {**lib_holding.nuevo(d.get("monto") or 0), "dia_ms": 0}
    dia = ms // lib_holding.DIA_MS * lib_holding.DIA_MS
    if int(h.get("dia_ms") or 0) >= dia:
        prox = dia + lib_holding.DIA_MS
        if h["partes"] < p["partes"] and h.get("ultima_ms"):
            prox = max(prox, int(h["ultima_ms"]) + p["cada_ms"])
        return {"decision": "esperando", "proxima_ms": prox}
    precio = {par: precio_fresco(par, ms) for par in p["reparto"]}
    if any(not x for x in precio.values()):
        return {"decision": "sin_datos", "faltan": [par for par, x in precio.items() if not x]}
    bajo = {par: _bajo_de(par, dia - lib_holding.DIA_MS) for par in p["reparto"]}
    taker = lib_tamano.comisiones(lib_costos.comisiones())["taker"]
    movs = lib_holding.paso(h, ms, precio, {k: v for k, v in bajo.items() if v}, p, taker)
    for m in movs:
        if m["que"] == "compra":
            lib_registro.anotar(AMBIENTE, "compra_holding", par=m["par"], ms=ms,
                                orden={"lado": "compra", "tipo": "limite" if m["por"] == "limite" else "mercado",
                                       "precio": m["precio"], "cantidad": m["cantidad"], "monto": m["monto"],
                                       "estado": "llenada"},
                                resultado={"comision": m["comision"], "por": m["por"], "n": h["partes"]})
        else:
            lib_registro.anotar(AMBIENTE, "venta_holding", par=m["par"], ms=ms,
                                orden={"lado": "venta", "tipo": "mercado", "precio": m["precio"], "cantidad": m["cantidad"],
                                       "monto": m["monto"], "estado": "llenada"},
                                resultado={"precio": m["precio"], "neto": m["ganancia"], "comision": m["comision"],
                                           "por": m["por"]})
    h["dia_ms"] = dia
    d["holding_v"] = h
    if not movs:
        return {"decision": "esperando", "proxima_ms": dia + lib_holding.DIA_MS}
    ques = {m["que"] for m in movs}
    return {"decision": "venta" if ques == {"venta"} else "compra", "parte": h["partes"],
            "por": sorted({m["por"] for m in movs})}


def _vuelta_mezcla(d, ms, f):
    """Una mezcla: cada parte decide con su propio libro y su parte del monto, igual que si anduviera sola."""
    p = lib_perfiles.de(d["perfil"])
    partes = d.setdefault("mezcla", {})
    salida = {}
    for comp, peso in p["componentes"]:
        sub = partes.setdefault(comp, {"monto": _numero(d.get("monto")) * peso, "peso": peso})
        tipo = lib_perfiles.de(comp)["tipo"]
        salida[comp] = _vuelta_rotacion(sub, ms, f, comp) if tipo == "rotar" else _vuelta_holding_v(sub, ms, comp)
    decisiones = {v.get("decision") for v in salida.values()}
    decision = next((x for x in ("rotacion", "venta", "compra", "sin_datos") if x in decisiones), "esperando")
    return {"decision": decision, "partes": salida}


def decidir(ctx=None, ahora_ms=None):
    """El gancho del motor. En prueba con un perfil puesto, opera el perfil; si no, deciden los tres modos de siempre."""
    c = ctx if isinstance(ctx, dict) else {}
    ms = _ms(c.get("ahora_ms") if c.get("ahora_ms") is not None else ahora_ms)
    amb = c.get("ambiente") or lib_estado.activo()
    d = guardado()
    if amb != AMBIENTE or not d.get("activo"):
        return lib_modos.decidir(c, ahora_ms=ms)
    f = c.get("frenos") if isinstance(c.get("frenos"), dict) else lib_frenos.escribir(lib_frenos.revisar(ms))
    ej = c.get("ejecutor") if isinstance(c.get("ejecutor"), dict) else lib_ejecutor_prueba.guardado()
    if lib_perfiles.de(d["perfil"])["tipo"] == "mezcla":
        vuelta = _vuelta_mezcla(d, ms, f)
    elif lib_perfiles.de(d["perfil"])["tipo"] == "acumular" and lib_perfiles.de(d["perfil"]).get("variante"):
        vuelta = _vuelta_holding_v(d, ms)
    elif lib_perfiles.de(d["perfil"])["tipo"] == "acumular":
        vuelta = _vuelta_holding(d, ms)
    elif lib_perfiles.de(d["perfil"])["tipo"] == "rotar":
        vuelta = _vuelta_rotacion(d, ms, f)
    elif lib_perfiles.de(d["perfil"])["tipo"] == "tendencia":
        vuelta = _vuelta_tendencia(d, ms, f)
    else:
        puerta = lib_frenos.permite_entrada(f)
        vuelta = ({"decision": "frenado", "motivo": puerta["motivo"]} if not puerta["puede"]
                  else _vuelta_senales(d, ms, f, ej))
        if vuelta["decision"] in ("entrada", "rechazo"):
            ej = lib_ejecutor_prueba.escribir(lib_ejecutor_prueba.estado(ms))
    d["ultima_ms"], d["ultima"] = ms, vuelta
    guardar(d)
    return {"ejecutor": ej, "piloto": {"perfil": d["perfil"], **vuelta}}


# ── Lo que lee la pantalla ───────────────────────────────────────────────────────────────────────────────────────────

MOVIMIENTOS = ("perfil_empezado", "perfil_detenido", "compra_holding", "venta_holding", "rotacion_compra", "rotacion_venta",
               "tendencia_compra", "tendencia_venta", "entrada_ruptura", "entrada_rebote", "objetivo",
               "stop", "stop_movil", "cierre_manual", "propuesta_vencida", "rechazo", "freno_diario", "freno_racha",
               "freno_piso", "freno_piso_absoluto", "saldo_reiniciado")


def movimientos(desde_ms=0, cuantos=200):
    """Lo que hizo el robot desde que empezó, de lo más nuevo a lo más viejo, en el formato fijo del registro."""
    lineas, _ = lib_registro.ultimas(AMBIENTE, cuantos * 3)
    return [x for x in lineas if x.get("razon") in MOVIMIENTOS and int(x.get("ms") or 0) >= desde_ms][:cuantos]


def estado(ahora_ms=None, minutos=None):
    """La prueba en vivo como está: el perfil, cuánto se puso, cuánto vale ahora, lo que tiene y lo que hizo."""
    ms = _ms(ahora_ms)
    d = guardado()
    ahora = precios(minutos)
    perfil = lib_perfiles.de(d.get("perfil"))
    monto = _numero(d.get("monto"))
    posiciones, efectivo, tenencias = [], 0.0, []
    mezcla = []
    if perfil and perfil["tipo"] == "mezcla":
        for comp, peso in perfil["componentes"]:
            sub = (d.get("mezcla") or {}).get(comp) or {}
            libro = sub.get("holding_v") or sub.get("rotacion") or {}
            propias = []
            for par, cantidad in sorted((libro.get("tenencias") or {}).items()):
                gastado = _numero((libro.get("costo") or libro.get("gastado") or {}).get(par))
                precio = ahora.get(par) or precio_fresco(par, ms)
                ahora[par] = precio
                propias.append({"par": par, "cantidad": _numero(cantidad), "gastado": gastado, "precio_ahora": precio,
                                "valor": gastado if precio is None else _numero(cantidad) * precio,
                                "precio_medio": gastado / _numero(cantidad) if _numero(cantidad) > 0 else None,
                                "parte": comp})
            caja = _numero(libro.get("efectivo")) if libro else _numero(d.get("monto")) * peso
            efectivo += caja
            tenencias += propias
            mezcla.append({"perfil": comp, "peso": peso,
                           "valor": caja + sum(_numero(x["valor"]) for x in propias)})
        valor = efectivo + sum(_numero(x["valor"]) for x in tenencias)
    elif perfil and perfil["tipo"] == "acumular" and perfil.get("variante"):
        h = d.get("holding_v") or {}
        efectivo = _numero(h.get("efectivo"))
        for par, cantidad in sorted((h.get("tenencias") or {}).items()):
            gastado = _numero((h.get("costo") or {}).get(par))
            precio = ahora.get(par) or precio_fresco(par, ms)
            ahora[par] = precio
            tenencias.append({"par": par, "cantidad": _numero(cantidad), "gastado": gastado, "precio_ahora": precio,
                              "valor": gastado if precio is None else _numero(cantidad) * precio,
                              "precio_medio": gastado / _numero(cantidad) if _numero(cantidad) > 0 else None})
        valor = efectivo + sum(_numero(x["valor"]) for x in tenencias)
    elif perfil and perfil["tipo"] == "acumular":
        h = d.get("holding") or {}
        efectivo = _numero(h.get("efectivo"))
        for par, cantidad in sorted((h.get("tenencias") or {}).items()):
            compras = [x for x in h.get("compras") or [] if x.get("par") == par]
            gastado = sum(_numero(x.get("monto")) for x in compras)
            precio = ahora.get(par)
            tenencias.append({"par": par, "cantidad": _numero(cantidad), "gastado": gastado, "precio_ahora": precio,
                              "valor": None if precio is None else _numero(cantidad) * precio,
                              "precio_medio": gastado / _numero(cantidad) if _numero(cantidad) > 0 else None})
        valor = efectivo + sum(_numero(x["valor"]) for x in tenencias)
    elif perfil and perfil["tipo"] == "rotar":
        r = d.get("rotacion") or {}
        efectivo = _numero(r.get("efectivo"))
        for par, cantidad in sorted((r.get("tenencias") or {}).items()):
            gastado = _numero((r.get("gastado") or {}).get(par))
            precio = ahora.get(par) or precio_fresco(par, ms)
            ahora[par] = precio
            tenencias.append({"par": par, "cantidad": _numero(cantidad), "gastado": gastado, "precio_ahora": precio,
                              "valor": gastado if precio is None else _numero(cantidad) * precio,
                              "precio_medio": gastado / _numero(cantidad) if _numero(cantidad) > 0 else None})
        valor = efectivo + sum(_numero(x["valor"]) for x in tenencias)
    elif perfil and perfil["tipo"] == "tendencia":
        t = d.get("tendencia") or {}
        efectivo = _numero(t.get("efectivo"))
        for par, cantidad in sorted((t.get("cantidad") or {}).items()):
            gastado = _numero((t.get("costo") or {}).get(par))
            precio = ahora.get(par) or precio_fresco(par, ms)
            ahora[par] = precio
            tenencias.append({"par": par, "cantidad": _numero(cantidad), "gastado": gastado, "precio_ahora": precio,
                              "valor": gastado if precio is None else _numero(cantidad) * precio,
                              "precio_medio": gastado / _numero(cantidad) if _numero(cantidad) > 0 else None})
        valor = efectivo + sum(_numero(x["valor"]) for x in tenencias)
    else:
        ej = lib_ejecutor_prueba.estado(ms, minutos=minutos)
        efectivo = _numero(ej.get("saldo")) - _numero(ej.get("comprometido"))
        posiciones = ej.get("posiciones") or []
        # Lo que vale: el saldo, con lo abierto a precio de ahora en vez de a precio de entrada.
        valor = _numero(ej.get("saldo")) + sum(_numero(p.get("ganancia")) for p in posiciones
                                                if p.get("estado") == lib_ejecutor_prueba.ABIERTA)
    hay = bool(perfil) and monto > 0
    return {"formato": FORMATO, "cuando": lib_datos.iso(ms), "ambiente": lib_estado.activo(),
            "activo": bool(d.get("activo")), "perfil": d.get("perfil") or "", "monto": monto,
            "desde_ms": int(d.get("desde_ms") or 0), "detenido_ms": int(d.get("detenido_ms") or 0),
            "valor": valor if hay else None, "ganancia": (valor - monto) if hay else None,
            "ganancia_relativa": (valor / monto - 1) if hay else None, "efectivo": efectivo,
            "posiciones": posiciones, "tenencias": tenencias, "precios": ahora,
            "holding": (d.get("holding_v") if perfil.get("variante") else d.get("holding"))
            if perfil and perfil["tipo"] == "acumular" else None,
            "rotacion": d.get("rotacion") if perfil and perfil["tipo"] == "rotar"
            else next((x.get("rotacion") for x in (d.get("mezcla") or {}).values() if x.get("rotacion")), None),
            "mezcla": mezcla,
            "tendencia": d.get("tendencia") if perfil and perfil["tipo"] == "tendencia" else None,
            "pares": list(lib_perfiles.pares_de(d.get("perfil"))) if perfil else [],
            # Las reglas del perfil puesto, para que la pantalla diga su plan con los mismos números.
            "reglas": {k: (list(x) if isinstance(x, tuple) else x) for k, x in (perfil or {}).items()},
            "ultima": d.get("ultima") or {}, "ultima_ms": int(d.get("ultima_ms") or 0),
            "jugadas": d.get("jugadas") or {},
            "movimientos": movimientos(int(d.get("desde_ms") or 0)) if hay else [],
            "parametros": lib_perfiles.parametros()}
