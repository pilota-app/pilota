#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Pieza «contrato»: que la interfaz y cada plataforma de la app digan lo mismo. Solo biblioteca estándar.

    python3 pruebas/contrato.py                    # la app donde está este archivo
    python3 pruebas/contrato.py --app ../otra      # otra app (solo lee: nunca escribe nada)
    python3 pruebas/contrato.py --json             # los problemas como JSON (para otra herramienta)

Revisa, sin código propio de la app:
  1. Cada acción que manda la interfaz (`host.enviar("x")` en el código propio de ui/, y lo que mandan por su cuenta las piezas de
     interfaz, como «componentes») la atiende cada plataforma de la app: **registrada** (Mac `p.registrar("x")`, Electron
     `host.acciones.registrar` o el objeto `ACCIONES` de main.js, celular `ACCIONES`/`SOLO_MAC` de movil/host/host.js), **del host**
     (lo que trae «host-mac»/«host-escritorio»: listo, config, abrirEnlace, copiar y, si la app les pasa la pieza
     «actualizaciones», buscarActualizacion y actualizar) o **declarada** en acciones.json. Y está en `simular()` (vista previa).
  2. Nada sobra: una acción registrada que la interfaz no pide, una registrada que también está declarada (gana la registrada),
     una declarada que nadie pide (va en app.json → «sin_acciones»).
  3. acciones.json al día con app.json (lo que arma `pieza.py acciones`: las de las piezas de piezas.json + las de app.json − las
     de «sin_acciones»), sus scripts existen en bin/, tienen límite y nada que escribe la persona va como argumento ($campo solo
     enum o entero).
  4. Cada función que llaman las plataformas (`llamar("x")`, `window.<App>.x`, `A().x` en el celular) o que responde una declarada
     (`responde`, `progreso`) existe en `window.<App>` (`host.responder({…})` de host-ui).
  5. Seguridad común: CSP de ui/index.html con `script-src 'self'` y sin `unsafe-*`, sin scripts ni manejadores en línea; ningún
     archivo propio de la app (Swift o Electron) arma el comando de una IA (eso es de bin/ia.py); Info.plist sin excepciones de ATS;
     el bundle id de Info.plist igual al de la firma de empaquetar.sh; acciones.json dentro del paquete (empaquetar.sh y
     extraResources); la misma versión en Info.plist y escritorio/package.json; las ventanas propias de Electron con sandbox y
     contextIsolation; Capacitor sin servidor remoto ni http en claro; Android sin respaldo automático ni componentes exportados de
     más; los métodos nativos que llama el celular existen en Swift, en Kotlin/Java y en el Capacitor falso de las pruebas.

Lo propio de cada app va en **pruebas/contrato_app.py** (opcional, chico, en la app; esta pieza nunca lo pisa):

    EXCEPCIONES = {"mac:calendarioICS": "en Mac el calendario se lee del sistema (EventKit)"}   # «código:cosa» → motivo
    UI = ["ui/proyectos.js"]                  # más archivos propios de la interfaz (por omisión, todo ui/**/*.js que no es de una pieza)
    ENVIA = [r'data-av="(\\w+)"']             # más formas de mandar una acción desde la interfaz
    REGISTRADAS = {"mac": [r'case "(\\w+)"']}   # más formas de registrar lo nativo, por plataforma (mac, escritorio, movil)
    LLAMADAS = [r'llamarFuncion\\([^"]*"(\\w+)"']  # más formas de llamar window.<App>.x desde una plataforma
    SWIFT = ["app/Sources/Minuta/VisorWeb.swift"]   # dónde está el Swift propio: carpetas o archivos (por omisión, app/Sources/* que no es una pieza)
    DEL_HOST = {"mac": []}                    # lo que trae el host en una plataforma, si la app no usa su puente (Minuta en Mac)
    PLUGINS = {"Camera": ("movil/node_modules/@capacitor/camera/ios/**/*.swift", "movil/node_modules/@capacitor/camera/android/**/*.java")}
    def revisar(c): ...                       # revisiones propias: c.leer(ruta), c.acciones, c.funciones, c.declaradas,
                                              #   c.problema("codigo", "cosa", "texto")

Cada problema tiene un código («mac:x», «simular:x», «sobra-declarada:x»…): una excepción a propósito es ese código con su motivo,
en un solo lugar. Una excepción que ya no hace falta también se avisa (así no quedan excepciones viejas tapando nada).
"""
import glob
import importlib.util
import json
import os
import re
import sys

PLATAFORMAS_HOST = {"tauri": "escritorio/src/pieza/host.rs", "mac": "app/Sources", "escritorio": "escritorio/src/main.js", "movil": "movil/host/host.js",
                    "ios": "movil/ios/Fuentes"}
#: Lo que trae cada host (pieza «host-mac» y «host-escritorio») sin que la app lo registre.
DEL_HOST = {"listo", "config", "abrirEnlace", "copiar"}
DEL_HOST_ACTUALIZACIONES = {"buscarActualizacion", "actualizar"}
#: Respuestas que el host manda solo si la interfaz pidió algo que la app quizás no usa.
RESPUESTAS_OPCIONALES = {"copiado": "copiar", "archivoCambiado": None, "soltados": None, "soltando": None,
                         "error": None}   # host-ios: una acción que el iPhone no atiende (la interfaz puede mostrarlo o no)
#: Señales de que un archivo arma el comando de una IA (eso es de bin/ia.py, pieza «ia»).
COMANDO_IA = re.compile(r'"--disallowedTools"|"--strict-mcp-config"|"--skip-git-repo-check"|["\'](claude|codex|gemini|agy)["\']\s*,\s*\[')


# ── Leer JS sin ejecutarlo: lo justo para encontrar bloques y claves ─────────────────────────────────────────────────────────

#: Acciones que manda una pieza de interfaz solo si la app usa la parte que la manda (acción → lo que la app tiene que llamar).
#: Sin esa pieza instalada y sin que la app lo llame, no se exige.
USO_PIEZAS_UI = {"probarIA": ("ia", r"\bfilasIA\(|\bprobarIA\(")}


def sin_comentarios(texto):
    """Quita los comentarios de línea completa (los ejemplos de las piezas nombran acciones que no existen)."""
    return re.sub(r"^\s*(//|///|\*|/\*\*|#).*$", "", texto or "", flags=re.M)


def _fin_de_bloque(texto, i):
    """Dado `texto[i] == "{"`, el índice de su `}`. Salta textos, plantillas, comentarios y expresiones regulares."""
    pila, n, j = [], len(texto), i
    previo = ""
    while j < n:
        ch = texto[j]
        if ch in "\"'":
            j += 1
            while j < n and texto[j] != ch:
                j += 2 if texto[j] == "\\" else 1
        elif ch == "`":
            pila.append("`")
            j += 1
            while j < n:
                if texto[j] == "\\":
                    j += 2
                    continue
                if texto[j] == "`":
                    pila.pop()
                    break
                if texto.startswith("${", j):
                    k = _fin_de_bloque(texto, j + 1)
                    j = k + 1
                    continue
                j += 1
        elif texto.startswith("//", j):
            j = texto.find("\n", j)
            j = n if j < 0 else j
            continue
        elif texto.startswith("/*", j):
            j = texto.find("*/", j)
            j = n if j < 0 else j + 2
            continue
        elif ch == "/" and (previo in "(,=:[!&|?{};+-*%<>~^" or re.search(r"\b(return|typeof|case|of|in|void|yield|await)\s*$", texto[max(0, j - 12):j])):
            j += 1
            clase = False
            while j < n and (texto[j] != "/" or clase) and texto[j] != "\n":
                if texto[j] == "\\":
                    j += 1
                elif texto[j] == "[":
                    clase = True
                elif texto[j] == "]":
                    clase = False
                j += 1
        elif ch in "{([":
            pila.append(ch)
        elif ch in "})]":
            if pila and pila[-1] in "{([":
                pila.pop()
            if not pila:
                return j
        if not ch.isspace():
            previo = ch
        j += 1
    return n


def bloque(texto, marca):
    """El texto entre la primera llave después de `marca` y la que la cierra (vacío si no está)."""
    i = (texto or "").find(marca)
    if i < 0:
        return ""
    if marca.endswith("("):  # una función: su cuerpo empieza después de los parámetros (que pueden traer {…} por omisión)
        i = _fin_de_bloque(texto, i + len(marca) - 1)
    i = texto.find("{", i + len(marca) - 1 if marca.endswith("{") else i)
    return texto[i + 1:_fin_de_bloque(texto, i)] if i >= 0 else ""


def claves(objeto):
    """Las claves de primer nivel de un literal de objeto JS (`a(…) {`, `async b(…)`, `c: …`, `d,`)."""
    r, prof, j, n = set(), 0, 0, len(objeto)
    inicio = True
    while j < n:
        ch = objeto[j]
        if prof == 0 and inicio and not ch.isspace() and not objeto.startswith(("//", "/*"), j):
            m = re.match(r"(?:async\s+)?(?:get\s+|set\s+)?[\"']?([A-Za-z_$][\w$]*)[\"']?\s*(\(|:|,|$)", objeto[j:])
            if m:
                r.add(m.group(1))
            inicio = False
        if ch in "\"'`" or ch in "{([" or objeto.startswith("//", j) or objeto.startswith("/*", j):
            if ch in "{([":
                k = _fin_de_bloque(objeto, j)
            elif ch in "\"'":
                k = j + 1
                while k < n and objeto[k] != ch:
                    k += 2 if objeto[k] == "\\" else 1
            elif ch == "`":
                k = _fin_de_bloque("(" + objeto[j:] + ")", 0) + j - 2  # la plantilla entre paréntesis: termina donde ella
            elif objeto.startswith("//", j):
                k = objeto.find("\n", j)
                k = n if k < 0 else k
                inicio = inicio or prof == 0
            else:
                k = objeto.find("*/", j)
                k = n if k < 0 else k + 1
            j = k + 1
            continue
        if ch == "," and prof == 0:
            inicio = True
        j += 1
    return r


# ── El contrato ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

class Contrato:
    def __init__(self, raiz, extension=None):
        self.raiz = os.path.abspath(raiz)
        self.problemas = []          # [(codigo, texto)]
        self.avisos = []
        self.ext = self._cargar_extension(extension)
        self.excepciones = dict(getattr(self.ext, "EXCEPCIONES", {}) or {})
        self.usadas = set()
        self.app = self.json("app.json") or {}
        self.lock = self.json("piezas.json") or {"piezas": {}}
        self.de_piezas = {r for p in (self.lock.get("piezas") or {}).values() for r in (p.get("archivos") or {})}

    # Archivos
    def ruta(self, r):
        return os.path.join(self.raiz, r)

    def existe(self, r):
        return os.path.exists(self.ruta(r))

    def leer(self, r):
        try:
            with open(self.ruta(r), encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError:
            return None

    def json(self, r):
        t = self.leer(r)
        try:
            return json.loads(t) if t is not None else None
        except ValueError:
            self.problema("json", r, f"{r} no es un JSON válido")
            return None

    def archivos(self, *patrones, propios=True):
        """Rutas relativas que calzan con los patrones; `propios`: sin los archivos que copió una pieza (piezas.json)."""
        vistos = []
        for p in patrones:
            for f in sorted(glob.glob(self.ruta(p), recursive=True)):
                rel = os.path.relpath(f, self.raiz).replace(os.sep, "/")
                if os.path.isfile(f) and rel not in vistos and not (propios and rel in self.de_piezas) \
                        and "/node_modules/" not in "/" + rel and "/.build/" not in "/" + rel:
                    vistos.append(rel)
        return vistos

    def juntar(self, *patrones, propios=True):
        return "\n".join(self.leer(r) or "" for r in self.archivos(*patrones, propios=propios))

    # Problemas
    def problema(self, codigo, cosa, texto):
        clave = f"{codigo}:{cosa}" if cosa else codigo
        if clave in self.excepciones:
            self.usadas.add(clave)
            return
        if any(k == clave and t == texto for k, t in self.problemas):
            return
        self.problemas.append((clave, texto))

    def aviso(self, texto):
        self.avisos.append(texto)

    def _cargar_extension(self, ruta):
        ruta = ruta or self.ruta("pruebas/contrato_app.py")
        if not os.path.isfile(ruta):
            return None
        spec = importlib.util.spec_from_file_location("contrato_app", ruta)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def extra(self, nombre, defecto):
        v = getattr(self.ext, nombre, None) if self.ext else None
        return defecto if v is None else v

    # ── 0. Qué tiene la app ────────────────────────────────────────────────────────────────────────────────────────────────
    def plataformas(self):
        """Las plataformas con código en el repo: mac (app/Sources), escritorio (Electron), movil (Capacitor) e ios (host-ios)."""
        declaradas = set(self.app.get("plataformas") or [])
        hay = {}
        # host-tauri: un solo host (Rust) para Mac, Windows y Linux. Con él, lo de antes (Swift, Electron) ya no cuenta.
        tauri = self.existe("escritorio/src/pieza/host.rs")
        if tauri:
            hay["tauri"] = True
        if self.existe("app/Sources") and not tauri:
            hay["mac"] = True
        if self.existe("escritorio/src/main.js") and not tauri:
            hay["escritorio"] = True
        if self.existe("movil/host/host.js"):
            hay["movil"] = True
        if self.existe("movil/ios/Fuentes/PiezaHost/Puente.swift"):   # pieza «host-ios» (Swift, sin Capacitor)
            hay["ios"] = True
        for p, donde in (("mac", "mac"), ("windows", "escritorio"), ("linux", "escritorio"), ("ios", "movil"), ("android", "movil")):
            if (p == "ios" and "ios" in hay) or (p in ("mac", "windows", "linux") and "tauri" in hay):
                continue
            if p in declaradas and donde not in hay:
                self.aviso(f"app.json dice «{p}» y no encuentro {PLATAFORMAS_HOST[donde]}: no lo reviso (¿todavía no existe?)")
        return list(hay)

    def interfaz(self):
        propios = self.archivos("ui/**/*.js") + list(self.extra("UI", []))
        propios = [r for r in dict.fromkeys(propios) if not r.startswith("ui/demo") and "/idiomas/" not in r]
        self.ui = {r: self.leer(r) or "" for r in propios}
        self.ui_todo = "\n".join(self.ui.values())
        piezas_ui = {r: self.leer(r) or "" for r in self.archivos("ui/**/*.js", propios=False)
                     if r in self.de_piezas and not r.endswith(("/host.js", "/i18n.js"))}
        envia = [r'host\.enviar\(\s*"(\w+)"'] + list(self.extra("ENVIA", []))
        self.acciones = set()
        for patron in envia:
            self.acciones |= set(re.findall(patron, sin_comentarios(self.ui_todo)))
        for texto in piezas_ui.values():
            self.acciones |= set(re.findall(r'(?<![\w.])enviar\("(\w+)"', sin_comentarios(texto)))
        # Lo que una pieza de interfaz manda solo si la app usa esa parte: «probarIA» sale de las filas de «Tu IA» de
        # «componentes»; una app sin la pieza «ia» que no las pinta nunca lo pide.
        instaladas = set((self.lock.get("piezas") or {}))
        for accion, (pieza, usa) in USO_PIEZAS_UI.items():
            if accion in self.acciones and pieza not in instaladas and not re.search(usa, sin_comentarios(self.ui_todo)) \
                    and not re.search(rf'enviar\(\s*"{accion}"', sin_comentarios(self.ui_todo)):
                self.acciones.discard(accion)
        # El nombre global (window.<App>) sale de crearHost de la pieza «host-ui».
        m = re.search(r'crearHost\(\{[^}]*?global:\s*"(\w+)"', self.ui_todo)
        self.global_ = m.group(1) if m else (self.app.get("nombre") or "App")
        if not m:
            self.problema("host-ui", "", "ui/: no encuentro PiezaHost.crearHost({…, global: \"<App>\"}) (pieza «host-ui»)")
        self.funciones = set()
        for texto in self.ui.values():
            i = 0
            while True:
                i = texto.find("host.responder({", i)
                if i < 0:
                    break
                self.funciones |= claves(bloque(texto[i:], "host.responder({"))
                i += 1
            # Lo que la app le pide a la página y espera (host-tauri: pedir) también queda en window.<App>.
            self.funciones |= set(re.findall(r'host\.atender\(\s*"(\w+)"', sin_comentarios(texto)))
        if not self.funciones:
            self.problema("host-ui", "responder", f"ui/: no encuentro host.responder({{…}}): las respuestas quedan en window.{self.global_}")

    # ── 1. La vista previa ─────────────────────────────────────────────────────────────────────────────────────────────────
    def vista_previa(self):
        cuerpo = ""
        for texto in self.ui.values():
            if "function simular(" in texto:
                cuerpo = bloque(texto, "function simular(")
                obj = re.search(r"const SIMULAR\s*=\s*\{", texto)
                if obj:
                    cuerpo += "\n" + "\n".join(f'case "{k}"' for k in claves(bloque(texto[obj.start():], "const SIMULAR")))
                break
        if not cuerpo:
            self.problema("simular", "", "ui/: no encuentro function simular(accion, d, c) (la vista previa del navegador)")
            return
        simuladas = set(re.findall(r'case\s+"(\w+)"', cuerpo))
        if re.search(r"default:[^\n]*COMUNES\[accion\]|hasOwn\(COMUNES|COMUNES\[accion\]\(d, c\)", cuerpo):
            comunes = bloque(self.leer("ui/host.js") or "", "function simulacionesComunes(")
            simuladas |= set(re.findall(r"^\s+(\w+): \(d, c\)", comunes, re.M))
        for a in sorted(self.acciones - simuladas):
            self.problema("simular", a, f"La vista previa (simular) no responde «{a}»")

    # ── 2. acciones.json ───────────────────────────────────────────────────────────────────────────────────────────────────
    def declaradas_(self):
        aj = self.json("acciones.json")
        self.declaradas = dict((aj or {}).get("acciones") or {})
        sin = set(self.app.get("sin_acciones") or [])
        if aj is None:
            if self.app.get("acciones") or any(p.get("acciones") for p in (self.lock.get("piezas") or {}).values()):
                self.problema("acciones-json", "", "Falta acciones.json: python3 <pieza>/herramientas/pieza.py acciones .")
            return
        esperadas = {}
        for pid, p in (self.lock.get("piezas") or {}).items():
            for n, a in (p.get("acciones") or {}).items():
                esperadas[n] = {**a, "pieza": pid}
        for n, a in (self.app.get("acciones") or {}).items():
            esperadas[n] = {k: v for k, v in a.items() if k != "scriptDeLaApp"}
        for n in sin:
            esperadas.pop(n, None)
        quitar = lambda d: {k: v for k, v in d.items() if k not in ("pieza", "scriptDeLaApp")}
        for n in sorted(set(esperadas) | set(self.declaradas)):
            if quitar(esperadas.get(n, {})) != quitar(self.declaradas.get(n, {})):
                self.problema("acciones-json", n, f"acciones.json no está al día en «{n}»: python3 <pieza>/herramientas/pieza.py acciones .")
        for n in sorted(sin & self.acciones):
            self.problema("sin-acciones", n, f"app.json → sin_acciones deja fuera «{n}» y la interfaz la pide")
        for n, d in sorted(self.declaradas.items()):
            if not self.existe(os.path.join("bin", d.get("script", ""))) or not re.fullmatch(r"\w+\.py", d.get("script", "")):
                self.problema("script", n, f"La acción declarada «{n}» usa bin/{d.get('script')}, que no existe")
            if not d.get("limite"):
                self.problema("limite", n, f"La acción declarada «{n}» no tiene límite de tiempo")
            for arg in d.get("args") or []:
                if isinstance(arg, str) and arg.startswith("$") and (d.get("datos") or {}).get(arg[1:], {}).get("tipo") not in ("enum", "entero"):
                    self.problema("argumento", n, f"«{n}»: {arg} va como argumento y no es enum ni entero (lo que escribe la persona va en el archivo de entrada)")
            if n not in self.acciones:
                self.problema("sobra-declarada", n, f"acciones.json declara «{n}» y la interfaz nunca la pide (súmala a app.json → sin_acciones)")
            for f in (d.get("responde"), d.get("progreso")):
                if f and f not in self.funciones and n in self.acciones:
                    self.problema("funcion", f, f"La acción declarada «{n}» responde «{f}» y window.{self.global_} no la tiene")

    # ── 3. Cada plataforma ─────────────────────────────────────────────────────────────────────────────────────────────────
    def _swift_propio(self):
        carpetas = self.extra("SWIFT", None)
        if carpetas is None:
            carpetas = [os.path.relpath(c, self.raiz).replace(os.sep, "/") for c in sorted(glob.glob(self.ruta("app/Sources/*")))
                        if os.path.isdir(c) and not os.path.basename(c).startswith("Pieza")]
        return self.juntar(*[c if c.endswith(".swift") else f"{c}/**/*.swift" for c in carpetas])

    def plataforma(self, nombre):
        extra_reg = list((self.extra("REGISTRADAS", {}) or {}).get(nombre, []))
        llamadas_extra = list(self.extra("LLAMADAS", []))
        con_act = False
        if nombre == "mac":
            propio = self._swift_propio()
            host = self.juntar("app/Sources/PiezaHost/*.swift", propios=False)
            puente = self.leer("app/Sources/PiezaHost/Puente.swift") or ""
            registradas = set(re.findall(r'registrar\("(\w+)"', sin_comentarios(propio)))
            del_host = set(re.findall(r'internas\["(\w+)"\]', sin_comentarios(puente)))
            con_act = "p.actualizaciones = " in propio or "actualizaciones = .init(" in propio
            llama = set(re.findall(r'llamar\("(\w+)"', sin_comentarios(propio + "\n" + host)))
            etiqueta = "Mac"
        elif nombre == "tauri":
            # Lo propio es el Rust de escritorio/src fuera de pieza/ (main.rs y lo que la app sume); el host, escritorio/src/pieza/.
            propio = "\n".join(self.leer(r) or "" for r in self.archivos("escritorio/src/**/*.rs") if "/pieza/" not in r.replace(os.sep, "/"))
            host = self.juntar("escritorio/src/pieza/*.rs", propios=False)
            registradas = set(re.findall(r'\.registrar\("(\w+)"', sin_comentarios(propio)))
            interna = bloque(self.leer("escritorio/src/pieza/host.rs") or "", "fn interna(")
            del_host = set(re.findall(r'^\s*"(\w+)"(?:\s+if\s[^=]*)?\s*=>', interna, re.M))
            con_act = bool(re.search(r"^\s*actualizaciones:\s", sin_comentarios(propio), re.M))
            # `h.pedir("x", …)` también llama window.<App>.x (la página lo atiende con host.atender).
            llama = set(re.findall(r'(?:llamar|pedir)\("(\w+)"', sin_comentarios(propio + "\n" + host)))
            etiqueta = "Mac/Windows/Linux"
        elif nombre == "escritorio":
            main = self.leer("escritorio/src/main.js") or ""
            propio = self.juntar("escritorio/src/**/*.js")
            host = self.leer("escritorio/src/host.js") or ""
            registradas = set(re.findall(r'(?:^|[^\w])(?:\w+\.)*registrar\("(\w+)"', sin_comentarios(propio)))
            registradas -= set(re.findall(r'medios\.registrar\("(\w+)"', propio))
            if re.search(r"Object\.entries\(ACCIONES\)\)\s*host\.acciones\.registrar", main):
                registradas |= claves(bloque(main, "const ACCIONES = {"))
            del_host = set(re.findall(r'internas\.set\("(\w+)"', sin_comentarios(host)))
            con_act = bool(re.search(r"\bactualizaciones\s*[:,]", bloque(main, "crearHost({") + main[main.find("crearHost({"):][:3000]))
            llama = set(re.findall(r'llamar\("(\w+)"', sin_comentarios(propio + "\n" + host)))
            etiqueta = "Windows/Linux"
        elif nombre == "ios":
            # host-ios: lo propio es el Swift de movil/ios/Fuentes (sin PiezaHost). En el iPhone no hay Python: nada declarado corre.
            propio = self.juntar("movil/ios/Fuentes/**/*.swift")
            host = self.juntar("movil/ios/Fuentes/PiezaHost/*.swift", propios=False)
            puente = self.leer("movil/ios/Fuentes/PiezaHost/Puente.swift") or ""
            registradas = set(re.findall(r'registrar\("(\w+)"', sin_comentarios(propio)))
            del_host = set(re.findall(r'internas\["(\w+)"\]', sin_comentarios(puente)))
            llama = set(re.findall(r'llamar\("(\w+)"', sin_comentarios(propio + "\n" + host)))
            etiqueta = "iPhone"
        else:
            propio = self.leer("movil/host/host.js") or ""
            registradas = claves(bloque(propio, "const ACCIONES = {"))
            m = re.search(r"const SOLO_\w+\s*=\s*\[([^\]]*)\]", propio)
            registradas |= set(re.findall(r'"(\w+)"', m.group(1))) if m else set()
            del_host = set()
            llama = set(re.findall(r"\bA\(\)\.(\w+)", propio))
            host = ""
            etiqueta = "Celular"
        if not con_act:
            del_host -= DEL_HOST_ACTUALIZACIONES
        propio_host = (self.extra("DEL_HOST", {}) or {}).get(nombre)
        if propio_host is not None:  # la app no usa el puente del host en esa plataforma: ni lo atiende ni llama nada
            del_host = set(propio_host)
            llama = set(re.findall(r'llamar\("(\w+)"', sin_comentarios(propio))) if nombre != "movil" else llama
        for patron in extra_reg:
            registradas |= set(re.findall(patron, sin_comentarios(propio)))
        for patron in llamadas_extra:
            llama |= set(re.findall(patron, sin_comentarios(propio)))
        llama |= set(re.findall(rf"window\.{re.escape(self.global_)}\.(\w+)", sin_comentarios(propio)))
        declaradas = set(self.declaradas) if nombre not in ("movil", "ios") else set()
        atiende = registradas | del_host | declaradas
        if nombre == "ios":
            # Lo declarado (scripts de Python) y las actualizaciones son del computador: en el iPhone host-ios responde «error»
            # con código «falta» y la interfaz no queda esperando. Lo que la interfaz pide solo en el iPhone sí tiene que estar.
            atiende |= set(self.declaradas) | DEL_HOST_ACTUALIZACIONES
        for a in sorted(self.acciones - atiende):
            self.problema(nombre, a, f"{etiqueta} no atiende «{a}» (ni registrada, ni del host, ni declarada)")
        for a in sorted(registradas - self.acciones):
            self.problema(f"sobra-{nombre}", a, f"{etiqueta} registra «{a}» y la interfaz nunca la pide")
        for a in sorted(registradas & declaradas):
            self.problema(f"doble-{nombre}", a, f"«{a}» está registrada en {etiqueta} y también declarada: gana la registrada (saca una)")
        for f, accion in RESPUESTAS_OPCIONALES.items():
            if accion is None or accion not in self.acciones:
                llama.discard(f)
        for f in sorted(llama - self.funciones):
            self.problema("funcion", f, f"{etiqueta} llama window.{self.global_}.{f} y la interfaz no la tiene")
        if COMANDO_IA.search(propio or ""):
            self.problema(f"ia-{nombre}", "", f"{etiqueta}: el código propio arma el comando de una IA (eso lo hace solo bin/ia.py, pieza «ia»)")
        self.registradas[nombre] = registradas
        self.del_host[nombre] = del_host & self.acciones

    # ── 4. Seguridad común ─────────────────────────────────────────────────────────────────────────────────────────────────
    def seguridad(self, plataformas):
        html = self.leer("ui/index.html")
        if html is not None:
            csp = re.search(r'Content-Security-Policy"\s+content="([^"]+)"', html)
            politica = dict((x.strip().split(" ", 1) + [""])[:2] for x in (csp.group(1) if csp else "").split(";") if x.strip())
            scripts = politica.get("script-src", politica.get("default-src", ""))
            if not csp or not re.match(r"'self'(\s|$)", scripts.strip()) or "unsafe" in scripts or "*" in scripts or "http" in scripts:
                self.problema("csp", "", "ui/index.html: la Content-Security-Policy necesita script-src 'self' (sin unsafe-eval ni unsafe-inline)")
            if re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html) or re.search(r"<[^>]+\son[a-z]+\s*=", html):
                self.problema("en-linea", "index.html", "ui/index.html: nada de scripts ni manejadores (onclick=…) en línea: la CSP los bloquea")
        for r, t in self.ui.items():
            if re.search(r"""[\s"'`]on(click|load|error|input|change|submit|mouseover|focus)\s*=\s*["\\]""", sin_comentarios(t)):
                self.problema("en-linea", r, f"{r}: un manejador en línea (onclick=…): la CSP lo bloquea, usa addEventListener")
        plist = self.leer("app/Info.plist")
        if plist is not None:
            if "NSAppTransportSecurity" in plist:
                self.problema("ats", "app/Info.plist", "app/Info.plist: sin excepciones de App Transport Security")
            bid = re.search(r"<key>CFBundleIdentifier</key>\s*<string>([^<]+)</string>", plist)
            emp = self.leer("herramientas/empaquetar.sh") or ""
            firma = re.search(r'designated\s*=>\s*identifier\s+"([^"]+)"', emp)
            if bid and emp and (not firma or firma.group(1) != bid.group(1)):
                self.problema("bundle", "", f"El bundle id de app/Info.plist ({bid.group(1)}) no es el de la firma de herramientas/empaquetar.sh "
                                            f"({firma.group(1) if firma else 'sin --requirements designated'}): los permisos no sobrevivirían a una actualización")
            if emp and self.existe("acciones.json") and "acciones.json" not in emp:
                self.problema("empaquetar", "", "herramientas/empaquetar.sh tiene que copiar acciones.json junto a app.json (lo lee host-mac)")
            paquete = self.json("escritorio/package.json") if "escritorio" in plataformas else None
            v = re.search(r"<key>CFBundleShortVersionString</key>\s*<string>([^<]+)</string>", plist)
            if paquete and v and paquete.get("version") != v.group(1):
                self.problema("version", "", f"La versión de app/Info.plist ({v.group(1)}) y la de escritorio/package.json ({paquete.get('version')}) tienen que ser iguales")
        if "tauri" in plataformas:
            conf = self.json("escritorio/tauri.conf.json") or {}
            emp = self.leer("herramientas/empaquetar.sh") or ""
            firma = re.search(r'designated\s*=>\s*identifier\s+"([^"]+)"', emp)
            if emp and (not firma or firma.group(1) != conf.get("identifier")):
                self.problema("bundle", "", f"El identificador de escritorio/tauri.conf.json ({conf.get('identifier')}) no es el de la firma de "
                                            f"herramientas/empaquetar.sh ({firma.group(1) if firma else 'sin --requirements designated'}): los permisos no sobrevivirían a una actualización")
            recursos = (conf.get("bundle") or {}).get("resources") or {}
            if self.existe("acciones.json") and "../acciones.json" not in recursos:
                self.problema("empaquetar", "tauri", "escritorio/tauri.conf.json: acciones.json va dentro de la app (bundle.resources)")
            if conf.get("app", {}).get("withGlobalTauri"):
                self.problema("tauri-global", "", "escritorio/tauri.conf.json: withGlobalTauri expone toda la API de Tauri a la página: la interfaz solo usa el puente")
            if "NSAppTransportSecurity" in (self.leer("escritorio/Info.plist") or ""):
                self.problema("ats", "escritorio/Info.plist", "escritorio/Info.plist: sin excepciones de App Transport Security")
            if COMANDO_IA.search(self.juntar("escritorio/src/**/*.rs") or ""):
                pass  # lo revisa plataforma(«tauri») con lo propio
        if "escritorio" in plataformas:
            paquete = self.json("escritorio/package.json") or {}
            extra = json.dumps((paquete.get("build") or {}).get("extraResources") or [])
            if self.existe("acciones.json") and "acciones.json" not in extra:
                self.problema("empaquetar", "escritorio", "escritorio/package.json: acciones.json va dentro de la app (build.extraResources)")
            for r in self.archivos("escritorio/src/**/*.js"):
                t = self.leer(r) or ""
                for m in re.finditer(r"new BrowserWindow\(\{", t):
                    cuerpo = bloque(t[m.start():], "new BrowserWindow({")
                    if "nodeIntegration: true" in cuerpo or ("webPreferences: {" in cuerpo and ("sandbox: true" not in cuerpo or "contextIsolation: true" not in cuerpo)):
                        self.problema("electron-ventana", r, f"{r}: una ventana propia sin sandbox o sin contextIsolation (o con nodeIntegration)")
            if "ignore-scripts=true" not in (self.leer("escritorio/.npmrc") or ""):
                self.problema("npmrc", "escritorio", "escritorio/.npmrc: falta ignore-scripts=true (ningún paquete corre scripts al instalarse)")
        if "movil" in plataformas:
            self.movil()

    def movil(self):
        cap = self.json("movil/capacitor.config.json") or {}
        servidor = cap.get("server") or {}
        for clave in ("url", "cleartext", "allowNavigation"):
            if clave in servidor:
                self.problema("capacitor", clave, f"movil/capacitor.config.json: server.{clave} no va (la app sirve sus archivos desde el teléfono)")
        if (cap.get("android") or {}).get("allowMixedContent") or (cap.get("android") or {}).get("webContentsDebuggingEnabled"):
            self.problema("capacitor", "android", "movil/capacitor.config.json: android.allowMixedContent y webContentsDebuggingEnabled no van")
        man = self.leer("movil/android/app/src/main/AndroidManifest.xml")
        if man is not None:
            for atributo in ('android:allowBackup="false"', 'android:usesCleartextTraffic="false"'):
                if atributo not in man:
                    self.problema("android", atributo, f"AndroidManifest.xml: falta {atributo}")
            exportados = [n for _, n in re.findall(r'<(activity|service|receiver|provider)\b[^>]*android:name="([^"]+)"[^>]*android:exported="true"', man, re.S)]
            for n in exportados:
                if n != ".MainActivity":
                    self.problema("android-exportado", n, f"AndroidManifest.xml: {n} exportado (solo .MainActivity)")
        if "NSAppTransportSecurity" in (self.leer("movil/ios/App/App/Info.plist") or ""):
            self.problema("ats", "movil", "movil/ios/App/App/Info.plist: sin excepciones de App Transport Security")
        # Los métodos nativos que llama el anfitrión del teléfono existen en iOS, en Android y en el Capacitor falso de las pruebas.
        host = self.leer("movil/host/host.js") or ""
        falso = self.leer("pruebas/capacitor_falso.js") or ""
        planes = dict(self.extra("PLUGINS", {}) or {})
        for plugin, metodo in sorted(set(re.findall(r'llamar\("(\w+)", "(\w+)"', host))):
            ios, android = planes.get(plugin) or self._plugin(plugin)
            for que, patron in (("iOS", ios), ("Android", android)):
                if not patron:
                    self.problema("plugin", plugin, f"No encuentro el plugin «{plugin}» de {que} (en movil/plugins/* o en pruebas/contrato_app.py → PLUGINS)")
                    continue
                codigo = self.juntar(patron, propios=False)
                if not codigo:
                    if "node_modules" not in patron:
                        self.problema("plugin", f"{plugin}.{que}", f"No encuentro el plugin {plugin} de {que} ({patron})")
                    continue
                ok = (re.search(rf'CAPPluginMethod\(name: "{metodo}"', codigo) and re.search(rf"func {metodo}\(_ call: CAPPluginCall\)", codigo)) \
                    if que == "iOS" else re.search(rf"@PluginMethod[^\n]*\n\s*(?:public )?(?:fun|void) {metodo}\(", codigo)
                if not ok:
                    self.problema("plugin", f"{plugin}.{metodo}.{que}", f"{plugin}.{metodo} no existe en el plugin de {que}")
            if falso and not re.search(rf"\b{metodo}\b", falso[falso.find(plugin + ": {"):] if plugin + ": {" in falso else ""):
                self.problema("plugin-falso", f"{plugin}.{metodo}", f"{plugin}.{metodo} no está en pruebas/capacitor_falso.js")

    def pagina(self, plataformas):
        """Si la app tiene la página de la pieza «pagina»: lo que dice que pide (docs/pagina.json → «usa») es lo que usa el código."""
        d = self.json("docs/pagina.json") if self.existe("docs/pagina.json") else None
        if not isinstance(d, dict) or not isinstance(d.get("usa"), dict):
            return
        swift = self._swift_propio() if "mac" in plataformas else ""
        electron = self.juntar("escritorio/src/**/*.js") if "escritorio" in plataformas else ""
        rust = "\n".join(self.leer(r) or "" for r in self.archivos("escritorio/src/**/*.rs") if "/pieza/" not in r.replace(os.sep, "/")) if "tauri" in plataformas else ""
        usa = {"llavero": bool(re.search(r"\bSecretos\(", sin_comentarios(swift)) or re.search(r"\.secretos\(", sin_comentarios(rust))),
               "notificaciones": bool(re.search(r"\bNotificaciones\b", sin_comentarios(swift)) or re.search(r"host\.notificaciones\b", electron)
                                      or re.search(r"\.notificaciones\(\)", sin_comentarios(rust)))}
        for clave, de_verdad in usa.items():
            dice = bool(d["usa"].get(clave))
            if dice != de_verdad:
                self.problema("pagina-usa", clave, f"docs/pagina.json → usa.{clave} dice {str(dice).lower()} y el código {'sí' if de_verdad else 'no'} lo usa: "
                                                   "la página promete de más o de menos (cámbialo y corre pieza.py generar . pagina)")

    def _plugin(self, plugin):
        """Dónde está un plugin propio: la carpeta de movil/plugins cuyo código lo nombra (jsName / @CapacitorPlugin)."""
        for carpeta in sorted(glob.glob(self.ruta("movil/plugins/*"))):
            rel = os.path.relpath(carpeta, self.raiz).replace(os.sep, "/")
            codigo = self.juntar(f"{rel}/**/*.swift", f"{rel}/**/*.kt", f"{rel}/**/*.java", propios=False)
            if re.search(rf'jsName\s*=\s*"{plugin}"|@CapacitorPlugin\(\s*name\s*=\s*"{plugin}"', codigo):
                return f"{rel}/ios/**/*.swift", f"{rel}/android/**/*.[kj]*"
        # Uno oficial de Capacitor (@capacitor/<nombre>): se revisa solo si está instalado (npm ci en movil/).
        nombre = re.sub(r"(?<!^)([A-Z])", r"-\1", plugin).lower()
        base = f"movil/node_modules/@capacitor/{nombre}"
        return f"{base}/ios/**/*.swift", f"{base}/android/**/*.[kj]*"

    # ── Todo ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
    def correr(self):
        if not self.app:
            self.problema("app-json", "", "Falta app.json (pieza.py iniciar)")
            return self
        self.registradas, self.del_host = {}, {}
        plataformas = self.plataformas()
        self.interfaz()
        self.vista_previa()
        self.declaradas_()
        for p in plataformas:
            self.plataforma(p)
        self.seguridad(plataformas)
        self.pagina(plataformas)
        if self.ext and hasattr(self.ext, "revisar"):
            self.ext.revisar(self)
        for clave, motivo in self.excepciones.items():
            if not str(motivo or "").strip():
                self.problemas.append((f"excepcion:{clave}", f"pruebas/contrato_app.py: la excepción «{clave}» necesita su motivo"))
            elif clave not in self.usadas:
                self.problemas.append((f"excepcion:{clave}", f"pruebas/contrato_app.py: la excepción «{clave}» ya no hace falta (sácala)"))
        self.plataformas_ = plataformas
        return self

    def resumen(self):
        partes = [f"{len(self.acciones)} acciones", f"{len(self.funciones)} funciones en window.{self.global_}",
                  f"{len(self.declaradas)} declaradas"]
        for p in self.plataformas_:
            partes.append(f"{ {'tauri': 'Mac/Windows/Linux', 'mac': 'Mac', 'escritorio': 'Windows/Linux', 'movil': 'celular', 'ios': 'iPhone'}[p]}: {len(self.registradas[p])} registradas")
        return ", ".join(partes)


def main(argv):
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    extension, como_json = None, False
    i = 0
    while i < len(argv):
        if argv[i] == "--app" and i + 1 < len(argv):
            raiz, i = argv[i + 1], i + 1
        elif argv[i] == "--extension" and i + 1 < len(argv):
            extension, i = argv[i + 1], i + 1
        elif argv[i] == "--json":
            como_json = True
        else:
            sys.exit(__doc__.split("\n\n")[1])
        i += 1
    c = Contrato(raiz, extension).correr()
    if como_json:
        print(json.dumps({"ok": not c.problemas, "problemas": [{"codigo": k, "texto": t} for k, t in c.problemas],
                          "avisos": c.avisos}, ensure_ascii=False, indent=1))
        return 1 if c.problemas else 0
    for a in c.avisos:
        print(f"· {a}")
    if c.problemas:
        print("✗ Contrato roto (una excepción a propósito va en pruebas/contrato_app.py → EXCEPCIONES con su código y motivo):")
        print("\n".join(f"  - [{k}] {t}" for k, t in c.problemas))
        return 1
    print(f"✓ Contrato: {c.resumen()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
