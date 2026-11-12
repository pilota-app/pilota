#!/usr/bin/env python3
"""muestreo — lo que Binance no guarda: el libro y los últimos trades, cada 5 minutos, y las velas de 1 m. Solo biblioteca estándar.

  muestreo.py estado <entrada.json {}> <salida.json>     → {ok, datos}
  muestreo.py encender <entrada.json {}> <salida.json>   → {ok, datos, error?}   (trabajo: avance y «Detener»)
  muestreo.py apagar <entrada.json {}> <salida.json>     → {ok, datos}

Binance **no da libro de órdenes histórico**: el mejor precio de compra y de venta de hoy, si no se guarda hoy, no se puede
recuperar nunca. Por eso este trabajo parte desde el primer día: cada 5 minutos guarda una muestra (mejor compra, mejor venta,
la diferencia entre las dos y los últimos trades) de los dos pares que se operan. Con 60 días de muestras propias, el backtest
reajusta su modelo de spread y de no llenado; hasta entonces usa un modelo conservador (eso es cosa de su propio paso).

Además mantiene al día las velas de 1 h, 4 h y 1 d (`velas_al_dia`: las que mira la prueba en vivo) y las de 1 m de los
últimos 30 días, que son las que ven los cruces de stop y objetivo en el modo
prueba y las que se recorren al despertar para reconciliar.

Lo que no se negocia aquí:
- **Una muestra guardada no se toca nunca más** (`lib_datos.guardar_muestra`: una línea al final del archivo del mes).
- **Solo velas cerradas**, y la ventana de 1 m se corre: 30 días y lo anterior se suelta.
- **El reloj que manda es el de Binance** (`cliente.ahora_ms()`), no el del computador.
- **Una vuelta que falla no termina el muestreo.** Lo que no se guarde hoy no existe mañana, así que un tropezón de red o un
  límite de Binance se anota (`fallos`, `error`) y en 5 minutos se vuelve a intentar. Recién a las `FALLOS_SEGUIDOS` vueltas
  malas seguidas se da por vencido y lo dice; una vuelta buena borra la cuenta.
- **El hueco queda escrito.** La muestra que no se tomó no se va a poder recuperar, así que cada ventana sin muestras queda
  anotada en el plan (`sin_cobertura`: desde cuándo, hasta cuándo, cuántas vueltas y por qué). Las vueltas malas seguidas son
  un solo hueco, y la primera vuelta buena lo cierra. Más adelante el backtest tiene que saber qué tramos no tienen libro.
- **En prueba esto solo corre con el motor encendido**: la pantalla lo dice y el ciclo deja escrito cuándo fue la última vuelta.

Dónde queda: `<datos>/mercado/muestreo.json` (el plan con el avance), `<datos>/mercado/muestras/<AAAA-MM>.jsonl` (las muestras)
y las velas de 1 m, donde siempre (`<datos>/mercado/velas/<PAR>-1m.json`).
"""
import time

import lib_candado
import lib_datos
import lib_trabajo
import nucleo

TIPO = "muestreo"
#: Una muestra cada 5 minutos: el mismo ritmo con el que revisa el motor.
CICLO_SEGUNDOS = 300
#: Primero se llenan las velas de 1 m (eso tarda); después solo se muestrea y se agrega lo nuevo.
ETAPAS = ("minutos", "muestras")
SEGUNDOS_POR_PEDIDO = 0.8
#: Cuántas vueltas seguidas pueden salir mal antes de darse por vencido: una muestra perdida no se recupera, así que vale
#: mucho más seguir intentando que terminar el trabajo con el primer tropezón de red.
FALLOS_SEGUIDOS = 3
#: Cuántas ventanas sin muestras se guardan en el plan: las últimas, para que el archivo no crezca sin fin.
HUECOS_GUARDADOS = 50


def armar(ahora_ms, dias=lib_datos.DIAS_MINUTOS, antes=None):
    """El plan: cómo van las velas de 1 m de cada par operado y qué se lleva muestreado."""
    antes = antes or {}
    viejas = {s.get("par"): s for s in (antes.get("minutos") or []) if isinstance(s, dict)}
    paso = lib_datos.PASO_MS[lib_datos.MINUTO]
    fin = (ahora_ms // paso) * paso
    inicio = fin - dias * lib_datos.DIA_MS
    minutos = []
    for par in lib_datos.PARES_OPERADOS:
        velas = [v for v in lib_datos.leer_serie(par, lib_datos.MINUTO) if inicio <= v[0] < fin]
        quedo = (viejas.get(par) or {}).get("siguiente")
        siguiente = quedo if isinstance(quedo, int) and inicio <= quedo <= fin else inicio
        siguiente = min(fin, max(siguiente, lib_datos.fin_continuo(velas, lib_datos.MINUTO, inicio)))
        minutos.append({"par": par, "inicio": inicio, "fin": fin, "siguiente": siguiente, "velas": len(velas),
                        "esperadas": dias * lib_datos.DIA_MS // paso, "huecos": len(lib_datos.huecos(velas, lib_datos.MINUTO)),
                        "desde": velas[0][0] if velas else None, "hasta": velas[-1][0] if velas else None,
                        "pedidos": lib_datos.pedidos(inicio, fin, lib_datos.MINUTO),
                        "faltan": lib_datos.pedidos(siguiente, fin, lib_datos.MINUTO), "listo": siguiente >= fin})
    plan = {"formato": 1, "dias": dias, "estado": "nunca", "etapa": ETAPAS[0], "trabajo": "", "error": "",
            "segundos_por_pedido": 0, "cuando": "", "muestras": 0, "ciclos": 0, "ultima": None, "proxima": 0,
            "fallos": 0, "sin_cobertura": []}
    # Del plan viejo se guarda lo que se lleva hecho (las muestras, la última, los huecos, en qué quedó); la ventana se
    # recalcula.
    plan.update({k: v for k, v in antes.items() if k in plan and k not in ("formato", "dias")})
    plan["sin_cobertura"] = huecos_de(plan)
    plan["minutos"] = minutos
    return plan


def huecos_de(plan):
    """Las ventanas sin muestras que trae el plan, ya limpias: el archivo lo pudo haber tocado cualquiera."""
    lista = plan.get("sin_cobertura")
    if not isinstance(lista, list):
        return []
    return [h for h in lista if isinstance(h, dict) and isinstance(h.get("desde"), int)][-HUECOS_GUARDADOS:]


def resumen(plan):
    """Lo que ve la pantalla: cómo van las velas de 1 m (con su porcentaje y el tiempo que falta), la última muestra y cuántas
    se llevan guardadas."""
    total = sum(s["pedidos"] for s in plan["minutos"])
    faltan = sum(s["faltan"] for s in plan["minutos"])
    por_pedido = plan.get("segundos_por_pedido") or SEGUNDOS_POR_PEDIDO
    meses = lib_datos.meses_con_muestras()
    return {"formato": 1, "dias": plan["dias"], "ciclo_segundos": CICLO_SEGUNDOS, "estado": plan.get("estado") or "nunca",
            "etapa": plan.get("etapa") or ETAPAS[0], "minutos": [dict(s) for s in plan["minutos"]],
            "velas": sum(s["velas"] for s in plan["minutos"]), "esperadas": sum(s["esperadas"] for s in plan["minutos"]),
            "pedidos": total, "faltan": faltan, "pct": round(100 * (total - faltan) / total, 1) if total else 0,
            "falta_segundos": int(faltan * por_pedido), "muestras": int(plan.get("muestras") or 0),
            "ciclos": int(plan.get("ciclos") or 0), "fallos": int(plan.get("fallos") or 0),
            "sin_cobertura": [dict(h) for h in huecos_de(plan)],
            "mes_desde": meses[0] if meses else "", "meses": len(meses),
            "ultima": plan.get("ultima"), "proxima": int(plan.get("proxima") or 0), "cuando": plan.get("cuando") or "",
            "error": plan.get("error") or "", "corriendo": bool(plan.get("corriendo")),
            "deteniendo": bool(plan.get("deteniendo"))}


# ── Un ciclo ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def muestrear(cliente, ahora_ms, guardadas=None):
    """Una muestra de cada par operado, guardada al tiro. Va primero en el ciclo: el libro es de este momento y no espera.

    Si el segundo par no se puede pedir, el primero ya quedó en disco: `guardadas` (una lista) recibe las que alcanzaron a
    guardarse, para que el ciclo que falló a medias no las cuente de menos."""
    pares = []
    for par in lib_datos.PARES_OPERADOS:
        libro = cliente.libro(par)
        trades = cliente.trades(par)
        lib_datos.guardar_muestra({"ms": ahora_ms, "par": par, **libro, "trades": trades})
        pares.append({"par": par, **libro, "trades": len(trades),
                      "ultimo": trades[-1][1] if trades else None})
        if guardadas is not None:
            guardadas.append(pares[-1])
    return {"cuando": lib_datos.iso(ahora_ms), "ms": ahora_ms, "pares": pares}


def abrir_hueco(plan, ms, error):
    """Anota la ventana que se queda sin muestras. Las vueltas malas seguidas son un solo hueco (se alarga el de arriba);
    empieza donde quedó la última muestra buena, que es desde cuándo no hay libro guardado."""
    huecos = huecos_de(plan)
    if huecos and huecos[-1].get("abierto"):
        huecos[-1].update({"hasta": max(ms, int(huecos[-1]["desde"])), "ciclos": int(huecos[-1].get("ciclos") or 0) + 1,
                           "error": error})
    else:
        desde = (plan.get("ultima") or {}).get("ms")
        desde = int(desde) if isinstance(desde, int) else ms
        huecos.append({"desde": desde, "hasta": max(ms, desde), "ciclos": 1, "error": error, "abierto": True})
    plan["sin_cobertura"] = huecos[-HUECOS_GUARDADOS:]
    return plan


def cerrar_hueco(plan, ms):
    """La primera vuelta buena cierra el hueco: desde aquí vuelve a haber muestras."""
    huecos = huecos_de(plan)
    if huecos and huecos[-1].get("abierto"):
        huecos[-1].update({"hasta": max(ms, int(huecos[-1]["desde"])), "abierto": False})
    plan["sin_cobertura"] = huecos
    return plan


def minutos_al_dia(cliente, plan, al_avanzar=None, detener=None):
    """Pone al día las velas de 1 m de los últimos días y suelta las que se salieron de la ventana."""
    for serie in plan["minutos"]:
        if detener is not None and detener():
            break
        if serie["listo"]:
            continue
        antes = serie["velas"]
        avance = lib_datos.bajar_tramo(cliente, serie["par"], lib_datos.MINUTO, serie["siguiente"], serie["fin"],
                                       detener=detener, recortar_desde=serie["inicio"],
                                       al_avanzar=lambda a, s=serie, v=antes: _anotar(s, v, a, al_avanzar))
        _anotar(serie, antes, avance, al_avanzar, pagina=False)
    return plan


def _anotar(serie, antes, avance, al_avanzar, pagina=True):
    serie.update({"siguiente": avance["siguiente"], "velas": antes + avance["nuevas"],
                  "faltan": lib_datos.pedidos(avance["siguiente"], serie["fin"], lib_datos.MINUTO),
                  "listo": avance["siguiente"] >= serie["fin"]})
    if al_avanzar is not None:
        al_avanzar(pagina)


# ── Las acciones ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def velas_al_dia(cliente, ahora_ms):
    """Las velas de 1 h, 4 h y 1 d de los cuatro pares, al día: solo se pide la serie que ya tiene una vela nueva cerrada.
    Así la prueba en vivo decide con la última vela de verdad, no con la del día en que se bajó el historial."""
    nuevas = 0
    for par in lib_datos.PARES:
        for t in lib_datos.TEMPORALIDADES:
            paso = lib_datos.PASO_MS[t]
            velas = lib_datos.leer_serie(par, t)
            if velas and velas[-1][0] + 2 * paso > ahora_ms:
                continue                       # la última cerrada ya está guardada
            nuevas += lib_datos.bajar_serie(cliente, par, t, ahora_ms=ahora_ms)
    return nuevas


def estado(d=None, ahora_ms=None):
    """En qué quedó, sin tocar la red."""
    guardado = lib_trabajo.mirar(TIPO, lib_trabajo.leer_plan(TIPO))
    plan = armar(ahora_ms or lib_datos.ahora_local_ms(), guardado.get("dias") or lib_datos.DIAS_MINUTOS, guardado)
    plan["corriendo"], plan["deteniendo"] = guardado["corriendo"], guardado["deteniendo"]
    if not plan["corriendo"]:
        lib_trabajo.guardar_plan(TIPO, plan)
    return {"ok": True, "datos": resumen(plan)}


def encender(d=None, cliente=None, ahora_ms=None, dias=lib_datos.DIAS_MINUTOS, dormir=time.sleep, ciclos=0, latir=True):
    """Uno solo a la vez: si ya hay uno corriendo (otra ventana de la app, o uno que quedó vivo), este no parte."""
    try:
        with lib_candado.unico(TIPO):
            return _encender(d, cliente, ahora_ms, dias, dormir, ciclos, latir)
    except lib_candado.YaCorriendo:
        return {"ok": False, "datos": estado(d)["datos"], "error": "ya_corriendo"}


def _encender(d=None, cliente=None, ahora_ms=None, dias=lib_datos.DIAS_MINUTOS, dormir=time.sleep, ciclos=0, latir=True):
    """Muestrea cada `CICLO_SEGUNDOS` hasta que le pidan parar. Todo lo que no es `d` solo se pasa en las pruebas (`ciclos`
    corta después de unas vueltas; la acción no corta sola: la corta «Detener» o el cierre de la app)."""
    cliente = cliente or lib_datos.Binance()
    try:
        inicial = ahora_ms or cliente.ahora_ms()
    except (lib_datos.Limitado, lib_datos.Temporal, lib_datos.Respuesta):
        inicial = lib_datos.ahora_local_ms()   # Binance no contesta justo ahora: el trabajo parte igual y lo dice en la vuelta
    plan = armar(inicial, dias, lib_trabajo.leer_plan(TIPO))
    t = lib_trabajo.nuevo(TIPO, ETAPAS, {"ciclo_segundos": CICLO_SEGUNDOS, "dias": dias}, latir=latir)
    plan.update({"estado": "corriendo", "trabajo": t.id, "error": "", "corriendo": True})
    reloj, paginas, vuelta = time.monotonic(), [0], 0

    def anotar(pagina=True):
        paginas[0] += 1 if pagina else 0
        if paginas[0]:
            plan["segundos_por_pedido"] = round(max(0.01, (time.monotonic() - reloj) / paginas[0]), 2)
        lib_trabajo.guardar_plan(TIPO, plan)
        lib_trabajo.publicar(t, resumen(plan))

    error = ""
    while not t.detenido() and not (ciclos and vuelta >= ciclos) and not lib_candado.huerfano():
        vuelta += 1
        guardadas, muestreada = [], False
        try:
            ahora = ahora_ms or cliente.ahora_ms()
            plan.update(armar(ahora, dias, plan))      # la ventana se corre con la hora de Binance
            muestra = muestrear(cliente, ahora, guardadas)
            muestreada = True
            plan.update({"ultima": muestra, "muestras": int(plan.get("muestras") or 0) + len(muestra["pares"]),
                         "ciclos": int(plan.get("ciclos") or 0) + 1, "fallos": 0, "error": "",
                         "proxima": ahora + CICLO_SEGUNDOS * 1000, "corriendo": True})
            cerrar_hueco(plan, ahora)                  # si venía de un tropezón, aquí termina la ventana sin muestras
            t.etapa(ETAPAS[1] if all(s["listo"] for s in plan["minutos"]) else ETAPAS[0])
            plan["etapa"] = t.x["etapa"]
            anotar(pagina=False)
            minutos_al_dia(cliente, plan, al_avanzar=anotar, detener=t.detenido)
            plan["velas_nuevas"] = velas_al_dia(cliente, ahora)
            plan["etapa"] = ETAPAS[1] if all(s["listo"] for s in plan["minutos"]) else ETAPAS[0]
            anotar(pagina=False)
        except (lib_datos.Limitado, lib_datos.Temporal, lib_datos.Respuesta) as e:
            # Esta vuelta no resultó: se anota y se vuelve a intentar en el próximo ciclo. La hora es la de este computador
            # (es una espera local, no una vela), porque la de Binance es justo lo que no se pudo preguntar.
            fallos = int(plan.get("fallos") or 0) + 1
            ms = ahora_ms or lib_datos.ahora_local_ms()
            plan.update({"fallos": fallos, "error": lib_trabajo.codigo_de(e), "corriendo": True,
                         "proxima": ms + CICLO_SEGUNDOS * 1000})
            if not muestreada:
                # La muestra de este momento se perdió para siempre: queda escrito el hueco. Lo que alcanzó a guardarse
                # antes de cortarse (el primer par) se cuenta igual, que ya está en disco. Si el que falló fue el historial
                # de 1 m, no hay hueco que anotar: esas velas se vuelven a pedir donde quedaron.
                plan["muestras"] = int(plan.get("muestras") or 0) + len(guardadas)
                abrir_hueco(plan, ms, plan["error"])
            anotar(pagina=False)
            if fallos >= FALLOS_SEGUIDOS:
                error = plan["error"]
                break
        if ciclos and vuelta >= ciclos:
            break
        lib_trabajo.esperar(CICLO_SEGUNDOS, dormir=dormir, detenido=t.detenido)
    detenido = t.detenido()
    plan.update({"error": error, "corriendo": False, "deteniendo": False,
                 "estado": lib_trabajo.terminar(t, error, detenido)})
    lib_trabajo.guardar_plan(TIPO, plan)
    return {"ok": not error, "datos": resumen(plan), "error": error}


def apagar(d=None):
    """«Detener»: deja de muestrear. Lo guardado queda; la ventana de 1 m se vuelve a poner al día cuando se encienda."""
    pedido = lib_trabajo.detener(TIPO)
    r = estado(d)
    r["datos"]["deteniendo"] = r["datos"]["deteniendo"] or pedido
    return r


if __name__ == "__main__":
    nucleo.script({"estado": estado, "encender": encender, "apagar": apagar}, __doc__)
