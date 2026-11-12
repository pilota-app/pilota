#!/usr/bin/env python3
"""lib_ejecutor_real — el conector real: las órdenes de verdad en Binance. Solo biblioteca estándar. No es una acción.

Tiene **el mismo contrato** que el ejecutor de prueba (`entrar`, `revisar`, `cerrar`, `estado`, `escribir`, `guardado`,
`repetida`): los tres modos y el motor no saben con qué dinero se juega, solo preguntan `lib_estado.activo()`.

Cómo vive una posición en real:

1. **Entrar.** Las mismas puertas que en prueba: la oportunidad, los frenos, el tamaño y que la protección **cabe** con
   los mínimos de Binance. Además, la llave sigue siendo segura (se revisa al menos una vez al día). Si falta FDUSD, se
   convierte lo justo desde USDT. La compra es una límite **LIMIT_MAKER** en el nivel.
2. **Llenada (aunque sea en parte) → protegida en la misma revisión.** Lo que falte por llenar se cancela y lo comprado
   recibe su OCO: el objetivo (límite) y el stop (a mercado al tocarlo). Si Binance no la acepta, se vende a mercado.
3. **Cerrada.** Cuando la OCO terminó, se suman los llenados de verdad (`myTrades`, con sus comisiones) y el saldo se mueve
   con lo recibido menos lo pagado.

Lo que no se negocia aquí:
- **Ids cortos y fijos por oportunidad** (`ids`): de la misma oportunidad salen siempre los mismos ids (entrada, conversión,
  protección, sus dos patas y la salida), con el prefijo propio y nunca más de 36 caracteres (lo que acepta Binance).
- **Se escribe antes de mandar.** Cada paso que cambia algo en Binance queda guardado **antes** del pedido (`fase`), y si la
  red se corta a mitad, la revisión siguiente **pregunta por ese id** antes de volver a mandar nada. Nunca se compra ni se
  vende dos veces por un corte.
- **La cantidad es la propia, neta.** Lo comprado se cuenta con los llenados de verdad menos la comisión cobrada en la
  moneda (BTC o ETH). Pilota nunca vende más de eso: las monedas que la persona ya tenía no se tocan.
- **Un candado** (`candado`): el motor y la pantalla no pueden tocar la cuenta real al mismo tiempo.
- **Solo lo propio.** Lo que no lleva el prefijo de Pilota no se mira, no se cancela y no se vende.
- **Ante la duda, nada nuevo.** Sin conexión, la revisión no inventa nada y lo dice. Las protecciones ya puestas siguen en
  Binance aunque el equipo se apague.
- **En real la posición sale entera.** La salida en dos mitades y el stop móvil son de prueba por ahora.
- `cliente` se puede pasar (las pruebas pasan un Binance falso); si no, se arma con la llave del llavero.
"""
import contextlib
import fcntl
import math
import os
import time

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
from lib_ejecutor_prueba import (ABIERTA, CANCELADA, CERRADA, LLENADA, PREFIJO, PUESTA, RAZON_ENTRADA, RAZON_VENCIDA,
                                 VENCIDA, cabe, es_nuestro, minutos_de, precio_de, vigencia_de)

AMBIENTE = lib_estado.REAL
CONVERSION = "FDUSDUSDT"
MONEDA_PAR = "FDUSD"
RECHAZOS = ("sin_ambiente", "sin_cuenta", "sin_opcion", "no_permitida", "repetida", "sin_minimos", "sin_llave",
            "sin_conexion", "sin_saldo", "cruzaria", "binance", "llave_insegura", "ocupado",
            *lib_tamano.RECHAZOS, *lib_frenos.RECHAZOS)
MOTIVOS = ("frenado", "sin_cuenta", "sin_minimos", "sin_llave", "sin_conexion", "binance", "llave_insegura", "ocupado")
#: Lo que Binance dice de una orden que ya no va a cambiar.
TERMINADAS = ("FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH")
#: Cada cuánto se vuelve a preguntar a Binance qué permisos tiene la llave.
REVISAR_LLAVE_MS = 24 * 60 * 60 * 1000
#: Cuántas oportunidades ya usadas se recuerdan para no repetir un id.
USADAS = 400
LARGO_MAXIMO_ID = 36
ESPERA_CANDADO = 60
TOLERANCIA = 1e-9
#: Una letra por par y por estrategia, para que los ids sean cortos.
LETRA_PAR = {"BTCFDUSD": "B", "ETHFDUSD": "E"}
LETRA_ESTRATEGIA = {"ruptura": "R", "rebote": "V"}
SUFIJOS = {"entrada": "e", "conversion": "c", "proteccion": "p", "objetivo": "po", "stop": "ps", "salida": "x"}


class Ocupado(Exception):
    """Otro proceso tiene el candado de la cuenta real."""


def ruta_ejecutor():
    return os.path.join(lib_datos.carpeta_mercado(), "ejecutor_real.json")


def ruta_conexion():
    return os.path.join(lib_datos.carpeta_mercado(), "conexion.json")


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


# ── Ids: cortos, fijos por oportunidad y con el prefijo propio ───────────────────────────────────────────────────────

def _base36(n):
    n, cifras, texto = int(n), "0123456789abcdefghijklmnopqrstuvwxyz", ""
    while True:
        n, r = divmod(n, 36)
        texto = cifras[r] + texto
        if n == 0:
            return texto


def base_de(o):
    """La raíz de los ids de una oportunidad: par, estrategia y vela. De la misma oportunidad sale siempre la misma."""
    vela = o.get("vela", o.get("vela_ms"))
    return (f"{PREFIJO}-{AMBIENTE[0]}-{LETRA_PAR.get(o.get('par'), 'X')}"
            f"{LETRA_ESTRATEGIA.get(o.get('estrategia'), 'X')}{_base36(_entero(vela))}")


def ids(base):
    return {k: f"{base}-{v}" for k, v in SUFIJOS.items()}


# ── El candado: una sola cosa a la vez sobre la cuenta real ──────────────────────────────────────────────────────────

@contextlib.contextmanager
def candado(espera=None):
    espera = ESPERA_CANDADO if espera is None else espera
    ruta = os.path.join(lib_estado.carpeta(), "real.candado")
    fd = os.open(ruta, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        limite = time.monotonic() + espera
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= limite:
                    raise Ocupado() from None
                time.sleep(0.2)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


# ── Lo de siempre ────────────────────────────────────────────────────────────────────────────────────────────────────

def nuestras(cuerpo):
    return [p for p in ((cuerpo or {}).get("posiciones") or []) if isinstance(p, dict) and es_nuestro(p.get("id"))]


def ajenas(cuerpo):
    return [p for p in ((cuerpo or {}).get("posiciones") or []) if isinstance(p, dict) and not es_nuestro(p.get("id"))]


def repetida(cuerpo, o):
    """Si esa oportunidad ya está abierta o ya se usó alguna vez en real: sus ids son fijos y no se reusan."""
    base = base_de(o)
    return any(p.get("base") == base for p in nuestras(cuerpo)) or base in ((cuerpo or {}).get("usadas") or [])


def _editable(cuenta):
    return not cuenta.get("frenado") and not (cuenta.get("arranque") or {}).get("nuevo")


def bajar(numero, paso):
    return minimo_viable.bajar_al_tick(numero, paso) if paso > 0 else numero


def conectar(cliente=None):
    if cliente is not None:
        return cliente
    llave = lib_llavero.leer()
    return bp.Privada(*llave) if llave else None


def libres(cli):
    return {b.get("asset"): _numero(b.get("free")) for b in (cli.cuenta().get("balances") or []) if isinstance(b, dict)}


def moneda_de(par, filtros=None):
    return (filtros or {}).get("moneda") or par.replace(MONEDA_PAR, "")


def _registro_orden(p, estado):
    return {"id": p["id"], "lado": lib_frenos.LADO_ENTRADA, "tipo": lib_frenos.TIPO_ENTRADA, "precio": p["precio"],
            "cantidad": p["cantidad"], "monto": p["monto"], "stop": p["stop"], "objetivo": p["objetivo"],
            "estado": estado, "vence_ms": p["vence_ms"]}


def _rechazo(o, motivo, ms, tamano_=None):
    lib_registro.anotar(AMBIENTE, "rechazo", par=o.get("par") or "", puntaje=o.get("puntaje"), ms=ms,
                        resultado={"motivo": motivo})
    return {"puesta": False, "motivo": motivo, "posicion": None, "tamano": tamano_, "proteccion": None}


def _cargar(ms):
    cuenta = lib_estado.cargar(AMBIENTE, ahora_ms=ms)
    return cuenta, lib_estado.cuerpo_de(cuenta)


def _guardar(cuerpo, posiciones, ms):
    nuevo = {**cuerpo, "cuando": lib_datos.iso(ms), "cuando_ms": ms, "posiciones": [*ajenas(cuerpo), *posiciones]}
    lib_estado.guardar(AMBIENTE, nuevo)
    return nuevo


def _con(cuerpo, p, ms):
    """El cuerpo con la posición `p` puesta (o reemplazada por id) y escrito: es la escritura adelantada."""
    otras = [x for x in nuestras(cuerpo) if x.get("id") != p["id"]]
    return _guardar(cuerpo, [*otras, p], ms)


def _sin(cuerpo, p, ms):
    return _guardar(cuerpo, [x for x in nuestras(cuerpo) if x.get("id") != p["id"]], ms)


# ── La llave: segura al conectar y segura cada día ───────────────────────────────────────────────────────────────────

def permisos_inseguros(per):
    """Lo que hace insegura una llave: poder retirar o mover fondos fuera de la cuenta spot."""
    return [k for k in ("enableWithdrawals", "enableInternalTransfer", "permitsUniversalTransfer") if per.get(k)]


def llave_al_dia(cli, ms):
    """Si la llave sigue siendo segura. Pregunta a Binance si la última revisión tiene más de un día."""
    c = nucleo.leer_json(ruta_conexion(), {}, maximo=256 * 1024)
    c = c if isinstance(c, dict) else {}
    if c.get("ok") and ms - _entero(c.get("cuando_ms")) < REVISAR_LLAVE_MS:
        return not (c.get("retiro") or c.get("transferencias"))
    per = cli.permisos()
    malos = permisos_inseguros(per)
    nucleo.escribir_json(ruta_conexion(), {**c, "ok": True, "cuando": lib_datos.iso(ms), "cuando_ms": ms,
                                           "retiro": bool(per.get("enableWithdrawals")),
                                           "transferencias": any(m != "enableWithdrawals" for m in malos),
                                           "ip": bool(per.get("ipRestrict")), "lectura": bool(per.get("enableReading")),
                                           "spot": bool(per.get("enableSpotAndMarginTrading"))})
    return not malos


# ── Entrar ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def entrar(opcion, ahora_ms=None, tamano_=None, frenos=None, com=None, calibracion=None, cliente=None):
    try:
        with candado():
            return _entrar(opcion, ahora_ms, tamano_, frenos, com, calibracion, cliente)
    except Ocupado:
        return {"puesta": False, "motivo": "ocupado", "posicion": None, "tamano": None, "proteccion": None}


def _entrar(opcion, ahora_ms, tamano_, frenos, com, calibracion, cliente):
    ms = _ms(ahora_ms)
    o = opcion if isinstance(opcion, dict) else {}
    vacio = {"puesta": False, "motivo": "", "posicion": None, "tamano": None, "proteccion": None}
    if lib_estado.activo() != AMBIENTE:
        return {**vacio, "motivo": "sin_ambiente"}
    cuenta, cuerpo = _cargar(ms)
    if (cuenta.get("arranque") or {}).get("nuevo"):
        return {**vacio, "motivo": "sin_cuenta"}
    if (o.get("estrategia") not in RAZON_ENTRADA or o.get("par") not in LETRA_PAR
            or not (_numero(o.get("entrada")) > 0 and _numero(o.get("stop")) > 0)):
        return _rechazo(o, "sin_opcion", ms)
    if not o.get("permitida"):
        return _rechazo(o, "no_permitida", ms)
    f = frenos if isinstance(frenos, dict) else lib_frenos.aplicar(AMBIENTE, ms)
    cuenta, cuerpo = _cargar(ms)
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
    base = base_de(o)
    i = ids(base)
    p = {"id": i["entrada"], "base": base, "par": o["par"], "estrategia": o.get("estrategia") or "",
         "temporalidad": o.get("temporalidad") or "", "vela_ms": _entero(o.get("vela")), "estado": PUESTA,
         "fase": "enviando", "precio": _numero(t["precio"]), "stop": _numero(t["stop"]),
         "stop_inicial": _numero(t["stop"]), "objetivo": objetivo, "cantidad": _numero(t["cantidad"]),
         "monto": _numero(t["monto"]), "mitad": None, "entera": True, "movil": False, "puntaje": o.get("puntaje"),
         "puesta_ms": ms, "vence_ms": vigencia_de(o, ms), "llenada_ms": 0, "revisado_ms": ms, "reposiciones": 0,
         "protegida": False, "comprada": 0.0, "pagado": 0.0, "vendido": 0.0, "recibido": 0.0,
         "proteccion_id": i["proteccion"]}
    p["vence"] = lib_datos.iso(p["vence_ms"]) if p["vence_ms"] else ""
    try:
        cli.sincronizar()
        if not llave_al_dia(cli, ms):
            return _rechazo(o, "llave_insegura", ms, t)
        saldo = libres(cli)
        falta = p["monto"] - saldo.get(MONEDA_PAR, 0.0)
        if falta > TOLERANCIA:
            pedir = math.ceil(falta * 1.002 * 100) / 100           # un poco más: la conversión también cobra
            if saldo.get("USDT", 0.0) + TOLERANCIA < pedir:
                return _rechazo(o, "sin_saldo", ms, t)
            cli.comprar_con(CONVERSION, bp.texto(pedir, 0.01), i["conversion"])
    except bp.ErrorBinance:
        return _rechazo(o, "binance", ms, t)
    except bp.SinRed:
        return _rechazo(o, "sin_conexion", ms, t)
    # Escritura adelantada: la posición y su oportunidad quedan guardadas ANTES de mandar la compra.
    usadas = [*((cuerpo.get("usadas") or [])[-(USADAS - 1):]), base]
    cuerpo = _con({**cuerpo, "usadas": usadas}, p, ms)
    try:
        cli.comprar_limite(p["par"], bp.texto(p["cantidad"], paso), bp.texto(p["precio"], tick), p["id"])
    except bp.SinRed:
        # No se sabe si Binance la recibió: queda guardada y la próxima revisión pregunta por su id.
        return {"puesta": True, "motivo": "sin_confirmar", "posicion": p, "tamano": t, "proteccion": c}
    except bp.ErrorBinance as e:
        _sin(cuerpo, p, ms)
        motivo = "binance"
        if e.codigo == bp.SIN_SALDO:
            try:
                motivo = "sin_saldo" if libres(cli).get(MONEDA_PAR, 0.0) + TOLERANCIA < p["monto"] else "cruzaria"
            except (bp.SinRed, bp.ErrorBinance):
                motivo = "binance"
        return _rechazo(o, motivo, ms, t)
    p = {**p, "fase": ""}
    _con(cuerpo, p, ms)
    lib_registro.anotar(AMBIENTE, RAZON_ENTRADA[p["estrategia"]], par=p["par"], puntaje=p["puntaje"], ms=ms,
                        orden=_registro_orden(p, PUESTA))
    return {"puesta": True, "motivo": "", "posicion": p, "tamano": t, "proteccion": c}


# ── Lo que dice Binance de una orden ─────────────────────────────────────────────────────────────────────────────────

def _orden_o_nada(cli, par, cid):
    try:
        return cli.orden(par, cid)
    except bp.ErrorBinance as e:
        if e.codigo == bp.NO_EXISTE:
            return None
        raise


def llenado(cli, par, orden, moneda):
    """Lo que de verdad dejó una orden, con sus llenados: la cantidad bruta, la neta (menos la comisión cobrada en la
    moneda), lo cotizado y la comisión cobrada en FDUSD."""
    if not orden or _numero(orden.get("executedQty")) <= 0:
        return {"bruta": 0.0, "neta": 0.0, "cotizado": 0.0, "comision_cotizada": 0.0}
    llenos = cli.llenados(par, orden.get("orderId")) or []
    bruta = sum(_numero(x.get("qty")) for x in llenos)
    cotizado = sum(_numero(x.get("quoteQty")) for x in llenos)
    en_moneda = sum(_numero(x.get("commission")) for x in llenos if x.get("commissionAsset") == moneda)
    en_par = sum(_numero(x.get("commission")) for x in llenos if x.get("commissionAsset") == MONEDA_PAR)
    if bruta <= 0:                       # sin llenados todavía visibles: lo que dice la orden
        bruta, cotizado = _numero(orden.get("executedQty")), _numero(orden.get("cummulativeQuoteQty"))
    return {"bruta": bruta, "neta": max(0.0, bruta - en_moneda), "cotizado": cotizado, "comision_cotizada": en_par}


def _cerrar(cuerpo, p, por, ms, motivo=""):
    """Anota el cierre de verdad y mueve el saldo: todo lo recibido menos todo lo pagado (con comisiones)."""
    neto = _numero(p.get("recibido")) - _numero(p.get("pagado"))
    cuerpo = lib_frenos.con_cierre(cuerpo, neto, ms)
    razon = "proteccion_sin_confirmar" if motivo == "sin_proteccion" else {"objetivo": "objetivo", "stop": "stop"}.get(
        por, "cierre_manual")
    vividos = max(0, ms - _entero(p.get("llenada_ms"))) // lib_datos.PASO_MS[lib_datos.MINUTO]
    vendido = _numero(p.get("vendido"))
    precio = _numero(p.get("recibido")) / vendido if vendido > 0 else 0.0
    lib_registro.anotar(AMBIENTE, razon, par=p["par"], puntaje=p.get("puntaje"), ms=ms,
                        orden={"id": p["id"], "lado": "venta", "cantidad": vendido, "precio": precio,
                               "estado": CERRADA},
                        resultado={"por": por, "precio": precio, "neto": neto,
                                   "neto_relativo": neto / p["pagado"] if _numero(p.get("pagado")) > 0 else None,
                                   "saldo": cuerpo["saldo"], "referencia": cuerpo["referencia"], "minutos": vividos,
                                   **({"motivo": motivo} if motivo else {})})
    return _sin(cuerpo, p, ms)


def _vender(cli, cuerpo, p, filtros, ms, por, motivo=""):
    """Vende a mercado lo propio que quede y cierra. Idempotente: si la venta ya existe, se usa esa."""
    i, moneda = ids(p["base"]), moneda_de(p["par"], filtros)
    p = {**p, "fase": "vendiendo", "por": por, "motivo_cierre": motivo}
    cuerpo = _con(cuerpo, p, ms)
    o = _orden_o_nada(cli, p["par"], i["salida"])
    if o is None:
        falta = _numero(p.get("comprada")) - _numero(p.get("vendido"))
        cantidad = bajar(min(falta, libres(cli).get(moneda, 0.0)), _numero(filtros.get("paso")))
        if cantidad > 0:
            o = cli.vender_mercado(p["par"], bp.texto(cantidad, _numero(filtros.get("paso"))), i["salida"])
    if o is not None:
        v = llenado(cli, p["par"], o, moneda)
        p = {**p, "vendido": _numero(p.get("vendido")) + v["bruta"],
             "recibido": _numero(p.get("recibido")) + v["cotizado"] - v["comision_cotizada"]}
    return _cerrar(cuerpo, p, por, ms, motivo)


def _patas(cli, p, moneda):
    """Lo que dejaron las dos patas de la protección: lo vendido, lo recibido y cuál se llenó."""
    i = ids(p["base"])
    total, recibido, por = 0.0, 0.0, ""
    for que, cid in (("objetivo", i["objetivo"]), ("stop", i["stop"])):
        o = _orden_o_nada(cli, p["par"], cid)
        v = llenado(cli, p["par"], o, moneda)
        if v["bruta"] > 0:
            total += v["bruta"]
            recibido += v["cotizado"] - v["comision_cotizada"]
            por = por or que
    return total, recibido, por


def _proteger(cli, cuerpo, p, filtros, ms):
    """Pone la OCO de lo comprado. Idempotente: si ya existe con ese id, se usa. Si Binance no la acepta, se vende."""
    i, moneda = ids(p["base"]), moneda_de(p["par"], filtros)
    paso, tick = _numero(filtros.get("paso")), _numero(filtros.get("tick"))
    p = {**p, "fase": "protegiendo"}
    cuerpo = _con(cuerpo, p, ms)
    try:
        lista = cli.proteccion(i["proteccion"])
    except bp.ErrorBinance as e:
        if e.codigo != bp.NO_EXISTE:
            raise
        lista = None
    if lista and lista.get("listOrderStatus") != "REJECT":
        # Ya estaba puesta (se cortó la red justo después): su cantidad quedó guardada antes de mandarla.
        return _con(cuerpo, {**p, "fase": "", "estado": ABIERTA, "protegida": True}, ms)
    cantidad = bajar(min(_numero(p.get("comprada")), libres(cli).get(moneda, 0.0)), paso)
    if lista is None and cabe(filtros, p["precio"], p["stop"], p["objetivo"], cantidad, False)["cabe"]:
        p = {**p, "cantidad": cantidad}
        cuerpo = _con(cuerpo, p, ms)              # escritura adelantada: la cantidad protegida, antes de mandarla
        try:
            cli.proteger(p["par"], bp.texto(cantidad, paso), bp.texto(p["objetivo"], tick), bp.texto(p["stop"], tick),
                         i["proteccion"])
            return _con(cuerpo, {**p, "fase": "", "estado": ABIERTA, "cantidad": cantidad, "protegida": True}, ms)
        except bp.ErrorBinance:
            pass
    # Sin protección no se queda: se vende a mercado lo que se compró.
    return _vender(cli, cuerpo, p, filtros, ms, "manual", "sin_proteccion")


def _seguir(cli, cuerpo, p, filtros, ms):
    """Una posición contra Binance. Devuelve el cuerpo ya escrito."""
    moneda = moneda_de(p["par"], filtros)
    if p.get("fase") == "vendiendo":
        return _vender(cli, cuerpo, p, filtros, ms, p.get("por") or "manual", p.get("motivo_cierre") or "")
    if p.get("fase") == "protegiendo":
        return _proteger(cli, cuerpo, p, filtros, ms)
    if p["estado"] == PUESTA:
        o = _orden_o_nada(cli, p["par"], p["id"])
        if o is None:
            # Nunca llegó a Binance (se cortó al mandarla), o Binance ya archivó una orden cancelada sin llenar.
            if p.get("fase") != "enviando":
                lib_registro.anotar(AMBIENTE, RAZON_VENCIDA, par=p["par"], puntaje=p.get("puntaje"), ms=ms,
                                    orden=_registro_orden(p, VENCIDA))
            return _sin(cuerpo, p, ms)
        if p.get("fase") == "enviando":
            p = {**p, "fase": ""}
            cuerpo = _con(cuerpo, p, ms)
            lib_registro.anotar(AMBIENTE, RAZON_ENTRADA[p["estrategia"]], par=p["par"], puntaje=p.get("puntaje"),
                                ms=ms, orden=_registro_orden(p, PUESTA))
        estado = o.get("status")
        vencida = bool(_entero(p.get("vence_ms")) and ms >= p["vence_ms"])
        # Llenada en parte: se cancela lo que falta y se protege lo comprado AHORA, no al vencer.
        if estado == "NEW" and not vencida:
            return _con(cuerpo, {**p, "revisado_ms": ms}, ms)
        if estado in ("NEW", "PARTIALLY_FILLED"):
            try:
                cli.cancelar(p["par"], p["id"])
            except bp.ErrorBinance as e:
                if e.codigo not in (bp.CANCELAR_FALLO, bp.NO_EXISTE):
                    raise
            o = _orden_o_nada(cli, p["par"], p["id"]) or o
        v = llenado(cli, p["par"], o, moneda)
        if v["neta"] <= 0:
            lib_registro.anotar(AMBIENTE, RAZON_VENCIDA, par=p["par"], puntaje=p.get("puntaje"), ms=ms,
                                orden=_registro_orden(p, CANCELADA if o.get("status") == "CANCELED" else VENCIDA))
            return _sin(cuerpo, p, ms)
        p = {**p, "comprada": v["neta"], "pagado": v["cotizado"] + v["comision_cotizada"], "llenada_ms": ms}
        lib_registro.anotar(AMBIENTE, RAZON_ENTRADA[p["estrategia"]], par=p["par"], puntaje=p.get("puntaje"), ms=ms,
                            orden=_registro_orden(p, LLENADA))
        return _proteger(cli, cuerpo, p, filtros, ms)
    # ABIERTA: cómo está su protección
    try:
        lista = cli.proteccion(p["proteccion_id"])
    except bp.ErrorBinance as e:
        if e.codigo != bp.NO_EXISTE:
            raise
        lista = {"listOrderStatus": "REJECT"}
    if lista.get("listOrderStatus") == "EXECUTING":
        return _con(cuerpo, {**p, "revisado_ms": ms, "protegida": True}, ms)
    vendido, recibido, por = _patas(cli, p, moneda)
    p = {**p, "vendido": vendido, "recibido": recibido, "protegida": False}
    if vendido >= _numero(p.get("cantidad")) - max(_numero(filtros.get("paso")), TOLERANCIA):
        return _cerrar(cuerpo, p, por or "manual", ms)
    # La protección terminó sin vender todo (rechazada, o la canceló alguien): se vende el resto ahora.
    return _vender(cli, cuerpo, p, filtros, ms, por or "manual", "sin_proteccion")


def huerfanas_reales(cli, par, conocidas):
    """Cancela las entradas propias abiertas en Binance que no tienen posición guardada. Con la escritura adelantada no
    debería haber ninguna: si aparece una, no se compra encima de ella. Las protecciones (OCO) no se tocan."""
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
    try:
        with candado():
            return _revisar(ms, cliente)
    except Ocupado:
        return estado(ms, motivo="ocupado")


def _revisar(ms, cliente):
    cuenta, cuerpo = _cargar(ms)
    if not _editable(cuenta):
        return estado(ms, cuenta=cuenta)
    cli = conectar(cliente)
    if cli is None:
        return estado(ms, cuenta=cuenta, motivo="sin_llave" if nuestras(cuerpo) else "")
    pares, _ = lib_tamano.filtros_de()
    motivo = ""
    try:
        cli.sincronizar()
        conocidas = {p["id"] for p in nuestras(cuerpo)}
        for par in lib_datos.PARES_OPERADOS:
            huerfanas_reales(cli, par, conocidas)
    except bp.SinRed:
        return estado(ms, cuenta=cuenta, motivo="sin_conexion")
    except bp.ErrorBinance:
        motivo = "binance"
    for p in nuestras(cuerpo):
        try:
            _, cuerpo = _cargar(ms)
            cuerpo = _seguir(cli, cuerpo, p, pares.get(p.get("par")) or {}, ms)
        except bp.SinRed:
            motivo = "sin_conexion"
        except bp.ErrorBinance:
            motivo = "binance"
    return estado(ms, motivo=motivo)


def cerrar(identificador=None, ahora_ms=None, cliente=None, com=None):
    """Cierra a mercado una posición propia (o todas, sin id): cancela su entrada o su protección y vende lo propio."""
    ms = _ms(ahora_ms)
    try:
        with candado():
            return _cerrar_todo(identificador, ms, cliente)
    except Ocupado:
        return {"hecho": False, "motivo": "ocupado", "cerradas": 0, "estado": estado(ms)}


def _cerrar_todo(identificador, ms, cliente):
    cuenta, cuerpo = _cargar(ms)
    elegidas = [p for p in nuestras(cuerpo) if identificador is None or p.get("id") == identificador]
    if not elegidas:
        return {"hecho": False, "motivo": "sin_posicion", "cerradas": 0, "estado": estado(ms, cuenta=cuenta)}
    cli = conectar(cliente)
    if cli is None:
        return {"hecho": False, "motivo": "sin_llave", "cerradas": 0, "estado": estado(ms, cuenta=cuenta)}
    pares, _ = lib_tamano.filtros_de()
    cerradas, motivo = 0, ""
    for p in elegidas:
        filtros = pares.get(p["par"]) or {}
        moneda = moneda_de(p["par"], filtros)
        try:
            _, cuerpo = _cargar(ms)
            if p.get("fase") == "vendiendo":
                cuerpo = _vender(cli, cuerpo, p, filtros, ms, "manual")
            elif p["estado"] == PUESTA and p.get("fase") != "protegiendo":
                try:
                    cli.cancelar(p["par"], p["id"])
                except bp.ErrorBinance as e:
                    if e.codigo not in (bp.CANCELAR_FALLO, bp.NO_EXISTE):
                        raise
                o = _orden_o_nada(cli, p["par"], p["id"])
                v = llenado(cli, p["par"], o, moneda)
                if v["neta"] <= 0:
                    lib_registro.anotar(AMBIENTE, RAZON_VENCIDA, par=p["par"], puntaje=p.get("puntaje"), ms=ms,
                                        orden=_registro_orden(p, CANCELADA))
                    cuerpo = _sin(cuerpo, p, ms)
                else:
                    p = {**p, "comprada": v["neta"], "pagado": v["cotizado"] + v["comision_cotizada"], "llenada_ms": ms}
                    cuerpo = _vender(cli, cuerpo, p, filtros, ms, "manual")
            else:
                if p.get("fase") == "protegiendo" or p["estado"] == ABIERTA:
                    try:
                        cli.cancelar_proteccion(p["par"], p["proteccion_id"])
                    except bp.ErrorBinance as e:
                        if e.codigo not in (bp.CANCELAR_FALLO, bp.NO_EXISTE):
                            raise
                vendido, recibido, _ = _patas(cli, p, moneda)
                cuerpo = _vender(cli, cuerpo, {**p, "vendido": vendido, "recibido": recibido}, filtros, ms, "manual")
            cerradas += 1
        except (bp.SinRed, bp.ErrorBinance) as e:
            motivo = "sin_conexion" if isinstance(e, bp.SinRed) else "binance"
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
