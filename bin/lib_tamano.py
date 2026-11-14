#!/usr/bin/env python3
"""El tamaño de una operación: cuánto se compra, en USDT. Solo biblioteca estándar. No es una acción.

El orden es **fijo** y es el mismo con el que se calcula el capital mínimo viable (`bin/minimo_viable.py`, que hace esta
misma cuenta al revés con un stop supuesto):

1. **Los mínimos de Binance.** La cantidad tiene que servir para la compra y para las dos patas de la protección
   automática (la OCO: una con el objetivo y otra con el stop). La pata del stop vale menos USDT, así que es la que
   manda (`cantidad_minima`, `minimo_de`).
2. **La reserva**: el 40 % del capital se queda en USDT y no se opera nunca.
3. **Dos posiciones** a la vez: lo que queda se reparte entre las dos, y lo que ya está puesto en una posición abierta
   no se reparte de nuevo (`reparto`).
4. **Riesgo máximo del 2 %** del capital por operación.

Monto = **el menor** entre el riesgo dividido por la distancia al stop y lo disponible para esa posición, y nunca más
que el tope mientras el modelo esté «Aún sin validar» (`lib_calibracion.TOPE_NO_VALIDADO`). `manda` dice cuál de los
tres cortó.

Si lo que sale queda **bajo el mínimo de Binance, no hay orden**: `puede` queda en falso y el motivo viaja en código
(`bajo_minimo`, con cuánto haría falta por posición y de capital) para que la pantalla lo diga. Una orden que Binance
rechaza es una posición sin protección, así que acá se rechaza antes.

Las dos capas son las de siempre:
- Las de siempre (`reparto`, `cantidad_minima`, `minimo_de`, `tamano`): números y nada más, sin leer nada del disco.
  Son las que van a usar los frenos, el ejecutor de prueba y el conector real, en sus pasos.
- Las de la app (`de_opcion`, `estado`): el tamaño de **ahora** de cada oportunidad puntuada, leyendo el puntaje
  guardado, el estado firmado de la cuenta activa y los filtros del último cálculo del capital mínimo viable.

Lo que no se negocia aquí:
- **Ningún mínimo se inventa.** Sin los filtros de Binance (`mercado/minimo.json`) no se calcula ningún tamaño
  (`sin_minimos`), y un par detenido o sin protección automática tampoco (`sin_operar`, `sin_proteccion`).
- **De un estado del que no se puede fiar nadie no sale un tamaño.** Si la cuenta arrancó frenada, sus números vienen
  en cero (`lib_estado.cargar`) y acá queda `frenado`.
- **Los costos se equivocan para el lado caro**: la conversión USDT↔FDUSD, la comisión maker de la entrada y la taker
  del stop se descuentan del monto **y** se cuentan dentro del 2 % de riesgo, así que lo que se arriesga de verdad
  nunca pasa el freno.
- **La cantidad se redondea para abajo** (`bajar_al_paso`) y el precio y el stop al tick que acepta Binance: redondear
  para arriba sería pasarse del límite que acaba de calcularse.
- **El tope del modelo sin validar es un corte, no un rechazo**: queda marcado (`topado`, `manda`) y la pantalla lo
  dice. Lo que el modelo promete todavía no está probado.

Dónde queda: `<datos>/mercado/tamano.json` (lo que devuelve `estado()`, con la hora del cálculo).
"""
import math
import os
from decimal import ROUND_FLOOR, Decimal

import lib_calibracion
import lib_datos
import lib_estado
import lib_puntaje
import minimo_viable
import nucleo

#: Los tres frenos del orden fijo, los mismos del capital mínimo viable: que no se separen lo revisa una prueba.
RESERVA = minimo_viable.RESERVA
POSICIONES = minimo_viable.POSICIONES
RIESGO = minimo_viable.RIESGO
#: Por qué no hay tamaño. Son códigos: la pantalla los traduce y nunca se muestra el código pelado.
RECHAZOS = ("frenado", "sin_minimos", "sin_operar", "sin_proteccion", "sin_precio", "sin_stop", "posiciones_llenas",
            "sin_capital", "sin_disponible", "bajo_minimo")
#: Cuál de los tres límites cortó el monto (el paso 4 del orden).
LIMITES = ("riesgo", "disponible", "tope")


def ruta_tamano():
    return os.path.join(lib_datos.carpeta_mercado(), "tamano.json")


# ── Números, sin creerle a nadie ─────────────────────────────────────────────────────────────────────────────────────

def _numero(valor, defecto=0.0):
    """El valor si es un número finito y, si no, el de partida: lo que llega puede venir de un archivo editado a mano."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        return defecto
    return float(valor)


def bajar_al_paso(cantidad, paso):
    """El múltiplo del paso igual o menor que `cantidad`: la cantidad se redondea **para abajo**, así el monto nunca
    pasa el límite que acaba de calcularse (la de arriba, la que sube al paso, es la del mínimo: `minimo_viable`)."""
    if paso <= 0:
        return max(0.0, cantidad)
    p = Decimal(str(paso))
    if cantidad <= 0:
        return 0.0
    return float((Decimal(str(cantidad)) / p).quantize(Decimal(1), rounding=ROUND_FLOOR) * p)


def comisiones(com=None):
    """Las comisiones con las que se hace la cuenta: las que llegan (la familia costo del puntaje, o las que dejó
    escritas el conector real) y, lo que falte, las supuestas. `origen` dice cuál de las dos es, y la pantalla lo
    muestra: una cuenta con costos supuestos se dice."""
    def valida(v):
        return (not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)
                and 0 <= v <= minimo_viable.COMISION_MAXIMA)

    c = com if isinstance(com, dict) else {}
    cuales = ("maker", "taker", "conversion")
    salida = dict(minimo_viable.COMISIONES_SUPUESTAS)
    completo = all(valida(c.get(k)) for k in cuales)
    for k in cuales:
        if valida(c.get(k)):
            salida[k] = float(c[k])
    salida["origen"] = c.get("origen") if completo and c.get("origen") in ("api", "supuesto") else "supuesto"
    return salida


def costo_de(com):
    """Qué parte del nocional se llevan los costos de la vuelta completa: la conversión USDT↔FDUSD, la comisión maker
    de la entrada (límite post-only contra FDUSD) y la taker del stop, que sale a mercado."""
    return com["conversion"] + com["maker"] + com["taker"]


# ── Los pasos 1 al 3: el mínimo y el reparto ─────────────────────────────────────────────────────────────────────────

def cantidad_minima(f, precio, stop):
    """Paso 1: la cantidad más chica que Binance acepta para ese par con **este** stop. Tiene que pasar la cantidad
    mínima y el nocional mínimo en la compra y en las dos patas de la protección; la del stop vale menos USDT, así que
    es la que manda (la del objetivo está más arriba y nunca es la que corta)."""
    nocional = _numero(f.get("nocional_minimo"))
    niveles = [p for p in (_numero(precio), _numero(stop)) if p > 0]
    pide = [_numero(f.get("cantidad_minima"))] + [nocional / p for p in niveles]
    return minimo_viable.subir_al_paso(max(pide), _numero(f.get("paso")))


def parte_del_capital(distancia_stop, costo=0.0):
    """Qué parte del capital puede usar una posición: lo que dejan la reserva y las dos posiciones (pasos 2 y 3), o lo
    que deja el riesgo máximo con este stop (paso 4). Manda la menor, igual que en el capital mínimo viable."""
    reparte = (1 - RESERVA) / POSICIONES
    if distancia_stop + costo <= 0:
        return reparte
    return min(reparte, RIESGO / (distancia_stop + costo))


def minimo_de(f, precio, stop, com=None):
    """Paso 1 completo: la posición más chica que se puede abrir de ese par con este stop —la cantidad mínima, lo que
    vale en USDT con sus costos— y el capital que haría falta para abrirla sin romper la reserva ni el riesgo. Es lo que
    se muestra cuando el tamaño queda bajo el mínimo: el motivo con un número, no un «no se puede»."""
    com = comisiones(com)
    costo = costo_de(com)
    precio, stop = _numero(precio), _numero(stop)
    cantidad = cantidad_minima(f, precio, stop)
    entrada = cantidad * precio
    posicion = entrada * (1 + costo)
    parte = parte_del_capital((precio - stop) / precio if precio > 0 else 0.0, costo)
    return {"cantidad": cantidad, "entrada": entrada, "costos": entrada * costo, "posicion": posicion,
            "parte": parte, "capital": math.ceil(posicion / parte) if parte > 0 else None,
            "cantidad_minima": _numero(f.get("cantidad_minima")), "nocional_minimo": _numero(f.get("nocional_minimo"))}


def reparto(capital, abiertas=0, comprometido=0.0):
    """Pasos 2 y 3: cuánto se puede operar y cuánto le toca a una posición. La reserva se queda en USDT siempre, las
    posiciones son como máximo dos y lo que ya está puesto en las abiertas no se reparte de nuevo."""
    capital = max(0.0, _numero(capital))
    comprometido = max(0.0, _numero(comprometido))
    abiertas = max(0, int(_numero(abiertas)))
    operable = capital * (1 - RESERVA)
    por_posicion = operable / POSICIONES
    libre = max(0.0, operable - comprometido)
    return {"capital": capital, "reserva": RESERVA, "en_usdt": capital - operable, "operable": operable,
            "posiciones": POSICIONES, "abiertas": abiertas, "quedan": max(0, POSICIONES - abiertas),
            "comprometido": comprometido, "libre": libre, "por_posicion": por_posicion,
            "disponible": min(por_posicion, libre), "riesgo": RIESGO, "riesgo_maximo": capital * RIESGO}


# ── El paso 4: el monto ──────────────────────────────────────────────────────────────────────────────────────────────

def tamano(capital, precio, stop, filtros=None, com=None, tope=None, abiertas=0, comprometido=0.0, frenado=False):
    """El tamaño de una operación, en el orden fijo. `filtros` son los de ese par como los dejó el capital mínimo
    viable (tick, paso, cantidad mínima y nocional mínimo); `tope` es el del modelo mientras no esté validado (None
    cuando sí lo está) y `frenado` es lo que dice el estado firmado de la cuenta.

    Devuelve siempre la misma forma: el reparto, los tres límites con cuál mandó, el mínimo de Binance, la cantidad y
    el monto con sus costos, lo que se arriesga de verdad, y `puede` con su `motivo` en código."""
    com = comisiones(com)
    costo = costo_de(com)
    f = filtros if isinstance(filtros, dict) else {}
    r = reparto(capital, abiertas, comprometido)
    tick, paso = _numero(f.get("tick")), _numero(f.get("paso"))
    entrada = minimo_viable.bajar_al_tick(_numero(precio), tick) if tick > 0 else _numero(precio)
    nivel_stop = minimo_viable.bajar_al_tick(_numero(stop), tick) if tick > 0 else _numero(stop)
    hay_niveles = entrada > 0 and 0 < nivel_stop < entrada
    distancia = (entrada - nivel_stop) / entrada if hay_niveles else None
    base = {**r, "par": f.get("par") or "", "moneda": f.get("moneda") or "", "precio": entrada,
            "precio_pedido": _numero(precio), "stop": nivel_stop, "stop_pedido": _numero(stop),
            "distancia_stop": distancia, "costo_relativo": costo, "comisiones": com,
            "tope": tope, "topado": tope is not None, "tick": tick, "paso": paso,
            "minimo": minimo_de(f, entrada, nivel_stop, com) if hay_niveles and paso > 0 else None,
            "limites": [], "manda": "", "cantidad": 0.0, "entrada": 0.0, "costos": 0.0, "monto": 0.0,
            "arriesgado": 0.0, "arriesgado_relativo": None}

    # El orden de las revisiones es el orden del rechazo: lo que falta se dice antes de hacer una cuenta con nada.
    if frenado:
        return {**base, "puede": False, "motivo": "frenado"}
    if not (f.get("par") and tick > 0 and paso > 0 and _numero(f.get("cantidad_minima")) > 0):
        return {**base, "puede": False, "motivo": "sin_minimos"}
    if f.get("motivo") in ("sin_operar", "sin_proteccion"):
        return {**base, "puede": False, "motivo": f["motivo"]}
    if entrada <= 0:
        return {**base, "puede": False, "motivo": "sin_precio"}
    if not hay_niveles:
        return {**base, "puede": False, "motivo": "sin_stop"}
    if r["quedan"] <= 0:
        return {**base, "puede": False, "motivo": "posiciones_llenas"}
    if r["capital"] <= 0:
        return {**base, "puede": False, "motivo": "sin_capital"}
    if r["disponible"] <= 0:
        return {**base, "puede": False, "motivo": "sin_disponible"}

    # El menor entre el riesgo dividido por la distancia al stop, lo disponible para esta posición y el tope. Los
    # costos van en las tres: el stop también paga comisión, y el monto que sale de la cuenta los lleva adentro.
    limites = [{"que": "riesgo", "monto": r["riesgo_maximo"] / (distancia + costo)},
               {"que": "disponible", "monto": r["disponible"] / (1 + costo)}]
    if tope is not None:
        limites.append({"que": "tope", "monto": max(0.0, _numero(tope)) / (1 + costo)})
    corta = min(limites, key=lambda x: x["monto"])
    cantidad = bajar_al_paso(corta["monto"] / entrada, paso)
    minimo = base["minimo"]
    base = {**base, "limites": limites, "manda": corta["que"]}
    if cantidad < minimo["cantidad"]:
        return {**base, "puede": False, "motivo": "bajo_minimo"}
    nocional = cantidad * entrada
    costos = nocional * costo
    arriesgado = cantidad * (entrada - nivel_stop) + costos
    return {**base, "puede": True, "motivo": "", "cantidad": cantidad, "entrada": nocional, "costos": costos,
            "monto": nocional + costos, "arriesgado": arriesgado,
            "arriesgado_relativo": arriesgado / r["capital"] if r["capital"] > 0 else None}


def parametros():
    """Con qué números se calcula el tamaño: los lee la pantalla y quedan en el archivo."""
    return {"reserva": RESERVA, "posiciones": POSICIONES, "riesgo": RIESGO,
            "tope_no_validado": lib_calibracion.TOPE_NO_VALIDADO, "rechazos": list(RECHAZOS), "limites": list(LIMITES)}


# ── Lo que usa la app: el tamaño de ahora ────────────────────────────────────────────────────────────────────────────

def filtros_de(minimo=None):
    """Los filtros vigentes de cada par operado, del último cálculo del capital mínimo viable, y ese cálculo al lado.
    Sin cálculo no hay filtros y no se calcula ningún tamaño: un mínimo inventado es una orden que Binance rechaza."""
    d = minimo_viable.guardado() if minimo is None else (minimo if isinstance(minimo, dict) else {})
    pares = {p["par"]: p for p in (d.get("pares") or [])
             if isinstance(p, dict) and p.get("par") in lib_datos.PARES_OPERADOS}
    if minimo is None:
        # Las monedas del robot en prueba traen sus propios mínimos (`lib_universo.filtros`), pedidos a Binance igual.
        import lib_universo
        for par, f in lib_universo.filtros_guardados().items():
            pares.setdefault(par, f)
    return pares, d


def posiciones_de(cuenta):
    """Cuántas posiciones tiene abiertas la cuenta y cuánto tienen comprometido en USDT. Las escriben el ejecutor de
    prueba y el conector real, en sus pasos; acá solo se cuentan, y lo que no se entienda cuenta como cero."""
    abiertas = [p for p in ((cuenta or {}).get("posiciones") or []) if isinstance(p, dict)]
    comprometido = 0.0
    for p in abiertas:
        monto = _numero(p.get("monto"), None)
        if monto is None:      # una posición que no dice su monto: lo que vale su cantidad al precio de entrada
            monto = _numero(p.get("cantidad")) * _numero(p.get("precio"))
        comprometido += max(0.0, monto)
    return len(abiertas), comprometido


def de_opcion(o, filtros=None, capital=0.0, com=None, tope=None, abiertas=0, comprometido=0.0, frenado=False):
    """Una oportunidad puntuada (`lib_puntaje.opcion`) con su tamaño al lado: el mismo orden fijo, con el nivel de
    entrada y el stop que trae la señal. El puntaje no entra en la cuenta —el tamaño no premia una oportunidad
    linda—: la exigencia y los frenos son sus propios pasos."""
    t = tamano(capital, o.get("entrada"), o.get("stop"), filtros, com, tope, abiertas, comprometido, frenado)
    return {"estrategia": o.get("estrategia") or "", "par": o.get("par") or "",
            "temporalidad": o.get("temporalidad") or "", "razon": o.get("razon") or "",
            # La vela de la que salió la señal viaja con ella: es la que dice que dos propuestas son la misma
            # oportunidad (`lib_modos.id_de`, `lib_ejecutor_prueba.repetida`), y sin ella se abriría dos veces.
            "vela": o.get("vela"),
            "puntaje": o.get("puntaje"), "permitida": bool(o.get("permitida")), "filtro": o.get("filtro") or "",
            "entrada": o.get("entrada"), "stop": o.get("stop"), "objetivo": o.get("objetivo"),
            "vence": o.get("vence"), "tamano": t, "puede": bool(t["puede"]), "motivo": t["motivo"]}


def mejor_de(oportunidades):
    """La que más puntúa de las que se pueden entrar **y** tienen tamaño: una oportunidad sin monto no es una opción.
    Cuál se entra de verdad lo deciden la exigencia y los tres modos, en sus pasos."""
    candidatas = [o for o in oportunidades if o["puede"] and o["permitida"] and o.get("puntaje") is not None]
    return max(candidatas, key=lambda o: o["puntaje"]) if candidatas else None


def estado(ahora_ms=None, puntaje=None, cuentas=None, minimo=None, calibracion=None):
    """El tamaño de ahora de cada oportunidad puntuada, con el reparto del capital de la cuenta activa y el tope del
    modelo. `puntaje`, `cuentas`, `minimo` y `calibracion` se pueden pasar ya calculados (el motor, en su paso, los
    tiene a mano) para no recorrer las velas ni leer el disco dos veces.

    `listo` pide lo que hace falta para poder decir un monto: los mínimos de Binance calculados, una cuenta que no
    arrancó frenada, capital y alguna posición libre. Que ahora mismo no haya ninguna oportunidad no es que falte
    algo: eso lo dice el puntaje, en su paso."""
    ahora = ahora_ms or lib_datos.ahora_local_ms()
    cal = lib_calibracion.guardada() if calibracion is None else calibracion
    modelo = lib_calibracion.modelo(cal)
    p = lib_puntaje.estado(ahora, calibracion=cal) if puntaje is None else puntaje
    e = lib_estado.estado(ahora_ms=ahora) if cuentas is None else cuentas
    esta = next((c for c in (e.get("cuentas") or []) if c.get("ambiente") == e.get("activo")), {})
    pares, md = filtros_de(minimo)
    com = comisiones(p.get("comisiones"))
    frenado = bool(esta.get("frenado"))
    capital = _numero(esta.get("saldo"))
    abiertas, comprometido = posiciones_de(esta)
    tope = modelo["tope"] if modelo["topado"] else None
    r = reparto(capital, abiertas, comprometido)
    oportunidades = [de_opcion(o, pares.get(o.get("par")), capital, com, tope, abiertas, comprometido, frenado)
                     for o in (p.get("opciones") or [])]
    motivos = []
    if frenado:
        motivos.append({"codigo": "frenado", "par": "", "n": 0})
    if not md.get("calculado"):
        motivos.append({"codigo": "sin_minimos", "par": "", "n": 0})
    else:
        for par in lib_datos.PARES_OPERADOS:
            suyo = pares.get(par) or {}
            if suyo.get("motivo") in ("sin_operar", "sin_proteccion"):
                motivos.append({"codigo": suyo["motivo"], "par": par, "n": 0})
    if not frenado and capital <= 0:
        motivos.append({"codigo": "sin_capital", "par": "", "n": 0})
    if r["quedan"] <= 0:
        motivos.append({"codigo": "posiciones_llenas", "par": "", "n": r["abiertas"]})
    elif capital > 0 and r["disponible"] <= 0:
        motivos.append({"codigo": "sin_disponible", "par": "", "n": r["abiertas"]})
    return {"formato": 1, "cuando": lib_datos.iso(ahora), "moneda": "USDT", "ambiente": e.get("activo") or "",
            "frenado": frenado, "motivo": esta.get("motivo") or "", "modo": esta.get("modo") or "",
            "saldo": capital, "referencia": _numero(esta.get("referencia")), "reparto": r,
            "modelo": {"estado": modelo["estado"], "calibrado": bool(modelo["calibrado"]),
                       "validado": bool(modelo["validado"]), "exigencia": modelo["exigencia"],
                       "tope": modelo["tope"], "topado": bool(modelo["topado"]),
                       "cuando": modelo["cuando"], "motivo": modelo["motivo"]},
            "minimos": {"calculado": bool(md.get("calculado")), "cuando": md.get("cuando") or "",
                        "capital_minimo": md.get("capital_minimo") or 0},
            "comisiones": com, "oportunidades": oportunidades, "mejor": mejor_de(oportunidades),
            "parametros": parametros(), "motivos": motivos, "listo": not motivos}


def escribir(d):
    """Deja escrito el último tamaño: lo leen los frenos, el ejecutor y la pantalla sin volver a calcular nada."""
    nucleo.escribir_json(ruta_tamano(), d)
    return d


def guardado():
    """El último tamaño calculado o, si no hay ninguno, nada. Sin red y sin recorrer nada."""
    d = nucleo.leer_json(ruta_tamano(), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    return d if isinstance(d, dict) and d.get("formato") == 1 else {}
