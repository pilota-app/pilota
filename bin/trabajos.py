#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Pieza «trabajos»: lo que tarda minutos corre en segundo plano, por etapas, sin perder nada. Solo biblioteca estándar.

Un trabajo deja TODO en disco a medida que avanza, así nada se pierde si se cierra la ventana o la app:
- su estado en <carpeta de datos>/trabajos/<id>.json (nunca en la carpeta de la persona), escrito de una vez en cada cambio;
- sus eventos, línea por línea (JSONL), en el archivo que dice <ID>_PROGRESO (lo pone el host y lo lee cada ~0,5 s con su
  lector de progreso, `LectorProgreso` en Swift o `lectorProgreso` en Electron, para pasarlo a la interfaz):
  {"t": "estado", "trabajo": <vista>} en cada cambio de estado y {"t": "lee" | "busca", …} por cada archivo que lee la IA;
- un «latido» cada pocos segundos: si el estado dice «corriendo» y el latido es viejo, el proceso murió (la app se cerró) y el
  trabajo queda «interrumpido», listo para «Seguir» (lo ya hecho no se repite). El mismo latido toca el archivo que dice
  <ID>_LATIDO (lo pone el host para una acción con «limite»: "trabajo"): si deja de latir, el host lo corta;
- «Detener» (`detener(id)`) deja el archivo trabajos/<id>.detener: el trabajo lo ve con t.detenido(), corta la IA y queda «detenido».
- «esperando»: el trabajo le preguntó algo a la persona (t.esperar(preguntas)) y terminó su proceso; todo queda en disco y la
  respuesta lo retoma (t.seguir()). Un trabajo que espera no se borra con los viejos.

Un tipo de trabajo nuevo: un módulo de la app con sus ETAPAS y una función que avanza con t.etapa(...), t.poner_item(...),
t.leyo(ruta), t.guardar() y t.detenido(), y termina con t.terminar(estado, error). Con la pieza «ia»:

    t = trabajos.Trabajo.nuevo("resumir", carpeta, ["leer", "escribir"], {"archivos": [...]})
    t.latir()
    texto, error = ia.preguntar_vivo(pedido, al_evento=lambda e: t.leyo(e["ruta"]) if e["t"] == "lee" else t.busco(e["patron"]),
                                     detener=t.detenido)
    t.terminar("detenido" if ia.detenido(error) else "error" if error else "listo", error or "")

Estados: corriendo → listo | con-fallas | detenido | error | esperando; un «corriendo» sin latido es «interrumpido».

Uso: trabajos.py ver <entrada {id}> <salida.json>       → {ok, trabajo}
     trabajos.py detener <entrada {id}> <salida.json>   → {ok, deteniendo?, trabajo}
"""
import datetime
import json
import os
import re
import signal
import threading
import time

import nucleo

LATIDO = 5          # segundos entre latidos
MUERTO = 45         # sin latido por más que esto = el proceso ya no está
MAX_GUARDADOS = 40  # trabajos viejos que se conservan


def carpeta():
    return os.path.join(nucleo.carpeta_datos(), "trabajos")


def ahora():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def id_valido(i):
    return isinstance(i, str) and re.fullmatch(r"\d{8}T\d{6}-[0-9a-f]{6}", i) is not None


_lock_progreso = threading.Lock()


def latir_host():
    """Le dice al host que el script sigue vivo (si lo pidió con <ID>_LATIDO: una acción con «limite»: "trabajo"). Sin eso,
    el host corta el script a los 45 s sin latido. Lo llama solo el hilo de `Trabajo.latir()`; para algo largo sin trabajo,
    `mantener_vivo()`."""
    ruta = nucleo.entorno("LATIDO")
    if not ruta:
        return
    try:
        with open(ruta, "a", encoding="utf-8"):
            pass
        os.utime(ruta, None)
    except OSError:
        pass


def mantener_vivo(limpiar_al_cortar=True):
    """Un hilo que late para el host mientras el script corre (algo largo que no es un Trabajo, en una acción "trabajo").

    Además, si nadie lo hizo antes, al cerrar la app (el host manda SIGTERM a lo que siga corriendo) el script sale con
    `SystemExit`: corren los `finally` y los `with`, así borra sus temporales en vez de morir en seco. `limpiar_al_cortar=False`
    no toca la señal."""
    if limpiar_al_cortar:
        cortar_con_systemexit()

    def latido():
        while True:
            latir_host()
            time.sleep(LATIDO)
    threading.Thread(target=latido, daemon=True).start()


def cortar_con_systemexit():
    """SIGTERM → `SystemExit(143)` (limpia al salir). Solo desde el hilo principal y si la señal sigue con lo de siempre (un
    manejador propio de la app gana). True si quedó puesto."""
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "SIGTERM"):
        return False
    try:
        if signal.getsignal(signal.SIGTERM) not in (signal.SIG_DFL, None):
            return False
        signal.signal(signal.SIGTERM, _salir_por_senal)
    except (ValueError, OSError):
        return False
    return True


def _salir_por_senal(_senal, _marco):
    raise SystemExit(128 + signal.SIGTERM)


def emitir(evento):
    """Una línea de progreso para el host (si la pidió con <ID>_PROGRESO)."""
    ruta = nucleo.entorno("PROGRESO")
    if not ruta:
        return
    linea = json.dumps(evento, ensure_ascii=False) + "\n"
    with _lock_progreso:
        try:
            with open(ruta, "a", encoding="utf-8") as f:
                f.write(linea)
        except OSError:
            pass


class Trabajo:
    """Estado de un trabajo: {formato, id, tipo, proyecto (carpeta abierta, absoluta), estado, etapa, etapas, inicio, fin, latido,
    datos (lo propio del tipo), items (la lista visible: [{ruta, titulo, tipo, estado, error?}]), leidos, leyendo, error}."""

    def __init__(self, x):
        self.x = x
        self._lock = threading.RLock()
        self._latiendo = False

    # ── crear y cargar ──
    @classmethod
    def nuevo(cls, tipo, proyecto, etapas, datos):
        i = datetime.datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + os.urandom(3).hex()
        t = cls({"formato": 1, "id": i, "tipo": tipo, "proyecto": proyecto, "estado": "corriendo", "etapa": etapas[0],
                 "etapas": list(etapas), "hechas": [], "inicio": ahora(), "latido": time.time(), "datos": datos, "items": [],
                 "leidos": 0, "leyendo": "", "error": ""})
        t.guardar()
        limpiar_viejos()
        return t

    @classmethod
    def cargar(cls, i):
        if not id_valido(i):
            raise ValueError("No encontré ese trabajo.")
        x = nucleo.leer_json(os.path.join(carpeta(), i + ".json"), None)
        if not isinstance(x, dict) or x.get("formato") != 1:
            raise ValueError("No encontré ese trabajo.")
        return cls(x)

    @property
    def id(self):
        return self.x["id"]

    def guardar(self, emitir_estado=True):
        with self._lock:
            nucleo.carpeta_privada(carpeta())
            nucleo.escribir_json(os.path.join(carpeta(), self.id + ".json"), self.x)
            if emitir_estado:
                emitir({"t": "estado", "trabajo": self.vista()})

    # ── avanzar ──
    def etapa(self, nombre):
        with self._lock:
            if self.x["etapa"] not in self.x["hechas"] and self.x["etapa"] != nombre:
                self.x["hechas"].append(self.x["etapa"])
            self.x["etapa"] = nombre
            self.guardar()

    def terminar(self, estado, error=""):
        """`error`: un texto o un error de la IA ({codigo, plantilla, valores}); este último queda además en `error_ia` para que la
        interfaz lo traduzca."""
        texto, error_ia = _error(error)
        with self._lock:
            if estado == "listo" and self.x["etapa"] not in self.x["hechas"]:
                self.x["hechas"].append(self.x["etapa"])
            # Lo que quedó a medias vuelve a la cola: «Seguir» lo retoma.
            for i in self.x["items"]:
                if i.get("estado") == "escribiendo":
                    i["estado"] = "cola"
            self.x.update({"estado": estado, "fin": ahora(), "error": texto, "leyendo": ""})
            self.x.pop("error_ia", None)
            if error_ia:
                self.x["error_ia"] = error_ia
            self.guardar()
        self._latiendo = False
        try:
            os.unlink(self.ruta_detener())
        except OSError:
            pass

    def esperar(self, preguntas, **publico):
        """Le pregunta algo a la persona: queda «esperando» con las preguntas (ya validadas) y el proceso termina. La respuesta llega
        con la orden `responder` y el trabajo sigue donde quedó."""
        with self._lock:
            self.x.setdefault("publico", {}).update({"preguntas": preguntas, **publico})
            self.x["publico"].pop("visto", None)
            self.x.update({"estado": "esperando", "fin": ahora(), "error": "", "leyendo": ""})
            self.x.pop("error_ia", None)
            self.guardar()
        self._latiendo = False

    def seguir(self):
        """Vuelve a correr (después de «responder», «Seguir» o «Reintentar»)."""
        with self._lock:
            self.x.update({"estado": "corriendo", "error": "", "latido": time.time()})
            self.x.pop("error_ia", None)
            self.x.pop("fin", None)
            self.x.setdefault("publico", {}).pop("preguntas", None)
            self.guardar()

    def item(self, ruta):
        return next((i for i in self.x["items"] if i["ruta"] == ruta), None)

    def poner_item(self, ruta, **campos):
        if "error" in campos:
            campos["error"], error_ia = _error(campos["error"])
            campos["error_ia"] = error_ia
        with self._lock:
            i = self.item(ruta)
            if i is None:
                i = {"ruta": ruta}
                self.x["items"].append(i)
            if "error" not in campos and campos.get("estado") in ("escribiendo", "listo", "cola"):
                i.pop("error", None)
                i.pop("error_ia", None)
            i.update(campos)
            if not i.get("error_ia"):
                i.pop("error_ia", None)
            self.guardar()

    def leyo(self, ruta):
        """La IA está leyendo `ruta` (relativa al código): cuenta, recuerda y avisa, sin guardar todo el estado cada vez."""
        with self._lock:
            vistos = self.x.setdefault("vistos", [])
            nuevo = ruta not in vistos
            if nuevo and len(vistos) < 5000:
                vistos.append(ruta)
            self.x["leidos"] = len(vistos)
            self.x["leyendo"] = ruta
        emitir({"t": "lee", "id": self.id, "ruta": ruta, "n": self.x["leidos"]})

    def busco(self, patron):
        emitir({"t": "busca", "id": self.id, "patron": patron[:200]})

    # ── detener y latido ──
    def ruta_detener(self):
        return os.path.join(carpeta(), self.id + ".detener")

    def detenido(self):
        return os.path.exists(self.ruta_detener())

    def latir(self):
        """Un hilo que actualiza el latido (y guarda lo leído) mientras el trabajo corre."""
        self._latiendo = True

        def latido():
            while self._latiendo:
                with self._lock:
                    self.x["latido"] = time.time()
                    self.guardar(emitir_estado=False)
                latir_host()
                time.sleep(LATIDO)
        threading.Thread(target=latido, daemon=True).start()

    # ── lo que ve la interfaz (sin rutas absolutas) ──
    def vista(self):
        x = self.x
        return {"id": x["id"], "tipo": x["tipo"], "carpeta": x["proyecto"], "estado": estado_real(x), "etapa": x["etapa"], "etapas": x["etapas"], "hechas": x["hechas"],
                "inicio": x["inicio"], "fin": x.get("fin"), "items": [dict(i) for i in x["items"]], "leidos": x.get("leidos", 0),
                "leyendo": x.get("leyendo", ""), "error": x.get("error", ""), **({"error_ia": x["error_ia"]} if x.get("error_ia") else {}), **{k: v for k, v in (x.get("publico") or {}).items()}}


def _error(error):
    """(texto en español, error_ia o None): un error de la IA llega como {codigo, plantilla, valores} (pieza «ia»)."""
    if isinstance(error, dict):
        valores = error.get("valores") if isinstance(error.get("valores"), dict) else {}
        ia_ = {"codigo": str(error.get("codigo") or ""), "plantilla": str(error.get("plantilla") or ""),
               "valores": {str(k): ("" if v is None else str(v))[:300] for k, v in valores.items()}}
        texto = ia_["plantilla"]
        for k, v in ia_["valores"].items():
            texto = texto.replace("{" + k + "}", str(v))
        return texto.strip()[:600], ia_
    return str(error or "")[:600], None


def estado_real(x):
    """«corriendo» con un latido viejo es un trabajo interrumpido (se cerró la app o se cortó el proceso)."""
    if x.get("estado") == "corriendo" and time.time() - float(x.get("latido") or 0) > MUERTO:
        return "interrumpido"
    return x.get("estado")


def _nombres():
    try:
        return sorted((n for n in os.listdir(carpeta()) if n.endswith(".json") and id_valido(n[:-5])), reverse=True)
    except OSError:
        return []


def del_proyecto(proyecto, tipo=None):
    """El último trabajo de esta carpeta (el más nuevo primero), o None. `tipo`: uno o varios tipos de trabajo."""
    tipos = (tipo,) if isinstance(tipo, str) else tipo
    for n in _nombres()[:MAX_GUARDADOS * 3]:
        x = nucleo.leer_json(os.path.join(carpeta(), n), None)
        if isinstance(x, dict) and x.get("proyecto") == proyecto and (tipos is None or x.get("tipo") in tipos):
            return Trabajo(x)
    return None


def esperando(proyecto):
    """Los trabajos de esta carpeta que esperan respuestas de la persona (el más nuevo primero)."""
    r = []
    for n in _nombres()[:MAX_GUARDADOS * 3]:
        x = nucleo.leer_json(os.path.join(carpeta(), n), None)
        if isinstance(x, dict) and x.get("proyecto") == proyecto and x.get("estado") == "esperando":
            r.append(Trabajo(x))
    return r


def limpiar_viejos():
    nombres = _nombres()
    # Los que esperan respuestas no se borran: son de la persona hasta que responda o los descarte.
    viejos = [n for n in nombres[MAX_GUARDADOS:] if (nucleo.leer_json(os.path.join(carpeta(), n), {}) or {}).get("estado") != "esperando"]
    for n in viejos:
        for ext in (".json", ".antes.json", ".detener"):
            try:
                os.unlink(os.path.join(carpeta(), n[:-5] + ext))
            except OSError:
                pass


def limpiar_preguntas(lista, prefijo, maximo=5):
    """Las preguntas para la persona, validadas: [{id, pregunta, porque, opciones}] (de la IA o fijas). Lo que no sirve se descarta."""
    r = []
    for p in lista if isinstance(lista, list) else []:
        if not isinstance(p, dict) or not isinstance(p.get("pregunta"), str) or not p["pregunta"].strip():
            continue
        opciones = [re.sub(r"\s+", " ", o).strip()[:100] for o in (p.get("opciones") or []) if isinstance(o, str) and o.strip()][:5]
        r.append({"id": f"{prefijo}-{len(r) + 1}", "pregunta": re.sub(r"\s+", " ", p["pregunta"]).strip()[:300],
                  "porque": re.sub(r"\s+", " ", str(p.get("porque") or "")).strip()[:200], "opciones": list(dict.fromkeys(opciones))})
        if len(r) >= maximo:
            break
    return r


def limpiar_respuestas(respuestas, preguntas):
    """Lo que respondió la persona, contra las preguntas que se le hicieron: {id: {respuesta, nose, saltada}}. Lo desconocido se ignora."""
    ids = {p["id"] for p in preguntas}
    r = {}
    for x in respuestas if isinstance(respuestas, list) else []:
        if not isinstance(x, dict) or x.get("id") not in ids:
            continue
        texto = re.sub(r"\s+", " ", str(x.get("respuesta") or "")).strip()[:1000]
        r[x["id"]] = {"respuesta": texto, "nose": bool(x.get("nose")) and not texto, "saltada": not texto and not x.get("nose")}
    for i in ids - set(r):
        r[i] = {"respuesta": "", "nose": False, "saltada": True}
    return r


def detener(i):
    """«Detener»: deja la marca que el trabajo revisa con t.detenido(). Solo si sigue corriendo."""
    t = Trabajo.cargar(i)
    if estado_real(t.x) != "corriendo":
        return {"ok": True, "trabajo": t.vista()}
    nucleo.carpeta_privada(carpeta())
    with open(t.ruta_detener(), "w", encoding="utf-8") as f:
        f.write(ahora())
    return {"ok": True, "deteniendo": True, "trabajo": t.vista()}


if __name__ == "__main__":
    nucleo.script({"ver": lambda d: {"ok": True, "trabajo": Trabajo.cargar(d.get("id")).vista()},
                   "detener": lambda d: detener(d.get("id"))}, __doc__)
