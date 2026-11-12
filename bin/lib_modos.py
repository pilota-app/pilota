#!/usr/bin/env python3
"""lib_modos — los tres modos y las propuestas que vencen. Solo biblioteca estándar. No es una acción (`bin/propuestas.py`).

Acá se decide **cuándo** se entra, que es lo único que faltaba: el puntaje dice qué tan buena se ve una oportunidad
(`lib_puntaje`), la exigencia cuál alcanza (`lib_calibracion`), el tamaño cuánto (`lib_tamano`), los frenos si se puede
(`lib_frenos`) y el ejecutor la pone (`lib_ejecutor_prueba`). Los tres modos solo eligen quién dice «sí»:

| Modo | Qué hace |
|---|---|
| manual | **propone** y espera: puntaje, razón, monto en USDT y stop, con su hora de vencimiento (`VENCIMIENTOS`) |
| semiautomático | opera solo cuando el puntaje es **claramente alto** y el monto cabe en el que se eligió; si no, pregunta |
| automático | opera solo, y activarlo pide **dos** confirmaciones (`CONFIRMACIONES`) |

Lo que no se negocia aquí:
- **Si nadie responde, la propuesta vence. Siempre.** No existe un camino donde el silencio opere: quien quiera que
  Pilota opere sola hasta un monto usa el semiautomático, que es ese monto escrito y a la vista (`ajustes`).
- **Mirar es aplicar**, como en los frenos y en el ejecutor: `estado` también hace vencer la propuesta que se pasó de su
  hora y la deja en el registro que no se borra (`caducar`). No hay un «solo mirar» que deje viva una propuesta vencida.
- **Sin calibración, el semiautomático y el automático no se pueden elegir** (`permitido`, `SIN_CALIBRACION`): lo que el
  modelo promete todavía no está probado, así que la persona decide cada entrada. El motivo viaja en código y la pantalla
  lo dice; el modo queda apagado, no escondido.
- **Tras cualquier freno se vuelve a manual.** Eso ya lo hace `lib_frenos.aplicar` sobre el estado firmado; acá se
  respeta en los dos sentidos: con un freno puesto no se puede elegir otro modo y, si el estado dice uno que ya no
  corresponde, la vuelta se decide **como manual** (`efectivo`).
- **«Claramente alto» no se muestra como una suma.** En el código es `MARGEN_CLARO` sobre la exigencia; en pantalla va
  en palabras, porque un número que la persona no eligió no es una perilla suya.
- **La propuesta es una foto, no una orden.** Al responder «Sí» el tamaño y los frenos se vuelven a calcular de cero
  (`opcion_de`, `lib_ejecutor_prueba.entrar` sin tamaño inyectado): lo que valía hace 15 minutos se revisa de nuevo, y
  una propuesta nunca vive más que su propia señal (`propuesta_de`).
- **Decir «No» es quedarse en USDT**, y así queda escrito (`RAZON_NO`): el registro no inventa razones nuevas para lo
  mismo.
- **Prueba y real llevan lo suyo separado.** Hoy esto es del ejecutor de prueba (`AMBIENTE`); el conector real es su
  propio paso y mientras no exista no se decide nada sobre dinero de verdad (`SIN_AMBIENTE`).

Los ajustes de la persona (cuánto espera una propuesta y hasta cuánto opera solo el semiautomático) y las propuestas
viven en `<datos>/mercado/modos.json`. El modo vive donde tiene que vivir: en el estado firmado de la cuenta
(`lib_estado`, campo `modo`), con los frenos.
"""
import math
import os

import lib_calibracion
import lib_datos
import lib_ejecutor_prueba
import lib_ejecutor_real
import lib_estado
import lib_frenos
import lib_puntaje
import lib_registro
import lib_tamano
import nucleo

#: El ambiente que se decide hoy: el otro es el conector real, en su paso.
AMBIENTE = lib_ejecutor_prueba.AMBIENTE
#: Por qué una propuesta no se ejecuta: nació en prueba y ahora se juega con dinero real (o al revés).
CAMBIO_AMBIENTE = "cambio_ambiente"


def ejecutor_de(amb):
    """El ejecutor del dinero con que se juega: el de prueba o el conector real. Los dos tienen el mismo contrato."""
    return lib_ejecutor_real if amb == lib_estado.REAL else lib_ejecutor_prueba
#: Los tres modos (los del estado firmado: son los mismos en todas partes) y el de partida.
MODOS = lib_estado.MODOS
MANUAL, SEMI, AUTO = MODOS
#: Cuánto puede esperar una propuesta, en minutos: lo elige la persona y no hay otra opción que estas tres.
VENCIMIENTOS = (5, 15, 60)
VENCIMIENTO = 15
#: Hasta cuánto opera solo el semiautomático, en USDT: visible y editable, con 15 por defecto. Los montos que ofrece la
#: pantalla son estos; el tope de lo que Pilota se cree como monto es el del estado firmado.
MONTOS = (10, 15, 25, 50)
MONTO = 15.0
MONTO_MAXIMO = lib_estado.SALDO_MAXIMO
#: Cuánto sobre la exigencia es «claramente alto» para el semiautomático. En pantalla va en palabras, no como suma.
MARGEN_CLARO = 10.0
#: Cuántas veces hay que confirmar para activar el automático.
CONFIRMACIONES = 2
#: Cuántas propuestas se guardan (las últimas: el archivo no crece sin fin) y cuántas líneas del registro se miran hacia
#: atrás para contar las que vencieron hoy.
PROPUESTAS_GUARDADAS = 20
VENCIDAS_MIRADAS = 200

#: En qué puede quedar una propuesta. Son códigos: la pantalla los traduce.
PROPUESTA, VENCIDA, ACEPTADA, RECHAZADA = "propuesta", "vencida", "aceptada", "rechazada"
ESTADOS = (PROPUESTA, VENCIDA, ACEPTADA, RECHAZADA)
#: Con qué razón queda cada cosa en el registro que no se borra (las de `lib_registro.RAZONES`): una propuesta nueva, la
#: que nadie respondió y el «No», que es quedarse en USDT.
RAZON_PROPUESTA = "propuesta"
RAZON_VENCIDA = lib_ejecutor_prueba.RAZON_VENCIDA
RAZON_NO = "quedarse_en_usdt"
#: En qué quedó una vuelta de decisión. También son códigos.
ENTRADA, ESPERANDO, REPETIDA = "entrada", "esperando", "repetida"
SIN_OPORTUNIDAD, BAJO_EXIGENCIA, EN_USDT, FRENADO, RECHAZO, SIN_AMBIENTE = (
    "sin_oportunidad", "bajo_exigencia", "en_usdt", "frenado", "rechazo", "sin_ambiente")
DECISIONES = (PROPUESTA, ENTRADA, ESPERANDO, REPETIDA, SIN_OPORTUNIDAD, BAJO_EXIGENCIA, EN_USDT, FRENADO, RECHAZO,
              SIN_AMBIENTE)
#: Por qué no se pudo hacer lo que se pidió. Los primeros son de acá; los del ejecutor, el tamaño y los frenos llegan tal
#: como los dijeron ellos.
SIN_CALIBRACION, SIN_PROPUESTA, FALTAN_CONFIRMACIONES = "sin_calibracion", "sin_propuesta", "faltan_confirmaciones"
#: Por qué el semiautomático preguntó en vez de operar solo.
NO_CLARO, MONTO_MAYOR = "no_claro", "monto_mayor"
RECHAZOS = tuple(dict.fromkeys((SIN_PROPUESTA, VENCIDA, SIN_CALIBRACION, FALTAN_CONFIRMACIONES, NO_CLARO, MONTO_MAYOR,
                                "modo", "vencimiento", "monto", "frenado", CAMBIO_AMBIENTE,
                                *lib_ejecutor_prueba.RECHAZOS, *lib_ejecutor_real.RECHAZOS)))
#: Ruido de coma flotante, no un monto distinto.
TOLERANCIA = 1e-9


def ruta_modos():
    return os.path.join(lib_datos.carpeta_mercado(), "modos.json")


# ── Números, sin creerle a nadie ─────────────────────────────────────────────────────────────────────────────────────

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


# ── El archivo: los ajustes de la persona y las propuestas ───────────────────────────────────────────────────────────

def ajustes(d=None):
    """Lo que eligió la persona: cuánto espera una propuesta antes de vencer y hasta cuánto opera solo el
    semiautomático. El archivo lo pudo haber tocado cualquiera, así que lo que no se entiende vuelve a su valor de
    partida."""
    x = d if isinstance(d, dict) else guardado()
    minutos = _entero(x.get("vencimiento_min"), VENCIMIENTO)
    monto = _numero(x.get("monto"), MONTO)
    return {"vencimiento_min": minutos if minutos in VENCIMIENTOS else VENCIMIENTO,
            "monto": monto if 0 < monto <= MONTO_MAXIMO else MONTO}


def propuestas_de(d):
    """Las propuestas que trae el archivo, ya limpias y en orden. Lo que no lleva el prefijo propio no es de Pilota."""
    lista = (d or {}).get("propuestas")
    if not isinstance(lista, list):
        return []
    limpias = [p for p in lista if isinstance(p, dict) and lib_ejecutor_prueba.es_nuestro(p.get("id"))
               and p.get("estado") in ESTADOS]
    return limpias[-PROPUESTAS_GUARDADAS:]


def guardado():
    """El archivo tal como está, con los ajustes y las propuestas. Sin red y sin recorrer nada."""
    d = nucleo.leer_json(ruta_modos(), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    d = d if isinstance(d, dict) and d.get("formato") == 1 else {}
    return {"formato": 1, **ajustes(d), "propuestas": propuestas_de(d)}


def guardar(d):
    """Deja el archivo escrito de una sola vez: solo los ajustes y las propuestas, nada de lo que se calcula al mirar."""
    nucleo.escribir_json(ruta_modos(), {"formato": 1, **ajustes(d), "propuestas": propuestas_de(d)})
    return d


# ── Una propuesta ────────────────────────────────────────────────────────────────────────────────────────────────────

def id_de(o):
    """El id de una propuesta: **determinista** (el par, la vela y la estrategia), con el prefijo propio delante. De la
    misma señal sale el mismo id, así una revisión más no propone dos veces lo mismo."""
    return (f"{lib_ejecutor_prueba.PREFIJO}-{lib_estado.activo()[0]}-prop-{o.get('par') or ''}-{_entero(o.get('vela'))}"
            f"-{o.get('estrategia') or ''}")


def _orden(p, estado):
    """Lo que dice del pedido la línea del registro (`lib_registro.CAMPOS_ORDEN`): números y códigos, nada más. Una
    propuesta todavía no es una orden en ninguna parte, y por eso su estado es el de la propuesta."""
    return {"id": p.get("id") or "", "lado": lib_frenos.LADO_ENTRADA, "tipo": lib_frenos.TIPO_ENTRADA,
            "precio": _numero(p.get("entrada")), "cantidad": _numero(p.get("cantidad")),
            "monto": _numero(p.get("monto")), "stop": _numero(p.get("stop")), "objetivo": _numero(p.get("objetivo")),
            "estado": estado, "vence_ms": _entero(p.get("vence_ms"))}


def propuesta_de(o, ahora_ms, vencimiento_min=VENCIMIENTO, exigencia=None, motivo=""):
    """La propuesta como se le muestra a la persona: el puntaje, la razón, el monto en USDT y el stop, y hasta cuándo
    espera. Una propuesta **nunca vive más que su propia señal**: si la oportunidad vence antes, vence con ella."""
    t = o.get("tamano") if isinstance(o.get("tamano"), dict) else {}
    minutos = _entero(vencimiento_min, VENCIMIENTO)
    minutos = minutos if minutos in VENCIMIENTOS else VENCIMIENTO
    vence = ahora_ms + minutos * 60_000
    suya = _entero(o.get("vence"))
    if suya > 0:
        vence = min(vence, suya)
    p = {"id": id_de(o), "ambiente": lib_estado.activo(), "par": o.get("par") or "", "estrategia": o.get("estrategia") or "",
         "temporalidad": o.get("temporalidad") or "", "razon": o.get("razon") or "", "vela_ms": _entero(o.get("vela")),
         "puntaje": o.get("puntaje"), "exigencia": exigencia, "permitida": bool(o.get("permitida")),
         "entrada": _numero(t.get("precio")) or _numero(o.get("entrada")),
         "stop": _numero(t.get("stop")) or _numero(o.get("stop")), "objetivo": _numero(o.get("objetivo")),
         "cantidad": _numero(t.get("cantidad")), "monto": _numero(t.get("monto")),
         "arriesgado": _numero(t.get("arriesgado")), "distancia_stop": t.get("distancia_stop"),
         "estado": PROPUESTA, "motivo": motivo or "", "minutos": minutos,
         "puesta_ms": ahora_ms, "puesta": lib_datos.iso(ahora_ms), "vence_ms": vence, "vence": lib_datos.iso(vence),
         "orden_vence_ms": suya, "respondida_ms": 0}
    return p


def opcion_de(p):
    """La propuesta de vuelta como la oportunidad que pide el ejecutor (`lib_ejecutor_prueba.entrar`). No lleva el
    tamaño: al responder «Sí» se calcula de nuevo con el saldo y el modelo de ahora, porque la propuesta es una foto."""
    return {"estrategia": p.get("estrategia"), "par": p.get("par") or "", "temporalidad": p.get("temporalidad") or "",
            "razon": p.get("razon") or "", "vela": _entero(p.get("vela_ms")), "entrada": _numero(p.get("entrada")),
            "stop": _numero(p.get("stop")), "objetivo": _numero(p.get("objetivo")), "puntaje": p.get("puntaje"),
            "permitida": bool(p.get("permitida")), "vence": _entero(p.get("orden_vence_ms"))}


def vigentes(d, ahora_ms):
    """Las propuestas que todavía esperan un «Sí»."""
    return [p for p in propuestas_de(d)
            if p.get("estado") == PROPUESTA and _entero(p.get("vence_ms")) > ahora_ms]


def caducar(d, ahora_ms, anotar=True):
    """Las propuestas que se pasaron de su hora: vencidas y en el registro que no se borra, una sola vez. Si nadie
    responde, la propuesta vence siempre."""
    propuestas, vencidas = [], []
    for p in propuestas_de(d):
        if p.get("estado") == PROPUESTA and _entero(p.get("vence_ms")) <= ahora_ms:
            p = {**p, "estado": VENCIDA, "respondida_ms": 0}
            vencidas.append(p)
        propuestas.append(p)
    if anotar:
        for p in vencidas:
            lib_registro.anotar(p.get("ambiente") or AMBIENTE, RAZON_VENCIDA, par=p.get("par") or "", puntaje=p.get("puntaje"),
                                ms=ahora_ms, orden=_orden(p, VENCIDA), resultado={"motivo": VENCIDA})
    return {**(d if isinstance(d, dict) else {}), "propuestas": propuestas}, vencidas


def con_propuesta(d, p):
    """La propuesta nueva en el archivo, pisando la que tuviera el mismo id (los ids son deterministas)."""
    otras = [x for x in propuestas_de(d) if x.get("id") != p["id"]]
    return {**d, "propuestas": [*otras, p]}


def proponer(o, ahora_ms, d=None, vencimiento_min=VENCIMIENTO, exigencia=None, motivo=""):
    """Deja una oportunidad propuesta, esperando el «Sí», con su línea en el registro. No pone ninguna orden: eso pasa
    recién cuando la persona responde."""
    archivo = d if isinstance(d, dict) else guardado()
    p = propuesta_de(o, ahora_ms, vencimiento_min, exigencia, motivo)
    archivo = con_propuesta(archivo, p)
    lib_registro.anotar(p["ambiente"], RAZON_PROPUESTA, par=p["par"], puntaje=p["puntaje"], ms=ahora_ms,
                        orden=_orden(p, PROPUESTA), resultado={"motivo": motivo} if motivo else None)
    return archivo, p


def vencidas_hoy(ambiente=AMBIENTE, ahora_ms=None, mirar=VENCIDAS_MIRADAS):
    """Cuántas propuestas vencieron en el día (el día UTC, el mismo del registro y de los frenos). La pantalla las
    cuenta porque una propuesta que nadie respondió también es una decisión. Solo cuenta las propuestas: la entrada que
    se canceló en el nivel la cuenta el ejecutor, con la misma razón pero otro estado."""
    ms = _ms(ahora_ms)
    hoy = lib_frenos.fecha_de(ms)
    lineas, _ = lib_registro.ultimas(ambiente, mirar)
    return len([x for x in lineas if x.get("razon") == RAZON_VENCIDA
                and (x.get("orden") or {}).get("estado") == VENCIDA
                and str(x.get("fecha") or "")[:10] == hoy])


# ── Qué modo se puede usar ───────────────────────────────────────────────────────────────────────────────────────────

def _cuenta_frenos(f):
    """Los frenos de la cuenta activa: `lib_frenos.estado` los trae arriba y también en la lista de las dos cuentas."""
    if not isinstance(f, dict):
        return {}
    if "activos" in f:
        return f
    return next((c for c in (f.get("cuentas") or []) if c.get("ambiente") == f.get("activo")), {})


def permitido(modo, modelo=None, frenos=None):
    """Si ese modo se puede usar ahora mismo, con su motivo en código. El manual siempre se puede —es el de partida y el
    de después de cualquier freno—; los otros dos piden calibración y que no haya ningún freno puesto."""
    if modo not in MODOS:
        return {"puede": False, "motivo": "modo"}
    if modo == MANUAL:
        return {"puede": True, "motivo": ""}
    m = lib_calibracion.modelo() if modelo is None else (modelo or {})
    if not m.get("calibrado"):
        return {"puede": False, "motivo": SIN_CALIBRACION}
    c = _cuenta_frenos(frenos)
    if c.get("manual") or c.get("frenado"):
        return {"puede": False, "motivo": (c.get("activos") or [""])[0] or FRENADO}
    return {"puede": True, "motivo": ""}


def _editable(cuenta):
    """Si a esta cuenta se le puede escribir el estado: la misma regla de los frenos y del ejecutor."""
    return not cuenta.get("frenado") and not (cuenta.get("arranque") or {}).get("nuevo")


def claramente_alto(puntaje, exigencia):
    """Si el puntaje es **claramente** alto, que es lo único que opera solo el semiautomático. En pantalla esto va en
    palabras: el margen es del código, no una perilla de la persona."""
    return _numero(puntaje, -1.0) >= _numero(exigencia) + MARGEN_CLARO


# ── Una vuelta de decisión ───────────────────────────────────────────────────────────────────────────────────────────

def decidir(ctx=None, ahora_ms=None, tamano=None, puntaje=None, calibracion=None, frenos=None):
    """Una vuelta: las propuestas que se pasaron de su hora vencen y, con la mejor oportunidad de ahora, el modo dice
    qué hacer. Es el gancho del motor (`lib_reconciliar.reconciliar(decidir=…)`), así que devuelve el ejecutor como lo
    dejó y lo que le suma al resumen (`modos`).

    Acá no se discute ningún freno ni ningún monto: el tamaño y los frenos ya hablaron, y una orden que no pase por los
    dos no se pone. `ctx`, `tamano`, `puntaje` y `calibracion` llegan ya calculados cuando el motor los tiene a mano."""
    c = ctx if isinstance(ctx, dict) else {}
    ms = _ms(c.get("ahora_ms") if c.get("ahora_ms") is not None else ahora_ms)
    amb = c.get("ambiente") or lib_estado.activo()
    # Mirar los frenos es aplicarlos, y van primero: lo que se decida después ya cuenta con ellos puestos.
    f = c.get("frenos") if isinstance(c.get("frenos"), dict) else (
        frenos if isinstance(frenos, dict) else lib_frenos.escribir(lib_frenos.revisar(ms)))
    d, vencidas = caducar(guardado(), ms)
    guardar(d)                       # lo que venció queda escrito antes de decidir nada: si no, vencería dos veces
    aj = ajustes(d)
    cuenta = lib_estado.cargar(amb, ahora_ms=ms)
    modo = cuenta.get("modo") if cuenta.get("modo") in MODOS else MANUAL
    cal = lib_calibracion.guardada() if calibracion is None else calibracion
    modelo = lib_calibracion.modelo(cal)
    permiso = permitido(modo, modelo, f)
    # Si el estado dice un modo que ya no corresponde, la vuelta se decide como manual: Pilota propone y la persona
    # decide. `lib_frenos.aplicar` es quien deja el modo escrito en manual; acá no se pisa el estado firmado.
    efectivo = modo if permiso["puede"] else MANUAL
    motivo_modo = "" if permiso["puede"] else permiso["motivo"]
    # El ejecutor como lo dejó el motor; si esto lo pide la acción suelta, el último que quedó escrito. Lo que vuelve es
    # lo que el motor va a mostrar, así que nunca es un diccionario vacío con ceros que no son.
    ex = ejecutor_de(amb)
    ej = c.get("ejecutor") if isinstance(c.get("ejecutor"), dict) else ex.guardado()
    vuelta = {"modo": modo, "efectivo": efectivo, "motivo_modo": motivo_modo, "decision": "", "motivo": "",
              "par": "", "puntaje": None, "exigencia": _numero(modelo.get("exigencia")), "monto": None,
              "id": "", "propuestas": 0, "entradas": 0, "vencidas": len(vencidas), "vigentes": 0}

    def fin(decision, motivo="", ejecutor=None, propuesta=None):
        guardar(d)
        vuelta.update({"decision": decision, "motivo": motivo, "vigentes": len(vigentes(d, ms))})
        if propuesta:
            vuelta.update({"id": propuesta["id"], "par": propuesta["par"], "puntaje": propuesta["puntaje"],
                           "monto": propuesta["monto"]})
        return {"ejecutor": ejecutor if isinstance(ejecutor, dict) else ej, "modos": vuelta}

    if amb not in (AMBIENTE, lib_estado.REAL):
        return fin(SIN_AMBIENTE, SIN_AMBIENTE)
    p = puntaje if isinstance(puntaje, dict) else lib_puntaje.escribir_estado(lib_puntaje.estado(ms, calibracion=cal))
    t = tamano if isinstance(tamano, dict) else lib_tamano.escribir(
        lib_tamano.estado(ms, puntaje=p, calibracion=cal))
    exigencia = _numero((t.get("modelo") or {}).get("exigencia"), _numero(modelo.get("exigencia")))
    mejor = t.get("mejor") if isinstance(t.get("mejor"), dict) else None
    usdt = p.get("usdt") if isinstance(p.get("usdt"), dict) else {}
    vuelta["exigencia"] = exigencia
    if mejor:
        vuelta.update({"par": mejor.get("par") or "", "puntaje": mejor.get("puntaje"),
                       "monto": _numero((mejor.get("tamano") or {}).get("monto"))})

    puerta = lib_frenos.permite_entrada(f)
    if not puerta["puede"]:
        return fin(FRENADO, puerta["motivo"])
    if mejor is None:
        return fin(SIN_OPORTUNIDAD, (([x for x in (t.get("motivos") or []) if x.get("codigo")] or [{}])[0]
                                     .get("codigo") or ""))
    # Quedarse en USDT puntúa en la misma escala, así que se compara de frente: si gana, no se entra a nada.
    if usdt.get("sola") or _numero(usdt.get("puntaje"), -1.0) >= _numero(mejor.get("puntaje")):
        return fin(EN_USDT, usdt.get("razon") or "")
    if _numero(mejor.get("puntaje"), -1.0) < exigencia:
        return fin(BAJO_EXIGENCIA)
    if any(x["id"] == id_de(mejor) for x in vigentes(d, ms)):
        return fin(ESPERANDO)        # esa misma señal ya está propuesta y esperando: no se propone dos veces
    if ex.repetida(lib_estado.cuerpo_de(cuenta), mejor):
        return fin(REPETIDA, REPETIDA)

    solo, motivo = True, ""
    if efectivo == MANUAL:
        solo, motivo = False, motivo_modo
    elif efectivo == SEMI:
        if not claramente_alto(mejor.get("puntaje"), exigencia):
            solo, motivo = False, NO_CLARO
        elif _numero((mejor.get("tamano") or {}).get("monto")) > aj["monto"] + TOLERANCIA:
            solo, motivo = False, MONTO_MAYOR
    if not solo:
        d, propuesta = proponer(mejor, ms, d, aj["vencimiento_min"], exigencia, motivo)
        vuelta["propuestas"] = 1
        return fin(PROPUESTA, motivo, propuesta=propuesta)
    r = ex.entrar(mejor, ahora_ms=ms, tamano_=mejor.get("tamano"), frenos=f, calibracion=cal)
    nuevo = ex.escribir(ex.estado(ms))
    if not r["puesta"]:
        return fin(RECHAZO, r["motivo"], ejecutor=nuevo)
    vuelta["entradas"] = 1
    return fin(ENTRADA, "", ejecutor=nuevo)


# ── Lo que hace la persona: responder, elegir el modo y ajustar ───────────────────────────────────────────────────────

def responder(identificador=None, si=True, ahora_ms=None, calibracion=None):
    """El «Sí» o el «No» a una propuesta. El «Sí» pone la orden con el tamaño y los frenos **de ahora**, no con los de
    cuando se propuso; el «No» se anota como lo que es: quedarse en USDT. Sin id se responde la única que esté
    esperando: con dos a la vista hay que decir cuál."""
    ms = _ms(ahora_ms)
    d, _ = caducar(guardado(), ms)
    guardar(d)                       # lo que venció queda escrito antes de poner nada: si no, vencería dos veces
    vivas = vigentes(d, ms)
    elegida = (next((p for p in vivas if p.get("id") == identificador), None) if identificador
               else (vivas[-1] if len(vivas) == 1 else None))
    if elegida is None:
        guardar(d)
        pasada = any(p.get("id") == identificador for p in propuestas_de(d)) if identificador else False
        return {"hecho": False, "motivo": VENCIDA if pasada else SIN_PROPUESTA, "propuesta": None,
                "datos": estado(ms, archivo=d)}
    if not si:
        p = {**elegida, "estado": RECHAZADA, "respondida_ms": ms}
        d = con_propuesta(d, p)
        guardar(d)
        lib_registro.anotar(p.get("ambiente") or AMBIENTE, RAZON_NO, par=p["par"], puntaje=p.get("puntaje"), ms=ms,
                            orden=_orden(p, RECHAZADA), resultado={"motivo": RECHAZADA})
        return {"hecho": True, "motivo": "", "propuesta": p, "datos": estado(ms, archivo=d)}
    if (elegida.get("ambiente") or AMBIENTE) != lib_estado.activo():
        # Una propuesta que nació con el otro dinero no se ejecuta con este: se deja vencer.
        return {"hecho": False, "motivo": CAMBIO_AMBIENTE, "propuesta": elegida, "datos": estado(ms, archivo=d)}
    f = lib_frenos.escribir(lib_frenos.revisar(ms))
    cal = lib_calibracion.guardada() if calibracion is None else calibracion
    ex = ejecutor_de(lib_estado.activo())
    r = ex.entrar(opcion_de(elegida), ahora_ms=ms, frenos=f, calibracion=cal)
    ej = ex.escribir(ex.estado(ms))
    # Si no se pudo poner (un freno que apareció, un monto que ya no alcanza), la propuesta sigue esperando mientras le
    # quede hora: el motivo se muestra y la persona puede volver a decir «Sí».
    p = {**elegida, "estado": ACEPTADA, "respondida_ms": ms} if r["puesta"] else elegida
    d = con_propuesta(d, p)
    guardar(d)
    return {"hecho": bool(r["puesta"]), "motivo": r["motivo"], "propuesta": p,
            "datos": estado(ms, archivo=d, frenos=f, ejecutor=ej)}


def elegir(modo, confirmaciones=0, ahora_ms=None, calibracion=None):
    """El modo en el que queda la cuenta. Sin calibración el semiautomático y el automático no se pueden elegir, con un
    freno puesto tampoco, y el automático pide dos confirmaciones. Queda en el estado firmado y en el registro."""
    ms = _ms(ahora_ms)
    if modo not in MODOS:
        return {"hecho": False, "motivo": "modo", "datos": estado(ms)}
    # Mirar los frenos es aplicarlos: si hay uno puesto, el modo ya volvió a manual antes de contestar esto.
    f = lib_frenos.escribir(lib_frenos.revisar(ms))
    amb = lib_estado.activo()
    cuenta = lib_estado.cargar(amb, ahora_ms=ms)
    cal = lib_calibracion.guardada() if calibracion is None else calibracion
    permiso = permitido(modo, lib_calibracion.modelo(cal), f)
    if not _editable(cuenta):
        return {"hecho": False, "motivo": FRENADO, "datos": estado(ms, frenos=f)}
    if not permiso["puede"]:
        return {"hecho": False, "motivo": permiso["motivo"], "datos": estado(ms, frenos=f)}
    faltan = max(0, CONFIRMACIONES - _entero(confirmaciones))
    if modo == AUTO and faltan:
        return {"hecho": False, "motivo": FALTAN_CONFIRMACIONES, "faltan": faltan, "datos": estado(ms, frenos=f)}
    if cuenta.get("modo") != modo:
        lib_estado.guardar(amb, lib_estado.con_modo(lib_estado.cuerpo_de(cuenta), modo, ahora_ms=ms))
        lib_registro.anotar(amb, "cambio_modo", ms=ms, resultado={"motivo": modo})
    return {"hecho": True, "motivo": "", "datos": estado(ms, frenos=f)}


def ajustar(vencimiento_min=None, monto=None, ahora_ms=None):
    """Cuánto espera una propuesta y hasta cuánto opera solo el semiautomático. Las dos cosas son de la persona: acá
    solo se revisa que estén dentro de lo que Pilota ofrece."""
    ms = _ms(ahora_ms)
    d, _ = caducar(guardado(), ms)
    guardar(d)                       # lo que venció queda escrito antes de revisar nada: si no, vencería dos veces
    cambios = {}
    if vencimiento_min is not None:
        if _entero(vencimiento_min, -1) not in VENCIMIENTOS:
            return {"hecho": False, "motivo": "vencimiento", "datos": estado(ms, archivo=d)}
        cambios["vencimiento_min"] = _entero(vencimiento_min)
    if monto is not None:
        if not 0 < _numero(monto) <= MONTO_MAXIMO:
            return {"hecho": False, "motivo": "monto", "datos": estado(ms, archivo=d)}
        cambios["monto"] = _numero(monto)
    d = {**d, **cambios}
    guardar(d)
    return {"hecho": True, "motivo": "", "datos": estado(ms, archivo=d)}


# ── Lo que lee la pantalla ───────────────────────────────────────────────────────────────────────────────────────────

def parametros():
    """Con qué reglas trabajan los tres modos: los lee la pantalla y quedan en el archivo. `margen` está acá para que se
    pueda revisar, no para mostrarlo: en pantalla «claramente alto» va en palabras."""
    return {"modos": list(MODOS), "modo_frenado": MANUAL, "vencimientos": list(VENCIMIENTOS),
            "vencimiento": VENCIMIENTO, "montos": list(MONTOS), "monto": MONTO, "monto_maximo": MONTO_MAXIMO,
            "confirmaciones": CONFIRMACIONES, "margen": MARGEN_CLARO, "estados": list(ESTADOS),
            "decisiones": list(DECISIONES), "rechazos": list(RECHAZOS), "razones": {"propuesta": RAZON_PROPUESTA,
            "vencida": RAZON_VENCIDA, "no": RAZON_NO}, "ambiente": AMBIENTE, "guardadas": PROPUESTAS_GUARDADAS,
            "puntaje_maximo": lib_puntaje.PUNTAJE_MAXIMO}


def _vista(p, ahora_ms):
    """Una propuesta como se ve: lo que le queda de vida y si todavía espera una respuesta."""
    queda = max(0, _entero(p.get("vence_ms")) - ahora_ms)
    return {**p, "queda_ms": queda, "queda_min": queda // 60_000, "espera": p.get("estado") == PROPUESTA and queda > 0}


def estado(ahora_ms=None, archivo=None, tamano=None, frenos=None, ejecutor=None, calibracion=None):
    """Los tres modos tal como están: en cuál quedó la cuenta, cuáles se pueden usar y por qué no, las propuestas que
    esperan un «Sí» con lo que les queda, cuántas vencieron hoy y la exigencia con la que se mide el puntaje. **Mirar
    también es aplicar**: la propuesta que se pasó de su hora vence acá. Lo que no hace es proponer ni operar: eso es
    `decidir`.

    La mejor oportunidad sale del último tamaño escrito (`lib_tamano.guardado`), con su hora al lado: esta vista no
    recorre ninguna vela."""
    ms = _ms(ahora_ms)
    if isinstance(archivo, dict):
        d = archivo
    else:
        d, _ = caducar(guardado(), ms)
        guardar(d)
    amb = lib_estado.activo()
    cuenta = lib_estado.cargar(amb, ahora_ms=ms)
    f = frenos if isinstance(frenos, dict) else lib_frenos.guardado()
    ej = ejecutor if isinstance(ejecutor, dict) else ejecutor_de(amb).guardado()
    t = tamano if isinstance(tamano, dict) else lib_tamano.guardado()
    modelo = lib_calibracion.modelo(calibracion)
    aj = ajustes(d)
    modo = cuenta.get("modo") if cuenta.get("modo") in MODOS else MANUAL
    permiso = permitido(modo, modelo, f)
    puerta = lib_frenos.permite_entrada(f) if f else {"puede": True, "motivo": ""}
    propuestas = [_vista(p, ms) for p in propuestas_de(d)]
    esperando = [p for p in propuestas if p["espera"]]
    mejor = t.get("mejor") if isinstance(t.get("mejor"), dict) else None
    motivos = []
    if amb not in (AMBIENTE, lib_estado.REAL):
        motivos.append({"codigo": SIN_AMBIENTE, "par": "", "n": 0})
    if f and not puerta["puede"]:
        motivos.append({"codigo": puerta["motivo"] or FRENADO, "par": "", "n": 0})
    return {"formato": 1, "cuando": lib_datos.iso(ms), "ambiente": amb, "moneda": "USDT",
            "modo": modo, "efectivo": modo if permiso["puede"] else MANUAL,
            "motivo_modo": "" if permiso["puede"] else permiso["motivo"],
            "modos": [{"modo": m, "actual": m == modo, "confirmaciones": CONFIRMACIONES if m == AUTO else 0,
                       **permitido(m, modelo, f)} for m in MODOS],
            "vencimiento_min": aj["vencimiento_min"], "vencimientos": list(VENCIMIENTOS),
            "monto": aj["monto"], "montos": list(MONTOS),
            "propuestas": propuestas, "esperando": len(esperando), "vencidas_hoy": vencidas_hoy(amb, ms),
            "exigencia": _numero(modelo.get("exigencia")), "puntaje_maximo": lib_puntaje.PUNTAJE_MAXIMO,
            "modelo": {"estado": modelo.get("estado") or "", "calibrado": bool(modelo.get("calibrado")),
                       "validado": bool(modelo.get("validado")), "exigencia": _numero(modelo.get("exigencia")),
                       "tope": modelo.get("tope"), "topado": bool(modelo.get("topado")),
                       "cuando": modelo.get("cuando") or "", "motivo": modelo.get("motivo") or ""},
            "mejor": mejor, "tamano_cuando": t.get("cuando") or "",
            "frenado": bool(f.get("frenado")), "pausado": bool(f.get("pausado")),
            "entradas": puerta, "saldo": _numero(ej.get("saldo"), _numero(cuenta.get("saldo"))),
            "abiertas": _entero(ej.get("abiertas")), "puestas": _entero(ej.get("puestas")),
            "parametros": parametros(), "motivos": motivos, "listo": not motivos}
