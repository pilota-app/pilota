#!/usr/bin/env python3
"""vivo — el robot en vivo: elige perfil y monto, conéctate a Binance y míralo operar al segundo. Solo biblioteca estándar.

  vivo.py estado   <entrada.json {}>                      <salida.json>   → {ok, datos}
  vivo.py empezar  <entrada.json {perfil, monto}>         <salida.json>   → {ok, datos, error?}
  vivo.py detener  <entrada.json {}>                      <salida.json>   → {ok, datos}
  vivo.py encender <entrada.json {}>                      <salida.json>   → {ok, datos, error?}   (trabajo: el flujo en vivo)
  vivo.py apagar   <entrada.json {}>                      <salida.json>   → {ok, datos}
  vivo.py grafico  <entrada.json {par, temporalidad}>     <salida.json>   → {ok, datos}

`encender` es el corazón: abre el flujo de Binance (`lib_flujo`) y se queda escuchando. Cada segundo publica el precio y la
vela en curso (el evento `vivoProgreso`). Cuando cierra una vela de 1 minuto, la guarda, pone al día las de 1 h, 4 h y 1 d si
también cerró alguna y hace una revisión completa en ese mismo instante (`lib_reconciliar.reconciliar` con el gancho
`lib_piloto.decidir`): llenados, stops, objetivos, frenos y las entradas del perfil. Lo que pasó viaja en el mismo evento
(`eventos`), así la pantalla lo muestra al tiro.

Lo que no se negocia aquí:
- **Uno solo a la vez** (`lib_candado.unico`) y **una revisión a la vez** (el candado de `reconciliar`): el motor de cada 5
  minutos y el flujo pueden convivir sin pisarse.
- **Se decide con velas cerradas, igual que en el pasado.** La vela en curso se muestra, pero no decide nada: el robot reacciona
  en el instante en que cierra, no antes.
- **Si la app se cierra de golpe, el trabajo termina solo** (`lib_candado.huerfano`): nunca queda un robot suelto.
- **Si el flujo se cae, se vuelve a conectar** con una espera que crece hasta `ESPERA_MAXIMA`, y la pantalla lo dice.
"""
import time

import lib_candado
import lib_datos
import lib_ejecutor_prueba
import lib_estado
import lib_flujo
import lib_perfiles
import lib_piloto
import lib_reconciliar
import lib_registro
import lib_trabajo
import muestreo
import nucleo

TIPO = "vivo"
ETAPAS = ("conectando", "en_vivo")
MINUTO_MS = lib_datos.PASO_MS[lib_datos.MINUTO]
#: Cada cuánto se avisa a la pantalla, como mucho (Binance manda la vela de 1 s cada segundo).
PUBLICAR_CADA = 1.0
ESPERA_MAXIMA = 30
#: Si una vela de 1 m cerró en un par y el otro no avisa, la revisión se hace igual después de este rato.
ESPERA_PAR_MS = 5000
#: Las temporalidades del gráfico y cuántas velas se mandan de cada una.
TEMPORALIDADES_GRAFICO = ("1m", "5m", "1h", "4h")
VELAS_GRAFICO = 260
#: Qué líneas del registro son una compra o una venta en el gráfico.
COMPRAS = ("entrada_ruptura", "entrada_rebote", "compra_holding")
VENTAS = ("objetivo", "stop", "stop_movil", "cierre_manual")


def _ms():
    return lib_datos.ahora_local_ms()


def flujo_estado():
    """Si el flujo está corriendo y conectado, sin tocar la red."""
    plan = lib_trabajo.mirar(TIPO, lib_trabajo.leer_plan(TIPO))
    return {"corriendo": bool(plan.get("corriendo")), "conectado": bool(plan.get("corriendo") and plan.get("conectado")),
            "estado": plan.get("estado") or "", "error": plan.get("error") or "",
            "reconexiones": int(plan.get("reconexiones") or 0), "revision_ms": int(plan.get("revision_ms") or 0)}


def estado(d=None, ahora_ms=None):
    return {"ok": True, "datos": {**lib_piloto.estado(ahora_ms), "flujo": flujo_estado()}}


def empezar(d=None, ahora_ms=None):
    d = d if isinstance(d, dict) else {}
    r = lib_piloto.empezar(d.get("perfil"), d.get("monto"), ahora_ms)
    if not r["ok"]:
        return {"ok": False, "error": r["error"], "datos": estado(None, ahora_ms)["datos"]}
    return estado(None, ahora_ms)


def detener(d=None, ahora_ms=None):
    lib_piloto.detener(ahora_ms)
    return estado(None, ahora_ms)


def apagar(d=None, ahora_ms=None):
    lib_trabajo.detener(TIPO)
    return estado(None, ahora_ms)


# ── El flujo en vivo ─────────────────────────────────────────────────────────────────────────────────────────────────

def con_vela(formandose, v):
    """La vela de 1 m en curso de un par, puesta al día con un mensaje del flujo (de 1 s o de 1 m). Pura."""
    inicio = v["t"] // MINUTO_MS * MINUTO_MS
    actual = formandose.get(v["par"])
    if v["intervalo"] == "1m":
        return [v["t"], v["o"], v["h"], v["l"], v["c"], v["v"]]
    if actual is None or actual[0] < inicio:
        return [inicio, v["o"], v["h"], v["l"], v["c"], 0.0]
    if actual[0] > inicio:
        return actual                       # un segundo atrasado: la vela de este minuto ya se pasó
    return [actual[0], actual[1], max(actual[2], v["h"]), min(actual[3], v["l"]), v["c"], actual[5]]


def guardar_minuto(cliente, v):
    """Agrega a lo guardado la vela de 1 m que acaba de cerrar. Si falta alguna antes (el flujo se cortó), se piden a la API
    las que falten: la serie de 1 m es la que dice qué se cruzó, y no puede tener hoyos."""
    par = v["par"]
    velas = lib_datos.leer_serie(par, lib_datos.MINUTO)
    nueva = [v["t"], v["o"], v["h"], v["l"], v["c"], v["v"]]
    if velas and velas[-1][0] >= v["t"]:
        if velas[-1][0] == v["t"]:
            velas[-1] = nueva
            lib_datos.guardar_serie(par, lib_datos.MINUTO, velas)
        return 0
    if velas and velas[-1][0] + MINUTO_MS == v["t"]:
        lib_datos.guardar_serie(par, lib_datos.MINUTO, [*velas, nueva])
        return 1
    try:
        return lib_datos.bajar_serie(cliente, par, lib_datos.MINUTO, dias=lib_datos.DIAS_MINUTOS,
                                     ahora_ms=v["t"] + MINUTO_MS)
    except (lib_datos.Limitado, lib_datos.Temporal, lib_datos.Respuesta):
        return 0


def eventos_desde(ambiente, desde_ms):
    """Las líneas del registro posteriores a `desde_ms`, de la más vieja a la más nueva."""
    lineas, _ = lib_registro.ultimas(ambiente, 50)
    return [x for x in reversed(lineas) if int(x.get("ms") or 0) > desde_ms]


def revisar(cliente, ms, desde_ms):
    """La revisión del instante en que cerró una vela: las velas largas al día, reconciliar y decidir. Devuelve lo que pasó."""
    try:
        muestreo.velas_al_dia(cliente, ms)
    except (lib_datos.Limitado, lib_datos.Temporal, lib_datos.Respuesta):
        pass                                 # sin las velas largas la decisión dice «sin_datos»: no se inventa nada
    resumen = {}
    try:
        r = lib_reconciliar.reconciliar(ms, decidir=lib_piloto.decidir)
        resumen = (r or {}).get("resumen") or {}
    except (OSError, lib_candado.Ocupado):
        pass
    amb = lib_estado.activo()
    return {"eventos": eventos_desde(amb, desde_ms), "piloto": resumen.get("piloto") or resumen.get("modos") or {}}


def encender(d=None, flujo=None, cliente=None, ciclos=0, latir=True, reloj=time.monotonic, dormir=time.sleep):
    """Uno solo a la vez. Todo lo que no es `d` solo se pasa en las pruebas (`ciclos` corta después de esas conexiones)."""
    try:
        with lib_candado.unico(TIPO):
            return _encender(flujo, cliente, ciclos, latir, reloj, dormir)
    except lib_candado.YaCorriendo:
        return {"ok": False, "datos": estado()["datos"], "error": "ya_corriendo"}


def _encender(flujo, cliente, ciclos, latir, reloj, dormir):
    t = lib_trabajo.nuevo(TIPO, ETAPAS, {}, latir=latir)
    plan = {"formato": 1, "estado": "corriendo", "trabajo": t.id, "conectado": False, "reconexiones": 0, "error": "",
            "revision_ms": 0}
    lib_trabajo.guardar_plan(TIPO, plan)
    cliente = cliente or lib_datos.Binance()
    flujo = flujo or lib_flujo.Flujo()
    formandose, cerradas, visto = {}, {}, _ms()
    ultimo_pub, espera, conexiones = [0.0], 1, 0

    def publicar(eventos=None, piloto=None, vivo=None, forzar=False):
        if not forzar and not eventos and reloj() - ultimo_pub[0] < PUBLICAR_CADA:
            return
        ultimo_pub[0] = reloj()
        avance = {"estado": plan["estado"], "conectado": plan["conectado"], "error": plan["error"],
                  "reconexiones": plan["reconexiones"], "ms": _ms(), "revision_ms": plan["revision_ms"],
                  "velas": {par: v for par, v in formandose.items()}, "eventos": eventos or [],
                  "piloto": piloto or {}}
        if vivo is not None:
            avance["vivo"] = vivo
        lib_trabajo.publicar(t, avance)

    def revision(ms):
        nonlocal visto
        r = revisar(cliente, ms, visto)
        if r["eventos"]:
            visto = max(int(x.get("ms") or 0) for x in r["eventos"])
        plan["revision_ms"] = ms
        lib_trabajo.guardar_plan(TIPO, plan)
        publicar(r["eventos"], r["piloto"], vivo={**lib_piloto.estado(ms), "flujo": flujo_estado()}, forzar=True)

    while not t.detenido() and not lib_candado.huerfano() and not (ciclos and conexiones >= ciclos):
        conexiones += 1
        try:
            flujo.conectar()
            plan.update(conectado=True, error="")
            t.etapa(ETAPAS[1])
            revision(_ms())                  # al conectar, ponerse al día con lo que pasó mientras no mirábamos
            espera = 1
            for v in flujo.velas(detenido=t.detenido):
                formandose[v["par"]] = con_vela(formandose, v)
                if v["intervalo"] == "1m" and v["cerrada"]:
                    guardar_minuto(cliente, v)
                    cerradas.setdefault(v["t"], set()).add(v["par"])
                # Cuando cerró el minuto en los dos pares (o uno ya esperó bastante), se revisa al tiro.
                for minuto in sorted(cerradas):
                    listos = cerradas[minuto]
                    if len(listos) >= len(lib_datos.PARES_OPERADOS) or _ms() - (minuto + MINUTO_MS) > ESPERA_PAR_MS:
                        del cerradas[minuto]
                        revision(minuto + MINUTO_MS)
                publicar()
                if lib_candado.huerfano():
                    break
        except lib_flujo.Caido as e:
            plan.update(conectado=False, error=str(e) or "red", reconexiones=plan["reconexiones"] + 1)
            lib_trabajo.guardar_plan(TIPO, plan)
            publicar(forzar=True)
            if ciclos and conexiones >= ciclos:
                break
            lib_trabajo.esperar(espera, dormir=dormir, detenido=t.detenido, trozo=1)
            espera = min(ESPERA_MAXIMA, espera * 2)
        finally:
            flujo.cerrar()
            plan["conectado"] = False
    detenido = t.detenido()
    plan.update({"conectado": False, "estado": lib_trabajo.terminar(t, "", detenido)})
    lib_trabajo.guardar_plan(TIPO, plan)
    return {"ok": True, "datos": estado()["datos"]}


# ── El gráfico ───────────────────────────────────────────────────────────────────────────────────────────────────────

def velas_grafico(par, temporalidad):
    if temporalidad == "1m":
        return lib_datos.leer_serie(par, lib_datos.MINUTO)[-VELAS_GRAFICO:]
    if temporalidad in lib_perfiles.AGRUPADAS:
        n = lib_perfiles.AGRUPADAS[temporalidad]
        return lib_perfiles.agrupar(lib_datos.leer_serie(par, lib_datos.MINUTO)[-VELAS_GRAFICO * n - n:], n)[-VELAS_GRAFICO:]
    return lib_datos.leer_serie(par, temporalidad)[-VELAS_GRAFICO:]


def marcas_de(par, desde_ms, lineas=None):
    """Las compras y las ventas de ese par en el registro de la cuenta activa, para dibujarlas sobre las velas."""
    if lineas is None:
        lineas, _ = lib_registro.ultimas(lib_estado.activo(), 2000)
    salida = []
    for x in lineas:
        if x.get("par") != par or int(x.get("ms") or 0) < desde_ms:
            continue
        o, r = x.get("orden") or {}, x.get("resultado") or {}
        if x.get("razon") in COMPRAS and (x["razon"] == "compra_holding" or o.get("estado") == "llenada"):
            salida.append({"ms": x["ms"], "tipo": "compra", "precio": o.get("precio")})
        elif x.get("razon") in VENTAS:
            salida.append({"ms": x["ms"], "tipo": "venta", "precio": r.get("precio") or o.get("precio"),
                           "neto": r.get("neto"), "por": x["razon"]})
    return sorted(salida, key=lambda m: m["ms"])


def niveles_de(par):
    """Las líneas de lo que está abierto o esperando en ese par: la entrada, el stop y el objetivo."""
    salida = []
    for p in (lib_ejecutor_prueba.guardado().get("posiciones") or []):
        if p.get("par") != par:
            continue
        if p.get("estado") == lib_ejecutor_prueba.PUESTA:
            salida.append({"tipo": "espera", "precio": p.get("precio")})
        elif p.get("estado") == lib_ejecutor_prueba.ABIERTA:
            salida += [{"tipo": "entrada", "precio": p.get("precio")}, {"tipo": "stop", "precio": p.get("stop")},
                       {"tipo": "objetivo", "precio": p.get("objetivo")}]
    return [n for n in salida if isinstance(n.get("precio"), (int, float)) and n["precio"] > 0]


def grafico(d=None, ahora_ms=None):
    d = d if isinstance(d, dict) else {}
    par = d.get("par") if d.get("par") in lib_datos.PARES_OPERADOS else lib_datos.PARES_OPERADOS[0]
    temporalidad = d.get("temporalidad") if d.get("temporalidad") in TEMPORALIDADES_GRAFICO else "1m"
    velas = velas_grafico(par, temporalidad)
    return {"ok": True, "datos": {"par": par, "temporalidad": temporalidad, "paso_ms": lib_datos.PASO_MS[temporalidad],
                                  "velas": velas, "marcas": marcas_de(par, velas[0][0] if velas else 0),
                                  "niveles": niveles_de(par)}}


if __name__ == "__main__":
    nucleo.script({"estado": estado, "empezar": empezar, "detener": detener, "encender": encender, "apagar": apagar,
                   "grafico": grafico}, __doc__)
