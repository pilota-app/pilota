#!/usr/bin/env python3
"""lib_ejecutor_prueba — el ejecutor del modo prueba: saldo ficticio, cruces con velas de 1 m y protección simulada. Solo
biblioteca estándar. No es una acción.

Es el **mismo contrato** que va a tener el conector real (`entrar`, `revisar`, `cerrar`, `estado`) con una sola diferencia:
acá no hay dinero. Todo lo demás es de verdad —los precios, las velas de 1 m, los mínimos de Binance, el tamaño de la
operación y los frenos—, así que lo que en real no se puede hacer acá tampoco.

| Qué | Dónde vive |
|---|---|
| el saldo ficticio, las posiciones y sus órdenes | el estado firmado de la cuenta de prueba (`lib_estado`, campo `posiciones`) |
| lo que pasó | el registro que no se borra (`lib_registro`): una línea por entrada, por llenado, por cierre y por rechazo |
| lo último que se calculó | `<datos>/mercado/ejecutor.json` (`escribir`, `guardado`): lo leen la pantalla y el motor, sin recorrer nada |

Lo que no se negocia aquí:
- **Toda orden pasa antes por el tamaño y por los frenos.** `entrar` no decide cuánto ni si se puede: eso ya lo dijeron
  `lib_tamano.tamano` y `lib_frenos.revisar_orden`, y una orden que no venga de ahí se rechaza con su motivo en código
  (`RECHAZOS`). El ejecutor no es el lugar donde se discute un freno.
- **Una posición sin protección no se abre.** Antes de poner la entrada se revisa que la protección automática **cabe**
  (`cabe`): el tick de los tres niveles, el paso de la cantidad y la cantidad y el nocional mínimos **de cada lado** (la
  compra, el stop y el objetivo). Si no cabe, no hay orden: una orden que Binance rechazaría es una posición desnuda.
- **La mitad que no alcanza el mínimo no se parte.** La estrategia de ruptura sale mitad con el objetivo y mitad con el
  stop móvil; si esa mitad queda bajo el mínimo de Binance, la posición **sale entera** (`entera`).
- **Los cruces se miran con velas de 1 m**, no con el libro: `seguir` recorre minuto por minuto las velas que faltaban y
  aplica la regla de siempre (`lib_resolucion.resolver`). El minuto que tocó el stop y el objetivo a la vez se cuenta como
  stop: del minuto no se baja más.
- **El stop móvil cancela y repone la protección.** Mover el stop es cancelar la OCO y poner otra (es lo que pide Binance),
  así que la cuenta de reposiciones y los ids nuevos quedan a la vista (`reposiciones`, `ordenes_de`).
- **Los ids son deterministas y llevan el prefijo propio** (`PREFIJO`, `id_de`): de los mismos datos sale el mismo id, y lo
  que **no** lleva el prefijo es de otro y Pilota no lo toca nunca (`es_nuestro`, `ajenas`).
- **El dinero se mueve una sola vez, al cerrar.** Entrar compromete el monto (`monto`, lo que mira el reparto del tamaño) y
  no toca el saldo; el saldo se mueve con lo que dejó la operación (`lib_frenos.con_cierre`: saldo, racha, día y una
  operación más), con los costos de los dos lados adentro (`lib_costos.resultado`).
- **En prueba la protección existe solo con el motor encendido**: lo que pasó mientras nadie miraba se aplica al revisar y
  el rato sin cobertura se dice (`cobertura`), nunca se tapa.
- **El saldo de prueba se reinicia donde se reiniciaba** (`lib_estado.reiniciar`: una sola confirmación, al tiro y queda en
  el registro). Acá no hay otra puerta para eso.
"""
import math
import os

import lib_calibracion
import lib_costos
import lib_datos
import lib_estado
import lib_estrategias
import lib_frenos
import lib_registro
import lib_resolucion
import lib_tamano
import minimo_viable
import nucleo

#: El ambiente que mueve este ejecutor: el otro es el conector real, en su paso.
AMBIENTE = lib_estado.PRUEBA
#: El prefijo de todo id de orden de Pilota (el clientOrderId). Lo que no lo tenga es de otro: no se cancela ni se cierra.
PREFIJO = "pil"
#: Las tres patas de una posición y los dos lados.
ENTRADA, STOP, OBJETIVO = "entrada", "stop", "objetivo"
LADO_SALIDA = "venta"
TIPO_STOP, TIPO_OBJETIVO = "stop", "limite"
#: En qué estado puede estar una orden o una posición.
PUESTA, ABIERTA, LLENADA, VENCIDA, CANCELADA, CERRADA = "puesta", "abierta", "llenada", "vencida", "cancelada", "cerrada"
ESTADOS = (PUESTA, ABIERTA)
#: Lo que puede pasarle a una posición cuando se recorren sus velas de 1 m.
CIERRE = "cierre"
#: Las estrategias que salen en dos mitades (la otra sale entera). La mitad es la mitad justa: el resto se queda con el
#: stop móvil.
ESTRATEGIAS_PARCIALES = ("ruptura",)
MITAD = 0.5
#: Con qué razón queda cada cosa en el registro que no se borra (las de `lib_registro.RAZONES`).
RAZON_ENTRADA = {"ruptura": "entrada_ruptura", "rebote": "entrada_rebote"}
RAZON_SALIDA = {OBJETIVO: "objetivo", STOP: "stop", "stop_movil": "stop_movil", "manual": "cierre_manual"}
RAZON_VENCIDA = "propuesta_vencida"
#: Por qué no hay orden. Son códigos: la pantalla los traduce y nunca se muestra el código pelado. Los primeros son de
#: acá; los del tamaño y de los frenos llegan tal como los dijeron ellos.
RECHAZOS = tuple(dict.fromkeys(("sin_ambiente", "sin_cuenta", "sin_opcion", "no_permitida", "repetida", "sin_minimos",
                                "sin_filtros", "sin_niveles", "tick", "paso", "cantidad_minima", "nocional_compra",
                                "nocional_stop", "nocional_objetivo", *lib_tamano.RECHAZOS, *lib_frenos.RECHAZOS)))
#: Por qué no se puede cerrar algo a mercado.
SIN_PRECIO, SIN_POSICION = "sin_precio", "sin_posicion"
#: Por qué todavía no se puede operar en prueba (`estado`).
MOTIVOS = ("frenado", "sin_cuenta", "sin_minimos", "sin_1m", "sin_capital")
#: Cuánto rato sin velas de 1 m se le perdona antes de decir que la protección quedó sin cubrir: dos vueltas del motor.
GRACIA_COBERTURA_MS = 10 * 60 * 1000
#: Ruido de coma flotante, no un número distinto.
TOLERANCIA = 1e-9


def ruta_ejecutor():
    return os.path.join(lib_datos.carpeta_mercado(), "ejecutor.json")


# ── Números y ids, sin creerle a nadie ───────────────────────────────────────────────────────────────────────────────

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


def id_de(par, ms, que, n=0):
    """El clientOrderId de una orden: **determinista** (de los mismos datos sale el mismo id, así reconciliar dos veces no
    duplica nada) y con el prefijo propio delante. `n` es la reposición: cada vez que el stop móvil cancela y repone la
    protección, sus patas son órdenes nuevas."""
    base = f"{PREFIJO}-{AMBIENTE[0]}-{par}-{_entero(ms)}-{que}"
    return base if n <= 0 else f"{base}-{int(n)}"


def es_nuestro(identificador):
    """Si esa orden la puso Pilota. Lo que no lleva el prefijo es de otro: no se cancela, no se cierra y no se cuenta como
    protegido. Es la misma regla con la que el conector real va a mirar las órdenes abiertas en Binance."""
    return isinstance(identificador, str) and identificador.startswith(PREFIJO + "-")


def nuestras(cuerpo):
    """Las posiciones de Pilota en el estado firmado, en orden."""
    return [p for p in ((cuerpo or {}).get("posiciones") or []) if isinstance(p, dict) and es_nuestro(p.get("id"))]


def ajenas(cuerpo):
    """Lo que hay en `posiciones` y no es de Pilota: se deja exactamente como está."""
    return [p for p in ((cuerpo or {}).get("posiciones") or []) if isinstance(p, dict) and not es_nuestro(p.get("id"))]


def _editable(cuenta):
    """Si a esta cuenta se le puede escribir el estado: la misma regla de los frenos (el archivo sospechoso no se pisa y
    una cuenta que todavía no existe no se inventa)."""
    return not cuenta.get("frenado") and not (cuenta.get("arranque") or {}).get("nuevo")


# ── La protección automática: ¿cabe? ─────────────────────────────────────────────────────────────────────────────────

def mitad_de(cantidad, paso):
    """La mitad de la cantidad, bajada al paso de Binance: la parte que sale con el objetivo."""
    return lib_tamano.bajar_al_paso(_numero(cantidad) * MITAD, _numero(paso))


def _pata(que, precio, cantidad):
    return {"que": que, "precio": precio, "cantidad": cantidad, "nocional": precio * cantidad}


def cabe(filtros, precio, stop, objetivo, cantidad, parcial=False):
    """Si la protección automática cabe en ese par con **estos** niveles y esta cantidad: los tres precios en el tick, la
    cantidad en el paso, y la cantidad y el nocional mínimos en **cada lado** (la compra, la pata del stop y la del
    objetivo). La del stop es la que vale menos USDT, así que es la que suele cortar.

    `parcial` es la estrategia que sale en dos mitades: si la mitad no pasa por sí sola los mínimos, la posición sale
    entera (`entera` en verdadero, que no es un rechazo). Devuelve `cabe` con su `motivo` en código (`RECHAZOS`)."""
    f = filtros if isinstance(filtros, dict) else {}
    tick, paso = _numero(f.get("tick")), _numero(f.get("paso"))
    minima, nocional = _numero(f.get("cantidad_minima")), _numero(f.get("nocional_minimo"))
    precio, stop, objetivo, cantidad = (_numero(x) for x in (precio, stop, objetivo, cantidad))
    base = {"cabe": False, "motivo": "", "entera": True, "mitad": 0.0, "resto": cantidad, "patas": [],
            "cantidad_minima": minima, "nocional_minimo": nocional}

    def no(motivo):
        return {**base, "motivo": motivo}

    if not (f.get("par") and tick > 0 and paso > 0 and minima > 0):
        return no("sin_filtros")
    if not (0 < stop < precio < objetivo):
        return no("sin_niveles")
    if any(abs(x - minimo_viable.bajar_al_tick(x, tick)) > TOLERANCIA for x in (precio, stop, objetivo)):
        return no("tick")
    if cantidad <= 0 or abs(cantidad - lib_tamano.bajar_al_paso(cantidad, paso)) > TOLERANCIA:
        return no("paso")
    if cantidad + TOLERANCIA < minima:
        return no("cantidad_minima")
    patas = [_pata("compra", precio, cantidad), _pata(STOP, stop, cantidad), _pata(OBJETIVO, objetivo, cantidad)]
    base = {**base, "patas": patas}
    for pata in patas:
        if pata["nocional"] + TOLERANCIA < nocional:
            return no("nocional_" + pata["que"])
    # La mitad que sale con el objetivo tiene que pasar los mínimos ella sola, y el resto también: si no, no se parte.
    mitad, resto = 0.0, cantidad
    if parcial:
        mitad = mitad_de(cantidad, paso)
        resto = lib_tamano.bajar_al_paso(cantidad - mitad, paso)
        if not (mitad + TOLERANCIA >= minima and resto + TOLERANCIA >= minima
                and mitad * objetivo + TOLERANCIA >= nocional and mitad * stop + TOLERANCIA >= nocional
                and resto * stop + TOLERANCIA >= nocional):
            mitad, resto = 0.0, cantidad
    return {**base, "cabe": True, "entera": not mitad, "mitad": mitad, "resto": resto}


def ordenes_de(p):
    """Las órdenes que Pilota tiene puestas por una posición, con su id determinista: la entrada mientras no se llena y,
    llenada, las patas de la protección simulada (la del objetivo solo por la mitad cuando la estrategia sale en dos)."""
    if p.get("estado") != ABIERTA:
        return [{"id": p["id"], "que": ENTRADA, "lado": lib_frenos.LADO_ENTRADA, "tipo": lib_frenos.TIPO_ENTRADA,
                 "precio": _numero(p.get("precio")), "cantidad": _numero(p.get("cantidad")), "estado": PUESTA}]
    ms, n = _entero(p.get("llenada_ms")), _entero(p.get("reposiciones"))
    patas = [{"id": id_de(p["par"], ms, STOP, n), "que": STOP, "lado": LADO_SALIDA, "tipo": TIPO_STOP,
              "precio": _numero(p.get("stop")), "cantidad": _numero(p.get("cantidad")), "estado": PUESTA}]
    if _numero(p.get("objetivo")) > 0:
        patas.append({"id": id_de(p["par"], ms, OBJETIVO, n), "que": OBJETIVO, "lado": LADO_SALIDA,
                      "tipo": TIPO_OBJETIVO, "precio": _numero(p["objetivo"]),
                      "cantidad": _numero(p.get("mitad")) or _numero(p.get("cantidad")), "estado": PUESTA})
    return patas


# ── Entrar: lo que ya dijeron el tamaño y los frenos ─────────────────────────────────────────────────────────────────

def vigencia_de(o, ms):
    """Hasta cuándo espera la orden límite en el nivel. La trae la señal (`vence`); si no la trae, las mismas velas de
    vigencia de la estrategia (`lib_estrategias.VIGENCIA_VELAS`): una entrada que no se llenó en ese rato ya no es la
    misma oportunidad."""
    vence = _entero(o.get("vence"))
    if vence > 0:
        return vence
    paso = lib_datos.PASO_MS.get(o.get("temporalidad"), 0)
    return ms + (lib_estrategias.VIGENCIA_VELAS + 1) * paso if paso else 0


def repetida(cuerpo, o):
    """Si esa misma oportunidad ya está puesta: el mismo par, la misma estrategia y la misma vela. Así el motor puede
    revisar dos veces sin abrir dos posiciones por la misma señal."""
    return any(p.get("par") == o.get("par") and p.get("estrategia") == o.get("estrategia")
               and _entero(p.get("vela_ms")) == _entero(o.get("vela")) for p in nuestras(cuerpo))


def nueva_posicion(o, t, c, objetivo, ms):
    """La posición como queda al poner la entrada: los niveles ya bajados al tick por el tamaño, la cantidad en el paso,
    el monto comprometido y la protección que va a recibir cuando se llene."""
    precio, stop = _numero(t.get("precio")), _numero(t.get("stop"))
    p = {"id": id_de(o["par"], ms, ENTRADA), "par": o["par"], "estrategia": o.get("estrategia") or "",
         "temporalidad": o.get("temporalidad") or "", "vela_ms": _entero(o.get("vela")), "estado": PUESTA,
         "precio": precio, "stop": stop, "stop_inicial": stop, "objetivo": _numero(objetivo),
         "cantidad": _numero(t.get("cantidad")), "monto": _numero(t.get("monto")),
         "mitad": c["mitad"], "entera": bool(c["entera"]),
         "movil": o.get("estrategia") in ESTRATEGIAS_PARCIALES,
         "distancia_stop": (precio - stop) / precio if precio > 0 else 0.0,
         "puntaje": o.get("puntaje"), "puesta_ms": ms, "vence_ms": vigencia_de(o, ms), "llenada_ms": 0,
         "revisado_ms": ms, "maximo": 0.0, "reposiciones": 0, "protegida": False}
    p["vence"] = lib_datos.iso(p["vence_ms"]) if p["vence_ms"] else ""
    return {**p, "ordenes": ordenes_de(p)}


def _orden_registro(p, estado):
    """Lo que dice del pedido la línea del registro (`lib_registro.CAMPOS_ORDEN`): números y códigos, nada más."""
    return {"id": p["id"], "lado": lib_frenos.LADO_ENTRADA, "tipo": lib_frenos.TIPO_ENTRADA, "precio": p["precio"],
            "cantidad": p["cantidad"], "monto": p["monto"], "stop": p["stop"], "objetivo": p["objetivo"],
            "estado": estado, "vence_ms": p["vence_ms"]}


def _rechazo(o, motivo, ms, tamano_=None):
    """Una orden que no se puso, con su motivo en código y en el registro: un «no se puede» sin su motivo no sirve."""
    lib_registro.anotar(AMBIENTE, "rechazo", par=o.get("par") or "", puntaje=o.get("puntaje"), ms=ms,
                        resultado={"motivo": motivo})
    return {"puesta": False, "motivo": motivo, "posicion": None, "tamano": tamano_, "proteccion": None}


def entrar(opcion, ahora_ms=None, tamano_=None, frenos=None, com=None, calibracion=None):
    """Pone la entrada de una oportunidad: una compra límite post-only en el nivel, con su protección ya validada. Lo que
    se compra y si se puede comprar **no se decide acá**: viene del tamaño (`lib_tamano`) y de los frenos (`lib_frenos`), y
    una orden que no pasa por los dos se rechaza con su motivo. La exigencia y los tres modos son su propio paso.

    `tamano_`, `frenos`, `com` y `calibracion` se pueden pasar ya calculados (el motor, en su paso, los tiene a mano)."""
    ms = _ms(ahora_ms)
    o = opcion if isinstance(opcion, dict) else {}
    vacio = {"puesta": False, "motivo": "", "posicion": None, "tamano": None, "proteccion": None}
    if lib_estado.activo() != AMBIENTE:
        return {**vacio, "motivo": "sin_ambiente"}
    cuenta = lib_estado.cargar(AMBIENTE, ahora_ms=ms)
    if (cuenta.get("arranque") or {}).get("nuevo"):
        # Una cuenta que todavía no existe no se inventa, y tampoco se le escribe una línea de registro: el registro es
        # justo lo que diría, en el próximo arranque, que esta cuenta ya vivió algo y perdió su estado.
        return {**vacio, "motivo": "sin_cuenta"}
    if o.get("estrategia") not in RAZON_ENTRADA or not (_numero(o.get("entrada")) > 0 and _numero(o.get("stop")) > 0):
        return _rechazo(o, "sin_opcion", ms)
    if not o.get("permitida"):
        return _rechazo(o, "no_permitida", ms)
    f = frenos if isinstance(frenos, dict) else lib_frenos.aplicar(AMBIENTE, ms)
    cuenta = lib_estado.cargar(AMBIENTE, ahora_ms=ms)   # después de los frenos: ellos pudieron poner el día al día
    cuerpo = lib_estado.cuerpo_de(cuenta)
    if repetida(cuerpo, o):
        return _rechazo(o, "repetida", ms)
    pares, md = lib_tamano.filtros_de()
    filtros = pares.get(o.get("par")) or {}
    com = lib_tamano.comisiones(com if com is not None else lib_costos.comisiones())
    abiertas, comprometido = lib_tamano.posiciones_de(cuenta)
    if isinstance(tamano_, dict):
        t = tamano_
    else:
        # El tope del monto mientras el modelo esté «Aún sin validar» es el mismo del tamaño: acá no se agranda nada.
        modelo = lib_calibracion.modelo(lib_calibracion.guardada() if calibracion is None else calibracion)
        t = lib_tamano.tamano(_numero(cuenta.get("saldo")), o.get("entrada"), o.get("stop"), filtros, com,
                              modelo["tope"] if modelo["topado"] else None, abiertas, comprometido,
                              not _editable(cuenta))
    if not md.get("calculado"):
        return _rechazo(o, "sin_minimos", ms, t)
    # El tamaño es la primera puerta y su motivo es el que se muestra: «no se puede» sin su motivo no sirve de nada.
    if not t.get("puede"):
        return _rechazo(o, t.get("motivo") or "sin_tamano", ms, t)
    orden = {"lado": lib_frenos.LADO_ENTRADA, "tipo": lib_frenos.TIPO_ENTRADA, "precio": t.get("precio"),
             "stop": t.get("stop"), "cantidad": t.get("cantidad"), "monto": t.get("monto"),
             "apalancamiento": lib_frenos.APALANCAMIENTO}
    r = lib_frenos.revisar_orden(orden, f, t)
    if not r["puede"]:
        return _rechazo(o, r["motivo"], ms, t)
    objetivo = minimo_viable.bajar_al_tick(_numero(o.get("objetivo")), _numero(filtros.get("tick")))
    c = cabe(filtros, t["precio"], t["stop"], objetivo, t["cantidad"], o["estrategia"] in ESTRATEGIAS_PARCIALES)
    if not c["cabe"]:
        return _rechazo(o, c["motivo"], ms, t)
    if not _editable(cuenta):           # el archivo sospechoso no se pisa y una cuenta que no existe no se inventa
        return _rechazo(o, "frenado", ms, t)
    p = nueva_posicion(o, t, c, objetivo, ms)
    lib_estado.guardar(AMBIENTE, {**cuerpo, "cuando": lib_datos.iso(ms), "cuando_ms": ms,
                                  "posiciones": [*ajenas(cuerpo), *nuestras(cuerpo), p]})
    lib_registro.anotar(AMBIENTE, RAZON_ENTRADA[o["estrategia"]], par=p["par"], puntaje=p["puntaje"], ms=ms,
                        orden=_orden_registro(p, PUESTA))
    return {"puesta": True, "motivo": "", "posicion": p, "tamano": t, "proteccion": c}


# ── Seguir una posición minuto por minuto (sin tocar el disco) ───────────────────────────────────────────────────────

def _evento(que, ms, p, **extra):
    """Un evento con lo que la posición decía **en ese momento**: la cantidad, el stop, cuándo se llenó y cuántas veces se
    repuso su protección. Así la línea del registro no depende de cómo quedó la posición después."""
    return {"que": que, "ms": _entero(ms), "cantidad": _numero(p.get("cantidad")), "stop": _numero(p.get("stop")),
            "objetivo": _numero(p.get("objetivo")), "llenada_ms": _entero(p.get("llenada_ms")),
            "reposiciones": _entero(p.get("reposiciones")), **extra}


def seguir(pos, velas, filtros=None, spread=None, ahora_ms=None):
    """Lo que le pasó a una posición en las velas de 1 m que faltaban. No lee nada del disco y no mueve ningún saldo: es
    la capa que recorre el motor, en su paso, y la que se puede probar con velas inventadas.

    En cada vela, y en este orden: la entrada que venció se cancela; la entrada que se llenó recibe su protección
    simulada; se mira qué cruzó la vela con la regla de siempre (`lib_resolucion.resolver`: el minuto que tocó el stop y
    el objetivo a la vez se cuenta como stop) y recién al final el stop móvil sube —nunca con el máximo de la misma vela
    que todavía no se revisó—.

    Devuelve la posición como quedó (o `None` si se cerró o se canceló) y los eventos, que es lo que se anota en el
    registro y lo que mueve el saldo afuera (`revisar`)."""
    paso = lib_datos.PASO_MS[lib_datos.MINUTO]
    p = dict(pos)
    tick = _numero((filtros or {}).get("tick"))
    hoja = lib_costos.SPREAD_SUPUESTO if spread is None else _numero(spread, lib_costos.SPREAD_SUPUESTO)
    eventos = []
    for v in velas:
        if _entero(p.get("revisado_ms")) > v[0]:
            continue
        cierra_ms = v[0] + paso
        if p["estado"] == PUESTA:
            if _entero(p.get("vence_ms")) and v[0] >= p["vence_ms"]:
                eventos.append(_evento(VENCIDA, p["vence_ms"], p, precio=p["precio"]))
                return {"posicion": None, "eventos": eventos}
            # Tocar el nivel no alcanza: una límite se llena cuando el precio sigue en contra (`lib_costos.llena`).
            if not lib_costos.llena(p["precio"], v[3], hoja):
                p["revisado_ms"] = cierra_ms
                continue
            p.update(estado=ABIERTA, llenada_ms=cierra_ms, maximo=v[2], protegida=True)
            p["ordenes"] = ordenes_de(p)
            eventos.append(_evento(LLENADA, cierra_ms, p, precio=p["precio"]))
            # Y se sigue mirando **esta misma vela**: el precio pudo seguir bajando hasta el stop en el mismo minuto.
        objetivo = _numero(p.get("objetivo")) or math.inf
        r = lib_resolucion.resolver(v, _numero(p.get("stop")), objetivo)
        if r["por"] == lib_resolucion.POR_STOP:
            razon = "stop_movil" if _entero(p.get("reposiciones")) else STOP
            eventos.append(_evento(CIERRE, cierra_ms, p, por=STOP, razon=razon, precio=p["stop"],
                                   etiqueta=r["etiqueta"], entera=True))
            return {"posicion": None, "eventos": eventos}
        if r["por"] == lib_resolucion.POR_OBJETIVO:
            mitad = _numero(p.get("mitad"))
            entera = bool(p.get("entera")) or not mitad
            eventos.append(_evento(CIERRE, cierra_ms, p, por=OBJETIVO, razon=OBJETIVO, precio=p["objetivo"],
                                   etiqueta=r["etiqueta"], entera=entera,
                                   **({} if entera else {"cantidad": mitad})))
            if entera:
                return {"posicion": None, "eventos": eventos}
            # La mitad salió con el objetivo; el resto se queda solo con el stop móvil (sin pata de objetivo).
            queda = _numero(p["cantidad"]) - mitad
            p["monto"] = _numero(p.get("monto")) * (queda / _numero(p["cantidad"]))
            p.update(cantidad=queda, mitad=0.0, objetivo=0.0, entera=True)
            p["ordenes"] = ordenes_de(p)
        p["maximo"] = max(_numero(p.get("maximo")), v[2])
        if p.get("movil") and tick > 0:
            arriba = minimo_viable.bajar_al_tick(p["maximo"] * (1 - _numero(p.get("distancia_stop"))), tick)
            if arriba > _numero(p.get("stop")) + tick / 2:
                p["stop"] = arriba                      # cancelar la protección y poner otra: eso es moverlo
                p["reposiciones"] = _entero(p.get("reposiciones")) + 1
                p["ordenes"] = ordenes_de(p)
        p["revisado_ms"] = cierra_ms
    return {"posicion": p, "eventos": eventos}


# ── Lo que deja una operación ────────────────────────────────────────────────────────────────────────────────────────

def _lado_costo(por):
    """Con qué comisión sale: el objetivo es una límite (maker) y todo lo demás sale a mercado (taker, y además cruza el
    libro). Un cierre a mano paga lo mismo que un stop: también sale a mercado."""
    return OBJETIVO if por == OBJETIVO else STOP


def neto_de(entrada, salida, cantidad, por, spread=None, com=None):
    """Lo que deja en USDT cerrar `cantidad` de una posición, con los costos de los dos lados adentro (la comisión de
    cada lado, la conversión USDT↔FDUSD y, si sale a mercado, la diferencia entre compra y venta)."""
    hoja = lib_costos.SPREAD_SUPUESTO if spread is None else _numero(spread, lib_costos.SPREAD_SUPUESTO)
    r = lib_costos.resultado(_numero(entrada), _numero(salida), _lado_costo(por), hoja, lib_tamano.comisiones(com))
    cantidad = _numero(cantidad)
    return {"neto": cantidad * (r["recibido"] - r["pagado"]), "neto_relativo": r["neto"],
            "precio": r["precio_salida"], "costos": cantidad * r["pagado"] * r["costos"]}


# ── Revisar: las velas de 1 m que faltaban, aplicadas ────────────────────────────────────────────────────────────────

def minutos_de(pares=None):
    """Las velas de 1 m guardadas de cada par que se opera: son las que dicen qué se cruzó."""
    return {p: lib_datos.leer_serie(p, lib_datos.MINUTO) for p in (pares or lib_datos.PARES_OPERADOS)}


def _anotar_eventos(p, eventos, cuerpo, spread, com):
    """Las líneas del registro de una posición recorrida y el cuerpo con el saldo movido: el saldo solo se mueve al
    cerrar (`lib_frenos.con_cierre`: saldo, racha, día y una operación más). `p` es la posición como estaba antes de
    recorrer; lo que cambió en el camino viene en cada evento."""
    for ev in eventos:
        if ev["que"] == LLENADA:
            lib_registro.anotar(AMBIENTE, RAZON_ENTRADA[p["estrategia"]], par=p["par"], puntaje=p.get("puntaje"),
                                ms=ev["ms"], orden=_orden_registro(p, LLENADA))
        elif ev["que"] == VENCIDA:
            lib_registro.anotar(AMBIENTE, RAZON_VENCIDA, par=p["par"], puntaje=p.get("puntaje"), ms=ev["ms"],
                                orden=_orden_registro(p, ev.get("estado") or VENCIDA))
        elif ev["que"] == CIERRE:
            r = neto_de(p["precio"], ev["precio"], ev["cantidad"], ev["por"], spread, com)
            cuerpo = lib_frenos.con_cierre(cuerpo, r["neto"], ev["ms"])
            llenada = ev.get("llenada_ms") or _entero(p.get("llenada_ms"))
            vividos = max(0, ev["ms"] - llenada) // lib_datos.PASO_MS[lib_datos.MINUTO]
            lib_registro.anotar(
                AMBIENTE, RAZON_SALIDA[ev["razon"]], par=p["par"], puntaje=p.get("puntaje"), ms=ev["ms"],
                orden={"id": p["id"], "lado": LADO_SALIDA, "cantidad": ev["cantidad"], "precio": ev["precio"],
                       "estado": CERRADA if ev["entera"] else LLENADA},
                resultado={"por": ev["por"], "precio": r["precio"], "neto": r["neto"],
                           "neto_relativo": r["neto_relativo"], "comision": r["costos"],
                           "saldo": cuerpo["saldo"], "referencia": cuerpo["referencia"],
                           "minutos": vividos, "supuesto": ev["etiqueta"], "n": _entero(ev.get("reposiciones"))})
    return cuerpo


def revisar(ahora_ms=None, modelo=None, com=None, minutos=None):
    """Recorre las velas de 1 m que faltaban y deja aplicado lo que pasó: las entradas que se llenaron con su protección
    simulada, las que vencieron canceladas, los stops y objetivos que se cruzaron cobrados y el stop móvil donde quedó.
    Mirar es aplicar, como en los frenos: no hay un «solo mirar» que deje una posición cruzada abierta.

    De una cuenta cuyo archivo no es de fiar no se toca nada."""
    ms = _ms(ahora_ms)
    cuenta = lib_estado.cargar(AMBIENTE, ahora_ms=ms)
    series = minutos if isinstance(minutos, dict) else minutos_de()
    m = lib_costos.modelo() if modelo is None else modelo
    com = lib_tamano.comisiones(com if com is not None else lib_costos.comisiones())
    if not _editable(cuenta):
        return estado(ms, cuenta=cuenta, minutos=series, com=com)
    cuerpo = lib_estado.cuerpo_de(cuenta)
    pares, _ = lib_tamano.filtros_de()
    nuevo, vivas = cuerpo, []
    for p in nuestras(cuerpo):
        par = p.get("par")
        velas = [v for v in (series.get(par) or []) if v[0] >= _entero(p.get("revisado_ms"))]
        hoja = lib_costos.spread_de(m, par)
        r = seguir(p, velas, pares.get(par) or {}, hoja, ms)
        nuevo = _anotar_eventos(p, r["eventos"], nuevo, hoja, com)
        if r["posicion"]:
            vivas.append(r["posicion"])
    nuevo = {**nuevo, "posiciones": [*ajenas(cuerpo), *vivas]}
    sin_hora = lambda d: {k: v for k, v in d.items() if k not in ("cuando", "cuando_ms")}
    if sin_hora(nuevo) != sin_hora(cuerpo):
        lib_estado.guardar(AMBIENTE, {**nuevo, "cuando": lib_datos.iso(ms), "cuando_ms": ms})
        cuenta = lib_estado.cargar(AMBIENTE, ahora_ms=ms)
    return estado(ms, cuenta=cuenta, minutos=series, com=com)


def cerrar(identificador=None, ahora_ms=None, modelo=None, com=None, minutos=None):
    """Cierra a mercado una posición de Pilota (o todas, sin id: es lo que pide «Cerrar todo y pasar a USDT» y lo que va a
    pedir la reducción forzada del piso absoluto, en su paso). Lo que no lleva el prefijo propio no se toca nunca.

    El precio es el cierre de la última vela de 1 m guardada: sin esa vela no se cierra nada (`SIN_PRECIO`), porque un
    precio inventado no es un resultado. Una entrada que todavía no se llenó solo se cancela: no deja ni pérdida ni
    ganancia."""
    ms = _ms(ahora_ms)
    cuenta = lib_estado.cargar(AMBIENTE, ahora_ms=ms)
    series = minutos if isinstance(minutos, dict) else minutos_de()
    m = lib_costos.modelo() if modelo is None else modelo
    com = lib_tamano.comisiones(com if com is not None else lib_costos.comisiones())
    cuerpo = lib_estado.cuerpo_de(cuenta)
    elegidas = [p for p in nuestras(cuerpo) if identificador is None or p.get("id") == identificador]
    if not _editable(cuenta) or not elegidas:
        return {"hecho": False, "motivo": "frenado" if not _editable(cuenta) else SIN_POSICION, "cerradas": 0,
                "estado": estado(ms, cuenta=cuenta, minutos=series, com=com)}
    nuevo, quedan, cerradas, motivo = cuerpo, [], 0, ""
    for p in nuestras(cuerpo):
        if p not in elegidas:
            quedan.append(p)
            continue
        if p.get("estado") == PUESTA:            # una entrada que no se llenó solo se cancela: ni pérdida ni ganancia
            lib_registro.anotar(AMBIENTE, RAZON_VENCIDA, par=p["par"], puntaje=p.get("puntaje"), ms=ms,
                                orden=_orden_registro(p, CANCELADA))
            cerradas += 1
            continue
        precio = precio_de(series.get(p.get("par")) or [])
        if not _numero(precio) > 0:              # sin vela de 1 m no hay precio, y un precio inventado no es un cierre
            motivo = SIN_PRECIO
            quedan.append(p)
            continue
        hoja = lib_costos.spread_de(m, p.get("par"))
        nuevo = _anotar_eventos(p, [_evento(CIERRE, ms, p, por="manual", razon="manual", precio=precio,
                                            etiqueta=lib_resolucion.CLARA, entera=True)], nuevo, hoja, com)
        cerradas += 1
    lib_estado.guardar(AMBIENTE, {**nuevo, "cuando": lib_datos.iso(ms), "cuando_ms": ms,
                                  "posiciones": [*ajenas(cuerpo), *quedan]})
    return {"hecho": bool(cerradas), "motivo": motivo, "cerradas": cerradas,
            "estado": estado(ms, minutos=series, com=com)}


# ── Lo que lee la pantalla y el motor ────────────────────────────────────────────────────────────────────────────────

def precio_de(velas):
    """El cierre de la última vela de 1 m guardada, o `None`: con eso se muestra una posición y con eso se cierra a
    mercado. Un precio que no está no se inventa."""
    return velas[-1][4] if velas else None


def cobertura_de(series, ahora_ms):
    """Hasta cuándo llegan las velas de 1 m y cuánto rato quedó sin mirar. En prueba la protección existe solo con el
    motor encendido, así que este número se muestra: es el rato en que un stop no se habría aplicado."""
    paso = lib_datos.PASO_MS[lib_datos.MINUTO]
    ultimas = [velas[-1][0] + paso for velas in (series or {}).values() if velas]
    hasta = min(ultimas) if len(ultimas) == len(series or {}) and ultimas else 0
    sin = max(0, ahora_ms - hasta) if hasta else None
    return {"hasta": lib_datos.iso(hasta) if hasta else "", "hasta_ms": hasta, "gracia_min": GRACIA_COBERTURA_MS // 60_000,
            "sin_cobertura_min": None if sin is None else sin // paso,
            "cubierto": bool(hasta) and sin <= GRACIA_COBERTURA_MS,
            "pares": [{"par": par, "velas": len(velas or []),
                       "ultima": lib_datos.iso(velas[-1][0] + paso) if velas else ""}
                      for par, velas in sorted((series or {}).items())]}


def _vista(p, precio):
    """Una posición como se ve: lo que vale ahora y lo que lleva ganado o perdido, bruto (los costos se cobran al
    cerrar). Sin precio de ahora, los dos en `None`: no se supone ninguno."""
    cantidad, entrada = _numero(p.get("cantidad")), _numero(p.get("precio"))
    gana = None if precio is None else cantidad * (precio - entrada)
    return {**p, "precio_ahora": precio, "valor": None if precio is None else cantidad * precio,
            "ganancia": gana, "ganancia_relativa": None if gana is None or entrada <= 0 else gana / (cantidad * entrada),
            "movido": _numero(p.get("stop")) > _numero(p.get("stop_inicial")) + TOLERANCIA}


def parametros():
    """Con qué reglas opera el ejecutor de prueba: las lee la pantalla y quedan en el archivo."""
    return {"ambiente": AMBIENTE, "prefijo": PREFIJO, "mitad": MITAD, "estrategias_parciales": list(ESTRATEGIAS_PARCIALES),
            "estados": list(ESTADOS), "patas": [ENTRADA, STOP, OBJETIVO], "rechazos": list(RECHAZOS),
            "motivos": list(MOTIVOS),
            "razones": {**RAZON_ENTRADA, **RAZON_SALIDA, "vencida": RAZON_VENCIDA},
            "penetracion": lib_costos.PENETRACION_SPREADS, "temporalidad": lib_datos.MINUTO,
            "vigencia_velas": lib_estrategias.VIGENCIA_VELAS, "posiciones": lib_tamano.POSICIONES}


def estado(ahora_ms=None, cuenta=None, minutos=None, com=None):
    """El ejecutor de prueba tal como está: el saldo ficticio, las entradas puestas, las posiciones abiertas con su
    protección simulada y lo que valen ahora, y hasta cuándo llegan las velas de 1 m que las cuidan. No recorre ni aplica
    nada: eso es `revisar`.

    `listo` pide lo que hace falta para poder operar en prueba: una cuenta que no arrancó frenada, con capital, los
    mínimos de Binance calculados y velas de 1 m de los dos pares."""
    ms = _ms(ahora_ms)
    c = cuenta if isinstance(cuenta, dict) else lib_estado.cargar(AMBIENTE, ahora_ms=ms)
    series = minutos if isinstance(minutos, dict) else minutos_de()
    com = lib_tamano.comisiones(com if com is not None else lib_costos.comisiones())
    pares, md = lib_tamano.filtros_de()
    cuerpo = lib_estado.cuerpo_de(c)
    mias = nuestras(cuerpo)
    precios = {par: precio_de(velas) for par, velas in series.items()}
    posiciones = [_vista(p, precios.get(p.get("par"))) for p in mias]
    abiertas = [p for p in posiciones if p.get("estado") == ABIERTA]
    puestas = [p for p in posiciones if p.get("estado") == PUESTA]
    _, comprometido = lib_tamano.posiciones_de(cuerpo)
    saldo = _numero(cuerpo.get("saldo"))
    motivos = []
    if not _editable(c):
        motivos.append({"codigo": "frenado" if c.get("frenado") else "sin_cuenta", "par": "", "n": 0})
    if not md.get("calculado"):
        motivos.append({"codigo": "sin_minimos", "par": "", "n": 0})
    for par in lib_datos.PARES_OPERADOS:
        if not series.get(par):
            motivos.append({"codigo": "sin_1m", "par": par, "n": 0})
    if _editable(c) and saldo <= 0:
        motivos.append({"codigo": "sin_capital", "par": "", "n": 0})
    return {"formato": 1, "cuando": lib_datos.iso(ms), "ambiente": AMBIENTE, "moneda": "USDT", "ficticio": True,
            "frenado": bool(c.get("frenado")), "modo": c.get("modo") or "", "saldo": saldo,
            "referencia": _numero(cuerpo.get("referencia")), "comprometido": comprometido,
            "operaciones": _entero(cuerpo.get("operaciones")), "reinicios": _entero(cuerpo.get("reinicios")),
            "posiciones": posiciones, "abiertas": len(abiertas), "puestas": len(puestas),
            "protegidas": len([p for p in abiertas if p.get("protegida")]),
            "ordenes": [o for p in posiciones for o in (p.get("ordenes") or [])],
            "por_revisar": len([p for p in puestas if _entero(p.get("vence_ms")) and p["vence_ms"] <= ms]),
            "precios": precios, "cobertura": cobertura_de(series, ms), "ajenas": len(ajenas(cuerpo)),
            "comisiones": com, "minimos": {"calculado": bool(md.get("calculado")), "cuando": md.get("cuando") or ""},
            "parametros": parametros(), "motivos": motivos, "listo": not motivos}


def escribir(d):
    """Deja escrito lo último: lo leen la pantalla y el motor sin volver a recorrer nada."""
    nucleo.escribir_json(ruta_ejecutor(), d)
    return d


def guardado():
    """Lo último que se escribió o, si no hay nada, nada. Sin red y sin recorrer nada."""
    d = nucleo.leer_json(ruta_ejecutor(), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    return d if isinstance(d, dict) and d.get("formato") == 1 else {}
