#!/usr/bin/env python3
"""lib_resolucion — la regla de las velas sin 1 m, escrita en un solo lugar. Solo biblioteca estándar. No es una acción.

Una operación se cierra en la primera vela que tocó su stop o su objetivo. El problema es la vela que tocó **los dos**: con
velas de 1 h o de 4 h no se sabe qué se cruzó primero, y de hace años Pilota no tiene velas de 1 m (guarda los últimos
`lib_datos.DIAS_MINUTOS` días). Así que la regla es **explícita y conservadora**, y dice siempre con qué salió:

| Qué hay | Qué pasa | Etiqueta |
|---|---|---|
| la vela tocó un solo nivel | se cierra ahí, no hay nada que suponer | `CLARA` |
| la vela tocó los dos y están sus velas de 1 m completas | se mira minuto por minuto qué se cruzó primero | `CON_1M` |
| la vela tocó los dos y no están sus velas de 1 m (o el minuto tampoco lo dice) | **el stop antes que el objetivo** (`SUPUESTO_SIN_1M`) | `SIN_1M` |

La etiqueta no es un adorno: viaja con el resultado hasta el reporte y la pantalla, porque una tasa de acierto calculada
con el supuesto conservador no es la misma cosa que una medida con velas de 1 m.

Y el supuesto no se deja suelto: `validar` lo revisa contra los días que sí tienen velas de 1 m, resolviendo **las mismas**
velas ambiguas de las dos formas —con 1 m y con el supuesto— y contando cuántas fueron ambiguas, cuántas se pudieron
revisar, en cuántas el supuesto dijo lo mismo que el minuto (`iguales`, `acierto`) y en cuántas se equivocó (`distintas`).

Las dos capas son las de siempre:
- Las de siempre, sobre velas y números (`toco`, `en_minutos`, `de_ambigua`, `resolver`, `cerrar`, `comparar`): no leen
  nada del disco. Son las que usan el backtest, la calibración y el ejecutor de prueba, en sus pasos.
- `validar`, que si no se le pasan las velas de 1 m las lee de lo guardado (los `lib_datos.DIAS_MINUTOS` días de los dos
  pares que se operan).

Lo que no se negocia aquí:
- **El supuesto se equivoca para el lado caro.** Con el stop y el objetivo en la misma vela se cuenta el stop: suponer el
  objetivo sería prometer plata que nadie vio.
- **El resultado no puede cambiar porque la ventana de 1 m se corra.** Los 30 días de 1 m son una ventana que se mueve, así
  que el recorrido del historial va siempre con el supuesto (es `cerrar(..., minutos=None)`) y las velas de 1 m se usan para
  **validarlo**, no para mejorar el resultado de a poco. Donde sí se resuelve con 1 m de verdad es en el modo prueba y al
  reconciliar, en sus pasos: ahí las velas están.
- **Media ventana no resuelve nada.** Si falta un solo minuto de la vela, `trozo_de` no devuelve nada y manda el supuesto:
  el cruce pudo pasar justo en el minuto que falta.
- **Del minuto no se baja más.** Si el mismo minuto tocó los dos niveles, tampoco se sabe qué fue primero (no hay velas de
  un segundo): eso queda `sin_resolver` y manda el supuesto, sin contarse como acierto ni como error.
- **La etiqueta se dice siempre**, también cuando la vela fue clara. Un resultado sin su etiqueta no se puede comparar con
  otro.
- **El código del supuesto es el mismo del backtest** (`backtest.SUPUESTO_AMBIGUO`): la regla es una sola y la prueba revisa
  que no se separen.
- **Nada se redondea aquí.** El redondeo vive en la pantalla.
"""
import lib_datos

#: Por dónde puede salir una operación.
POR_STOP, POR_OBJETIVO = "stop", "objetivo"
#: El supuesto conservador, por su nombre —el mismo código que `backtest.SUPUESTO_AMBIGUO`— y el lado que elige.
SUPUESTO_SIN_1M = "stop_primero"
POR_SUPUESTO = POR_STOP
#: Las tres etiquetas con que sale una resolución (códigos: la pantalla los traduce, en su paso).
CLARA = "sin_ambiguedad"
CON_1M = "resuelto_con_1m"
SIN_1M = "supuesto_conservador_sin_1m"
#: Cuántas velas ambiguas revisa `validar` como máximo: es una validación del supuesto, no el recorrido.
REVISADAS_MAXIMAS = 2000
#: Cuántas velas ambiguas resueltas con 1 m pide la validación antes de darse por hecha (`validado`). Con tres velas
#: revisadas nadie validó nada: el acierto se informa igual, pero diciendo que todavía no alcanza.
VELAS_VALIDACION = 20


def parametros():
    """Con qué regla se resolvió, para el reporte: el supuesto, sus etiquetas y cuánto pide la validación."""
    return {"supuesto": SUPUESTO_SIN_1M, "por_supuesto": POR_SUPUESTO, "dias_1m": lib_datos.DIAS_MINUTOS,
            "velas_validacion": VELAS_VALIDACION, "revisadas_maximas": REVISADAS_MAXIMAS,
            "etiquetas": [CLARA, CON_1M, SIN_1M]}


# ── Las velas: qué tocó cada una ────────────────────────────────────────────────────────────────────────────────────────────

def toco(vela, stop, objetivo):
    """Qué niveles tocó una vela: `(stop, objetivo)`, con su mínimo (`vela[3]`) y su máximo (`vela[2]`). Tocar el nivel
    basta: una vez que el precio llegó ahí, la protección automática ya está en el libro."""
    return vela[3] <= stop, vela[2] >= objetivo


def indexar(velas):
    """Las velas de 1 m por su hora de apertura: así una vela de 4 h encuentra sus 240 minutos sin recorrer la serie."""
    return {v[0]: v for v in (velas or [])}


def trozo_de(minutos, apertura_ms, paso_ms):
    """Las velas de 1 m de una vela, en orden, o `None` si falta alguna o si la vela ya es de 1 m. `minutos` es la serie
    guardada (una lista) o el índice que deja `indexar`.

    La ventana tiene que estar **completa**: con un minuto faltando, el cruce pudo pasar justo ahí."""
    minuto = lib_datos.PASO_MS[lib_datos.MINUTO]
    if not minutos or paso_ms <= minuto:
        return None
    guardadas = minutos if isinstance(minutos, dict) else indexar(minutos)
    trozo = [guardadas.get(apertura_ms + x * minuto) for x in range(paso_ms // minuto)]
    return None if any(v is None for v in trozo) else trozo


def en_minutos(minutos, stop, objetivo):
    """Qué se cruzó primero dentro de la vela, minuto por minuto: `"stop"`, `"objetivo"` o `""` cuando el minuto tampoco lo
    dice —el mismo minuto tocó los dos (no hay velas de un segundo) o ninguno de los dos se cruzó ahí adentro—."""
    for v in minutos or []:
        abajo, arriba = toco(v, stop, objetivo)
        if abajo and arriba:
            return ""
        if abajo or arriba:
            return POR_STOP if abajo else POR_OBJETIVO
    return ""


# ── La regla ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def de_ambigua(stop, objetivo, minutos=None):
    """La regla de la vela ambigua, sola: la que tocó el stop **y** el objetivo. Con sus velas de 1 m completas
    (`minutos`), lo que de verdad pasó primero y la etiqueta `CON_1M`; sin ellas —o si el minuto tampoco lo dice—, el
    supuesto conservador `SUPUESTO_SIN_1M` (el stop) y la etiqueta `SIN_1M`.

    Es la única función que decide esto: `resolver` y `validar` la llaman las dos, así la regla no se escribe dos veces."""
    por = en_minutos(minutos, stop, objetivo) if minutos else ""
    if por:
        return {"por": por, "ambigua": True, "etiqueta": CON_1M, "supuesto": SUPUESTO_SIN_1M, "con_1m": True,
                "minutos": len(minutos)}
    return {"por": POR_SUPUESTO, "ambigua": True, "etiqueta": SIN_1M, "supuesto": SUPUESTO_SIN_1M, "con_1m": False,
            "minutos": len(minutos or [])}


def resolver(vela, stop, objetivo, minutos=None):
    """Qué le pasó a una operación en **esta** vela, con la etiqueta del supuesto con que salió. `minutos` son las velas de
    1 m de esta vela, completas (lo que devuelve `trozo_de`), o `None` si no están.

    - `por`: `"stop"`, `"objetivo"` o `""` si la vela no tocó ninguno de los dos (la operación sigue abierta).
    - `ambigua`: la vela tocó los dos niveles y hubo que decidir.
    - `etiqueta`: `CLARA` (no hubo nada que suponer), `CON_1M` (lo dijeron las velas de 1 m) o `SIN_1M` (mandó el supuesto
      conservador)."""
    abajo, arriba = toco(vela, stop, objetivo)
    if abajo and arriba:
        return de_ambigua(stop, objetivo, minutos)
    return {"por": (POR_STOP if abajo else POR_OBJETIVO) if (abajo or arriba) else "", "ambigua": False,
            "etiqueta": CLARA, "supuesto": SUPUESTO_SIN_1M, "con_1m": False, "minutos": 0}


def cerrar(velas, desde, stop, objetivo, temporalidad, minutos=None, maximo=None):
    """La operación completa: desde la vela `desde` (ya llenada) hasta la primera que tocó el stop o el objetivo, con la
    regla aplicada en esa vela. `minutos` son las velas de 1 m del par (la serie o el índice de `indexar`): sin ellas,
    manda el supuesto. `maximo` es cuántas velas se le dan antes de dejarla por no cerrada.

    Devuelve en qué vela salió (`i`), a qué hora cerró esa vela (`salida_ms`), cuántas velas vivió, por qué salió, a qué
    precio (el nivel, los costos son de `lib_costos`), si la vela fue ambigua y con qué etiqueta se resolvió. Si ninguna
    vela cruzó, `por` queda vacío y `motivo` dice `sin_cerrar`: una operación que no cerró no es un resultado."""
    paso = lib_datos.PASO_MS[temporalidad]
    guardadas = minutos if isinstance(minutos, dict) else indexar(minutos)
    inicio = max(0, int(desde))
    hasta = len(velas) if maximo is None else min(len(velas), inicio + int(maximo))
    for k in range(inicio, hasta):
        abajo, arriba = toco(velas[k], stop, objetivo)
        if not (abajo or arriba):
            continue
        trozo = trozo_de(guardadas, velas[k][0], paso) if (abajo and arriba) else None
        r = resolver(velas[k], stop, objetivo, trozo)
        return {**r, "i": k, "salida_ms": velas[k][0] + paso, "velas": k - inicio + 1,
                "precio": stop if r["por"] == POR_STOP else objetivo, "motivo": ""}
    return {"por": "", "ambigua": False, "etiqueta": CLARA, "supuesto": SUPUESTO_SIN_1M, "con_1m": False, "minutos": 0,
            "i": None, "salida_ms": None, "velas": 0, "precio": None, "motivo": "sin_cerrar"}


def comparar(velas, desde, stop, objetivo, temporalidad, minutos=None, maximo=None):
    """La **misma** operación resuelta de las dos formas: con las velas de 1 m y con el supuesto conservador. Si las dos
    dan lo mismo (`igual`), el supuesto no cambió nada; si no, se ve exactamente qué se perdió por no tener 1 m."""
    con = cerrar(velas, desde, stop, objetivo, temporalidad, minutos, maximo)
    sin = cerrar(velas, desde, stop, objetivo, temporalidad, None, maximo)
    return {"con_1m": con, "sin_1m": sin, "igual": con["por"] == sin["por"], "ambigua": sin["ambigua"],
            "revisada": con["con_1m"]}


# ── La validación contra los días que sí tienen velas de 1 m ────────────────────────────────────────────────────────────────

def _ventana_de(series):
    """De cuándo a cuándo llegan las velas de 1 m con las que se validó: es la ventana que se puede revisar."""
    aperturas = [v[0] for velas in (series or {}).values() for v in (velas or [])]
    desde, hasta = (min(aperturas), max(aperturas)) if aperturas else (None, None)
    return {"desde": desde, "hasta": hasta, "iso_desde": lib_datos.iso(desde) if desde else "",
            "iso_hasta": lib_datos.iso(hasta) if hasta else "",
            "velas": len(aperturas), "pares": sorted(p for p, v in (series or {}).items() if v)}


def validar(operaciones, minutos=None):
    """La regla, validada: cada vela ambigua de esas operaciones se resuelve **de las dos formas** —con sus velas de 1 m y
    con el supuesto conservador— y se cuenta en cuántas el supuesto dijo lo mismo que el minuto.

    Cada operación trae lo justo para volver a mirar su vela de salida: `par`, `temporalidad`, `stop`, `objetivo`,
    `salida_ms` y si fue `ambigua` (es lo que deja `backtest.seguir`). Las que no fueron ambiguas no se revisan: ahí no
    hubo supuesto que validar. `minutos` es `{par: velas}`; si no se pasa, se leen los `lib_datos.DIAS_MINUTOS` días
    guardados de los dos pares que se operan.

    - `velas`: cuántas velas fueron ambiguas. `con_1m` / `sin_1m`: cuántas de esas tenían (o no) su ventana de 1 m completa.
    - `stop_primero`, `objetivo_primero`, `sin_resolver`: qué dijo el minuto en las que sí se pudieron revisar.
    - `iguales` / `distintas`: en cuántas el supuesto acertó y en cuántas se equivocó; `acierto` es la parte que acertó.
    - `validado`: si se revisaron al menos `VELAS_VALIDACION`. Con menos, el acierto se informa igual, pero no valida nada."""
    series = minutos if minutos is not None else {p: lib_datos.leer_serie(p, lib_datos.MINUTO)
                                                  for p in lib_datos.PARES_OPERADOS}
    guardadas = {par: indexar(velas) for par, velas in (series or {}).items()}
    d = {"supuesto": SUPUESTO_SIN_1M, "etiqueta": SIN_1M, "dias_1m": lib_datos.DIAS_MINUTOS,
         "ventana": _ventana_de(series), "velas": 0, "con_1m": 0, "sin_1m": 0, "stop_primero": 0,
         "objetivo_primero": 0, "sin_resolver": 0, "iguales": 0, "distintas": 0, "resueltas": 0,
         "minimo": VELAS_VALIDACION, "acierto": None, "validado": False}
    for o in operaciones or []:
        if not o.get("ambigua"):
            continue
        d["velas"] += 1
        paso = lib_datos.PASO_MS.get(o.get("temporalidad"))
        if paso is None or o.get("salida_ms") is None or d["con_1m"] >= REVISADAS_MAXIMAS:
            continue
        trozo = trozo_de(guardadas.get(o.get("par")), o["salida_ms"] - paso, paso)
        if trozo is None:
            d["sin_1m"] += 1          # esa vela es de antes de la ventana de 1 m: no hay con qué revisarla
            continue
        d["con_1m"] += 1
        con = de_ambigua(o["stop"], o["objetivo"], trozo)
        sin = de_ambigua(o["stop"], o["objetivo"])
        if not con["con_1m"]:
            d["sin_resolver"] += 1    # el minuto tocó los dos o ninguno: no cuenta como acierto ni como error
            continue
        d["stop_primero" if con["por"] == POR_STOP else "objetivo_primero"] += 1
        d["iguales" if con["por"] == sin["por"] else "distintas"] += 1
    d["resueltas"] = d["iguales"] + d["distintas"]
    d["acierto"] = (d["iguales"] / d["resueltas"]) if d["resueltas"] else None
    d["validado"] = d["resueltas"] >= VELAS_VALIDACION
    return d
