#!/usr/bin/env python3
"""historial — los 3 años de velas, bajados en segundo plano y por etapas. Solo biblioteca estándar.

  historial.py estado <entrada.json {}> <salida.json>      → {ok, datos}
  historial.py descargar <entrada.json {}> <salida.json>   → {ok, datos, error?}   (trabajo: avance, «Detener» y «Seguir»)
  historial.py detener <entrada.json {}> <salida.json>     → {ok, datos}

Los 90 días con los que Pilota decide los baja `velas.py`; los 3 años son para el backtest y la calibración, así que vienen
después y sin apurar nada. «estado» no toca la red: dice en qué quedó. «descargar» es a la vez «empezar» y «Seguir donde
quedó»: el plan guardado dice desde dónde sigue cada serie.

Las etapas van de lo más barato a lo más caro (1 d, 4 h, 1 h): si se corta a la mitad, lo que quedó bajado ya sirve para algo.

Lo que no se negocia aquí:
- **Se guarda en cada página.** Cada pedido a Binance que trae velas nuevas se guarda al tiro, y el plan también: «Detener»
  o cerrar la app no pierde ni repite nada (`lib_datos.bajar_tramo`).
- **Los límites de la API se respetan** (los pone `lib_datos.Binance`: espera lo que pide Binance y reintenta).
- **Solo velas cerradas** y **continuidad al terminar cada par**: antes de dar una serie por lista se revisa paso por paso
  (hora por hora en `1h`) que no le falte ninguna vela en medio, y lo que falte se vuelve a pedir, un pedido por hoyo
  (`revisar`). Un hoyo que queda se anota en la serie (`huecos`), la pantalla lo dice y la próxima vuelta lo reintenta.
- **La historia que no existe no se inventa.** Un par más nuevo que la ventana (FDUSD) simplemente empieza más tarde: la serie
  queda recorrida con menos velas que las esperadas y el plan lo dice (`desde`). El empalme con el par de USDT es cosa del
  backtest, en su propio paso.

Dónde queda: `<datos>/mercado/historial.json` (el plan con el avance de las 12 series) y las velas, donde siempre
(`<datos>/mercado/velas/<PAR>-<TEMPORALIDAD>.json`).
"""
import time

import lib_datos
import lib_trabajo
import nucleo

TIPO = "historial"
#: Las etapas, en orden: primero el día (dos pedidos por par), al final la hora (la más larga).
ETAPAS = ("1d", "4h", "1h")
#: Lo que se supone que tarda un pedido mientras no se haya medido en este computador (se mide en la primera vuelta).
SEGUNDOS_POR_PEDIDO = 0.8


def armar(ahora_ms, dias=lib_datos.DIAS_HISTORIAL, antes=None):
    """El plan de las 12 series: de dónde a dónde va cada una y en qué quedó. Lo que hay en disco manda sobre el plan viejo:
    lo ya bajado no se vuelve a pedir, y si el plan se perdió se empieza de nuevo (sin perder ninguna vela)."""
    antes = antes or {}
    viejas = {f"{s.get('par')}-{s.get('temporalidad')}": s for s in (antes.get("series") or []) if isinstance(s, dict)}
    series = []
    for temporalidad in ETAPAS:
        paso = lib_datos.PASO_MS[temporalidad]
        fin = (ahora_ms // paso) * paso                 # el borde de lo cerrado, igual que en el resto de Pilota
        inicio = fin - dias * lib_datos.DIA_MS
        for par in lib_datos.PARES:
            velas = [v for v in lib_datos.leer_serie(par, temporalidad) if inicio <= v[0] < fin]
            antigua = viejas.get(f"{par}-{temporalidad}") or {}
            quedo = antigua.get("siguiente")
            siguiente = quedo if isinstance(quedo, int) and inicio <= quedo <= fin else inicio
            siguiente = min(fin, max(siguiente, lib_datos.fin_continuo(velas, temporalidad, inicio)))
            hoyos = lib_datos.huecos(velas, temporalidad)
            series.append({"par": par, "temporalidad": temporalidad, "inicio": inicio, "fin": fin, "siguiente": siguiente,
                           "velas": len(velas), "esperadas": dias * lib_datos.DIA_MS // paso,
                           "huecos": len(hoyos), "continua": not hoyos,
                           "desde": velas[0][0] if velas else None, "hasta": velas[-1][0] if velas else None,
                           "pedidos": lib_datos.pedidos(inicio, fin, temporalidad),
                           "faltan": lib_datos.pedidos(siguiente, fin, temporalidad), "listo": siguiente >= fin})
    plan = {"formato": 1, "dias": dias, "estado": "nunca", "etapa": ETAPAS[0], "trabajo": "", "error": "",
            "segundos_por_pedido": 0, "cuando": ""}
    # Del plan viejo se guarda en qué quedó (estado, etapa, trabajo…); la ventana y el avance se recalculan con lo que hay.
    plan.update({k: v for k, v in antes.items() if k in plan and k not in ("formato", "dias")})
    plan["series"] = series
    return plan


def terminada(serie):
    """Una serie está terminada cuando se recorrió toda su ventana **y** quedó continua: con un hoyo adentro no sirve para
    calcular, así que la próxima vuelta la vuelve a tomar (solo para rellenar el hoyo, no para bajarla de nuevo)."""
    return bool(serie.get("listo")) and bool(serie.get("continua", True))


def etapa_de(plan, temporalidad):
    """El resumen de una etapa: las 4 series de esa temporalidad juntas, como se ven en la pantalla."""
    series = [s for s in plan["series"] if s["temporalidad"] == temporalidad]
    desdes = [s["desde"] for s in series if s["desde"]]
    return {"temporalidad": temporalidad, "velas": sum(s["velas"] for s in series),
            "esperadas": sum(s["esperadas"] for s in series), "faltan": sum(s["faltan"] for s in series),
            "huecos": sum(s.get("huecos") or 0 for s in series),
            "desde": min(desdes) if desdes else None, "listo": all(s["listo"] for s in series)}


def resumen(plan):
    """Lo que ve la pantalla: el porcentaje, el tiempo que falta y en qué quedó cada etapa. El avance se mide en pedidos a
    Binance (cada uno trae hasta 1000 velas y tarda más o menos lo mismo); contar velas engañaría en los pares nuevos, que
    tienen menos historia que la ventana."""
    total = sum(s["pedidos"] for s in plan["series"])
    faltan = sum(s["faltan"] for s in plan["series"])
    hoyos = sum(s.get("huecos") or 0 for s in plan["series"])
    por_pedido = plan.get("segundos_por_pedido") or SEGUNDOS_POR_PEDIDO
    return {"formato": 1, "dias": plan["dias"], "estado": plan.get("estado") or "nunca", "etapa": plan.get("etapa") or ETAPAS[0],
            "etapas": [etapa_de(plan, t) for t in ETAPAS], "velas": sum(s["velas"] for s in plan["series"]),
            "esperadas": sum(s["esperadas"] for s in plan["series"]), "pedidos": total, "faltan": faltan,
            "pct": round(100 * (total - faltan) / total, 1) if total else 0, "huecos": hoyos, "continuo": not hoyos,
            "falta_segundos": int(faltan * por_pedido), "cuando": plan.get("cuando") or "", "error": plan.get("error") or "",
            "corriendo": bool(plan.get("corriendo")), "deteniendo": bool(plan.get("deteniendo"))}


# ── Continuidad: la revisión al terminar cada par ────────────────────────────────────────────────────────────────────────────

def continuidad(serie):
    """Revisa la serie con lo que hay **en disco**, paso por paso (hora por hora en `1h`), y deja anotado en el plan cuántos
    hoyos le quedaron. Devuelve los hoyos. Se mira el disco y no lo que se contó al pasar: eso es lo que de verdad va a leer
    el backtest."""
    velas = [v for v in lib_datos.leer_serie(serie["par"], serie["temporalidad"])
             if serie["inicio"] <= v[0] < serie["fin"]]
    hoyos = lib_datos.huecos(velas, serie["temporalidad"])
    serie.update({"velas": len(velas), "huecos": len(hoyos), "continua": not hoyos,
                  "desde": velas[0][0] if velas else None, "hasta": velas[-1][0] if velas else None})
    return hoyos


def rellenar(cliente, serie, hoyos, detener=None, al_avanzar=None):
    """Vuelve a pedir **solo** los tramos que quedaron sin velas: un pedido por hoyo, no la serie entera (lo que ya está no se
    baja de nuevo). Si Binance tampoco las tiene, el hoyo queda donde está: la historia que no existe no se inventa."""
    paso = lib_datos.PASO_MS[serie["temporalidad"]]
    pagina = (lambda avance: al_avanzar()) if al_avanzar is not None else None
    for hoyo in hoyos:
        if detener is not None and detener():
            break
        lib_datos.bajar_tramo(cliente, serie["par"], serie["temporalidad"], hoyo["desde"], hoyo["hasta"] + paso,
                              detener=detener, al_avanzar=pagina)


def revisar(cliente, serie, detener=None, al_avanzar=None):
    """Al terminar un par: la continuidad, un intento de rellenar lo que falte y la continuidad de nuevo. Un hoyo que
    sobrevive queda anotado (`huecos`) y la serie sin terminar, así la próxima vuelta lo reintenta sin bajar nada más."""
    hoyos = continuidad(serie)
    if hoyos:
        rellenar(cliente, serie, hoyos, detener=detener, al_avanzar=al_avanzar)
        continuidad(serie)
    serie["faltan"] = lib_datos.pedidos(serie["siguiente"], serie["fin"], serie["temporalidad"])
    serie["listo"] = serie["siguiente"] >= serie["fin"]
    return serie


# ── Las acciones ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def estado(d=None, ahora_ms=None):
    """En qué quedó, sin tocar la red: las velas que hay en disco y el estado del trabajo."""
    guardado = lib_trabajo.mirar(TIPO, lib_trabajo.leer_plan(TIPO))
    plan = armar(ahora_ms or lib_datos.ahora_local_ms(), guardado.get("dias") or lib_datos.DIAS_HISTORIAL, guardado)
    plan["corriendo"], plan["deteniendo"] = guardado["corriendo"], guardado["deteniendo"]
    if not plan["corriendo"]:
        lib_trabajo.guardar_plan(TIPO, plan)   # mientras el trabajo baja, el plan es suyo: no se le pisa
    return {"ok": True, "datos": resumen(plan)}


def descargar(d=None, cliente=None, ahora_ms=None, dias=lib_datos.DIAS_HISTORIAL, latir=True):
    """Baja (o sigue bajando) los 3 años, etapa por etapa. `cliente`, `ahora_ms`, `dias` y `latir` solo se pasan en las
    pruebas: la acción siempre habla con Binance y siempre son 3 años."""
    cliente = cliente or lib_datos.Binance()
    plan = armar(ahora_ms or cliente.ahora_ms(), dias, lib_trabajo.leer_plan(TIPO))
    t = lib_trabajo.nuevo(TIPO, ETAPAS, {"dias": dias}, latir=latir)
    plan.update({"estado": "corriendo", "trabajo": t.id, "error": "", "etapa": ETAPAS[0], "corriendo": True})
    reloj, paginas = time.monotonic(), [0]

    def avisar(pagina=False):
        """El avance, a los dos lados: el plan en disco y el evento de progreso que llega a la pantalla."""
        paginas[0] += 1 if pagina else 0
        if paginas[0]:
            plan["segundos_por_pedido"] = round(max(0.01, (time.monotonic() - reloj) / paginas[0]), 2)
        lib_trabajo.guardar_plan(TIPO, plan)
        lib_trabajo.publicar(t, resumen(plan))

    def anotar(serie, antes, avance, pagina=True):
        serie.update({"siguiente": avance["siguiente"], "velas": antes + avance["nuevas"],
                      "faltan": lib_datos.pedidos(avance["siguiente"], serie["fin"], serie["temporalidad"]),
                      "listo": avance["siguiente"] >= serie["fin"]})
        avisar(pagina)

    error = ""
    try:
        for temporalidad in ETAPAS:
            if t.detenido():
                break
            t.etapa(temporalidad)
            plan["etapa"] = temporalidad
            avisar()
            for serie in [s for s in plan["series"] if s["temporalidad"] == temporalidad and not terminada(s)]:
                if t.detenido():
                    break
                antes = serie["velas"]
                avance = lib_datos.bajar_tramo(cliente, serie["par"], temporalidad, serie["siguiente"], serie["fin"],
                                               detener=t.detenido, al_avanzar=lambda a, s=serie, v=antes: anotar(s, v, a))
                anotar(serie, antes, avance, pagina=False)
                if not t.detenido():
                    # Recién aquí el par está bajado: antes de pasar al siguiente se revisa que no le falte ninguna vela
                    # en medio y se rellena lo que falte (un par detenido a medias se revisa cuando se retome).
                    revisar(cliente, serie, detener=t.detenido, al_avanzar=lambda: avisar(True))
                    avisar()
    except (lib_datos.Limitado, lib_datos.Temporal, lib_datos.Respuesta) as e:
        error = lib_trabajo.codigo_de(e)
    detenido = t.detenido()
    plan.update({"error": error, "corriendo": False, "deteniendo": False,
                 "estado": lib_trabajo.terminar(t, error, detenido)})
    if not error and not detenido and any(not s["listo"] for s in plan["series"]):
        plan["estado"] = "detenido"     # nadie pidió parar y quedó algo: mejor decirlo que cantar victoria
    lib_trabajo.guardar_plan(TIPO, plan)
    return {"ok": not error, "datos": resumen(plan), "error": error}


def detener(d=None):
    """«Detener»: lo bajado queda guardado y «Seguir donde quedó» retoma desde ahí."""
    pedido = lib_trabajo.detener(TIPO)
    r = estado(d)
    r["datos"]["deteniendo"] = r["datos"]["deteniendo"] or pedido
    return r


if __name__ == "__main__":
    nucleo.script({"estado": estado, "descargar": descargar, "detener": detener}, __doc__)
