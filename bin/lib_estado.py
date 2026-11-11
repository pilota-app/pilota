#!/usr/bin/env python3
"""El estado de la app en un archivo con huella, separado para prueba y para real. Solo biblioteca estándar. No es una
acción.

Dónde queda: `<datos>/estado/<ambiente>.json`, con esta forma:

    {"formato": 1, "huella": "<sha256>", "estado": {…el cuerpo…}}

El **cuerpo** es lo que Pilota necesita saber de sí misma entre una vuelta y la siguiente: en qué modo está (manual,
semiautomático o automático), su saldo en USDT, el capital de referencia, el libro de aportes, las posiciones —con sus
órdenes puestas y su protección: las escribe el ejecutor de prueba (y el conector real, en su paso)— y los
contadores que miran los frenos. La **huella** es el sha256 del cuerpo en JSON canónico con el id de la app y el
ambiente adentro (`huella`): no es una firma contra alguien que quiera engañar a su propio computador —la llave estaría
al lado—, es para cachar el archivo perdido, pisado, copiado del otro ambiente o escrito a medias.

**Si el archivo falta, la huella no cuadra o la fecha es futura, Pilota arranca frenada en modo manual** (`cargar`): el
estado que vuelve tiene el modo manual, `frenado` en verdadero, el motivo en código y los números en cero —de un
archivo del que no se puede fiar nadie no se calcula un tamaño de operación—. Lo que decía el archivo viaja aparte, en
`leido`, solo para mostrarlo. Y el archivo sospechoso **no se pisa**: la evidencia se guarda y el arranque frenado queda
anotado en el registro que no se borra (`bin/lib_registro.py`).

La primera vez es otra cosa: sin archivo y sin registro no hay nada que perder, así que no es un freno
(`arranque.motivo` dice `primera_vez`) y el estado nace cuando la persona elige el monto de prueba (`reiniciar`).

Reglas que no se cambian sin pensarlo dos veces:
- **Prueba y real están separados** en todo: dos archivos, dos registros, dos juegos de frenos. El ambiente va dentro de
  la huella, así que el estado de prueba copiado sobre el de real no cuadra.
- **El capital de referencia es el saldo más alto alcanzado**: sube con las ganancias y nunca baja con las pérdidas. Lo
  único que lo mueve hacia abajo es un retiro, y los depósitos y retiros van **explícitos** en su libro (`aportes`,
  `aportado`): un depósito no es una ganancia ni un retiro una pérdida, que es justo lo que mira el piso de los frenos.
- **El saldo de prueba se reinicia con una sola confirmación y al tiro**, y queda en el registro (`reiniciar`). La
  espera de 24 h es solo para el desbloqueo del piso en real, en su paso. El saldo real no se reinicia nunca: lo dice
  Binance al reconciliar.
- **Los días que lleva la cuenta los cuenta el registro, no este archivo**: el estado se puede perder, el registro no.
- **El estado de los frenos vive acá**, dentro de la huella: los contadores (`racha`, `dia`, `desbloqueos`), la pausa
  (`pausado`), el desbloqueo pedido (`desbloqueo`) y los frenos que ya quedaron anotados (`frenos`). Acá nacen en cero
  y los mueve `bin/lib_frenos.py`: este módulo solo revisa que tengan la forma que corresponde.
"""
import hashlib
import hmac
import json
import math
import os

import lib_datos
import lib_registro
import minimo_viable
import nucleo

FORMATO = 1
#: Los dos ambientes (los de `lib_registro`: son los mismos en todas partes).
AMBIENTES = lib_registro.AMBIENTES
PRUEBA, REAL = AMBIENTES
#: Los tres modos. El de partida y el de después de cualquier freno es el manual: Pilota propone y la persona dice sí.
MODOS = ("manual", "semiautomatico", "automatico")
MODO_FRENADO = "manual"
#: El monto de prueba sugerido en USDT (la idea: 200) y el tope de lo que Pilota se cree como capital.
SALDO_SUGERIDO = 200.0
SALDO_MAXIMO = float(minimo_viable.CAPITAL_MAXIMO)
#: Cuánto se le perdona al reloj antes de decir que la fecha es futura: el del computador no es exacto y cambiar de huso
#: no es un freno. Más que esto ya no es el reloj: es un archivo que no es de ahora.
TOLERANCIA_FUTURO_MS = 5 * 60 * 1000
#: Lo más grande que puede ser el archivo de estado: con más que esto, algo pasó.
MAXIMO_ARCHIVO = 4 * 1024 * 1024

#: Por qué se arranca frenado. Los tres primeros son los de la idea; los otros dos son el mismo problema visto de otra
#: forma. La pantalla los traduce (nunca se muestra el código pelado).
SIN_ESTADO = "sin_estado"                  # el archivo no está y el registro dice que esta cuenta ya vivió algo
HUELLA_NO_CUADRA = "huella_no_cuadra"      # el cuerpo no es el que se firmó
FECHA_FUTURA = "fecha_futura"              # el archivo dice que es de más adelante que ahora
FORMATO_DESCONOCIDO = "formato_desconocido"  # no se pudo leer: quedó a medias o no tiene la forma que conocemos
OTRO_AMBIENTE = "otro_ambiente"            # el cuerpo dice que es del otro ambiente
MOTIVOS_FRENADO = (SIN_ESTADO, HUELLA_NO_CUADRA, FECHA_FUTURA, FORMATO_DESCONOCIDO, OTRO_AMBIENTE)
#: Y el motivo que no es un freno: la primera vez, cuando no hay nada que perder.
PRIMERA_VEZ = "primera_vez"
#: Las dos cosas que puede ser un aporte, siempre explícitas.
DEPOSITO, RETIRO = "deposito", "retiro"
#: Los campos del cuerpo, los únicos que se guardan: lo que le agrega el arranque (`frenado`, `arranque`, `leido`) no
#: entra al archivo ni a la huella. `cuerpo_de` deja un estado leído listo para volver a guardarse.
CAMPOS = ("formato", "ambiente", "cuando", "cuando_ms", "desde", "desde_ms", "modo", "saldo", "referencia", "aportado",
          "aportes", "posiciones", "operaciones", "racha", "dia", "desbloqueos", "desbloqueo", "pausado", "frenos",
          "reinicios")
#: Lo más largo que puede ser la lista de frenos anotados: son códigos cortos de `lib_frenos.FRENOS`, no texto.
FRENOS_MAXIMOS = 16


# ── Dónde vive y cómo se firma ───────────────────────────────────────────────────────────────────────────────────────

def carpeta():
    return nucleo.carpeta_privada(os.path.join(nucleo.carpeta_datos(), "estado"))


def ruta(ambiente):
    return os.path.join(carpeta(), lib_registro.ambiente_valido(ambiente) + ".json")


def huella(cuerpo, ambiente=None):
    """La huella del cuerpo: sha256 del JSON canónico (claves ordenadas, sin espacios) con el id de la app, el formato
    y el ambiente **del archivo** delante. Que el ambiente vaya adentro es lo que hace que un estado de prueba copiado
    sobre el de real no cuadre: son dos cuentas distintas y no se confunden nunca."""
    texto = json.dumps(cuerpo, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    semilla = f"{nucleo.app()['id']}:{FORMATO}:{ambiente or cuerpo.get('ambiente', '')}:"
    return hashlib.sha256((semilla + texto).encode("utf-8")).hexdigest()


# ── El cuerpo ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _monto(valor, que="monto", negativo=False):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ValueError(f"{que}: tiene que ser un número finito, no {valor!r}")
    v = float(valor)
    if not negativo and v < 0:
        raise ValueError(f"{que}: no puede ser negativo ({v})")
    if abs(v) > SALDO_MAXIMO:
        raise ValueError(f"{que}: más de {SALDO_MAXIMO:.0f} USDT no me lo creo ({v})")
    return v


def nuevo(ambiente, saldo=0.0, ahora_ms=None):
    """El estado de una cuenta que recién empieza: en manual, sin posiciones y con los contadores en cero. Con un saldo
    se anota como el primer aporte, para que el capital de referencia nazca del libro y no de la nada."""
    lib_registro.ambiente_valido(ambiente)
    ms = int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())
    cuerpo = {"formato": FORMATO, "ambiente": ambiente, "cuando": lib_datos.iso(ms), "cuando_ms": ms,
              "desde": lib_datos.iso(ms), "desde_ms": ms, "modo": MODO_FRENADO,
              "saldo": 0.0, "referencia": 0.0, "aportado": 0.0, "aportes": [], "posiciones": [], "operaciones": 0,
              # El estado de los frenos (`bin/lib_frenos.py`): nace en cero, sin pausa y sin ningún freno puesto.
              "racha": 0, "dia": {"fecha": "", "inicio": 0.0, "aportado": 0.0}, "desbloqueos": 0, "desbloqueo": {},
              "pausado": False, "frenos": [], "reinicios": 0}
    return con_aporte(cuerpo, saldo, ahora_ms=ms) if _monto(saldo, "saldo") > 0 else cuerpo


def con_aporte(cuerpo, monto, ahora_ms=None):
    """Un depósito (monto positivo) o un retiro (negativo), anotado en el libro propio. El capital de referencia se
    mueve con el aporte: así un depósito no cuenta como ganancia ni un retiro como pérdida."""
    ms = int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())
    monto = _monto(monto, "aporte", negativo=True)
    if cuerpo["saldo"] + monto < 0:
        raise ValueError(f"no se puede retirar {-monto} de un saldo de {cuerpo['saldo']}")
    saldo = cuerpo["saldo"] + monto
    aporte = {"ms": ms, "cuando": lib_datos.iso(ms), "que": DEPOSITO if monto >= 0 else RETIRO, "monto": abs(monto)}
    return {**cuerpo, "cuando": lib_datos.iso(ms), "cuando_ms": ms, "saldo": saldo,
            "aportado": max(0.0, cuerpo["aportado"] + monto),
            "referencia": max(max(0.0, cuerpo["referencia"] + monto), saldo),
            "aportes": [*cuerpo["aportes"], aporte]}


def con_saldo(cuerpo, saldo, ahora_ms=None):
    """El saldo de ahora. El capital de referencia es el saldo más alto que se haya alcanzado: sube con las ganancias y
    nunca baja con las pérdidas."""
    ms = int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())
    saldo = _monto(saldo, "saldo")
    return {**cuerpo, "cuando": lib_datos.iso(ms), "cuando_ms": ms, "saldo": saldo,
            "referencia": max(cuerpo["referencia"], saldo)}


def con_modo(cuerpo, modo, ahora_ms=None):
    """El modo en el que queda. Lo usan los tres modos y los frenos, cada uno en su paso: acá solo se revisa que sea
    uno de los tres."""
    if modo not in MODOS:
        raise ValueError(f"No conozco ese modo: {modo!r}")
    ms = int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())
    return {**cuerpo, "cuando": lib_datos.iso(ms), "cuando_ms": ms, "modo": modo}


def _entero(valor, defecto=0):
    return int(valor) if isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor) else defecto


def _numero(valor, defecto=0.0):
    return float(valor) if isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor) else defecto


def sanear(cuerpo, ambiente, ahora_ms=None):
    """El cuerpo leído del archivo, con cada campo en su tipo y lo que falte en su valor de partida. Pasa recién después
    de que la huella cuadra (el archivo es el nuestro), así que acá no se desconfía de nadie: se completa."""
    base = nuevo(ambiente, ahora_ms=ahora_ms)
    aportes = [{"ms": _entero(a.get("ms")), "cuando": str(a.get("cuando", ""))[:32],
                "que": a.get("que") if a.get("que") in (DEPOSITO, RETIRO) else DEPOSITO,
                "monto": _numero(a.get("monto"))}
               for a in cuerpo.get("aportes", []) if isinstance(a, dict)]
    dia = cuerpo.get("dia") if isinstance(cuerpo.get("dia"), dict) else {}
    des = cuerpo.get("desbloqueo") if isinstance(cuerpo.get("desbloqueo"), dict) else {}
    frenos = [f for f in cuerpo.get("frenos", []) if isinstance(f, str) and lib_registro.CODIGO.fullmatch(f)]
    return {**base, "cuando": str(cuerpo.get("cuando", base["cuando"]))[:32], "cuando_ms": _entero(cuerpo.get("cuando_ms")),
            "desde": str(cuerpo.get("desde", base["desde"]))[:32], "desde_ms": _entero(cuerpo.get("desde_ms")),
            "modo": cuerpo.get("modo") if cuerpo.get("modo") in MODOS else MODO_FRENADO,
            "saldo": _numero(cuerpo.get("saldo")), "referencia": _numero(cuerpo.get("referencia")),
            "aportado": _numero(cuerpo.get("aportado")), "aportes": aportes,
            "posiciones": [p for p in cuerpo.get("posiciones", []) if isinstance(p, dict)],
            "operaciones": _entero(cuerpo.get("operaciones")), "racha": _entero(cuerpo.get("racha")),
            "dia": {"fecha": str(dia.get("fecha", ""))[:10], "inicio": _numero(dia.get("inicio")),
                    "aportado": _numero(dia.get("aportado"))},
            "desbloqueos": _entero(cuerpo.get("desbloqueos")),
            "desbloqueo": {"n": _entero(des.get("n")), "pedido_ms": _entero(des.get("pedido_ms")),
                           "hasta_ms": _entero(des.get("hasta_ms"))} if des else {},
            "pausado": bool(cuerpo.get("pausado")), "frenos": frenos[:FRENOS_MAXIMOS],
            "reinicios": _entero(cuerpo.get("reinicios"))}


def cuerpo_de(cuenta):
    """El cuerpo de un estado leído, listo para volver a guardarse: solo los campos del archivo (`CAMPOS`), sin lo que
    le agrega el arranque. Lo usan los frenos y, en sus pasos, el ejecutor y el conector real."""
    return {c: cuenta[c] for c in CAMPOS if c in cuenta}


def legible(cuerpo):
    """Lo poco del archivo sospechoso que se puede mostrar sin creerle: los montos solo si son números y el modo solo si
    es uno de los tres. Nada de texto que venga del archivo."""
    if not isinstance(cuerpo, dict):
        return {}
    numeros = {c: (_numero(cuerpo.get(c)) if isinstance(cuerpo.get(c), (int, float))
                   and not isinstance(cuerpo.get(c), bool) else None) for c in ("saldo", "referencia", "aportado")}
    posiciones = cuerpo.get("posiciones")
    return {**numeros, "modo": cuerpo.get("modo") if cuerpo.get("modo") in MODOS else "",
            "cuando_ms": _entero(cuerpo.get("cuando_ms"), None),
            "posiciones": len([p for p in posiciones if isinstance(p, dict)]) if isinstance(posiciones, list) else None}


# ── Guardar y cargar ─────────────────────────────────────────────────────────────────────────────────────────────────

def guardar(ambiente, cuerpo):
    """Deja el estado escrito con su huella, de una sola vez (`nucleo.escribir_atomico`: nunca a medias). El ambiente
    del cuerpo es el del archivo, pase lo que pase."""
    cuerpo = {**cuerpo, "formato": FORMATO, "ambiente": lib_registro.ambiente_valido(ambiente)}
    nucleo.escribir_json(ruta(ambiente), {"formato": FORMATO, "huella": huella(cuerpo, ambiente), "estado": cuerpo})
    return cuerpo


def _arranque(cuerpo, motivo, primera, leido, ms):
    """El estado como lo ve el resto de Pilota: con `frenado` y el motivo arriba, el detalle del arranque al lado y, si
    el archivo no era de fiar, lo que decía en `leido` (solo para mostrarlo)."""
    frenado = motivo in MOTIVOS_FRENADO
    return {**cuerpo, "modo": MODO_FRENADO if frenado else cuerpo["modo"], "frenado": frenado,
            "motivo": motivo if frenado else "",
            "arranque": {"cuando": lib_datos.iso(ms), "frenado": frenado, "nuevo": primera,
                         "motivo": PRIMERA_VEZ if primera else motivo},
            "leido": leido}


def cargar(ambiente, ahora_ms=None):
    """El estado guardado de un ambiente, con su arranque. Si el archivo falta, la huella no cuadra o la fecha es
    futura, lo que vuelve es el estado frenado en manual y con los números en cero: nadie calcula un tamaño con
    números de los que no se puede fiar. No escribe nada (ni arregla el archivo: la evidencia se guarda)."""
    lib_registro.ambiente_valido(ambiente)
    ms = int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())
    en_cero = nuevo(ambiente, ahora_ms=ms)   # lo que se devuelve cuando el archivo no es de fiar: ningún número suyo
    archivo = ruta(ambiente)
    d = nucleo.leer_json(archivo, None, maximo=MAXIMO_ARCHIVO)
    if not isinstance(d, dict):
        if os.path.exists(archivo):
            return _arranque(en_cero, FORMATO_DESCONOCIDO, False, {}, ms)
        # Sin archivo: si el registro está vacío, es la primera vez y no hay nada que perder. Si tiene líneas, esta
        # cuenta ya vivió algo y el estado se perdió: eso sí es un freno.
        if lib_registro.cuantas(ambiente):
            return _arranque(en_cero, SIN_ESTADO, False, {}, ms)
        return _arranque(en_cero, "", True, {}, ms)
    cuerpo = d.get("estado")
    if d.get("formato") != FORMATO or not isinstance(cuerpo, dict):
        return _arranque(en_cero, FORMATO_DESCONOCIDO, False, legible(cuerpo), ms)
    if not isinstance(d.get("huella"), str) or not hmac.compare_digest(d["huella"], huella(cuerpo, ambiente)):
        return _arranque(en_cero, HUELLA_NO_CUADRA, False, legible(cuerpo), ms)
    if cuerpo.get("ambiente") != ambiente:   # por si acaso: con la huella del archivo esto ya no debería pasar
        return _arranque(en_cero, OTRO_AMBIENTE, False, legible(cuerpo), ms)
    cuando = cuerpo.get("cuando_ms")
    if not isinstance(cuando, (int, float)) or isinstance(cuando, bool) or not math.isfinite(cuando) \
            or cuando > ms + TOLERANCIA_FUTURO_MS:
        return _arranque(en_cero, FECHA_FUTURA, False, legible(cuerpo), ms)
    return _arranque(sanear(cuerpo, ambiente, ahora_ms=ms), "", False, {}, ms)


# ── Lo que hace la app ───────────────────────────────────────────────────────────────────────────────────────────────

def activo():
    """Con qué dinero se está jugando. Hoy siempre prueba: pasar a real es su propio paso y hasta que esté cerrado el
    interruptor no existe (la banda de la pantalla sale de acá)."""
    return PRUEBA


def arrancar(ahora_ms=None):
    """Lo que corre al abrir la app: carga los dos ambientes y, si alguno arrancó frenado, lo deja anotado en el
    registro que no se borra (una línea por arranque). No pisa el archivo sospechoso ni inventa un estado nuevo."""
    ms = int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())
    for ambiente in AMBIENTES:
        cuenta = cargar(ambiente, ahora_ms=ms)
        if cuenta["frenado"]:
            lib_registro.anotar(ambiente, "arranque_frenado", resultado={"motivo": cuenta["motivo"]}, ms=ms)
    return estado(ahora_ms=ms)


def reiniciar(saldo, ahora_ms=None):
    """Reinicia el saldo de prueba: una sola confirmación, al tiro, y queda en el registro. El saldo real no se
    reinicia nunca (lo dice Binance al reconciliar), así que esto es solo de prueba."""
    ms = int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())
    saldo = _monto(saldo, "saldo")
    antes = cargar(PRUEBA, ahora_ms=ms)
    cuerpo = nuevo(PRUEBA, saldo, ahora_ms=ms)
    cuerpo["reinicios"] = antes["reinicios"] + 1
    guardar(PRUEBA, cuerpo)
    lib_registro.anotar(PRUEBA, "saldo_reiniciado", ms=ms,
                        resultado={"saldo": cuerpo["saldo"], "referencia": cuerpo["referencia"],
                                   "n": cuerpo["reinicios"]})
    return estado(ahora_ms=ms)


def parametros():
    return {"ambientes": list(AMBIENTES), "modos": list(MODOS), "modo_frenado": MODO_FRENADO,
            "saldo_sugerido": SALDO_SUGERIDO, "saldo_maximo": SALDO_MAXIMO,
            "tolerancia_futuro_min": TOLERANCIA_FUTURO_MS // 60_000, "motivos": list(MOTIVOS_FRENADO),
            "campos": list(lib_registro.CAMPOS), "razones": list(lib_registro.RAZONES)}


def estado(ahora_ms=None):
    """Las dos cuentas con su arranque y su registro, y arriba lo de la que está activa: con qué dinero se juega, en qué
    modo quedó y si arrancó frenada. Es lo que lee la pantalla y lo que leen los pasos que vienen."""
    ms = int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())
    cuentas = []
    for ambiente in AMBIENTES:
        cuenta = cargar(ambiente, ahora_ms=ms)
        cuentas.append({**cuenta, "registro": lib_registro.resumen(ambiente, ahora_ms=ms)})
    cual = activo()
    esta = next(c for c in cuentas if c["ambiente"] == cual)
    return {"formato": FORMATO, "cuando": lib_datos.iso(ms), "activo": cual, "cuentas": cuentas,
            "frenado": esta["frenado"], "motivo": esta["motivo"], "modo": esta["modo"],
            "parametros": parametros()}
