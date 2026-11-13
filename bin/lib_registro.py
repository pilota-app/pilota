#!/usr/bin/env python3
"""El registro que no se borra: una línea por cada cosa que Pilota decide, con los mismos campos siempre. Solo
biblioteca estándar. No es una acción.

Dónde queda: `<datos>/registro/<ambiente>/<AAAA>.jsonl`, una línea por decisión. **Prueba y real llevan registros
separados** y ninguno de los dos se reescribe nunca: se abre con `O_APPEND`, se agrega al final y este módulo no tiene
ninguna función que borre ni corrija una línea. Una decisión que ya se anotó no se arregla: se anota la que viene.

Los **campos fijos** de cada línea (`CAMPOS`) son los de la idea —fecha, par, puntaje, razón, orden y resultado— más el
`ms` del que sale la fecha (la fecha en palabras es para leerla; las cuentas y el orden van con el número):

    {"ms": 1770732300000, "fecha": "2026-02-10T14:05:00Z", "par": "BTCFDUSD", "puntaje": 78.5,
     "razon": "entrada_ruptura", "orden": {"lado": "compra", "monto": 60.0, "precio": 94830.0, "stop": 93869.7},
     "resultado": {"por": "objetivo", "neto": 0.84, "saldo": 212.4}}

Nada de texto libre: la `razon` es uno de los códigos de `RAZONES` y `orden` y `resultado` solo aceptan las claves que
conocemos (`CAMPOS_ORDEN`, `CAMPOS_RESULTADO`) con números, booleanos o códigos cortos (`CODIGO`). Así un error de
Binance no puede entrar al registro —ni de ahí a la pantalla— convertido en texto: la interfaz traduce los códigos.

Lo que lee la pantalla pasa por `revisar`, que vuelve a armar cada línea con las mismas reglas: un archivo editado a mano
no se muestra tal cual. Una línea que quedó a medias (un corte de luz) se salta y se cuenta (`danadas`).

Para qué sirve que no se borre: el estado de la app sí se puede perder (`bin/lib_estado.py`), y entonces el registro es
el que dice que esta cuenta ya vivió algo (`cuantas`) y desde cuándo (`primera`) —las dos cosas que miran el arranque
frenado y, en su paso, los 14 días y las 100 operaciones que pide pasar a real—.
"""
import json
import math
import os
import re
import time
from collections import deque

import lib_datos
import nucleo

FORMATO = 1
#: Los dos ambientes, con todo separado: saldos, historiales, frenos y registro. Pasar de uno a otro es su propio paso.
AMBIENTES = ("prueba", "real")
#: Los campos fijos de cada línea, en este orden. No se le suman campos a una línea: lo que no quepa acá va en `orden`
#: o en `resultado`, que tienen sus claves conocidas.
CAMPOS = ("ms", "fecha", "par", "puntaje", "razon", "orden", "resultado")
#: La escala del puntaje que se anota, suelta a propósito (la misma de `lib_puntaje.PUNTAJE_MAXIMO`): el registro se
#: escribe desde todas partes y no arrastra el puntaje entero —con su backtest y sus indicadores— para anotar un número.
#: Que las dos no se separen lo revisa una prueba.
PUNTAJE_MAXIMO = 100.0
#: Cuántas líneas se le muestran a la persona por defecto (el registro completo se exporta a CSV, en su paso).
ULTIMAS = 20
#: Un código corto: nada de texto libre, nada de saltos de línea, nada que venga de Binance.
CODIGO = re.compile(r"[A-Za-z0-9_.:-]{1,64}")

#: Por qué se anota una línea. Cada paso suma las suyas acá y la pantalla las traduce; una razón que no esté en esta
#: lista no se puede anotar (un código inventado sería un texto sin traducción en pantalla).
RAZONES = (
    # El estado y el arranque (este paso)
    "arranque_frenado", "saldo_reiniciado", "aporte", "retiro", "referencia_reiniciada", "cambio_modo", "desbloqueo",
    # Lo que se propone y lo que se decide (sus pasos)
    "propuesta", "propuesta_vencida", "entrada_ruptura", "entrada_rebote", "quedarse_en_usdt", "rechazo",
    # Cómo terminó una posición (`orden.estado` dice si quedó puesta, llenada o cerrada: una salida parcial cierra la
    # mitad y la posición sigue abierta)
    "objetivo", "stop", "stop_movil", "cierre_manual", "proteccion_sin_confirmar",
    # Los frenos, cada uno con su nombre, y la pausa que pone la persona
    "freno_diario", "freno_racha", "freno_piso", "freno_piso_absoluto", "freno_comision", "freno_fdusd",
    "pausa", "reanudar",
    # La prueba en vivo con un perfil (`lib_piloto`): cuándo empezó y paró, y cada compra por partes del holding
    "perfil_empezado", "perfil_detenido", "compra_holding",
    # La rotación: pasa a la moneda que viene más fuerte (vende la que se cae del grupo y compra la que entra)
    "rotacion_compra", "rotacion_venta",
)
#: Lo que se puede decir de la orden: qué se pidió. `id` es el clientOrderId con el prefijo propio de Pilota (lo que no
#: lo tenga es de otro y Pilota no lo toca).
CAMPOS_ORDEN = ("id", "lado", "tipo", "precio", "cantidad", "monto", "stop", "objetivo", "estado", "vence_ms")
#: Lo que se puede decir del resultado: cómo terminó. `por` es el motivo del cierre y `motivo` el código de un rechazo,
#: un freno o un arranque frenado.
CAMPOS_RESULTADO = ("por", "precio", "neto", "neto_relativo", "saldo", "referencia", "comision", "minutos",
                    "supuesto", "motivo", "n", "perfil", "puesto", "fuerza")


# ── Las reglas de una línea ──────────────────────────────────────────────────────────────────────────────────────────

def ambiente_valido(ambiente):
    if ambiente not in AMBIENTES:
        raise ValueError(f"No conozco ese ambiente: {ambiente!r}")
    return ambiente


def _numero(valor, que):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ValueError(f"{que}: tiene que ser un número finito, no {valor!r}")
    return float(valor)


def _codigo(valor, que):
    if not isinstance(valor, str) or not CODIGO.fullmatch(valor):
        raise ValueError(f"{que}: solo códigos cortos, nunca texto de afuera ({valor!r})")
    return valor


def _campos(d, permitidos, que):
    """Un diccionario chico de números, booleanos y códigos: ni texto libre ni nada anidado, y solo las claves que
    conocemos. Lo que no esté en la lista es un error del código que anota, no algo que se guarde por si acaso."""
    if d is None:
        return {}
    if not isinstance(d, dict):
        raise ValueError(f"{que}: tiene que ser un objeto")
    sobran = sorted(k for k in d if k not in permitidos)
    if sobran:
        raise ValueError(f"{que}: no conozco {sobran} (las claves son {list(permitidos)})")
    limpio = {}
    for clave in permitidos:                     # siempre en el mismo orden: dos líneas iguales se leen iguales
        if clave not in d:
            continue
        valor = d[clave]
        if valor is None or isinstance(valor, bool):
            limpio[clave] = valor
        elif isinstance(valor, (int, float)):
            limpio[clave] = _numero(valor, f"{que}.{clave}")
        else:
            limpio[clave] = _codigo(valor, f"{que}.{clave}")
    return limpio


def linea(razon, par="", puntaje=None, orden=None, resultado=None, ms=None):
    """Una línea con los campos fijos, revisada. Sin `ms` es la hora de ahora (solo al anotar: leer una línea exige
    el `ms` que ya trae)."""
    if razon not in RAZONES:
        raise ValueError(f"No conozco esa razón: {razon!r}")
    if par and par not in lib_datos.CONOCIDOS:
        raise ValueError(f"No conozco ese par: {par!r}")
    cuando = int(_numero(ms, "ms")) if ms is not None else lib_datos.ahora_local_ms()
    if puntaje is not None:
        puntaje = _numero(puntaje, "puntaje")
        if not 0.0 <= puntaje <= PUNTAJE_MAXIMO:
            raise ValueError(f"puntaje: fuera de la escala de 0 a {PUNTAJE_MAXIMO:.0f} ({puntaje})")
    return {"ms": cuando, "fecha": lib_datos.iso(cuando), "par": par or "", "puntaje": puntaje, "razon": razon,
            "orden": _campos(orden, CAMPOS_ORDEN, "orden"), "resultado": _campos(resultado, CAMPOS_RESULTADO, "resultado")}


def revisar(d):
    """Una línea leída del archivo, armada de nuevo con las mismas reglas: lo que no calce no se muestra. La fecha se
    vuelve a sacar del `ms`, así una fecha editada a mano no engaña a nadie."""
    if not isinstance(d, dict):
        raise ValueError("una línea del registro tiene que ser un objeto")
    if d.get("ms") is None:
        raise ValueError("una línea del registro sin ms")
    return linea(d.get("razon"), par=d.get("par") or "", puntaje=d.get("puntaje"),
                 orden=d.get("orden"), resultado=d.get("resultado"), ms=d.get("ms"))


# ── Donde vive ───────────────────────────────────────────────────────────────────────────────────────────────────────

def carpeta(ambiente):
    return nucleo.carpeta_privada(os.path.join(nucleo.carpeta_datos(), "registro", ambiente_valido(ambiente)))


def anio_de(ms):
    return time.strftime("%Y", time.gmtime(ms / 1000))


def ruta(ambiente, ms=None):
    """Un archivo por año: el mismo corte con el que se exporta el CSV, en su paso."""
    return os.path.join(carpeta(ambiente), anio_de(ms if ms is not None else lib_datos.ahora_local_ms()) + ".jsonl")


def anios(ambiente):
    """Los años que ya tienen registro, del más viejo al más nuevo ("2026")."""
    try:
        nombres = os.listdir(carpeta(ambiente))
    except OSError:
        return []
    return sorted(n[:-6] for n in nombres if n.endswith(".jsonl") and len(n) == 10 and n[:4].isdigit())


def anotar(ambiente, razon, par="", puntaje=None, orden=None, resultado=None, ms=None):
    """Una línea al final del archivo del año, solo para la persona (0600). Lo que ya está escrito no se toca."""
    fila = linea(razon, par=par, puntaje=puntaje, orden=orden, resultado=resultado, ms=ms)
    texto = json.dumps(fila, ensure_ascii=False, separators=(",", ":")) + "\n"
    fd = os.open(ruta(ambiente, fila["ms"]), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(texto)
    return fila


# ── Leer lo que se anotó ─────────────────────────────────────────────────────────────────────────────────────────────

def _crudas(ambiente, anio):
    """Las líneas del archivo de un año, sin interpretar. Una a una: un año de registro no se carga entero."""
    try:
        with open(os.path.join(carpeta(ambiente), anio + ".jsonl"), encoding="utf-8") as f:
            for cruda in f:
                if cruda.strip():
                    yield cruda
    except OSError:
        return


def _interpretar(crudas):
    """Las líneas que se entienden, en el mismo orden, y cuántas no se entendieron."""
    filas, danadas = [], 0
    for cruda in crudas:
        try:
            filas.append(revisar(json.loads(cruda)))
        except (ValueError, TypeError):
            danadas += 1
    return filas, danadas


def leer(ambiente, anio):
    """Todas las líneas de un año, de la más vieja a la más nueva, y cuántas quedaron dañadas."""
    return _interpretar(_crudas(ambiente, anio))


def ultimas(ambiente, cuantas_=ULTIMAS):
    """Las últimas líneas, **de la más nueva a la más vieja**, y cuántas de las leídas estaban dañadas. Se van leyendo
    los años del más nuevo hacia atrás, y de cada uno solo su cola."""
    recientes, danadas = [], 0
    for anio in reversed(anios(ambiente)):
        cola = deque(_crudas(ambiente, anio), maxlen=max(0, cuantas_ - len(recientes)))
        filas, malas = _interpretar(cola)
        recientes.extend(reversed(filas))
        danadas += malas
        if len(recientes) >= cuantas_:
            break
    return recientes[:cuantas_], danadas


def primera(ambiente):
    """La primera línea que se anotó (la que dice desde cuándo vive esta cuenta), o None si el registro está vacío."""
    for anio in anios(ambiente):
        for cruda in _crudas(ambiente, anio):
            try:
                return revisar(json.loads(cruda))
            except (ValueError, TypeError):
                continue
    return None


def cuantas(ambiente):
    """Cuántas líneas lleva el registro. Es la señal de que esta cuenta ya vivió algo: si el estado de la app se
    perdió, el registro sigue ahí."""
    return sum(1 for anio in anios(ambiente) for _ in _crudas(ambiente, anio))


def resumen(ambiente, cuantas_=ULTIMAS, ahora_ms=None):
    """Lo que la pantalla muestra del registro: cuántas líneas lleva, desde cuándo, cuántos días y las últimas con sus
    campos fijos. No borra ni arregla nada: solo lee."""
    ms = ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms()
    recientes, danadas = ultimas(ambiente, cuantas_)
    inicio = primera(ambiente)
    return {"formato": FORMATO, "ambiente": ambiente_valido(ambiente), "campos": list(CAMPOS),
            "lineas": cuantas(ambiente), "anios": anios(ambiente),
            "desde": inicio["fecha"] if inicio else "", "desde_ms": inicio["ms"] if inicio else None,
            "dias": (max(0, ms - inicio["ms"]) // 86_400_000) if inicio else 0,
            "ultimas": recientes, "danadas": danadas}
