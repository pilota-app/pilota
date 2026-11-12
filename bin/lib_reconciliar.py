#!/usr/bin/env python3
"""lib_reconciliar — el motor: revisar cada 5 minutos y reconciliar al arrancar y al despertar. Solo biblioteca estándar.
No es una acción (la corre `bin/motor.py`).

El **motor** es el equipo donde corre Pilota: si está apagado, nadie mira los cruces. Cada `CICLO_SEGUNDOS` el motor hace
una **revisión**, y al arrancar o al despertar esa misma revisión **reconcilia** la ventana que nadie miró:

| Qué | Con qué |
|---|---|
| los frenos, revisados y aplicados | `lib_frenos.revisar` (mirarlos es aplicarlos: el modo vuelve a manual y lo nuevo queda en el registro) |
| las velas de 1 m perdidas, recorridas | `lib_ejecutor_prueba.revisar` (llenados, stops y objetivos cruzados, el stop móvil donde quedó y su protección repuesta) |
| lo huérfano, cerrado | `cerrar_huerfano`: la entrada que venció aunque no hubiera velas que la cancelaran y la posición abierta sin protección |
| la ventana sin cobertura, escrita | `anotar_ventana` (`sin_cobertura` del plan): en prueba la protección existe solo con el motor encendido |
| el resumen de lo que pasó | `cuentas_de` sobre el registro que no se borra: «Dormiste 9 h: 1 stop, 2 propuestas vencidas» |

Lo que no se negocia aquí:
- **El motor no inventa nada: reconcilia con lo que hay.** En prueba, con las velas de 1 m que están en disco (las trae el
  muestreo) y con el estado firmado de la cuenta; en real va a reconciliar contra lo que diga Binance —órdenes abiertas,
  saldos y llenados—, nunca contra lo guardado, y eso es cosa del conector real, en su paso (`SIN_CONECTOR`).
- **Las velas que todavía no llegaron no cierran la ventana.** Si el muestreo no alcanzó a bajar los minutos que faltaban,
  la ventana sin cobertura queda **abierta** y la revisión siguiente la vuelve a mirar: el rato en que un stop no se
  habría aplicado se dice, nunca se tapa.
- **Revisar dos veces no cambia nada dos veces.** Cada posición lleva hasta dónde la recorrieron (`revisado_ms`) y los ids
  de las órdenes son deterministas, así que reconciliar de nuevo no duplica ni un llenado ni una línea del registro.
- **El resumen sale del registro**, no de una cuenta aparte: lo que no quedó escrito no pasó.
- **De una cuenta cuyo archivo no es de fiar no se toca nada** (la misma regla de los frenos y del ejecutor).
- **Cuándo entrar no se decide acá.** La revisión deja el mundo al día y le pasa el contexto a quien decide (`decidir`):
  los tres modos y las propuestas que vencen son su propio paso.
"""
import math

import lib_datos
import lib_ejecutor_prueba
import lib_ejecutor_real
import lib_estado
import lib_frenos
import lib_registro
import lib_trabajo

#: El trabajo del motor (pieza «trabajos»), con su plan en `<datos>/mercado/motor.json`.
TIPO = "motor"
#: Cada cuánto revisa el motor: el mismo ritmo del muestreo, que es el que trae las velas de 1 m que se recorren.
CICLO_SEGUNDOS = 300
#: La primera vuelta reconcilia lo que nadie miró; después solo vigila.
ETAPAS = ("despertar", "vigilando")
#: Cuánto rato sin revisar se le perdona antes de decir que está dormido: dos vueltas, igual que la cobertura del
#: ejecutor de prueba (`lib_ejecutor_prueba.GRACIA_COBERTURA_MS`).
GRACIA_MS = lib_ejecutor_prueba.GRACIA_COBERTURA_MS
#: Cuántas ventanas sin cobertura se guardan en el plan: las últimas, para que el archivo no crezca sin fin.
VENTANAS_GUARDADAS = 50
#: Cuántas líneas del registro se miran hacia atrás para armar el resumen de la ventana. Si la ventana trae más, el
#: resumen lo dice (`topado`) en vez de dar un número que no es el total.
LINEAS_RESUMEN = 400
#: Cuántas vueltas seguidas pueden salir mal antes de que el trabajo se dé por vencido.
FALLOS_SEGUIDOS = 3
#: Lo que se cuenta de la ventana, cada cosa con su clave. Sale de las razones del registro (`lib_registro.RAZONES`).
CLAVES = ("propuestas", "entradas", "llenadas", "stops", "objetivos", "cierres", "vencidas", "rechazos", "frenos")
RAZONES_ENTRADA = tuple(lib_ejecutor_prueba.RAZON_ENTRADA.values())
#: Por qué el motor no está cuidando nada ahora mismo. Son códigos: la pantalla los traduce.
APAGADO, DORMIDO, SIN_1M, FRENADO, SIN_CONECTOR = "apagado", "dormido", "sin_1m", "frenado", "sin_conector"
MOTIVOS = (APAGADO, DORMIDO, SIN_1M, FRENADO, SIN_CONECTOR)
#: Por qué una ventana quedó sin cobertura.
VENTANA_DORMIDO, VENTANA_SIN_1M, VENTANA_ATRASADA = "dormido", "sin_1m", "atrasada"


def ruta_motor():
    return lib_trabajo.ruta_plan(TIPO)


def _numero(valor, defecto=0.0):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        return defecto
    return float(valor)


def _entero(valor, defecto=0):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        return defecto
    return int(valor)


def _ms(ahora_ms=None):
    return int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())


def _min(ms):
    return max(0, _entero(ms)) // 60_000


# ── El plan del motor ────────────────────────────────────────────────────────────────────────────────────────────────

def armar(ahora_ms, antes=None):
    """El plan: cuándo fue la última revisión, cuántas lleva, en qué quedó y las ventanas sin cobertura. El archivo lo
    pudo haber tocado cualquiera, así que de lo viejo se guarda solo lo que se entiende."""
    plan = {"formato": 1, "estado": "nunca", "etapa": ETAPAS[0], "trabajo": "", "error": "", "cuando": "",
            "ciclo_segundos": CICLO_SEGUNDOS, "vueltas": 0, "ultima_ms": 0, "ultima": "", "proxima": 0,
            "fallos": 0, "sin_cobertura": [], "resumen": {}}
    viejo = antes if isinstance(antes, dict) else {}
    plan.update({k: v for k, v in viejo.items() if k in plan and k not in ("formato", "ciclo_segundos")})
    plan["ultima_ms"] = _entero(plan.get("ultima_ms"))
    plan["ultima"] = lib_datos.iso(plan["ultima_ms"]) if plan["ultima_ms"] else ""
    plan["sin_cobertura"] = ventanas_de(plan)
    plan["resumen"] = plan["resumen"] if isinstance(plan.get("resumen"), dict) else {}
    return plan


def ventanas_de(plan):
    """Las ventanas sin cobertura que trae el plan, ya limpias."""
    lista = (plan or {}).get("sin_cobertura")
    if not isinstance(lista, list):
        return []
    return [v for v in lista if isinstance(v, dict) and isinstance(v.get("desde_ms"), int)][-VENTANAS_GUARDADAS:]


def ventana(plan, ahora_ms):
    """Desde cuándo nadie miró. La primera revisión no cuenta la historia entera: mira un ciclo hacia atrás, que es lo
    que alcanzó a pasar sin que nadie estuviera."""
    guardada = _entero((plan or {}).get("ultima_ms"))
    primera = guardada <= 0
    desde = ahora_ms - CICLO_SEGUNDOS * 1000 if primera else min(guardada, ahora_ms)
    dormido = max(0, ahora_ms - desde)
    return {"desde": lib_datos.iso(desde), "desde_ms": desde, "hasta": lib_datos.iso(ahora_ms), "hasta_ms": ahora_ms,
            "dormido_ms": dormido, "dormido_min": _min(dormido), "dormido_h": round(dormido / 3_600_000, 1),
            "primera": primera, "dormido": dormido > GRACIA_MS}


# ── Lo que pasó en la ventana, según el registro ─────────────────────────────────────────────────────────────────────

def lineas_de(ambiente, desde_ms, hasta_ms, tope=LINEAS_RESUMEN):
    """Las líneas del registro que caen en la ventana, de la más vieja a la más nueva, y si se llegó al tope."""
    recientes, _ = lib_registro.ultimas(ambiente, tope)
    dentro = [f for f in recientes if desde_ms < _entero(f.get("ms")) <= hasta_ms]
    dentro.reverse()
    return dentro, len(recientes) >= tope


def cuentas_de(lineas):
    """Qué pasó en la ventana, contado por razón: las entradas que se pusieron y las que se llenaron (lo dice
    `orden.estado`), los stops y los objetivos que se cruzaron, los cierres a mercado, las propuestas que vencieron, los
    rechazos y los frenos que se pusieron."""
    c = dict.fromkeys(CLAVES, 0)
    for f in lineas:
        razon = f.get("razon") or ""
        estado = (f.get("orden") or {}).get("estado")
        if razon in RAZONES_ENTRADA:
            c["llenadas" if estado == lib_ejecutor_prueba.LLENADA else "entradas"] += 1
        elif razon in ("stop", "stop_movil"):
            c["stops"] += 1
        elif razon == "objetivo":
            c["objetivos"] += 1
        elif razon == "cierre_manual":
            c["cierres"] += 1
        elif razon == lib_ejecutor_prueba.RAZON_VENCIDA:
            c["vencidas"] += 1
        elif razon == "propuesta":
            c["propuestas"] += 1
        elif razon == "rechazo":
            c["rechazos"] += 1
        elif razon.startswith("freno_"):
            c["frenos"] += 1
    return c


# ── Lo huérfano: lo que no puede quedar así ──────────────────────────────────────────────────────────────────────────

def huerfanas_de(ejecutor, ahora_ms):
    """Lo que no puede seguir como está después de reconciliar: la entrada que ya venció (aunque no hubiera velas de 1 m
    que la cancelaran: una propuesta vencida está vencida igual) y la posición abierta sin su protección (en real, la
    que Binance no confirmó). Lo que no lleva el prefijo propio no es de Pilota y no se mira."""
    vencidas, desnudas = [], []
    for p in ((ejecutor or {}).get("posiciones") or []):
        if not isinstance(p, dict) or not lib_ejecutor_prueba.es_nuestro(p.get("id")):
            continue
        if p.get("estado") == lib_ejecutor_prueba.PUESTA:
            vence = _entero(p.get("vence_ms"))
            if vence and vence <= ahora_ms:
                vencidas.append(p["id"])
        elif p.get("estado") == lib_ejecutor_prueba.ABIERTA and not p.get("protegida"):
            desnudas.append(p["id"])
    return {"vencidas": vencidas, "desnudas": desnudas}


def cerrar_huerfano(ejecutor, ahora_ms):
    """Cancela las entradas vencidas y cierra a mercado las posiciones sin protección, una por una y por su id: una
    posición desnuda no se queda abierta esperando. Devuelve el ejecutor como quedó."""
    h = huerfanas_de(ejecutor, ahora_ms)
    cerradas, motivo = 0, ""
    for identificador in [*h["vencidas"], *h["desnudas"]]:
        r = lib_ejecutor_prueba.cerrar(identificador, ahora_ms=ahora_ms)
        cerradas += _entero(r.get("cerradas"))
        motivo = motivo or (r.get("motivo") or "")
        ejecutor = r.get("estado") or ejecutor
    return {"ejecutor": ejecutor, "vencidas": len(h["vencidas"]), "desnudas": len(h["desnudas"]),
            "cerradas": cerradas, "motivo": motivo}


# ── La ventana sin cobertura ─────────────────────────────────────────────────────────────────────────────────────────

def anotar_ventana(plan, v, cobertura, ahora_ms):
    """Deja escrito el rato en que nadie cuidó las posiciones: en prueba la protección existe solo con el motor
    encendido, así que ese rato se dice y no se tapa. Mientras las velas de 1 m sigan atrasadas es **una sola** ventana
    (se alarga la de arriba) y la primera revisión con las velas al día la cierra."""
    ventanas = ventanas_de(plan)
    cubierto = bool((cobertura or {}).get("cubierto"))
    abierta = ventanas[-1] if ventanas and ventanas[-1].get("abierto") else None
    if cubierto and not v["dormido"]:
        if abierta:
            abierta.update({"hasta": lib_datos.iso(ahora_ms), "hasta_ms": ahora_ms, "abierto": False,
                            "min": _min(ahora_ms - _entero(abierta["desde_ms"]))})
        plan["sin_cobertura"] = ventanas
        return plan
    motivo = (VENTANA_DORMIDO if cubierto
              else (VENTANA_SIN_1M if not (cobertura or {}).get("hasta_ms") else VENTANA_ATRASADA))
    if abierta:
        abierta.update({"hasta": lib_datos.iso(ahora_ms), "hasta_ms": ahora_ms, "motivo": motivo,
                        "vueltas": _entero(abierta.get("vueltas")) + 1, "abierto": not cubierto,
                        "min": _min(ahora_ms - _entero(abierta["desde_ms"]))})
    else:
        ventanas.append({"desde": v["desde"], "desde_ms": v["desde_ms"], "hasta": lib_datos.iso(ahora_ms),
                         "hasta_ms": ahora_ms, "min": _min(ahora_ms - v["desde_ms"]), "vueltas": 1,
                         "motivo": motivo, "abierto": not cubierto})
    plan["sin_cobertura"] = ventanas[-VENTANAS_GUARDADAS:]
    return plan


# ── Una revisión ─────────────────────────────────────────────────────────────────────────────────────────────────────

def reconciliar(ahora_ms=None, plan=None, mercado=None, decidir=None):
    """Una revisión del motor, que al arrancar o al despertar es la reconciliación: los frenos aplicados, las velas de
    1 m que faltaban recorridas, lo huérfano cerrado, la ventana sin cobertura escrita y el resumen de lo que pasó.

    `decidir` es el gancho de los tres modos (su propio paso): recibe el contexto ya al día —la hora, el ambiente, los
    frenos, el ejecutor y el resumen— y puede devolver el ejecutor como lo dejó (`{"ejecutor": …}`) y lo que quiera
    sumarle al resumen. Acá no se abre ninguna posición."""
    ms = _ms(ahora_ms)
    # Quien revisa puede ser el trabajo (trae su plan, con `corriendo` puesto) o la acción suelta, con el motor
    # apagado o corriendo en otro lado: eso se mira, no se supone.
    entrante = plan if isinstance(plan, dict) else lib_trabajo.mirar(TIPO, lib_trabajo.leer_plan(TIPO))
    p = armar(ms, entrante)
    p["corriendo"], p["deteniendo"] = bool(entrante.get("corriendo")), bool(entrante.get("deteniendo"))
    v = ventana(p, ms)
    amb = lib_estado.activo()
    # Mirar los frenos es aplicarlos, y van primero: lo que decida el motor después ya cuenta con ellos puestos.
    frenos = lib_frenos.escribir(lib_frenos.revisar(ms, mercado))
    huerfano = {"vencidas": 0, "desnudas": 0, "cerradas": 0, "motivo": ""}
    if amb == lib_ejecutor_prueba.AMBIENTE:
        huerfano = cerrar_huerfano(lib_ejecutor_prueba.revisar(ms), ms)
        ej = lib_ejecutor_prueba.escribir(huerfano["ejecutor"])
    else:
        # En real se reconcilia contra Binance, nunca contra lo guardado: el conector mira cada orden propia.
        ej = lib_ejecutor_real.escribir(lib_ejecutor_real.revisar(ms))
    lineas, topado = lineas_de(amb, v["desde_ms"], ms)
    cobertura = ej.get("cobertura") or {}
    resumen = {**v, **cuentas_de(lineas), "ambiente": amb, "topado": topado,
               "huerfanas": huerfano["vencidas"] + huerfano["desnudas"], "desnudas": huerfano["desnudas"],
               "cerradas": huerfano["cerradas"], "motivo": huerfano["motivo"],
               "reposiciones": sum(_entero(x.get("reposiciones")) for x in (ej.get("posiciones") or [])),
               "protegidas": _entero(ej.get("protegidas")), "abiertas": _entero(ej.get("abiertas")),
               "sin_cobertura_min": cobertura.get("sin_cobertura_min"), "cubierto": bool(cobertura.get("cubierto"))}
    resumen["hubo"] = any(resumen[c] for c in CLAVES) or bool(resumen["cerradas"])
    if decidir is not None:
        d = decidir({"ahora_ms": ms, "ambiente": amb, "frenos": frenos, "ejecutor": ej, "resumen": resumen, "plan": p})
        if isinstance(d, dict):
            ej = d.get("ejecutor") if isinstance(d.get("ejecutor"), dict) else ej
            resumen.update({k: x for k, x in d.items() if k != "ejecutor"})
    p = anotar_ventana(p, v, cobertura, ms)
    p.update({"ultima": lib_datos.iso(ms), "ultima_ms": ms, "vueltas": _entero(p.get("vueltas")) + 1,
              "proxima": ms + CICLO_SEGUNDOS * 1000, "resumen": resumen, "error": ""})
    lib_trabajo.guardar_plan(TIPO, p)
    return vista(p, ms, frenos=frenos, ejecutor=ej)


# ── Lo que lee la pantalla ───────────────────────────────────────────────────────────────────────────────────────────

def parametros():
    """Con qué reglas trabaja el motor: las lee la pantalla y quedan en el archivo."""
    return {"tipo": TIPO, "ciclo_segundos": CICLO_SEGUNDOS, "etapas": list(ETAPAS), "gracia_min": GRACIA_MS // 60_000,
            "claves": list(CLAVES), "motivos": list(MOTIVOS), "ambiente": lib_ejecutor_prueba.AMBIENTE}


def vista(plan, ahora_ms=None, frenos=None, ejecutor=None):
    """El motor tal como está: cuándo fue la última revisión y hace cuántos minutos, si está activo o dormido, cuándo
    viene la próxima, el resumen de la última ventana y las ventanas que quedaron sin cobertura. No reconcilia nada:
    eso es `reconciliar`."""
    ms = _ms(ahora_ms)
    f = frenos if isinstance(frenos, dict) else lib_frenos.guardado()
    amb = lib_estado.activo()
    ej = ejecutor if isinstance(ejecutor, dict) else (
        lib_ejecutor_prueba.guardado() if amb == lib_ejecutor_prueba.AMBIENTE else lib_ejecutor_real.guardado())
    ultima = _entero(plan.get("ultima_ms"))
    hace = max(0, ms - ultima) if ultima else None
    corriendo = bool(plan.get("corriendo"))
    activo = bool(corriendo and hace is not None and hace <= GRACIA_MS)
    cobertura = ej.get("cobertura") or {}
    ventanas = ventanas_de(plan)
    motivos = []
    if not corriendo:
        motivos.append({"codigo": APAGADO, "par": "", "n": 0})
    elif not activo:
        motivos.append({"codigo": DORMIDO, "par": "", "n": _min(hace or 0)})
    if amb != lib_ejecutor_prueba.AMBIENTE:
        for m in (ej.get("motivos") or []):
            if m.get("codigo") in ("sin_llave", "sin_conexion"):
                motivos.append({"codigo": SIN_CONECTOR, "par": "", "n": 0})
                break
    if ej and not cobertura.get("cubierto"):
        motivos.append({"codigo": SIN_1M, "par": "", "n": _entero(cobertura.get("sin_cobertura_min"))})
    if f.get("frenado"):
        motivos.append({"codigo": FRENADO, "par": "", "n": 0})
    return {"formato": 1, "cuando": lib_datos.iso(ms), "ambiente": amb, "moneda": "USDT",
            "ciclo_segundos": CICLO_SEGUNDOS, "estado": plan.get("estado") or "nunca",
            "etapa": plan.get("etapa") or ETAPAS[0], "corriendo": corriendo,
            "deteniendo": bool(plan.get("deteniendo")), "activo": activo, "dormido": corriendo and not activo,
            "ultima": plan.get("ultima") or "", "ultima_ms": ultima, "hace_ms": hace,
            "hace_min": None if hace is None else _min(hace),
            "proxima": _entero(plan.get("proxima")), "vueltas": _entero(plan.get("vueltas")),
            "fallos": _entero(plan.get("fallos")), "error": plan.get("error") or "",
            "resumen": plan.get("resumen") if isinstance(plan.get("resumen"), dict) else {},
            "sin_cobertura": [dict(x) for x in ventanas],
            "abierta": bool(ventanas and ventanas[-1].get("abierto")),
            "cobertura": cobertura, "abiertas": _entero(ej.get("abiertas")), "puestas": _entero(ej.get("puestas")),
            "protegidas": _entero(ej.get("protegidas")), "saldo": _numero(ej.get("saldo")),
            "frenado": bool(f.get("frenado")), "estado_frenos": f.get("estado") or "", "modo": f.get("modo") or "",
            "parametros": parametros(), "motivos": motivos, "listo": not motivos}


def estado(ahora_ms=None):
    """En qué quedó el motor, sin reconciliar y sin tocar la red: lo que hay en su plan, en los frenos y en el ejecutor
    de la última revisión. Un plan que dice «corriendo» y dejó de latir queda `interrumpido`."""
    ms = _ms(ahora_ms)
    guardado = lib_trabajo.mirar(TIPO, lib_trabajo.leer_plan(TIPO))
    plan = armar(ms, guardado)
    plan["corriendo"], plan["deteniendo"] = guardado["corriendo"], guardado["deteniendo"]
    if not plan["corriendo"]:
        lib_trabajo.guardar_plan(TIPO, plan)
    return vista(plan, ms)


def guardado():
    """El último plan escrito, tal cual: sin red y sin recorrer nada."""
    return lib_trabajo.leer_plan(TIPO)
