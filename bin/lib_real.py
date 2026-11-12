#!/usr/bin/env python3
"""lib_real — conectar Binance, revisar la llave y encender o apagar el dinero de verdad. Solo biblioteca estándar. No es
una acción (la corre `bin/real.py`).

El paso a real tiene **requisitos que se ven** y no se saltan (`requisitos`):

1. **Simulaste el pasado** con tu monto (`bin/simular.py`).
2. **Probaste en vivo**: la cuenta de prueba lleva al menos `PRUEBA_DIAS` días y `PRUEBA_OPERACIONES` operaciones cerradas.
3. **La llave es segura**: puede leer y operar spot, **no puede retirar** y está **limitada a tu IP**. Una llave que puede
   retirar no se acepta nunca, aunque la persona insista: es la diferencia entre perder una operación y perder la cuenta.
4. **Los mínimos de Binance** están calculados (el capital mínimo viable).
5. **Hay fondos**: lo libre en USDT y FDUSD alcanza el capital mínimo viable.

Con todo en verde, la persona elige cuánto maneja Pilota (el presupuesto: nunca más que lo libre) y escribe la frase
`FRASE`. Recién ahí se enciende el interruptor (`lib_estado.poner_interruptor`).

Apagar no deja nada suelto: con posiciones reales abiertas no se apaga (el motor dejaría de mirarlas); para eso está
«Cerrar todo y volver a prueba» (`emergencia`), que cierra a mercado lo propio y después apaga.
"""
import os

import lib_binance_privado as bp
import lib_datos
import lib_ejecutor_real
import lib_estado
import lib_llavero
import lib_registro
import lib_tamano
import nucleo

PRUEBA_DIAS = 7
PRUEBA_OPERACIONES = 5
FRASE = "OPERAR CON DINERO REAL"
REQUISITOS = ("simulacion", "prueba", "llave", "minimos", "fondos")
MONEDAS = ("USDT", "FDUSD", "BTC", "ETH")


def ruta_conexion():
    return os.path.join(lib_datos.carpeta_mercado(), "conexion.json")


def conexion():
    d = nucleo.leer_json(ruta_conexion(), {}, maximo=256 * 1024)
    return d if isinstance(d, dict) else {}


def _ms(ahora_ms=None):
    return int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())


def _num(v, defecto=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return defecto


def revisar(ahora_ms=None, cliente=None):
    """Pregunta a Binance qué puede hacer la llave y cuánto hay libre. Escribe lo que ve (nunca la llave)."""
    ms = _ms(ahora_ms)
    cli = lib_ejecutor_real.conectar(cliente)
    base = {"formato": 1, "cuando": lib_datos.iso(ms), "cuando_ms": ms, "ok": False, "motivo": ""}
    if cli is None:
        d = {**base, "motivo": "sin_llave"}
    else:
        try:
            cli.sincronizar()
            per = cli.permisos()
            cta = cli.cuenta()
            libres = {b.get("asset"): _num(b.get("free")) for b in (cta.get("balances") or [])
                      if isinstance(b, dict) and b.get("asset") in MONEDAS}
            d = {**base, "ok": True, "lectura": bool(per.get("enableReading")),
                 "spot": bool(per.get("enableSpotAndMarginTrading")) and bool(cta.get("canTrade")),
                 "retiro": bool(per.get("enableWithdrawals")), "ip": bool(per.get("ipRestrict")),
                 "futuros": bool(per.get("enableFutures")), "margen": bool(per.get("enableMargin")),
                 "libres": {m: libres.get(m, 0.0) for m in MONEDAS}}
        except bp.ErrorBinance as e:
            d = {**base, "motivo": "llave_rechazada" if e.http in (401, 403) or e.codigo in (-2014, -2015)
                 else "binance", "codigo": e.codigo}
        except bp.SinRed:
            d = {**base, "motivo": "sin_conexion"}
    nucleo.escribir_json(ruta_conexion(), d)
    return d


def llave_segura(c):
    """Si la llave cumple: lee, opera spot, NO retira y está limitada a una IP."""
    return bool(c.get("ok") and c.get("lectura") and c.get("spot") and not c.get("retiro") and c.get("ip"))


def requisitos(ahora_ms=None, simulacion=None):
    ms = _ms(ahora_ms)
    import simular                              # acá para no cargar el backtest en cada import
    sim = simulacion if isinstance(simulacion, dict) else simular.guardado()
    prueba = lib_estado.cargar(lib_estado.PRUEBA, ahora_ms=ms)
    cuerpo = lib_estado.cuerpo_de(prueba)
    dias = max(0, ms - int(cuerpo.get("desde_ms") or ms)) // lib_datos.DIA_MS
    operaciones = int(cuerpo.get("operaciones") or 0)
    c = conexion()
    _, md = lib_tamano.filtros_de()
    minimo = _num(md.get("capital_minimo"))
    libres = c.get("libres") or {}
    fondos = _num(libres.get("USDT")) + _num(libres.get("FDUSD"))
    lista = [
        {"id": "simulacion", "cumple": bool(sim.get("listo")), "n": sim.get("monto"), "de": None},
        {"id": "prueba", "cumple": dias >= PRUEBA_DIAS and operaciones >= PRUEBA_OPERACIONES,
         "dias": dias, "operaciones": operaciones, "dias_pedidos": PRUEBA_DIAS,
         "operaciones_pedidas": PRUEBA_OPERACIONES},
        {"id": "llave", "cumple": llave_segura(c), "ok": bool(c.get("ok")), "retiro": bool(c.get("retiro")),
         "ip": bool(c.get("ip")), "spot": bool(c.get("spot")), "lectura": bool(c.get("lectura")),
         "motivo": c.get("motivo") or ""},
        {"id": "minimos", "cumple": bool(md.get("calculado")), "minimo": minimo},
        {"id": "fondos", "cumple": bool(md.get("calculado")) and c.get("ok") and fondos >= minimo > 0,
         "fondos": fondos, "minimo": minimo},
    ]
    return lista


def estado(ahora_ms=None):
    ms = _ms(ahora_ms)
    llave = lib_llavero.leer() if lib_llavero.disponible() else None
    req = requisitos(ms)
    real = lib_estado.cargar(lib_estado.REAL, ahora_ms=ms)
    cuerpo = lib_estado.cuerpo_de(real)
    return {"formato": 1, "cuando": lib_datos.iso(ms), "llavero": lib_llavero.disponible(),
            "conectado": llave is not None, "pista": lib_llavero.pista(llave[0]) if llave else "",
            "conexion": conexion(), "requisitos": req, "listo": all(r["cumple"] for r in req),
            "activo": lib_estado.activo() == lib_estado.REAL, "frase": FRASE,
            "cuenta": {"existe": not (real.get("arranque") or {}).get("nuevo"), "saldo": _num(cuerpo.get("saldo")),
                       "aportado": _num(cuerpo.get("aportado")), "operaciones": int(cuerpo.get("operaciones") or 0),
                       "posiciones": len(lib_ejecutor_real.nuestras(cuerpo))},
            "ejecutor": lib_ejecutor_real.guardado()}


def conectar(llave, secreto, ahora_ms=None, cliente=None):
    """Guarda la llave en el llavero y la revisa al tiro. Una llave que puede retirar se borra de inmediato."""
    if not (lib_llavero.valida(llave) and lib_llavero.valida(secreto)):
        return {"hecho": False, "motivo": "formato"}
    if not lib_llavero.disponible() and cliente is None:
        return {"hecho": False, "motivo": "sin_llavero"}
    if cliente is None:
        try:
            lib_llavero.guardar(llave, secreto)
        except lib_llavero.Llavero as e:
            return {"hecho": False, "motivo": str(e)}
    c = revisar(ahora_ms, cliente or bp.Privada(llave, secreto))
    if c.get("ok") and c.get("retiro"):
        if cliente is None:
            lib_llavero.borrar()
        return {"hecho": False, "motivo": "puede_retirar", "conexion": c}
    return {"hecho": bool(c.get("ok")), "motivo": c.get("motivo") or "", "conexion": c}


def desconectar(ahora_ms=None):
    if lib_estado.activo() == lib_estado.REAL:
        return {"hecho": False, "motivo": "activo"}
    lib_llavero.borrar()
    nucleo.escribir_json(ruta_conexion(), {"formato": 1, "ok": False, "motivo": "sin_llave"})
    return {"hecho": True, "motivo": ""}


def activar(presupuesto, frase, ahora_ms=None):
    """Enciende el dinero de verdad: todos los requisitos en verde, la frase escrita tal cual y un presupuesto que cabe."""
    ms = _ms(ahora_ms)
    req = requisitos(ms)
    falta = [r["id"] for r in req if not r["cumple"]]
    if falta:
        return {"hecho": False, "motivo": "requisitos", "faltan": falta}
    if (frase or "").strip().upper() != FRASE:
        return {"hecho": False, "motivo": "frase"}
    monto = _num(presupuesto, -1)
    minimo = next(r["minimo"] for r in req if r["id"] == "fondos")
    fondos = next(r["fondos"] for r in req if r["id"] == "fondos")
    if not (minimo <= monto <= fondos):
        return {"hecho": False, "motivo": "presupuesto", "minimo": minimo, "fondos": fondos}
    real = lib_estado.cargar(lib_estado.REAL, ahora_ms=ms)
    if (real.get("arranque") or {}).get("nuevo"):
        lib_estado.guardar(lib_estado.REAL, lib_estado.nuevo(lib_estado.REAL, monto, ahora_ms=ms))
        lib_registro.anotar(lib_estado.REAL, "aporte", ms=ms, resultado={"saldo": monto})
    elif real.get("frenado"):
        return {"hecho": False, "motivo": "frenado"}
    lib_estado.poner_interruptor(True, ms, presupuesto=monto)
    return {"hecho": True, "motivo": ""}


def desactivar(ahora_ms=None):
    """Vuelve a prueba. Con posiciones reales abiertas no: el motor dejaría de mirarlas."""
    ms = _ms(ahora_ms)
    cuerpo = lib_estado.cuerpo_de(lib_estado.cargar(lib_estado.REAL, ahora_ms=ms))
    if lib_ejecutor_real.nuestras(cuerpo):
        return {"hecho": False, "motivo": "con_posiciones"}
    lib_estado.poner_interruptor(False, ms)
    return {"hecho": True, "motivo": ""}


def emergencia(ahora_ms=None, cliente=None):
    """Cerrar todo y volver a prueba: cancela lo propio, vende a mercado lo comprado y apaga el dinero real. Si algo no
    se pudo cerrar (sin conexión), no apaga: lo dice, y las protecciones siguen en Binance."""
    ms = _ms(ahora_ms)
    r = lib_ejecutor_real.cerrar(None, ahora_ms=ms, cliente=cliente)
    cuerpo = lib_estado.cuerpo_de(lib_estado.cargar(lib_estado.REAL, ahora_ms=ms))
    if lib_ejecutor_real.nuestras(cuerpo):
        return {"hecho": False, "motivo": r.get("motivo") or "sin_conexion", "cerradas": r.get("cerradas", 0)}
    lib_estado.poner_interruptor(False, ms)
    return {"hecho": True, "motivo": "", "cerradas": r.get("cerradas", 0)}
