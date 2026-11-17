#!/usr/bin/env python3
"""motor — el motor de Pilota: revisa cada 5 minutos y reconcilia al arrancar y al despertar. Solo biblioteca estándar.

  motor.py estado   <entrada.json {}> <salida.json>   → {ok, datos}
  motor.py revisar  <entrada.json {}> <salida.json>   → {ok, datos}
  motor.py encender <entrada.json {}> <salida.json>   → {ok, datos, error?}   (trabajo: avance y «Detener»)
  motor.py apagar   <entrada.json {}> <salida.json>   → {ok, datos}

Ninguna toca la red: todo sale del estado firmado de cada cuenta, de las velas de 1 m que ya están en disco (las trae el
muestreo) y del registro que no se borra.

El motor es **el equipo donde corre Pilota**: si está apagado, nadie mira los cruces. `estado` dice en qué quedó —cuándo
fue la última revisión y hace cuántos minutos, si está activo o dormido, cuándo viene la próxima— sin reconciliar nada.

`revisar` es una revisión, y al arrancar o al despertar esa misma revisión **reconcilia** la ventana que nadie miró
(`bin/lib_reconciliar.py`): aplica los frenos, recorre las velas de 1 m perdidas con sus stops y objetivos cruzados,
repone la protección donde el stop móvil la movió, cancela la entrada que venció, cierra lo huérfano, deja escrita la
ventana sin cobertura y devuelve el resumen de lo que pasó («Dormiste 9 h: 1 stop, 2 propuestas vencidas»). Si las velas
que faltaban todavía no están en disco, la ventana queda abierta y la revisión siguiente la vuelve a mirar: el rato en
que un stop no se habría aplicado se dice, nunca se tapa.

`encender` es lo mismo cada `CICLO_SEGUNDOS` hasta que le pidan parar, como trabajo (pieza «trabajos»): la primera vuelta
reconcilia y las siguientes vigilan. `apagar` es «Detener»: lo que esté abierto mantiene su protección, pero en prueba esa
protección existe solo con el motor encendido y la pantalla lo dice.

Cuándo entrar lo deciden los tres modos (`bin/lib_modos.py`): el motor deja el mundo al día y les pasa el contexto, y
ellos proponen y esperan el «Sí» (manual), operan solo si el puntaje es claramente alto (semiautomático) u operan solo
(automático). En esa misma vuelta vencen las propuestas que nadie respondió.
"""
import time

import lib_candado
import lib_datos
import lib_piloto
import lib_reconciliar
import lib_trabajo
import nucleo


def estado(d=None, ahora_ms=None):
    """`ahora_ms` solo se pasa en las pruebas (una hora fija): la acción siempre mira con la hora de ahora."""
    return {"ok": True, "datos": lib_reconciliar.estado(ahora_ms)}


def revisar(d=None, ahora_ms=None):
    """Una revisión ahora mismo: reconcilia la ventana que nadie miró, deja aplicado lo que pasó y, con el mundo al día,
    los tres modos deciden (`lib_modos.decidir`)."""
    return {"ok": True, "datos": lib_reconciliar.reconciliar(ahora_ms, decidir=lib_piloto.decidir)}


def encender(d=None, ahora_ms=None, dormir=time.sleep, ciclos=0, latir=True):
    """Uno solo a la vez: si ya hay uno corriendo (otra ventana de la app, o uno que quedó vivo), este no parte."""
    try:
        with lib_candado.unico(lib_reconciliar.TIPO):
            return _encender(d, ahora_ms, dormir, ciclos, latir)
    except lib_candado.YaCorriendo:
        return {"ok": False, "datos": estado(d)["datos"], "error": "ya_corriendo"}


def _encender(d=None, ahora_ms=None, dormir=time.sleep, ciclos=0, latir=True):
    """Revisa cada `CICLO_SEGUNDOS` hasta que le pidan parar. Todo lo que no es `d` solo se pasa en las pruebas (`ciclos`
    corta después de unas vueltas; la acción no corta sola: la corta «Detener» o el cierre de la app)."""
    inicial = ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms()
    plan = lib_reconciliar.armar(inicial, lib_trabajo.leer_plan(lib_reconciliar.TIPO))
    t = lib_trabajo.nuevo(lib_reconciliar.TIPO, lib_reconciliar.ETAPAS,
                          {"ciclo_segundos": lib_reconciliar.CICLO_SEGUNDOS}, latir=latir)
    plan.update({"estado": "corriendo", "trabajo": t.id, "error": "", "corriendo": True})
    error, vuelta = "", 0
    while not t.detenido() and not (ciclos and vuelta >= ciclos) and not lib_candado.huerfano():
        vuelta += 1
        try:
            datos = lib_reconciliar.reconciliar(ahora_ms, plan=plan, decidir=lib_piloto.decidir)
            plan.update(lib_reconciliar.armar(datos["ultima_ms"], lib_trabajo.leer_plan(lib_reconciliar.TIPO)))
            plan.update({"estado": "corriendo", "trabajo": t.id, "fallos": 0, "error": "", "corriendo": True})
            # La primera vuelta es la que reconcilia lo que nadie miró; de ahí en adelante solo vigila.
            t.etapa(lib_reconciliar.ETAPAS[1])
            plan["etapa"] = t.x["etapa"]
            lib_trabajo.guardar_plan(lib_reconciliar.TIPO, plan)
            lib_trabajo.publicar(t, datos)
        except OSError:
            # Un problema para leer o escribir en disco: se anota y se vuelve a intentar en el próximo ciclo. Recién a
            # las `FALLOS_SEGUIDOS` vueltas malas seguidas el trabajo se da por vencido.
            fallos = int(plan.get("fallos") or 0) + 1
            plan.update({"fallos": fallos, "error": "archivo", "corriendo": True})
            lib_trabajo.guardar_plan(lib_reconciliar.TIPO, plan)
            lib_trabajo.publicar(t, lib_reconciliar.vista(plan, ahora_ms))
            if fallos >= lib_reconciliar.FALLOS_SEGUIDOS:
                error = plan["error"]
                break
        if ciclos and vuelta >= ciclos:
            break
        lib_trabajo.esperar(lib_reconciliar.CICLO_SEGUNDOS, dormir=dormir,
                            detenido=lambda: t.detenido() or lib_candado.huerfano())
    detenido = t.detenido()
    plan.update({"error": error, "corriendo": False, "deteniendo": False,
                 "estado": lib_trabajo.terminar(t, error, detenido)})
    lib_trabajo.guardar_plan(lib_reconciliar.TIPO, plan)
    return {"ok": not error, "datos": lib_reconciliar.vista(plan, ahora_ms), "error": error}


def apagar(d=None, ahora_ms=None):
    """«Detener»: el motor deja de revisar. Lo que está abierto mantiene su protección, pero en prueba esa protección
    existe solo con el motor encendido: desde aquí empieza una ventana sin cobertura."""
    pedido = lib_trabajo.detener(lib_reconciliar.TIPO)
    r = estado(d, ahora_ms)
    r["datos"]["deteniendo"] = r["datos"]["deteniendo"] or pedido
    return r


if __name__ == "__main__":
    nucleo.script({"estado": estado, "revisar": revisar, "encender": encender, "apagar": apagar}, __doc__)
