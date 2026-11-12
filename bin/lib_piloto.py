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
import lib_indicadores_mercado
import lib_modos
import lib_perfiles
import lib_registro
import lib_tamano
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
    if p["tipo"] == "acumular":
        d["holding"] = {"efectivo": monto, "tenencias": {par: 0.0 for par in p["reparto"]}, "partes": 0,
                        "ultima_ms": 0, "compras": []}
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

def contexto(ms=None):
    """La tendencia diaria de cada par y el filtro de BTC, como los arma el backtest. Sin ellos no hay entrada."""
    btc = lib_datos.leer_serie(lib_indicadores_mercado.CONTEXTO_PAR, lib_estrategias.TEMPORALIDAD_DIARIA)
    filtro = lib_estrategias.filtro_en(btc) if len(btc) >= VELAS_MINIMAS_DIA else None
    alzas = {}
    for par in lib_datos.PARES_OPERADOS:
        dia = lib_datos.leer_serie(lib_estrategias.PAR_DIARIO[par], lib_estrategias.TEMPORALIDAD_DIARIA)
        alzas[par] = lib_estrategias.al_alza_en(dia) if len(dia) >= VELAS_MINIMAS_DIA else None
    return filtro, alzas


def senales_de_ahora(perfil, ms, series=None, ctx=None):
    """Las señales de la última vela cerrada de cada par en las temporalidades del perfil, ya filtradas por el perfil.
    Devuelve las señales y las series que no estaban al día (`atrasadas`)."""
    p = lib_perfiles.de(perfil) or {}
    filtro, alzas = ctx if ctx is not None else contexto(ms)
    salida, atrasadas = [], []
    for par in lib_datos.PARES_OPERADOS:
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
                                pares.get(s["par"]) or {}, com, abiertas=abiertas, comprometido=comprometido)
        r = lib_ejecutor_prueba.entrar(s, ahora_ms=ms, tamano_=t, frenos=f)
        if r["puesta"]:
            break
        cuenta = lib_estado.cargar(AMBIENTE, ahora_ms=ms)
    return {"decision": "entrada" if r["puesta"] else "rechazo", "motivo": r.get("motivo") or "",
            "par": s["par"], "temporalidad": s["temporalidad"], "estrategia": s["estrategia"]}


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
    if lib_perfiles.de(d["perfil"])["tipo"] == "acumular":
        vuelta = _vuelta_holding(d, ms)
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

MOVIMIENTOS = ("perfil_empezado", "perfil_detenido", "compra_holding", "entrada_ruptura", "entrada_rebote", "objetivo",
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
    if perfil and perfil["tipo"] == "acumular":
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
            "holding": d.get("holding") if perfil and perfil["tipo"] == "acumular" else None,
            "ultima": d.get("ultima") or {}, "ultima_ms": int(d.get("ultima_ms") or 0),
            "movimientos": movimientos(int(d.get("desde_ms") or 0)) if hay else [],
            "parametros": lib_perfiles.parametros()}
