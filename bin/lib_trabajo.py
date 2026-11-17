"""lib_trabajo — lo que comparten los trabajos de Pilota. Solo biblioteca estándar.

No es una acción (nadie la corre sola): la usan `bin/historial.py` (los 3 años de velas), `bin/muestreo.py` (el libro, los
últimos trades y las velas de 1 m) y `bin/motor.py` (la revisión cada 5 minutos) sobre la pieza «trabajos»
(`bin/trabajos.py`, que no se edita aquí).

Lo que no se negocia aquí:
- **El avance vive en disco.** Cada trabajo guarda su plan en `<datos>/mercado/<tipo>.json` en cada página que baja, así
  «Detener» y «Seguir donde quedó» nunca repiten lo ya hecho ni pierden nada si se cierra la app.
- **La pantalla no manda ids.** Los trabajos de la pieza van por «proyecto» y Pilota no abre carpetas: su proyecto es siempre
  su carpeta de datos, así «Detener» encuentra solo el último trabajo de cada tipo.
- **Nada de Binance se muestra tal cual**: un problema de red se guarda como código (`red`, `limite`, `respuesta`) y la
  pantalla lo traduce.
"""
import os
import time

import lib_datos
import nucleo
import trabajos

#: Los errores de Binance como los entiende la pantalla (misma tabla que velas.py y minimo_viable.py).
ERRORES = ((lib_datos.Limitado, "limite"), (lib_datos.Temporal, "red"), (lib_datos.Respuesta, "respuesta"))


def proyecto():
    """El «proyecto» de los trabajos de Pilota: su carpeta de datos (no hay carpetas que abrir)."""
    return nucleo.carpeta_datos()


def ruta_plan(tipo):
    if tipo not in ("historial", "muestreo", "motor", "vivo"):
        raise ValueError(f"No conozco ese trabajo: {tipo!r}")
    return os.path.join(lib_datos.carpeta_mercado(), tipo + ".json")


def leer_plan(tipo):
    d = nucleo.leer_json(ruta_plan(tipo), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    return d if isinstance(d, dict) and d.get("formato") == 1 else {}


#: Lo que dice cómo va el trabajo ahora mismo: se mira cada vez (`mirar`) y no se guarda.
AL_VUELO = ("corriendo", "deteniendo")


def guardar_plan(tipo, plan):
    plan["cuando"] = lib_datos.iso(lib_datos.ahora_local_ms())
    nucleo.escribir_json(ruta_plan(tipo), {k: v for k, v in plan.items() if k not in AL_VUELO})
    return plan


def nuevo(tipo, etapas, datos, latir=True):
    """Un trabajo nuevo, latiendo. `latir=False` solo en las pruebas: sin el hilo que le dice al host que el script sigue vivo."""
    t = trabajos.Trabajo.nuevo(tipo, proyecto(), list(etapas), datos)
    if latir:
        t.latir()
    return t


def ultimo(tipo):
    return trabajos.del_proyecto(proyecto(), tipo)


def mirar(tipo, plan):
    """Pone al día el estado del trabajo en el plan, sin tocar la red: `corriendo` (está trabajando ahora), `deteniendo` (ya
    le pediste parar) y, si el plan dice «corriendo» y nadie está latiendo, `interrumpido`: se cerró la app y queda «Seguir
    donde quedó»."""
    t = ultimo(tipo)
    vivo = t is not None and t.x.get("id") == plan.get("trabajo") and trabajos.estado_real(t.x) == "corriendo"
    if plan.get("estado") == "corriendo" and not vivo:
        plan["estado"] = "interrumpido"
    plan["corriendo"] = vivo
    plan["deteniendo"] = vivo and t.detenido()
    return plan


def detener(tipo):
    """«Detener»: deja la marca que el trabajo revisa (la pieza «trabajos»). Lo bajado queda donde está."""
    t = ultimo(tipo)
    if t is None or trabajos.estado_real(t.x) != "corriendo":
        return False
    trabajos.detener(t.id)
    return True


def codigo_de(e):
    """El problema de Binance como código para la pantalla; nunca su texto (nada que venga de afuera se muestra)."""
    for clase, codigo in ERRORES:
        if isinstance(e, clase):
            return codigo
    return "respuesta"


def publicar(t, avance):
    """El avance, donde lo lee la pantalla: el evento de progreso de «trabajos» (el host lo pasa a la interfaz) con el mismo
    resumen que quedó guardado en el plan."""
    t.x.setdefault("publico", {})["avance"] = avance
    t.guardar()


def terminar(t, error, detenido):
    """Cierra el trabajo con el estado que corresponde y lo devuelve."""
    estado = "detenido" if detenido else ("error" if error else "listo")
    t.terminar(estado, error)
    return estado


def esperar(segundos, dormir=time.sleep, detenido=None, trozo=5):
    """Duerme en trozos cortos: «Detener» no tiene que esperar los cinco minutos del ciclo. Falso si te pidieron parar."""
    queda = max(0.0, float(segundos))
    while queda > 0:
        if detenido is not None and detenido():
            return False
        rato = min(trozo, queda)
        dormir(rato)
        queda -= rato
    return detenido is None or not detenido()
