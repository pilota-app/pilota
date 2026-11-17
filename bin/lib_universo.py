#!/usr/bin/env python3
"""lib_universo — las monedas que mira el robot en prueba: ocho contra USDT. Solo biblioteca estándar. No es una acción.

BTC, ETH, BNB, SOL, XRP, ADA, TRX y DOGE: las más líquidas de Binance, con el libro más apretado (lo que más importa cuando se
entra y sale seguido). Cada perfil mira las suyas (`lib_perfiles`), y la rotación las compara todas entre sí (`lib_rotacion`).

Lo que no se negocia aquí:
- **La lista es fija y vive en el código** (`lib_datos.UNIVERSO`): ningún nombre de moneda llega de afuera.
- **Los mínimos de Binance de cada una se piden, no se suponen** (`filtros`, con `minimo_viable.filtros_de`): sin ellos no hay
  tamaño y no hay orden.
- **Contra USDT no hay conversión** (`comisiones_de`): la comisión de cambiar USDT por FDUSD solo existe en los pares de FDUSD.
- **El dinero real sigue en BTC y ETH contra FDUSD** hasta que estas monedas hayan pasado su prueba en vivo: el conector real
  no las conoce.
"""
import os

import lib_datos
import minimo_viable
import nucleo

PARES = lib_datos.ACTIVOS
#: El nombre corto: BTC para BTCUSDT y SPY para SPYBUSDT (las acciones llevan una «B» antes de USDT).
MONEDA = {p: p[:-len("BUSDT")] if p in lib_datos.ACCIONES else p[:-len("USDT")] for p in PARES}
#: Lo que se baja de cada una la primera vez: 3 años de 1 d, 4 h y 1 h, y 3 días de 1 m (después crece sola con el flujo).
DIAS = {"1d": 3300, "4h": 1095, "1h": 1095, lib_datos.MINUTO: 3}
#: Cuántos días de 1 m se guardan como mucho (los mismos de los pares de siempre).
DIAS_MINUTOS = lib_datos.DIAS_MINUTOS
ORDEN_BAJADA = (lib_datos.MINUTO, "1d", "4h", "1h")


def ruta():
    return os.path.join(lib_datos.carpeta_mercado(), "universo.json")


def guardado():
    d = nucleo.leer_json(ruta(), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    return d if isinstance(d, dict) else {}


def es_usdt(par):
    return isinstance(par, str) and par.endswith("USDT")


def comisiones_de(par, com):
    """Las comisiones de un par: contra USDT no se paga la conversión a FDUSD."""
    c = dict(com or {})
    if es_usdt(par):
        c["conversion"] = 0.0
    return c


def filtros(cliente):
    """Los mínimos vigentes de las ocho, con la hora. Lo que Binance no diga bien no se guarda."""
    salida = {}
    for s in cliente.info_pares(PARES):
        par = s.get("symbol") if isinstance(s, dict) else None
        if par not in PARES:
            continue
        try:
            salida[par] = minimo_viable.filtros_de(s, par, MONEDA[par])
        except lib_datos.Respuesta:
            continue
    return salida


def listo(par):
    """Si ya están las cuatro series de esa moneda (lo justo para mirarla)."""
    return all(lib_datos.leer_serie(par, t) for t in ORDEN_BAJADA)


def preparar(cliente, ahora_ms=None, detenido=None, avisar=None):
    """Baja lo que falte de las ocho: los mínimos y las velas, de lo más barato a lo más caro. Se puede cortar y retomar:
    cada serie se guarda entera al bajarla y la próxima vez solo se piden las velas nuevas."""
    ms = ahora_ms or cliente.ahora_ms()
    d = guardado()
    if not d.get("filtros") or ms - int(d.get("filtros_ms") or 0) > lib_datos.DIA_MS:
        f = filtros(cliente)
        if f:
            d.update(filtros=f, filtros_ms=ms)
            nucleo.escribir_json(ruta(), d)
    hechas = 0
    for t in ORDEN_BAJADA:
        for par in PARES:
            if detenido is not None and detenido():
                return hechas
            lib_datos.bajar_serie(cliente, par, t, dias=DIAS[t], ahora_ms=ms)
            hechas += 1
            if avisar:
                avisar(par, t)
    d = guardado()
    d.update(preparado_ms=ms)
    nucleo.escribir_json(ruta(), d)
    return hechas


def filtros_guardados():
    return {p: f for p, f in (guardado().get("filtros") or {}).items() if p in PARES and isinstance(f, dict)}
