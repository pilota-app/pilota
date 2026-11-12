#!/usr/bin/env python3
"""lib_ejecutor_real — el conector real: las órdenes de verdad en Binance. Solo biblioteca estándar. No es una acción.

Tiene **el mismo contrato** que el ejecutor de prueba (`entrar`, `revisar`, `cerrar`, `estado`, `escribir`, `guardado`,
`repetida`): los tres modos y el motor no saben con qué dinero se juega, solo preguntan `lib_estado.activo()`.

Cómo vive una posición en real:

1. **Entrar.** Las mismas puertas que en prueba, en el mismo orden: la oportunidad, los frenos, el tamaño y que la
   protección **cabe** con los mínimos de Binance. Si falta FDUSD para la compra, se convierte lo justo desde USDT
   (`FDUSDUSDT`, a mercado). La compra es una límite **LIMIT_MAKER** en el nivel: si se llenara al tiro, Binance la
   rechaza (no se compra caro por apuro). El id es el determinista de siempre, con el prefijo propio y la letra `r`.
2. **Llenada → protegida al tiro.** En la revisión, una entrada llenada recibe su protección: una OCO de venta con el
   objetivo (límite) y el stop (a mercado al tocarlo, para que salga aunque el precio salte). La cantidad protegida es la
   comprada **o lo que hay libre de esa moneda, lo menor**: Pilota nunca vende monedas que no compró.
3. **Si Binance no acepta la protección, se vende a mercado en ese momento.** Una posición sin protección no se queda
   abierta esperando (`proteccion_sin_confirmar`, en el registro).
4. **Cerrada.** Cuando la OCO terminó, se mira cuál de las dos patas se llenó y a qué precio: el resultado es el de verdad
   (lo recibido menos lo pagado, con la comisión de salida), y el saldo se mueve con `lib_frenos.con_cierre`, como en
   prueba.
5. **Vencida.** Una entrada que no se llenó en su vigencia se cancela. Si alcanzó a llenarse una parte, esa parte se
   protege si llega a los mínimos y, si no, se vende a mercado.

Lo que no se negocia aquí:
- **Solo lo propio.** Lo que no lleva el prefijo de Pilota no se mira, no se cancela y no se vende.
- **Ante la duda, nada nuevo.** Sin conexión, la revisión no inventa nada: deja las posiciones como estaban y lo dice
  (`sin_conexion`). Las protecciones ya puestas siguen en Binance aunque el equipo se apague.
- **En real la posición sale entera.** La salida en dos mitades y el stop móvil son de prueba por ahora: en real cada
  movida del stop es cancelar y reponer la OCO, y eso se hará cuando esté probado aparte.
- `cliente` se puede pasar (las pruebas pasan un Binance falso); si no, se arma con la llave del llavero.
"""
import math
import os

import lib_binance_privado as bp
import lib_calibracion
import lib_costos
import lib_datos
import lib_estado
import lib_frenos
import lib_llavero
import lib_registro
import lib_tamano
import minimo_viable
import nucleo
from lib_ejecutor_prueba import (ABIERTA, CANCELADA, CERRADA, ENTRADA, LLENADA, PREFIJO, PUESTA, RAZON_ENTRADA,
                                 RAZON_VENCIDA, VENCIDA, cabe, es_nuestro, precio_de, minutos_de, vigencia_de)

AMBIENTE = lib_estado.REAL
CONVERSION = "FDUSDUSDT"
MONEDA_PAR = "FDUSD"
RECHAZOS = ("sin_ambiente", "sin_cuenta", "sin_opcion", "no_permitida", "repetida", "sin_minimos", "sin_llave",
            "sin_conexion", "sin_saldo", "cruzaria", "binance", *lib_tamano.RECHAZOS, *lib_frenos.RECHAZOS)
MOTIVOS = ("frenado", "sin_cuenta", "sin_minimos", "sin_llave", "sin_conexion", "sin_capital")
#: Lo que Binance dice de una orden que ya no va a cambiar.
TERMINADAS = ("FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH")
TOLERANCIA = 1e-9


def ruta_ejecutor():
    return os.path.join(lib_datos.carpeta_mercado(), "ejecutor_real.json")


def _numero(valor, defecto=0.0):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return defecto
    return v if math.isfinite(v) else defecto


def _entero(valor, defecto=0):
    v = _numero(valor, None)
    return int(v) if v is not None else defecto


def _ms(ahora_ms=None):
    return int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())


def id_de(par, ms, que):
    return f"{PREFIJO}-{AMBIENTE[0]}-{par}-{int(ms)}-{que}"


def nuestras(cuerpo):
    return [p for p in ((cuerpo or {}).get("posiciones") or []) if isinstance(p, dict) and es_nuestro(p.get("id"))]


def ajenas(cuerpo):
    return [p for p in ((cuerpo or {}).get("posiciones") or []) if isinstance(p, dict) and not es_nuestro(p.get("id"))]


def repetida(cuerpo, o):
    return any(p.get("par") == o.get("par") and p.get("estrategia") == o.get("estrategia")
               and _entero(p.get("vela_ms")) == _entero(o.get("vela")) for p in nuestras(cuerpo))


def _editable(cuenta):
    return not cuenta.get("frenado") and not (cuenta.get("arranque") or {}).get("nuevo")


def bajar(numero, paso):
    return minimo_viable.bajar_al_tick(numero, paso) if paso > 0 else numero


def conectar(cliente=None):
    """El cliente de Binance: el que llega (pruebas) o uno nuevo con la llave del llavero. `None` si no hay llave."""
    if cliente is not None:
        return cliente
    llave = lib_llavero.leer()
    return bp.Privada(*llave) if llave else None


def libres(cliente):
    """Lo libre de cada moneda en Binance (no lo bloqueado en órdenes)."""
    return {b.get("asset"): _numero(b.get("free")) for b in (cliente.cuenta().get("balances") or [])
            if isinstance(b, dict)}


def _registro_orden(p, estado):
    return {"id": p["id"], "lado": lib_frenos.LADO_ENTRADA, "tipo": lib_frenos.TIPO_ENTRADA, "precio": p["precio"],
            "cantidad": p["cantidad"], "monto": p["monto"], "stop": p["stop"], "objetivo": p["objetivo"],
            "estado": estado, "vence_ms": p["vence_ms"]}


def _rechazo(o, motivo, ms, tamano_=None):
    lib_registro.anotar(AMBIENTE, "rechazo", par=o.get("par") or "", puntaje=o.get("puntaje"), ms=ms,
                        resultado={"motivo": motivo})
    return {"puesta": False, "motivo": motivo, "posicion": None, "tamano": tamano_, "proteccion": None}


def _guardar(cuerpo, posiciones, ms):
    lib_estado.guardar(AMBIENTE, {**cuerpo, "cuando": lib_datos.iso(ms), "cuando_ms": ms,
                                  "posiciones": [*ajenas(cuerpo), *posiciones]})


# ── Entrar ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def entrar(opcion, ahora_ms=None, tamano_=None, frenos=None, com=None, calibracion=None, cliente=None):
    ms = _ms(ahora_ms)
    o = opcion if isinstance(opcion, dict) else {}
    vacio = {"puesta": False, "motivo": "", "posicion": None, "tamano": None, "proteccion": None}
    if lib_estado.activo() != AMBIENTE:
        return {**vacio, "motivo": "sin_ambiente"}
    cuenta = lib_estado.cargar(AMBIENTE, ahora_ms=ms)
    if (cuenta.get("arranque") or {}).get("nuevo"):
        return {**vacio, "motivo": "sin_cuenta"}
    if o.get("estrategia") not in RAZON_ENTRADA or not (_numero(o.get("entrada")) > 0 and _numero(o.get("stop")) > 0):
        return _rechazo(o, "sin_opcion", ms)
    if not o.get("permitida"):
        return _rechazo(o, "no_permitida", ms)
    f = frenos if isinstance(frenos, dict) else lib_frenos.aplicar(AMBIENTE, ms)
    cuenta = lib_estado.cargar(AMBIENTE, ahora_ms=ms)
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
        modelo = lib_calibracion.modelo(lib_calibracion.guardada() if calibracion is None else calibracion)
        t = lib_tamano.tamano(_numero(cuenta.get("saldo")), o.get("entrada"), o.get("stop"), filtros, com,
                              modelo["tope"] if modelo["topado"] else None, abiertas, comprometido,
                              not _editable(cuenta))
    if not md.get("calculado"):
        return _rechazo(o, "sin_minimos", ms, t)
    if not t.get("puede"):
        return _rechazo(o, t.get("motivo") or "sin_tamano", ms, t)
    orden = {"lado": lib_frenos.LADO_ENTRADA, "tipo": lib_frenos.TIPO_ENTRADA, "precio": t.get("precio"),
             "stop": t.get("stop"), "cantidad": t.get("cantidad"), "monto": t.get("monto"),
             "apalancamiento": lib_frenos.APALANCAMIENTO}
    r = lib_frenos.revisar_orden(orden, f, t)
    if not r["puede"]:
        return _rechazo(o, r["motivo"], ms, t)
    tick, paso = _numero(filtros.get("tick")), _numero(filtros.get("paso"))
    objetivo = bajar(_numero(o.get("objetivo")), tick)
    c = cabe(filtros, t["precio"], t["stop"], objetivo, t["cantidad"], False)
    if not c["cabe"]:
        return _rechazo(o, c["motivo"], ms, t)
    if not _editable(cuenta):
        return _rechazo(o, "frenado", ms, t)
    cli = conectar(cliente)
    if cli is None:
        return _rechazo(o, "sin_llave", ms, t)
    p = {"id": id_de(o["par"], ms, ENTRADA), "par": o["par"], "estrategia": o.get("estrategia") or "",
         "temporalidad": o.get("temporalidad") or "", "vela_ms": _entero(o.get("vela")), "estado": PUESTA,
         "precio": _numero(t["precio"]), "stop": _numero(t["stop"]), "stop_inicial": _numero(t["stop"]),
         "objetivo": objetivo, "cantidad": _numero(t["cantidad"]), "monto": _numero(t["monto"]),
         "mitad": None, "entera": True, "movil": False, "puntaje": o.get("puntaje"), "puesta_ms": ms,
         "vence_ms": vigencia_de(o, ms), "llenada_ms": 0, "revisado_ms": ms, "reposiciones": 0, "protegida": False,
         "comprada": 0.0, "pagado": 0.0, "proteccion_id": "", "convertido": 0.0}
    p["vence"] = lib_datos.iso(p["vence_ms"]) if p["vence_ms"] else ""
    try:
        cli.sincronizar()
        saldo = libres(cli)
        falta = p["monto"] - saldo.get(MONEDA_PAR, 0.0)
        if falta > TOLERANCIA:
            pedir = math.ceil(falta * 1.002 * 100) / 100           # un poco más: la conversión también cobra
            if saldo.get("USDT", 0.0) + TOLERANCIA < pedir:
                return _rechazo(o, "sin_saldo", ms, t)
            cli.comprar_con(CONVERSION, bp.texto(pedir, 0.01), id_de(o["par"], ms, "conversion"))
            p["convertido"] = pedir
        cli.comprar_limite(p["par"], bp.texto(p["cantidad"], paso), bp.texto(p["precio"], tick), p["id"])
    except bp.ErrorBinance as e:
        # -2010 en una LIMIT_MAKER es casi siempre «se habría llenado al tiro»: el precio ya pasó el nivel.
        return _rechazo(o, "cruzaria" if e.codigo == bp.SIN_SALDO else "binance", ms, t)
    except bp.SinRed:
        return _rechazo(o, "sin_conexion", ms, t)
    cuerpo = lib_estado.cuerpo_de(lib_estado.cargar(AMBIENTE, ahora_ms=ms))
    _guardar(cuerpo, [*nuestras(cuerpo), p], ms)
    lib_registro.anotar(AMBIENTE, RAZON_ENTRADA[p["estrategia"]], par=p["par"], puntaje=p["puntaje"], ms=ms,
                        orden=_registro_orden(p, PUESTA))
    return {"puesta": True, "motivo": "", "posicion": p, "tamano": t, "proteccion": c}


# ── Revisar: lo que dice Binance, aplicado ───────────────────────────────────────────────────────────────────────────

def _llenado(o):
    """Cuánto se llenó de una orden de Binance y a qué precio medio."""
    hecha = _numero(o.get("executedQty"))
    cotizado = _numero(o.get("cummulativeQuoteQty"))
    return hecha, (cotizado / hecha if hecha > 0 else 0.0), cotizado


def _proteger(cli, p, filtros, ms):
    """Pone la OCO de una posición recién llenada. Si Binance no la acepta, vende a mercado: nada queda desnudo."""
    paso, tick = _numero(filtros.get("paso")), _numero(filtros.get("tick"))
    moneda = filtros.get("moneda") or p["par"].replace(MONEDA_PAR, "")
    cantidad = bajar(min(p["comprada"], libres(cli).get(moneda, 0.0)), paso)
    c = cabe(filtros, p["precio"], p["stop"], p["objetivo"], cantidad, False)
    lista = id_de(p["par"], _entero(p["llenada_ms"]) or ms, "proteccion")
    if c["cabe"]:
        try:
            cli.proteger(p["par"], bp.texto(cantidad, paso), bp.texto(p["objetivo"], tick), bp.texto(p["stop"], tick),
                         lista)
            return {**p, "estado": ABIERTA, "cantidad": cantidad, "protegida": True, "proteccion_id": lista}, None
        except bp.ErrorBinance:
            pass
    # Sin protección no se queda: se vende a mercado lo que se compró.
    if cantidad <= 0:
        return None, {"por": "manual", "precio": p["precio"], "cantidad": 0.0, "recibido": 0.0, "motivo": "sin_proteccion"}
    v = cli.vender_mercado(p["par"], bp.texto(cantidad, paso), id_de(p["par"], ms, "salida"))
    hecha, precio, cotizado = _llenado(v)
    return None, {"por": "manual", "precio": precio, "cantidad": hecha, "recibido": cotizado, "motivo": "sin_proteccion"}


def _cerrar_en_cuerpo(cuerpo, p, salida, com, ms):
    """Anota el cierre de verdad y mueve el saldo: lo recibido (menos la comisión de salida) menos lo pagado."""
    lado = "maker" if salida["por"] == "objetivo" else "taker"
    comision = salida["recibido"] * _numero(com.get(lado))
    pagado = p["pagado"] * (salida["cantidad"] / p["comprada"]) if p["comprada"] > 0 else p["pagado"]
    neto = salida["recibido"] - comision - pagado
    cuerpo = lib_frenos.con_cierre(cuerpo, neto, ms)
    razon = {"objetivo": "objetivo", "stop": "stop"}.get(salida["por"], "cierre_manual")
    if salida.get("motivo") == "sin_proteccion":
        razon = "proteccion_sin_confirmar"
    vividos = max(0, ms - _entero(p.get("llenada_ms"))) // lib_datos.PASO_MS[lib_datos.MINUTO]
    lib_registro.anotar(AMBIENTE, razon, par=p["par"], puntaje=p.get("puntaje"), ms=ms,
                        orden={"id": p["id"], "lado": "venta", "cantidad": salida["cantidad"],
                               "precio": salida["precio"], "estado": CERRADA},
                        resultado={"por": salida["por"], "precio": salida["precio"], "neto": neto,
                                   "neto_relativo": neto / pagado if pagado > 0 else None, "comision": comision,
                                   "saldo": cuerpo["saldo"], "referencia": cuerpo["referencia"], "minutos": vividos,
                                   **({"motivo": salida["motivo"]} if salida.get("motivo") else {})})
    return cuerpo


def _seguir(cli, p, filtros, com, ms, cuerpo):
    """Una posición contra Binance. Devuelve (la posición como queda o None si terminó, el cuerpo)."""
    if p["estado"] == PUESTA:
        o = cli.orden(p["par"], p["id"])
        estado = o.get("status")
        if estado not in TERMINADAS and _entero(p.get("vence_ms")) and ms >= p["vence_ms"]:
            try:
                cli.cancelar(p["par"], p["id"])
            except bp.ErrorBinance as e:
                if e.codigo not in (bp.CANCELAR_FALLO, bp.NO_EXISTE):
                    raise
            o = cli.orden(p["par"], p["id"])
            estado = o.get("status")
        if estado not in TERMINADAS and estado != "PARTIALLY_FILLED":
            return {**p, "revisado_ms": ms}, cuerpo
        if estado == "PARTIALLY_FILLED" and not (_entero(p.get("vence_ms")) and ms >= p["vence_ms"]):
            return {**p, "revisado_ms": ms}, cuerpo
        hecha, precio, cotizado = _llenado(o)
        if hecha <= 0:
            lib_registro.anotar(AMBIENTE, RAZON_VENCIDA, par=p["par"], puntaje=p.get("puntaje"), ms=ms,
                                orden=_registro_orden(p, CANCELADA if estado == "CANCELED" else VENCIDA))
            return None, cuerpo
        p = {**p, "comprada": hecha, "pagado": cotizado, "precio_medio": precio, "llenada_ms": ms}
        lib_registro.anotar(AMBIENTE, RAZON_ENTRADA[p["estrategia"]], par=p["par"], puntaje=p.get("puntaje"), ms=ms,
                            orden=_registro_orden(p, LLENADA))
        nueva, salida = _proteger(cli, p, filtros, ms)
        if salida is not None:
            return None, _cerrar_en_cuerpo(cuerpo, p, salida, com, ms)
        return nueva, cuerpo
    # ABIERTA: cómo está su protección
    lista = cli.proteccion(p["proteccion_id"])
    if lista.get("listOrderStatus") != "ALL_DONE":
        return {**p, "revisado_ms": ms, "protegida": True}, cuerpo
    patas = {sufijo: cli.orden(p["par"], f"{p['proteccion_id']}-{sufijo}") for sufijo in ("o", "s")}
    for sufijo, por in (("o", "objetivo"), ("s", "stop")):
        hecha, precio, cotizado = _llenado(patas[sufijo])
        if hecha > 0:
            return None, _cerrar_en_cuerpo(cuerpo, p, {"por": por, "precio": precio, "cantidad": hecha,
                                                       "recibido": cotizado}, com, ms)
    # La protección terminó sin que se llenara ninguna pata (la canceló alguien): se vende a mercado ahora.
    paso = _numero(filtros.get("paso"))
    moneda = filtros.get("moneda") or p["par"].replace(MONEDA_PAR, "")
    cantidad = bajar(min(p["cantidad"], libres(cli).get(moneda, 0.0)), paso)
    if cantidad > 0:
        v = cli.vender_mercado(p["par"], bp.texto(cantidad, paso), id_de(p["par"], ms, "salida"))
        hecha, precio, cotizado = _llenado(v)
        return None, _cerrar_en_cuerpo(cuerpo, p, {"por": "manual", "precio": precio, "cantidad": hecha,
                                                   "recibido": cotizado, "motivo": "sin_proteccion"}, com, ms)
    return None, cuerpo


def huerfanas_reales(cli, par, conocidas):
    """Cancela las órdenes de entrada propias que están abiertas en Binance y no tienen posición guardada (por ejemplo, si
    el equipo se apagó justo entre poner la orden y guardarla). Las protecciones (OCO) huérfanas no se tocan: protegen
    algo, y se dicen. Lo ajeno no se mira."""
    canceladas = 0
    for o in cli.abiertas(par) or []:
        cid = o.get("clientOrderId") or ""
        if not es_nuestro(cid) or o.get("orderListId", -1) not in (-1, None) or cid in conocidas:
            continue
        try:
            cli.cancelar(par, cid)
            canceladas += 1
        except bp.ErrorBinance:
            pass
    return canceladas


def revisar(ahora_ms=None, cliente=None, com=None):
    """Mira cada posición propia en Binance y deja aplicado lo que pasó. Sin conexión no toca nada y lo dice."""
    ms = _ms(ahora_ms)
    cuenta = lib_estado.cargar(AMBIENTE, ahora_ms=ms)
    if not _editable(cuenta):
        return estado(ms, cuenta=cuenta)
    cli = conectar(cliente)
    if cli is None:
        return estado(ms, cuenta=cuenta, motivo="sin_llave")
    com = lib_tamano.comisiones(com if com is not None else lib_costos.comisiones())
    pares, _ = lib_tamano.filtros_de()
    cuerpo = lib_estado.cuerpo_de(cuenta)
    vivas, motivo = [], ""
    try:
        cli.sincronizar()
        conocidas = {p["id"] for p in nuestras(cuerpo)} | {p.get("proteccion_id") for p in nuestras(cuerpo)}
        for par in {p["par"] for p in nuestras(cuerpo)} | set(lib_datos.PARES_OPERADOS):
            huerfanas_reales(cli, par, conocidas)
        for p in nuestras(cuerpo):
            try:
                nueva, cuerpo = _seguir(cli, p, pares.get(p.get("par")) or {}, com, ms, cuerpo)
            except bp.SinRed:
                nueva, motivo = p, "sin_conexion"
            except bp.ErrorBinance:
                nueva, motivo = p, "binance"
            if nueva:
                vivas.append(nueva)
    except bp.SinRed:
        return estado(ms, cuenta=cuenta, motivo="sin_conexion")
    _guardar(cuerpo, vivas, ms)
    return estado(ms, motivo=motivo)


def cerrar(identificador=None, ahora_ms=None, cliente=None, com=None):
    """Cierra a mercado una posición propia (o todas, sin id): cancela su entrada o su protección y vende lo comprado."""
    ms = _ms(ahora_ms)
    cuenta = lib_estado.cargar(AMBIENTE, ahora_ms=ms)
    cuerpo = lib_estado.cuerpo_de(cuenta)
    elegidas = [p for p in nuestras(cuerpo) if identificador is None or p.get("id") == identificador]
    if not elegidas:
        return {"hecho": False, "motivo": "sin_posicion", "cerradas": 0, "estado": estado(ms, cuenta=cuenta)}
    cli = conectar(cliente)
    if cli is None:
        return {"hecho": False, "motivo": "sin_llave", "cerradas": 0, "estado": estado(ms, cuenta=cuenta)}
    com = lib_tamano.comisiones(com if com is not None else lib_costos.comisiones())
    pares, _ = lib_tamano.filtros_de()
    quedan, cerradas, motivo = [], 0, ""
    for p in nuestras(cuerpo):
        if p not in elegidas:
            quedan.append(p)
            continue
        filtros = pares.get(p["par"]) or {}
        paso = _numero(filtros.get("paso"))
        moneda = filtros.get("moneda") or p["par"].replace(MONEDA_PAR, "")
        try:
            if p["estado"] == PUESTA:
                try:
                    cli.cancelar(p["par"], p["id"])
                except bp.ErrorBinance as e:
                    if e.codigo not in (bp.CANCELAR_FALLO, bp.NO_EXISTE):
                        raise
                hecha, precio, cotizado = _llenado(cli.orden(p["par"], p["id"]))
                p = {**p, "comprada": hecha, "pagado": cotizado}
                if hecha <= 0:
                    lib_registro.anotar(AMBIENTE, RAZON_VENCIDA, par=p["par"], puntaje=p.get("puntaje"), ms=ms,
                                        orden=_registro_orden(p, CANCELADA))
                    cerradas += 1
                    continue
            else:
                try:
                    cli.cancelar_proteccion(p["par"], p["proteccion_id"])
                except bp.ErrorBinance as e:
                    if e.codigo not in (bp.CANCELAR_FALLO, bp.NO_EXISTE):
                        raise
            cantidad = bajar(min(p["comprada"], libres(cli).get(moneda, 0.0)), paso)
            if cantidad > 0:
                v = cli.vender_mercado(p["par"], bp.texto(cantidad, paso), id_de(p["par"], ms, "salida"))
                hecha, precio, cotizado = _llenado(v)
                cuerpo = _cerrar_en_cuerpo(cuerpo, p, {"por": "manual", "precio": precio, "cantidad": hecha,
                                                       "recibido": cotizado}, com, ms)
            cerradas += 1
        except (bp.SinRed, bp.ErrorBinance) as e:
            motivo = "sin_conexion" if isinstance(e, bp.SinRed) else "binance"
            quedan.append(p)
    _guardar(cuerpo, quedan, ms)
    return {"hecho": bool(cerradas), "motivo": motivo, "cerradas": cerradas, "estado": estado(ms, motivo=motivo)}


# ── Lo que lee la pantalla y el motor ────────────────────────────────────────────────────────────────────────────────

def estado(ahora_ms=None, cuenta=None, motivo=""):
    """El conector real como está: el saldo que maneja Pilota, sus posiciones y si puede operar. Sin red."""
    ms = _ms(ahora_ms)
    c = cuenta if isinstance(cuenta, dict) else lib_estado.cargar(AMBIENTE, ahora_ms=ms)
    cuerpo = lib_estado.cuerpo_de(c)
    series = minutos_de()
    precios = {par: precio_de(v) for par, v in series.items()}
    posiciones = []
    for p in nuestras(cuerpo):
        precio = precios.get(p.get("par"))
        cantidad = _numero(p.get("cantidad"))
        gana = None if precio is None or p.get("estado") != ABIERTA else cantidad * (precio - _numero(p.get("precio")))
        posiciones.append({**p, "precio_ahora": precio, "valor": None if precio is None else cantidad * precio,
                           "ganancia": gana, "ganancia_relativa": (gana / (cantidad * p["precio"])
                                                                   if gana is not None and p.get("precio") else None),
                           "movido": False})
    abiertas = [p for p in posiciones if p.get("estado") == ABIERTA]
    motivos = []
    if not _editable(c):
        motivos.append({"codigo": "frenado" if c.get("frenado") else "sin_cuenta", "par": "", "n": 0})
    if motivo:
        motivos.append({"codigo": motivo, "par": "", "n": 0})
    if not lib_tamano.filtros_de()[1].get("calculado"):
        motivos.append({"codigo": "sin_minimos", "par": "", "n": 0})
    _, comprometido = lib_tamano.posiciones_de(cuerpo)
    return {"formato": 1, "cuando": lib_datos.iso(ms), "ambiente": AMBIENTE, "moneda": "USDT", "ficticio": False,
            "frenado": bool(c.get("frenado")), "modo": c.get("modo") or "", "saldo": _numero(cuerpo.get("saldo")),
            "referencia": _numero(cuerpo.get("referencia")), "comprometido": comprometido,
            "operaciones": _entero(cuerpo.get("operaciones")), "posiciones": posiciones, "abiertas": len(abiertas),
            "puestas": len(posiciones) - len(abiertas), "protegidas": len([p for p in abiertas if p.get("protegida")]),
            "precios": precios, "cobertura": {"cubierto": True, "sin_cobertura_min": 0},
            "ajenas": len(ajenas(cuerpo)), "motivos": motivos, "listo": not motivos}


def escribir(d):
    nucleo.escribir_json(ruta_ejecutor(), d)
    return d


def guardado():
    d = nucleo.leer_json(ruta_ejecutor(), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    return d if isinstance(d, dict) and d.get("formato") == 1 else {}
