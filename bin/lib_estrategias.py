#!/usr/bin/env python3
"""lib_estrategias — las tres estrategias y el filtro de BTC. Solo biblioteca estándar. No es una acción.

Sobre los indicadores de las siete familias (`bin/lib_indicadores.py` y `bin/lib_indicadores_mercado.py`), las tres salidas
posibles de cada vuelta:

| Estrategia | Cuándo mira | Cómo entra | Cómo sale |
|---|---|---|---|
| `ruptura` (tendencia) | el cierre pasó el techo de las `RUPTURA_VELAS` velas anteriores, con volumen sobre `VOLUMEN_RUPTURA` y el día al alza | límite en el nivel roto, cuando el precio vuelve a él | objetivo a `OBJETIVO_RUPTURA` del nivel, stop a `STOP_ATR_RUPTURA` ATR |
| `rebote` (rango) | el cierre pegado a la banda de abajo de Bollinger (`POSICION_REBOTE`) con el ADX bajo (`ADX_RANGO`) | límite en la banda de abajo | objetivo en la media de la banda, stop a `STOP_ATR_REBOTE` ATR |
| `usdt` | siempre | no entra | — |

Y el freno que vale para las dos entradas: **si BTC cae, no se entra a nada** (`filtro_btc`, sobre la familia contexto).

Las dos capas son las de los indicadores: las de siempre, sobre las velas (`de_velas`, `tendencia_diaria`,
`contexto_diario`, `al_alza_en`, `filtro_en`), devuelven las señales vela por vela y son las que va a recorrer el backtest;
las de la app (`de_indicadores`, `estado`) dan las señales de **ahora** de cada par operado, a partir del estado de
indicadores que ya recorrió las velas una sola vez. `estado()` es lo que responde la acción `senalesEstado`
(`bin/senales.py`).

Lo que no se negocia aquí:
- **Estas son señales crudas**: dicen par, temporalidad, nivel de entrada, stop y objetivo, y nada más. El puntaje, la
  exigencia, el costo de entrar y salir y el tamaño de la orden son de sus propios pasos: una señal cruda no es una orden.
- **Solo se compra** (`lado` siempre `"compra"`) y siempre con **límite** (`orden`): la entrada es post-only contra FDUSD,
  del lado maker. Sin apalancamiento y sin vender en corto.
- **Si BTC cae, no se entra a nada**, y sin contexto tampoco: con BTC a ciegas ninguna oportunidad se mira. El filtro no
  borra la señal (el backtest necesita verla), le pone `permitida` en falso y su motivo.
- **La tendencia diaria no se supone.** Si falta la serie de 1 d con la que se mide, la estrategia de ruptura no se mira y
  eso queda en `motivos` (`sin_tendencia_diaria`). Sale del par contra USDT (`PAR_DIARIO`), que es el que tiene años de
  historia: el de FDUSD recién empieza y no llega a la media de 200 días, igual que en la familia contexto.
- **1 d no es temporalidad de entrada** (`TEMPORALIDADES_SENAL`): es la que dice para dónde va el día.
- **Nunca se mira el futuro.** `al_alza_en` y `filtro_en` responden con la última vela de 1 d **cerrada** antes de ese
  momento: en el backtest, decidir con una vela que todavía no cerró es inventar ganancias.
- **Nada se redondea** y ningún número se inventa: si a una vela le falta un parámetro (el ATR, la banda, el volumen
  relativo), esa vela no da señal.
- Los números de aquí (`VOLUMEN_RUPTURA`, `OBJETIVO_RUPTURA`, `ADX_RANGO`…) son los de partida, escritos antes de ver un
  solo resultado: los mueve la calibración, en su paso, y el reporte dice con cuáles quedó.

Dónde queda: `<datos>/mercado/senales.json` (lo que devuelve `estado()`, con la hora del cálculo).
"""
import bisect
import os

import lib_datos
import lib_indicadores
import lib_indicadores_mercado
import nucleo

#: Las tres estrategias, en el orden en que se cuentan.
ESTRATEGIAS = ("ruptura", "rebote", "usdt")
#: Las temporalidades en las que se entra. La de 1 d no es de entrada: es la que dice para dónde va el día.
TEMPORALIDADES_SENAL = ("1h", "4h")
TEMPORALIDAD_DIARIA = "1d"
#: De dónde sale la tendencia diaria de cada par: del par contra USDT, el que tiene años de historia (el de FDUSD recién
#: empieza y no llega a la media de 200 días). Es la misma razón por la que el contexto de BTC sale de `BTCUSDT`.
PAR_DIARIO = {"BTCFDUSD": "BTCUSDT", "ETHFDUSD": "ETHUSDT", "BTCUSDT": "BTCUSDT", "ETHUSDT": "ETHUSDT"}
#: Ruptura: cuántas veces el volumen de siempre pide la vela que rompe, dónde va el objetivo (el extremo de abajo del 1,5 a
#: 2 % de la idea: el que menos promete) y a cuántos ATR queda el stop del nivel roto.
VOLUMEN_RUPTURA = 1.5
OBJETIVO_RUPTURA = 0.015
STOP_ATR_RUPTURA = 1.5
#: Rebote: hasta qué ADX se considera que el mercado está sin rumbo, qué tan pegado a la banda de abajo tiene que cerrar el
#: precio (0 es la banda misma; por debajo, negativo) y a cuántos ATR queda el stop de la entrada.
ADX_RANGO = 20.0
POSICION_REBOTE = 0.05
STOP_ATR_REBOTE = 1.0
#: El filtro de BTC: una caída de este tamaño en el último día cerrado no deja entrar a nada.
CAIDA_BTC = 0.03
#: Cuántas velas espera la orden límite en el nivel: una entrada que no se llenó en ese rato ya no es la misma oportunidad.
VIGENCIA_VELAS = 3


def ruta_senales():
    return os.path.join(lib_datos.carpeta_mercado(), "senales.json")


def parametros():
    """Los números con los que se mira cada estrategia: los lee la pantalla y los va a mover la calibración."""
    return {"volumen_ruptura": VOLUMEN_RUPTURA, "objetivo_ruptura": OBJETIVO_RUPTURA,
            "stop_atr_ruptura": STOP_ATR_RUPTURA, "adx_rango": ADX_RANGO, "posicion_rebote": POSICION_REBOTE,
            "stop_atr_rebote": STOP_ATR_REBOTE, "caida_btc": CAIDA_BTC, "vigencia_velas": VIGENCIA_VELAS,
            "ruptura_velas": lib_indicadores_mercado.RUPTURA_VELAS}


# ── El filtro de BTC y la tendencia diaria ───────────────────────────────────────────────────────────────────────────────────

def filtro_btc(contexto):
    """El freno que vale para las dos entradas: si BTC cae, no se entra a nada. Mira los dos parámetros de la familia
    contexto (BTC en 1 d): cuánto se movió el último día cerrado y si quedó sobre su media de 200 días. Sin esos dos
    números no se entra tampoco (`sin_contexto`): con BTC a ciegas ninguna oportunidad se mira."""
    f = {"par": lib_indicadores_mercado.CONTEXTO_PAR, "temporalidad": lib_indicadores_mercado.CONTEXTO_TEMPORALIDAD,
         "pasa": False, "motivo": "sin_contexto", "caida": CAIDA_BTC, "cambio": None, "sobre_media": None}
    cambio, sobre_media = (contexto or {}).get("cambio"), (contexto or {}).get("sobre_media")
    if cambio is None or sobre_media is None:
        return f
    f.update(cambio=cambio, sobre_media=bool(sobre_media), motivo="")
    if cambio <= -CAIDA_BTC:
        f["motivo"] = "btc_cae"
    elif not sobre_media:
        f["motivo"] = "btc_bajo_media"
    f["pasa"] = not f["motivo"]
    return f


def al_alza_de(serie):
    """Si la tendencia diaria de una fila del estado de indicadores (una serie de 1 d) está al alza: el cierre sobre la
    media de 200 velas y la de 20 sobre la de 50. `None` si esa serie todavía no tiene indicadores: una tendencia que no se
    puede medir no se supone al alza."""
    if not serie or not serie.get("listo"):
        return None
    t = serie.get("tendencia") or {}
    corta, media, larga, cierre = t.get("media_20"), t.get("media_50"), t.get("media_200"), serie.get("cierre")
    if None in (corta, media, larga, cierre):
        return None
    return bool(cierre > larga and corta > media)


def tendencia_diaria(velas):
    """Si la tendencia diaria estaba al alza al cerrar cada vela: una lista del mismo largo que `velas`, con `None` mientras
    falte la media más larga. Es lo que mira la estrategia de ruptura, vela por vela."""
    cierres = [v[4] for v in velas]
    cortas, medias, largas = (lib_indicadores.sma(cierres, n) for n in lib_indicadores.MEDIAS)
    return [None if None in (cortas[i], medias[i], largas[i]) else bool(cierres[i] > largas[i] and cortas[i] > medias[i])
            for i in range(len(cierres))]


def contexto_diario(velas):
    """Lo que el filtro mira de BTC en cada vela de 1 d: cuánto se movió ese día y si cerró sobre su media de 200 velas.
    Las mismas dos cuentas de la familia contexto, pero sobre toda la serie: es lo que recorre el backtest."""
    cierres = [v[4] for v in velas]
    largas = lib_indicadores.sma(cierres, lib_indicadores.MEDIAS[-1])
    movio = lib_indicadores_mercado.cambios(cierres)
    return [{"cierre": cierres[i], "media_200": largas[i], "cambio": movio[i],
             "sobre_media": None if largas[i] is None else bool(cierres[i] > largas[i])} for i in range(len(cierres))]


def _en_el_tiempo(velas, temporalidad, valores):
    """Una función que dice qué valía `valores[i]` en un momento dado, mirando solo las velas que ya habían **cerrado**:
    en el backtest, decidir con una vela que todavía no cerró es inventar ganancias. Antes de la primera, `None`."""
    paso = lib_datos.PASO_MS[temporalidad]
    cierres = [v[0] + paso for v in velas]

    def en(ms):
        i = bisect.bisect_right(cierres, ms) - 1
        return valores[i] if i >= 0 else None
    return en


def al_alza_en(velas, temporalidad=TEMPORALIDAD_DIARIA):
    """La tendencia diaria en cualquier momento: `al_alza_en(velas_de_1d)(ms)` → `True`, `False` o `None`."""
    return _en_el_tiempo(velas, temporalidad, tendencia_diaria(velas))


def filtro_en(velas, temporalidad=TEMPORALIDAD_DIARIA):
    """El filtro de BTC en cualquier momento: `filtro_en(velas_de_btc_en_1d)(ms)` → lo que devuelve `filtro_btc`. Antes de
    la primera vela cerrada, el de no tener contexto: sin BTC a la vista no se entra a nada."""
    en = _en_el_tiempo(velas, temporalidad, [filtro_btc(c) for c in contexto_diario(velas)])
    return lambda ms: en(ms) or filtro_btc(None)


def contexto_en(velas, temporalidad=TEMPORALIDAD_DIARIA):
    """La familia contexto en cualquier momento: `contexto_en(velas_de_btc_en_1d)(ms)` → la fila de `contexto_diario` de
    la última vela de 1 d **cerrada** antes de ese momento, o `None` antes de la primera. El filtro solo necesita saber
    si deja entrar; el puntaje, en su paso, necesita los dos números."""
    return _en_el_tiempo(velas, temporalidad, contexto_diario(velas))


# ── Las tres estrategias, vela a vela ────────────────────────────────────────────────────────────────────────────────────────

def _senal(estrategia, v, entrada, stop, objetivo, razon):
    """La señal cruda: par, temporalidad, nivel de entrada, stop y objetivo, con la distancia a cada uno (la del stop es la
    que después pide el tamaño de la operación) y hasta cuándo espera la orden límite."""
    paso = lib_datos.PASO_MS[v["temporalidad"]]
    return {"estrategia": estrategia, "par": v["par"], "temporalidad": v["temporalidad"], "lado": "compra",
            "orden": "limite", "razon": razon, "vela": v["ms"], "cierre": v["cierre"],
            "entrada": entrada, "stop": stop, "objetivo": objetivo,
            "distancia_stop": (entrada - stop) / entrada, "distancia_objetivo": (objetivo - entrada) / entrada,
            "vigencia_velas": VIGENCIA_VELAS, "vence": v["ms"] + (VIGENCIA_VELAS + 1) * paso,
            "permitida": True, "filtro": ""}


def ruptura(v, al_alza):
    """La estrategia de tendencia en una vela, o `None`: el cierre pasó el techo de las velas anteriores, el volumen
    acompañó y el día viene al alza. La entrada es un límite **en el nivel roto** (se espera a que el precio vuelva a él, no
    se persigue), el stop queda a `STOP_ATR_RUPTURA` ATR por debajo y el objetivo a `OBJETIVO_RUPTURA` del nivel.

    `al_alza` en `None` (no se sabe) no entra, igual que en `False`: la tendencia diaria no se supone."""
    if not al_alza or not v.get("rompio_maximo"):
        return None
    nivel, relativo, medio = v.get("maximo"), v.get("relativo"), v.get("atr")
    if not nivel or relativo is None or medio is None or relativo < VOLUMEN_RUPTURA:
        return None
    stop = nivel - STOP_ATR_RUPTURA * medio
    if stop <= 0:
        return None
    return _senal("ruptura", v, nivel, stop, nivel * (1 + OBJETIVO_RUPTURA), "ruptura_con_volumen")


def rebote(v):
    """La estrategia de rango en una vela, o `None`: el cierre pegado a la banda de abajo de Bollinger con el ADX bajo (el
    precio sin rumbo, yendo y viniendo dentro de la banda). Sale en la media de la banda o con el stop.

    La entrada es el menor entre la banda de abajo y el cierre: una compra post-only no puede quedar sobre el precio."""
    adx, posicion, medio, cierre = v.get("adx"), v.get("posicion"), v.get("atr"), v.get("cierre")
    baja, media = v.get("banda_baja"), v.get("banda_media")
    if None in (adx, posicion, medio, cierre, baja, media):
        return None
    if adx > ADX_RANGO or posicion > POSICION_REBOTE:
        return None
    entrada = min(baja, cierre)
    stop = entrada - STOP_ATR_REBOTE * medio
    if entrada <= 0 or stop <= 0 or media <= entrada:
        return None
    return _senal("rebote", v, entrada, stop, media, "rebote_en_banda")


def quedarse(filtro, entrables=0):
    """La tercera estrategia: quedarse en USDT. Siempre está —también se va a puntuar, en su paso— y cuando el filtro de BTC
    no deja entrar es la única: `razon` dice por qué está ahí."""
    razon = "btc" if not filtro["pasa"] else ("hay_oportunidades" if entrables else "sin_oportunidad")
    return {"estrategia": "usdt", "par": "", "temporalidad": "", "lado": "quedarse", "orden": "", "razon": razon,
            "vela": None, "cierre": None, "entrada": None, "stop": None, "objetivo": None, "distancia_stop": None,
            "distancia_objetivo": None, "vigencia_velas": 0, "vence": None, "permitida": True,
            "filtro": filtro["motivo"]}


def vela_de(serie):
    """Lo que las dos entradas miran de una vela, sacado de una fila del estado de indicadores (o armado por `de_velas`):
    los parámetros de estructura, volumen, volatilidad y tendencia que usan las reglas, y nada más."""
    v, e = serie.get("volatilidad") or {}, serie.get("estructura") or {}
    return {"par": serie.get("par"), "temporalidad": serie.get("temporalidad"), "ms": serie.get("vela"),
            "cierre": serie.get("cierre"), "maximo": e.get("maximo"), "rompio_maximo": e.get("rompio_maximo"),
            "relativo": (serie.get("volumen") or {}).get("relativo"), "atr": v.get("atr"),
            "banda_baja": v.get("banda_baja"), "banda_media": v.get("banda_media"), "posicion": v.get("posicion"),
            "adx": (serie.get("tendencia") or {}).get("adx")}


def de_velas(par, temporalidad, velas, al_alza=None, filtro=None):
    """Las señales crudas de cada vela de una serie: una lista del mismo largo que `velas`, con las señales de esa vela
    (puede haber dos) o una lista vacía. Es la que recorre el backtest, y por eso recorre las velas una sola vez: los
    indicadores se calculan enteros y después se mira vela por vela.

    `al_alza(ms)` y `filtro(ms)` son las funciones de `al_alza_en` y `filtro_en` sobre las velas de 1 d (la tendencia del
    par y el contexto de BTC). Sin ellas no hay ruptura y ninguna señal queda permitida: aquí no se supone nada."""
    altos, bajos, cierres, volumenes = ([v[i] for v in velas] for i in (2, 3, 4, 5))
    banda = lib_indicadores_mercado.bollinger(cierres)
    medio = lib_indicadores_mercado.atr(altos, bajos, cierres)
    niveles = lib_indicadores_mercado.rupturas(altos, bajos, cierres)
    relativos = lib_indicadores_mercado.volumen_relativo(volumenes)
    fuerza = lib_indicadores.adx(altos, bajos, cierres)["adx"]
    paso = lib_datos.PASO_MS[temporalidad]
    salida = []
    for i, vela in enumerate(velas):
        cuando = vela[0] + paso            # el momento en que esta vela cerró: es con eso con lo que se decide
        v = {"par": par, "temporalidad": temporalidad, "ms": vela[0], "cierre": cierres[i],
             "maximo": niveles["maximo"][i], "rompio_maximo": niveles["rompio_maximo"][i], "relativo": relativos[i],
             "atr": medio[i], "banda_baja": banda["baja"][i], "banda_media": banda["media"][i],
             "posicion": banda["posicion"][i], "adx": fuerza[i]}
        f = (filtro(cuando) if filtro else None) or filtro_btc(None)
        suyas = [s for s in (ruptura(v, al_alza(cuando) if al_alza else None), rebote(v)) if s]
        for s in suyas:
            s.update(permitida=f["pasa"], filtro=f["motivo"])
        salida.append(suyas)
    return salida


# ── Lo que usa la app: las señales de ahora ──────────────────────────────────────────────────────────────────────────────────

def de_indicadores(serie, al_alza=None):
    """Las señales de ahora de una serie, a partir de su fila del estado de indicadores: así las velas se recorren una sola
    vez. Una serie sin indicadores (corta, atrasada o con hoyos) no da ninguna señal."""
    if not serie or not serie.get("listo"):
        return []
    v = vela_de(serie)
    return [s for s in (ruptura(v, al_alza), rebote(v)) if s]


def estado(ahora_ms=None, indicadores=None):
    """Las señales crudas de ahora de los dos pares que se operan, en las temporalidades de entrada, con el filtro de BTC y
    la opción de quedarse en USDT. `indicadores` es el estado de las siete familias: se le puede pasar el que ya calculó
    quien llama (el motor, en su paso) para no recorrer las velas dos veces.

    `listo` pide que no falte nada de lo que se necesita para mirar: las cuatro series, el contexto de BTC y la tendencia
    diaria de los dos pares. Que el filtro no deje entrar no es que falte algo: eso va en `filtro`."""
    ahora = ahora_ms or lib_datos.ahora_local_ms()
    e = lib_indicadores_mercado.estado(ahora) if indicadores is None else indicadores
    filas = {(s.get("par"), s.get("temporalidad")): s for s in (e.get("series") or [])}
    f = filtro_btc(e.get("contexto"))
    series, senales, motivos = [], [], []
    if f["motivo"] == "sin_contexto":
        motivos.append({"codigo": "sin_contexto", "par": f["par"], "temporalidad": f["temporalidad"],
                        "n": (e.get("contexto") or {}).get("cuantas") or 0})
    for par in lib_datos.PARES_OPERADOS:
        diaria = filas.get((PAR_DIARIO[par], TEMPORALIDAD_DIARIA)) or {}
        al_alza = al_alza_de(diaria)
        if al_alza is None:   # sin la serie de 1 d no se puede saber si el día viene al alza: la ruptura no se mira
            motivos.append({"codigo": "sin_tendencia_diaria", "par": PAR_DIARIO[par],
                            "temporalidad": TEMPORALIDAD_DIARIA, "n": diaria.get("cuantas") or 0})
        for temporalidad in TEMPORALIDADES_SENAL:
            s = filas.get((par, temporalidad)) or {}
            suyas = de_indicadores(s, al_alza)
            for x in suyas:
                x.update(permitida=f["pasa"], filtro=f["motivo"])
            fila = {"par": par, "temporalidad": temporalidad, "par_diario": PAR_DIARIO[par], "al_alza": al_alza,
                    "listo": bool(s.get("listo")), "motivo": s.get("motivo") or "", "cuantas": s.get("cuantas") or 0,
                    "vela": s.get("vela"), "cierre": s.get("cierre"), "senales": suyas}
            if fila["motivo"]:
                motivos.append({"codigo": fila["motivo"], "par": par, "temporalidad": temporalidad,
                                "n": fila["cuantas"]})
            series.append(fila)
            senales.extend(suyas)
    entrables = sum(1 for s in senales if s["permitida"])
    return {"formato": 1, "cuando": lib_datos.iso(ahora), "estrategias": list(ESTRATEGIAS),
            "temporalidades": list(TEMPORALIDADES_SENAL), "parametros": parametros(), "filtro": f,
            "series": series, "senales": senales, "usdt": quedarse(f, entrables), "entrables": entrables,
            "motivos": motivos, "listo": not motivos}


def escribir_estado(e):
    """Deja escrito el último cálculo: lo leen el backtest, el puntaje y el motor sin volver a recorrer las velas."""
    nucleo.escribir_json(ruta_senales(), e)
    return e
