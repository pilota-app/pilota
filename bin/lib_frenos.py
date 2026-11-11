#!/usr/bin/env python3
"""Los frenos y la máquina de estados: lo que Pilota no se puede saltar. Solo biblioteca estándar. No es una acción.

Los frenos están **en el código y fuera de la IA**: no son un consejo ni una preferencia, son la respuesta a «¿puedo abrir
algo?». El ejecutor y el conector real preguntan acá antes de poner una orden, y una orden que no pasó antes por el tamaño
(`bin/lib_tamano.py`) tampoco pasa de aquí.

| Freno | Cuándo | Qué hace |
|---|---|---|
| sin apalancamiento | siempre | solo se compra al contado y con lo que hay: una orden con apalancamiento no se pone nunca |
| máximo 2 posiciones | `POSICIONES` abiertas | no abre una más (el mismo número del tamaño y del capital mínimo viable) |
| piso absoluto | el saldo cae `PISO_ABSOLUTO` bajo el **capital aportado** | bloquea y **reduce la exposición a la fuerza**: cierra a mercado |
| piso | el saldo cae `PISO` bajo el **capital de referencia** | bloquea; lo abierto se queda con su protección automática |
| diario | se pierde `PERDIDA_DIARIA` en el día | bloquea hasta que el día cambia (`dia.hasta_ms`, que la pantalla muestra en hora local) |
| racha | `RACHA_MAXIMA` pérdidas seguidas | vuelve a manual (no bloquea: Pilota propone y la persona decide) |
| comisión | la maker de ahora pasa la que supuso el backtest | bloquea y avisa |
| FDUSD | FDUSD vale menos de `FDUSD_MINIMO` | bloquea y avisa; **no liquida nada** sin confirmación |

Los dos últimos miran el mercado, no la cuenta: **en prueba no frenan, pero se avisan igual** (`SOLO_REAL`, `avisa`), porque
en prueba no hay dinero de verdad que cuidar y sí hay algo que mostrar. Después de **cualquier** freno el modo vuelve a
manual (`lib_estado.MODO_FRENADO`).

La máquina de estados tiene cuatro estados (`ESTADOS`) y el que manda es el más grave:

    operando ──«Pausar»──> pausado ──«Seguir»──> operando
    operando/pausado ──un freno que bloquea──> frenado ──el freno se levanta (o se desbloquea)──> operando
    frenado ──el piso absoluto──> reduciendo ──cerrada la exposición──> frenado

Lo que no se negocia aquí:
- **El estado de los frenos vive en el archivo con huella** (`bin/lib_estado.py`): el saldo, el capital de referencia, el
  libro de aportes, la racha, el día, la pausa y los desbloqueos. Si ese archivo falta, su huella no cuadra o su fecha es
  futura, la cuenta ya viene frenada en manual y con los números en cero, y **el archivo sospechoso no se pisa**: `aplicar`
  no escribe nada en ese caso.
- **El capital de referencia es el saldo más alto alcanzado y los depósitos y retiros van explícitos** en su libro
  (`con_aporte`, `aportar`): un depósito no es una ganancia ni un retiro una pérdida, ni para el piso ni para el día.
- **«Pausar» nunca toca una protección automática**: cancela las entradas y nada más. Lo que está abierto sigue protegido y
  la pantalla lo dice (`protegidas`).
- **El piso se desbloquea a mano, en real, con 24 h de espera y como máximo `DESBLOQUEOS_MAXIMOS` veces**, y el desbloqueo
  es un **reinicio documentado** del capital de referencia (queda en el registro que no se borra). En prueba es al tiro: ahí
  la espera no cuida nada. El **piso absoluto no se desbloquea**.
- **Prueba y real llevan frenos separados**, como el saldo y el registro: dos cuentas, dos juegos de frenos.
- **Nada se mide dos veces de distinta forma**: las posiciones abiertas se cuentan con `lib_tamano.posiciones_de`, el número
  de posiciones es el del tamaño y el día es el día UTC (el mismo corte de Binance y del registro), que la pantalla muestra
  en hora local.

Dónde queda: `<datos>/mercado/frenos.json` (lo que devuelve `estado()`, con la hora de la revisión).
"""
import math
import os
import time

import lib_calibracion
import lib_datos
import lib_estado
import lib_estrategias
import lib_registro
import lib_tamano
import minimo_viable
import nucleo

#: Sin apalancamiento, nunca: Pilota compra al contado y con lo que tiene. Es un número para poder revisarlo en una orden.
APALANCAMIENTO = 1
#: Las mismas dos posiciones del tamaño y del capital mínimo viable: se importan, no se copian.
POSICIONES = minimo_viable.POSICIONES
#: El freno del día: un 5 % perdido en el día cierra el día.
PERDIDA_DIARIA = 0.05
#: Cuántas pérdidas seguidas vuelven a manual.
RACHA_MAXIMA = 4
#: El piso sobre el capital de referencia (el saldo más alto alcanzado) y el piso absoluto sobre el capital aportado. El
#: segundo es más abajo a propósito: el primero bloquea, el segundo además cierra lo que está abierto.
PISO = 0.25
PISO_ABSOLUTO = 0.35
#: Bajo cuánto FDUSD deja de ser un dólar. Se mide en USDT, que es lo más cercano al dólar que Pilota tiene.
FDUSD_MINIMO = 0.995
#: Con qué velas se mide FDUSD y cuánto vale la última: más viejas que esto no dicen nada del precio de ahora.
TEMPORALIDAD_FDUSD = "1h"
VIGENCIA_FDUSD_MS = 3 * 60 * 60 * 1000
#: Cuánto se le perdona a un número antes de decir que subió o que se pasó: ruido de coma flotante, no un cambio de verdad.
TOLERANCIA = 1e-9
#: El desbloqueo del piso en real: la espera y cuántas veces se puede.
ESPERA_DESBLOQUEO_MS = 24 * 60 * 60 * 1000
DESBLOQUEOS_MAXIMOS = 2

#: Los frenos, del que más manda al que menos. El orden es el del rechazo: el primero que bloquea es el motivo que se
#: muestra.
FRENOS = ("piso_absoluto", "piso", "diario", "racha", "comision", "fdusd")
#: Los que miran el mercado y no la cuenta: en prueba no frenan, pero se avisan.
SOLO_REAL = ("comision", "fdusd")
#: Qué hace cada freno. `manual` lo hacen todos: tras cualquier freno se vuelve a manual.
BLOQUEA, REDUCE, MANUAL = "bloquea", "reduce", "manual"
EFECTOS = {
    "piso_absoluto": (BLOQUEA, REDUCE, MANUAL),
    "piso": (BLOQUEA, MANUAL),
    "diario": (BLOQUEA, MANUAL),
    "racha": (MANUAL,),
    "comision": (BLOQUEA, MANUAL),
    "fdusd": (BLOQUEA, MANUAL),
}
#: Con qué razón queda cada freno en el registro que no se borra (las de `lib_registro.RAZONES`).
RAZON = {c: "freno_" + c for c in FRENOS}
#: Los cuatro estados de la máquina, del más tranquilo al más grave.
ESTADOS = ("operando", "pausado", "frenado", "reduciendo")
#: Por qué no se puede abrir algo. Son códigos: la pantalla los traduce y nunca se muestra el código pelado.
RECHAZOS = ("frenado", "pausado", "posiciones_llenas", *FRENOS, "sin_medir",
            "sin_tamano", "monto_mayor", "apalancamiento", "sin_proteccion", "lado", "tipo")
#: Lo único que Pilota pone para entrar: una compra con límite (post-only contra FDUSD).
LADO_ENTRADA = "compra"
TIPO_ENTRADA = "limite"
#: Por qué no se pudo medir FDUSD.
MOTIVOS_FDUSD = ("sin_velas", "sin_hora", "velas_viejas", "sin_precio")


def ruta_frenos():
    return os.path.join(lib_datos.carpeta_mercado(), "frenos.json")


# ── Números, sin creerle a nadie ─────────────────────────────────────────────────────────────────────────────────────

def _numero(valor, defecto=0.0):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        return defecto
    return float(valor)


def _entero(valor, defecto=0):
    return int(_numero(valor, defecto))


def _ms(ahora_ms):
    return int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())


# ── El día: el del mercado (UTC), que la pantalla muestra en hora local ──────────────────────────────────────────────

def fecha_de(ms):
    """El día al que pertenece ese momento: el día UTC, el mismo corte de Binance y del registro que no se borra."""
    return time.strftime("%Y-%m-%d", time.gmtime(_ms(ms) / 1000))


def fin_del_dia_ms(ms):
    """Cuándo se levanta el freno del día: el cambio de día. La pantalla lo muestra en hora local («se levanta a las
    21:00»): la hora del computador se usa para mostrar, nunca para decidir."""
    return (_ms(ms) // lib_datos.DIA_MS + 1) * lib_datos.DIA_MS


def al_dia(cuerpo, ahora_ms=None):
    """El cuerpo con el día de hoy puesto. Cuando el día cambia, el freno diario se levantó solo: el día parte de nuevo
    desde el saldo de ahora y sin aportes. Lo llaman el ejecutor en cada cierre y el motor al reconciliar."""
    ms = _ms(ahora_ms)
    hoy = fecha_de(ms)
    dia = cuerpo.get("dia") if isinstance(cuerpo.get("dia"), dict) else {}
    if dia.get("fecha") == hoy:
        return cuerpo
    return {**cuerpo, "dia": {"fecha": hoy, "inicio": _numero(cuerpo.get("saldo")), "aportado": 0.0}}


def dia_de(cuerpo, ahora_ms=None):
    """Cómo viene el día: desde cuánto partió, cuánto se perdió (los aportes del día no cuentan ni como ganancia ni
    como pérdida) y cuándo se levanta el freno."""
    ms = _ms(ahora_ms)
    dia = al_dia(cuerpo, ms)["dia"]
    inicio, aportado = _numero(dia.get("inicio")), _numero(dia.get("aportado"))
    saldo = _numero(cuerpo.get("saldo"))
    perdida = (inicio + aportado - saldo) / inicio if inicio > 0 else 0.0
    hasta = fin_del_dia_ms(ms)
    return {"fecha": dia.get("fecha") or "", "inicio": inicio, "aportado": aportado, "saldo": saldo,
            "perdida": perdida, "monto": inicio + aportado - saldo, "limite": PERDIDA_DIARIA,
            "piso": inicio * (1 - PERDIDA_DIARIA) + aportado,
            "hasta_ms": hasta, "hasta": lib_datos.iso(hasta)}


# ── Los dos pisos: el del capital de referencia y el absoluto, sobre lo aportado ─────────────────────────────────────

def piso_de(cuerpo):
    """Los dos pisos con sus números: el del capital de referencia (el saldo más alto alcanzado) y el absoluto, sobre el
    capital aportado —lo que la persona puso de verdad, depósitos menos retiros, anotados uno por uno—."""
    saldo = _numero(cuerpo.get("saldo"))
    referencia = _numero(cuerpo.get("referencia"))
    aportado = _numero(cuerpo.get("aportado"))
    return {"saldo": saldo, "referencia": referencia, "aportado": aportado,
            "parte": PISO, "parte_absoluto": PISO_ABSOLUTO,
            "piso": referencia * (1 - PISO), "piso_absoluto": aportado * (1 - PISO_ABSOLUTO),
            "caida": (referencia - saldo) / referencia if referencia > 0 else 0.0,
            "caida_aportado": (aportado - saldo) / aportado if aportado > 0 else 0.0}


# ── Los dos frenos del mercado: la comisión y FDUSD ──────────────────────────────────────────────────────────────────

def comision_de(calibracion=None, com=None):
    """La comisión maker de ahora contra la que supuso el backtest. Si subió, lo que el backtest prometió ya no vale y no
    se abre nada: la que supuso la calibración queda escrita con ella (`comisiones`), y sin calibración son las
    supuestas de siempre."""
    c = lib_calibracion.guardada() if calibracion is None else (calibracion or {})
    supuestas = c.get("comisiones") if isinstance(c.get("comisiones"), dict) else {}
    supuesto = supuestas.get("maker")
    de = "calibracion"
    if isinstance(supuesto, bool) or not isinstance(supuesto, (int, float)) or not math.isfinite(supuesto):
        supuesto, de = minimo_viable.COMISIONES_SUPUESTAS["maker"], "supuesto"
    ahora = com if isinstance(com, dict) else minimo_viable.comisiones()
    maker = _numero(ahora.get("maker"))
    return {"maker": maker, "taker": _numero(ahora.get("taker")), "supuesto": float(supuesto),
            "origen": ahora.get("origen") or "supuesto", "de": de, "subio": maker > supuesto + TOLERANCIA}


def _ultima_vela(par, velas=None):
    serie = velas.get(par) if isinstance(velas, dict) else None
    if serie is None:
        serie = lib_datos.leer_serie(par, TEMPORALIDAD_FDUSD)
    return serie[-1] if serie else None


def fdusd_de(ahora_ms=None, velas=None):
    """Cuánto vale FDUSD en USDT, implícito en los dos pares del mismo activo: el BTC que se compra con FDUSD y el que se
    compra con USDT es el mismo BTC, así que el precio de uno dividido por el del otro es el cambio. Binance no da un par
    FDUSD/USDT que Pilota baje, y esto se mide con las velas cerradas que ya tiene.

    Manda el valor **más bajo** de los que se pudieron medir: un freno se equivoca para el lado de frenar. Lo que no se
    puede medir no se inventa (`motivos`), y entonces el freno no se aplica pero queda dicho."""
    ms = _ms(ahora_ms)
    paso = lib_datos.PASO_MS[TEMPORALIDAD_FDUSD]
    pares = []
    for par in lib_datos.PARES_OPERADOS:
        contra = lib_estrategias.PAR_DIARIO[par]      # el par contra USDT del mismo activo
        p = {"par": par, "contra": contra, "fdusd": None, "ms": None, "cuando": "", "motivo": "sin_velas"}
        suya, otra = _ultima_vela(par, velas), _ultima_vela(contra, velas)
        if suya and otra:
            if suya[0] != otra[0]:
                p["motivo"] = "sin_hora"              # las dos velas tienen que ser de la misma hora
            else:
                cierre = int(suya[0]) + paso
                p.update(ms=cierre, cuando=lib_datos.iso(cierre))
                if cierre > ms + 60_000 or ms - cierre > VIGENCIA_FDUSD_MS:
                    p["motivo"] = "velas_viejas"
                elif suya[4] > 0 and otra[4] > 0:
                    p.update(fdusd=otra[4] / suya[4], motivo="")
                else:
                    p["motivo"] = "sin_precio"
        pares.append(p)
    valores = [p["fdusd"] for p in pares if p["fdusd"] is not None]
    valor = min(valores) if valores else None
    return {"minimo": FDUSD_MINIMO, "valor": valor, "pares": pares, "listo": valor is not None,
            "bajo": valor is not None and valor < FDUSD_MINIMO,
            "motivos": [{"codigo": p["motivo"], "par": p["par"]} for p in pares if p["motivo"]]}


def mercado_de(ahora_ms=None, calibracion=None, com=None, velas=None):
    """Lo que los dos frenos del mercado necesitan, leído una sola vez para las dos cuentas."""
    return {"comision": comision_de(calibracion, com), "fdusd": fdusd_de(ahora_ms, velas)}


# ── Los frenos de una cuenta ─────────────────────────────────────────────────────────────────────────────────────────

def _freno(codigo, pasado, aplica, **numeros):
    """Un freno siempre con la misma forma: su código, su razón en el registro, qué hace, si está pasado y si corre en
    esta cuenta. `avisa` es el de mercado en prueba: no frena, pero se dice."""
    return {"codigo": codigo, "razon": RAZON[codigo], "efectos": list(EFECTOS[codigo]), "aplica": bool(aplica),
            "activo": bool(pasado and aplica), "avisa": bool(pasado and not aplica), "pasado": bool(pasado), **numeros}


def desbloqueo_de(cuerpo, ambiente, bloquean=(), ahora_ms=None):
    """El desbloqueo del piso: en real pide 24 h de espera y se puede como máximo `DESBLOQUEOS_MAXIMOS` veces; en prueba
    es al tiro (ahí la espera no cuida nada). El piso absoluto no se desbloquea nunca: con el piso absoluto puesto, el
    del capital de referencia tampoco sirve de nada."""
    ms = _ms(ahora_ms)
    d = cuerpo.get("desbloqueo") if isinstance(cuerpo.get("desbloqueo"), dict) else {}
    usados = _entero(cuerpo.get("desbloqueos"))
    espera = ambiente == lib_estado.REAL
    hasta = _entero(d.get("hasta_ms"), 0) or None
    falta = max(0, hasta - ms) if hasta else 0
    salida = {"usados": usados, "maximos": DESBLOQUEOS_MAXIMOS, "quedan": max(0, DESBLOQUEOS_MAXIMOS - usados),
              "espera": espera, "espera_ms": ESPERA_DESBLOQUEO_MS if espera else 0,
              "pedido_ms": _entero(d.get("pedido_ms"), 0) or None, "hasta_ms": hasta,
              "hasta": lib_datos.iso(hasta) if hasta else "", "falta_ms": falta,
              "pedido": bool(hasta), "puede": False, "listo": False, "motivo": ""}
    if "piso_absoluto" in bloquean:
        return {**salida, "motivo": "piso_absoluto"}
    if "piso" not in bloquean:
        return {**salida, "motivo": "sin_freno"}
    if usados >= DESBLOQUEOS_MAXIMOS:
        return {**salida, "motivo": "sin_desbloqueos"}
    if not espera:
        return {**salida, "puede": True, "listo": True}
    if not hasta:
        return {**salida, "puede": True}                      # falta pedirlo: ahí empiezan las 24 h
    return {**salida, "puede": True, "listo": falta <= 0, "motivo": "" if falta <= 0 else "esperando"}


def de_cuenta(cuenta, ambiente=None, ahora_ms=None, mercado=None):
    """Los frenos de una cuenta, con sus números y en qué estado la dejan. `cuenta` es lo que devuelve
    `lib_estado.cargar` (o su cuerpo): si viene con el arranque frenado, esta cuenta ya está frenada y sus números son
    cero, así que no hay nada que calcular encima."""
    ms = _ms(ahora_ms)
    amb = ambiente or cuenta.get("ambiente") or lib_estado.PRUEBA
    m = mercado if isinstance(mercado, dict) else mercado_de(ms)
    real = amb == lib_estado.REAL
    cuerpo = al_dia(cuenta, ms)
    dia, piso = dia_de(cuerpo, ms), piso_de(cuerpo)
    racha = _entero(cuerpo.get("racha"))
    abiertas, comprometido = lib_tamano.posiciones_de(cuerpo)
    arranque = bool(cuenta.get("frenado"))
    com, fd = m["comision"], m["fdusd"]
    frenos = [
        _freno("piso_absoluto", piso["aportado"] > 0 and piso["saldo"] <= piso["piso_absoluto"], True,
               valor=piso["saldo"], limite=piso["piso_absoluto"], parte=PISO_ABSOLUTO, caida=piso["caida_aportado"]),
        _freno("piso", piso["referencia"] > 0 and piso["saldo"] <= piso["piso"], True,
               valor=piso["saldo"], limite=piso["piso"], parte=PISO, caida=piso["caida"]),
        _freno("diario", dia["inicio"] > 0 and dia["perdida"] >= PERDIDA_DIARIA - TOLERANCIA, True,
               valor=dia["saldo"], limite=dia["piso"], parte=PERDIDA_DIARIA, caida=dia["perdida"],
               hasta_ms=dia["hasta_ms"], hasta=dia["hasta"]),
        _freno("racha", racha >= RACHA_MAXIMA, True, valor=float(racha), limite=float(RACHA_MAXIMA), n=racha),
        _freno("comision", com["subio"], real, valor=com["maker"], limite=com["supuesto"], origen=com["origen"]),
        _freno("fdusd", fd["bajo"], real, valor=fd["valor"], limite=FDUSD_MINIMO, listo=fd["listo"]),
    ]
    activos = [f for f in frenos if f["activo"]]
    bloquean = [f["codigo"] for f in activos if BLOQUEA in f["efectos"]]
    reducen = [f["codigo"] for f in activos if REDUCE in f["efectos"]]
    pausado = bool(cuerpo.get("pausado"))
    frenado = bool(bloquean or arranque)
    quedan = max(0, POSICIONES - abiertas)
    # La máquina de estados: manda el más grave. Reducir la exposición es lo único que pasa por encima de frenado.
    estado_ = "reduciendo" if reducen else ("frenado" if frenado else ("pausado" if pausado else "operando"))
    # Por qué no se puede abrir una entrada, en el orden en que se revisa.
    motivo = ""
    if arranque:
        motivo = "frenado"
    elif bloquean:
        motivo = next(c for c in FRENOS if c in bloquean)
    elif pausado:
        motivo = "pausado"
    elif quedan <= 0:
        motivo = "posiciones_llenas"
    # Lo que no se pudo medir y en esta cuenta sí corre: con un freno a ciegas no se abre nada.
    motivos = [{"codigo": mo["codigo"], "par": mo["par"]} for mo in fd["motivos"]] if real else []
    if not motivo and motivos:
        motivo = "sin_medir"
    return {"formato": 1, "ambiente": amb, "cuando": lib_datos.iso(ms),
            "estado": estado_, "frenado": frenado, "pausado": pausado, "arranque": arranque,
            "arranque_motivo": cuenta.get("motivo") or "", "nuevo": bool((cuenta.get("arranque") or {}).get("nuevo")),
            "modo": lib_estado.MODO_FRENADO if (activos or arranque) else (cuerpo.get("modo") or lib_estado.MODO_FRENADO),
            "manual": bool(activos), "frenos": frenos, "activos": [f["codigo"] for f in activos],
            "bloquean": bloquean, "avisos": [f["codigo"] for f in frenos if f["avisa"]],
            "reduce": {"hay": bool(reducen), "por": reducen[0] if reducen else "", "posiciones": abiertas,
                       "monto": comprometido},
            "entradas": {"puede": not motivo and not motivos, "motivo": motivo, "quedan": quedan},
            "posiciones": {"abiertas": abiertas, "maximas": POSICIONES, "quedan": quedan,
                           "comprometido": comprometido, "protegidas": abiertas},
            "protegidas": abiertas, "dia": dia, "piso": piso, "racha": {"n": racha, "maxima": RACHA_MAXIMA},
            "desbloqueo": desbloqueo_de(cuerpo, amb, bloquean, ms),
            "apalancamiento": APALANCAMIENTO, "motivos": motivos, "listo": not motivos}


# ── La puerta: lo que pregunta el ejecutor antes de poner una orden ──────────────────────────────────────────────────

def permite_entrada(f):
    """Si se puede abrir una posición nueva, con su motivo en código. Es lo primero que pregunta el ejecutor."""
    e = (f or {}).get("entradas") or {}
    return {"puede": bool(e.get("puede")), "motivo": e.get("motivo") or ("" if e.get("puede") else "frenado")}


def revisar_orden(orden, frenos, tamano=None):
    """La revisión de una orden antes de ponerla. Primero que venga del tamaño —el ejecutor rechaza toda orden que no
    haya pasado antes por ahí—, después que sea lo único que Pilota pone (una compra con límite, sin apalancamiento y con
    su stop) y recién al final los frenos de la cuenta.

    Devuelve `puede` con su `motivo` en código (`RECHAZOS`): la pantalla lo traduce."""
    o = orden if isinstance(orden, dict) else {}
    t = tamano if isinstance(tamano, dict) else None
    precio, stop = _numero(o.get("precio")), _numero(o.get("stop"))
    cantidad, monto = _numero(o.get("cantidad")), _numero(o.get("monto"))
    apalancamiento = _numero(o.get("apalancamiento"), float(APALANCAMIENTO))

    def no(motivo):
        return {"puede": False, "motivo": motivo, "cantidad": cantidad, "monto": monto}

    if t is None or not t.get("puede"):
        return no("sin_tamano")
    if o.get("lado") != LADO_ENTRADA:
        return no("lado")
    if o.get("tipo") != TIPO_ENTRADA:
        return no("tipo")
    if apalancamiento > APALANCAMIENTO:
        return no("apalancamiento")
    if not (precio > 0 and 0 < stop < precio):
        return no("sin_proteccion")
    # Más de lo que dejó el tamaño no se pone, ni por un pelo: ese número ya trae la reserva, las dos posiciones, el 2 %
    # de riesgo y el tope del modelo adentro.
    if cantidad > _numero(t.get("cantidad")) * (1 + TOLERANCIA) or monto > _numero(t.get("monto")) * (1 + TOLERANCIA):
        return no("monto_mayor")
    puerta = permite_entrada(frenos)
    if not puerta["puede"]:
        return no(puerta["motivo"])
    return {"puede": True, "motivo": "", "cantidad": cantidad, "monto": monto}


# ── Lo que mueve los contadores: un cierre y un aporte ───────────────────────────────────────────────────────────────

def con_cierre(cuerpo, neto, ahora_ms=None):
    """Una posición que se cerró: el saldo con lo que dejó, la racha de pérdidas al día, una operación más y el día
    puesto al día **antes** de tocar el saldo (si el día cambió, el que parte es el nuevo). No escribe nada: lo guarda
    quien cierra la posición, con su línea en el registro."""
    ms = _ms(ahora_ms)
    neto = _numero(neto)
    c = al_dia(cuerpo, ms)
    c = lib_estado.con_saldo(c, max(0.0, _numero(c.get("saldo")) + neto), ahora_ms=ms)
    return {**c, "racha": _entero(c.get("racha")) + 1 if neto < 0 else 0,
            "operaciones": _entero(c.get("operaciones")) + 1}


def con_aporte(cuerpo, monto, ahora_ms=None):
    """Un depósito o un retiro, explícito y anotado en el libro propio (`lib_estado.con_aporte`), con el día al día: un
    depósito no es una ganancia del día ni un retiro una pérdida, y el capital de referencia se mueve con el aporte."""
    ms = _ms(ahora_ms)
    c = al_dia(cuerpo, ms)
    c = lib_estado.con_aporte(c, monto, ahora_ms=ms)
    return {**c, "dia": {**c["dia"], "aportado": _numero(c["dia"].get("aportado")) + _numero(monto)}}


# ── Lo que hace la app: revisar, pausar, desbloquear y aportar ───────────────────────────────────────────────────────

def _editable(cuenta):
    """Si a esta cuenta se le puede escribir el estado. El archivo sospechoso no se pisa (la evidencia se guarda) y una
    cuenta que todavía no existe no se inventa: nace cuando la persona elige su monto."""
    return not cuenta.get("frenado") and not (cuenta.get("arranque") or {}).get("nuevo")


def _resultado(f, codigo):
    """Lo que dice del freno la línea del registro: su motivo y los números que lo explican, cada uno en la clave que le
    toca (`lib_registro.CAMPOS_RESULTADO`). Nada de texto libre."""
    suyo = next(x for x in f["frenos"] if x["codigo"] == codigo)
    detalle = {
        "piso_absoluto": {"neto_relativo": -f["piso"]["caida_aportado"]},
        "piso": {"neto_relativo": -f["piso"]["caida"]},
        "diario": {"neto": -f["dia"]["monto"], "neto_relativo": -f["dia"]["perdida"]},
        "racha": {"n": f["racha"]["n"]},
        "comision": {"comision": suyo["valor"], "supuesto": suyo["limite"]},
        "fdusd": {"precio": suyo["valor"]},
    }
    return {"motivo": codigo, "saldo": f["piso"]["saldo"], "referencia": f["piso"]["referencia"],
            **detalle.get(codigo, {})}


def aplicar(ambiente=None, ahora_ms=None, mercado=None):
    """Revisa los frenos de una cuenta y los deja aplicados: el modo vuelve a manual y cada freno nuevo queda anotado en
    el registro que no se borra, **una sola vez** (los que ya estaban viven en `frenos` del estado firmado). Solo escribe
    si algo cambió, y de una cuenta cuyo archivo no es de fiar no escribe nada."""
    ms = _ms(ahora_ms)
    amb = lib_registro.ambiente_valido(ambiente or lib_estado.activo())
    cuenta = lib_estado.cargar(amb, ahora_ms=ms)
    f = de_cuenta(cuenta, amb, ms, mercado)
    if not _editable(cuenta):
        return f
    cuerpo = lib_estado.cuerpo_de(cuenta)
    nuevo = al_dia(cuerpo, ms)
    if f["manual"] and nuevo.get("modo") != lib_estado.MODO_FRENADO:
        nuevo = lib_estado.con_modo(nuevo, lib_estado.MODO_FRENADO, ahora_ms=ms)
        lib_registro.anotar(amb, "cambio_modo", resultado={"motivo": f["activos"][0]}, ms=ms)
    antes = [c for c in (cuerpo.get("frenos") or []) if isinstance(c, str)]
    nuevo = {**nuevo, "frenos": list(f["activos"])}
    for codigo in [c for c in FRENOS if c in f["activos"] and c not in antes]:
        lib_registro.anotar(amb, RAZON[codigo], resultado=_resultado(f, codigo), ms=ms)
    if nuevo != cuerpo:
        lib_estado.guardar(amb, nuevo)
    return de_cuenta({**cuenta, **nuevo}, amb, ms, mercado)


def revisar(ahora_ms=None, mercado=None):
    """Los frenos de las dos cuentas, revisados y aplicados, y el estado completo de vuelta. Es lo que corre la acción y
    lo que va a correr el motor cada 5 minutos y al reconciliar: mirar los frenos es aplicarlos."""
    ms = _ms(ahora_ms)
    m = mercado if isinstance(mercado, dict) else mercado_de(ms)
    for amb in lib_estado.AMBIENTES:
        aplicar(amb, ms, m)
    return estado(ahora_ms=ms, mercado=m)


def pausar(pausa=True, ambiente=None, ahora_ms=None):
    """«Pausar»: cancela las entradas y **nunca** toca una protección automática. Lo que está abierto sigue protegido, y
    eso es lo que se muestra (`protegidas`). Quitar la pausa es lo mismo al revés y no abre nada por su cuenta."""
    ms = _ms(ahora_ms)
    amb = lib_registro.ambiente_valido(ambiente or lib_estado.activo())
    cuenta = lib_estado.cargar(amb, ahora_ms=ms)
    if _editable(cuenta) and bool(cuenta.get("pausado")) != bool(pausa):
        cuerpo = {**lib_estado.cuerpo_de(cuenta), "pausado": bool(pausa),
                  "cuando": lib_datos.iso(ms), "cuando_ms": ms}
        lib_estado.guardar(amb, cuerpo)
        lib_registro.anotar(amb, "pausa" if pausa else "reanudar", ms=ms,
                            resultado={"n": len(cuenta.get("posiciones") or [])})
    return estado(ahora_ms=ms)


def desbloquear(ambiente=None, ahora_ms=None):
    """El desbloqueo del piso, a mano: en real la primera vez solo **pide** el desbloqueo y arranca la espera de 24 h; la
    segunda, pasada la espera, lo aplica. Aplicarlo es un **reinicio documentado del capital de referencia** (pasa a ser
    el saldo de ahora) y queda en el registro. En prueba es al tiro. El piso absoluto no se desbloquea."""
    ms = _ms(ahora_ms)
    amb = lib_registro.ambiente_valido(ambiente or lib_estado.activo())
    cuenta = lib_estado.cargar(amb, ahora_ms=ms)
    f = de_cuenta(cuenta, amb, ms)
    d = f["desbloqueo"]
    if not _editable(cuenta) or not d["puede"]:
        return {**estado(ahora_ms=ms), "hecho": False, "motivo": d["motivo"] or "frenado"}
    cuerpo = lib_estado.cuerpo_de(cuenta)
    if not d["listo"]:
        if d["pedido"]:         # ya está pedido: volver a pedirlo no reinicia la espera ni gasta otro desbloqueo
            return {**estado(ahora_ms=ms), "hecho": False, "motivo": "esperando"}
        hasta = ms + ESPERA_DESBLOQUEO_MS
        lib_estado.guardar(amb, {**cuerpo, "cuando": lib_datos.iso(ms), "cuando_ms": ms,
                                 "desbloqueo": {"n": d["usados"] + 1, "pedido_ms": ms, "hasta_ms": hasta}})
        lib_registro.anotar(amb, "desbloqueo", ms=ms, resultado={"motivo": "esperando", "n": d["usados"] + 1})
        return {**estado(ahora_ms=ms), "hecho": False, "motivo": "esperando"}
    saldo = _numero(cuerpo.get("saldo"))
    lib_estado.guardar(amb, {**cuerpo, "cuando": lib_datos.iso(ms), "cuando_ms": ms, "referencia": saldo,
                             "desbloqueos": d["usados"] + 1, "desbloqueo": {}, "frenos": []})
    lib_registro.anotar(amb, "referencia_reiniciada", ms=ms,
                        resultado={"motivo": "piso", "saldo": saldo, "referencia": saldo, "n": d["usados"] + 1})
    return {**estado(ahora_ms=ms), "hecho": True, "motivo": ""}


def aportar(monto, ambiente=None, ahora_ms=None):
    """Un depósito (positivo) o un retiro (negativo) en el libro propio, anotado en el registro. El capital de referencia
    se mueve con él: un depósito no es una ganancia ni un retiro una pérdida, y los dos pisos miran estos números."""
    ms = _ms(ahora_ms)
    amb = lib_registro.ambiente_valido(ambiente or lib_estado.activo())
    cuenta = lib_estado.cargar(amb, ahora_ms=ms)
    if not _editable(cuenta):
        return estado(ahora_ms=ms)
    cuerpo = con_aporte(lib_estado.cuerpo_de(cuenta), monto, ahora_ms=ms)
    lib_estado.guardar(amb, cuerpo)
    lib_registro.anotar(amb, "aporte" if _numero(monto) >= 0 else "retiro", ms=ms,
                        resultado={"neto": _numero(monto), "saldo": cuerpo["saldo"],
                                   "referencia": cuerpo["referencia"]})
    return estado(ahora_ms=ms)


def parametros():
    """Con qué números frena Pilota: los lee la pantalla y quedan en el archivo."""
    return {"apalancamiento": APALANCAMIENTO, "posiciones": POSICIONES, "perdida_diaria": PERDIDA_DIARIA,
            "racha_maxima": RACHA_MAXIMA, "piso": PISO, "piso_absoluto": PISO_ABSOLUTO,
            "fdusd_minimo": FDUSD_MINIMO, "desbloqueos_maximos": DESBLOQUEOS_MAXIMOS,
            "espera_desbloqueo_h": ESPERA_DESBLOQUEO_MS // 3_600_000, "frenos": list(FRENOS),
            "solo_real": list(SOLO_REAL), "efectos": {c: list(EFECTOS[c]) for c in FRENOS},
            "razones": {c: RAZON[c] for c in FRENOS}, "estados": list(ESTADOS), "rechazos": list(RECHAZOS),
            "modo_frenado": lib_estado.MODO_FRENADO}


def estado(ahora_ms=None, cuentas=None, mercado=None, calibracion=None):
    """Los frenos de las dos cuentas —prueba y real llevan los suyos— y arriba los de la que está activa: en qué estado
    quedó, si puede abrir algo y por qué no. No escribe ni cambia nada: eso es `aplicar`."""
    ms = _ms(ahora_ms)
    m = mercado if isinstance(mercado, dict) else mercado_de(ms, calibracion)
    lista = []
    for amb in lib_estado.AMBIENTES:
        cuenta = next((c for c in (cuentas or []) if c.get("ambiente") == amb), None) if cuentas else None
        lista.append(de_cuenta(cuenta if cuenta else lib_estado.cargar(amb, ahora_ms=ms), amb, ms, m))
    cual = lib_estado.activo()
    esta = next(c for c in lista if c["ambiente"] == cual)
    return {"formato": 1, "cuando": lib_datos.iso(ms), "activo": cual, "moneda": "USDT",
            "estado": esta["estado"], "frenado": esta["frenado"], "pausado": esta["pausado"],
            "modo": esta["modo"], "motivo": esta["entradas"]["motivo"], "entradas": esta["entradas"],
            "reduce": esta["reduce"], "protegidas": esta["protegidas"], "cuentas": lista, "mercado": m,
            "parametros": parametros(), "motivos": esta["motivos"], "listo": esta["listo"]}


def escribir(d):
    """Deja escrita la última revisión: la leen el ejecutor, el motor y la pantalla sin volver a calcular nada."""
    nucleo.escribir_json(ruta_frenos(), d)
    return d


def guardado():
    """La última revisión escrita o, si no hay ninguna, nada. Sin red y sin recorrer nada."""
    d = nucleo.leer_json(ruta_frenos(), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    return d if isinstance(d, dict) and d.get("formato") == 1 else {}
