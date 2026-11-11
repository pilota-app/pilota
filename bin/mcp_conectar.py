# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Conectar el servidor MCP de la app (bin/mcp_servidor.py) con la IA de la persona, en un clic (pieza «mcp»).

  mcp_conectar.py estado <salida.json>                 qué IA hay instaladas, cuáles ya tienen la app y qué puede hacer la IA
  mcp_conectar.py conectar <cliente> <salida.json>     agrega la app en esa IA
  mcp_conectar.py quitar <cliente> <salida.json>       la quita (no toca nada más de su configuración)
  mcp_conectar.py reparar <salida.json>                si la app cambió de lugar, actualiza la ruta donde ya estaba conectada

Cuando la IA tiene un comando para esto (claude/codex/gemini mcp add) se usa ese comando; si no, se edita su archivo de
configuración con cuidado: se lee entero, se cambia solo la entrada de la app, se guarda una copia de respaldo la primera vez
(<archivo>.antes-de-<id>) y se escribe de forma atómica. Nunca se borra otra entrada, y un archivo con errores no se toca.
"""
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nucleo  # noqa: E402

try:  # «ia» agrega al PATH las carpetas donde suelen quedar los CLI (las apps no heredan el PATH de la terminal)
    import ia  # noqa: E402,F401
except ImportError:
    pass

CASA = os.path.expanduser("~")
SERVIDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcp_servidor.py")


def nombre():
    """El nombre con que la app queda en la IA: su id (ya validado por nucleo: minúsculas y números)."""
    return nucleo.app()["id"]


def comando():
    """El Python que corre este script (en la app, el que viene adentro: <ID>_PYTHON) y la ruta del servidor."""
    return nucleo.entorno("PYTHON") or sys.executable, [SERVIDOR]


def _ruta_claude_desktop():
    if sys.platform == "darwin":
        return os.path.join(CASA, "Library", "Application Support", "Claude", "claude_desktop_config.json")
    if os.name == "nt":
        return os.path.join(os.environ.get("APPDATA", CASA), "Claude", "claude_desktop_config.json")
    return os.path.join(CASA, ".config", "Claude", "claude_desktop_config.json")


def _claude_desktop_instalado():
    rutas = ["/Applications/Claude.app", os.path.join(CASA, "Applications", "Claude.app"),
             os.path.join(os.environ.get("LOCALAPPDATA", CASA), "AnthropicClaude")]
    return any(os.path.exists(r) for r in rutas) or os.path.isdir(os.path.dirname(_ruta_claude_desktop()))


#: id → nombre visible, archivo donde queda la entrada y cómo se agrega. Los ids son los valores del enum de la acción.
CLIENTES = {
    "claude_desktop": {"nombre": "Claude (app de escritorio)", "archivo": _ruta_claude_desktop, "tipo": "json",
                       "instalado": _claude_desktop_instalado, "nota": "Cierra y vuelve a abrir Claude para que aparezca."},
    "claude_code": {"nombre": "Claude Code", "archivo": lambda: os.path.join(CASA, ".claude.json"), "tipo": "cli", "cli": "claude",
                    "agregar": lambda n, py, a: ["mcp", "add", "--scope", "user", n, "--", py, *a],
                    "quitar": lambda n: ["mcp", "remove", "--scope", "user", n]},
    "codex": {"nombre": "ChatGPT (app de escritorio y Codex)", "archivo": lambda: os.path.join(CASA, ".codex", "config.toml"),
              "tipo": "cli", "cli": "codex", "agregar": lambda n, py, a: ["mcp", "add", n, "--", py, *a],
              "quitar": lambda n: ["mcp", "remove", n]},
    "gemini": {"nombre": "Gemini CLI", "archivo": lambda: os.path.join(CASA, ".gemini", "settings.json"), "tipo": "cli", "cli": "gemini",
               "agregar": lambda n, py, a: ["mcp", "add", "-s", "user", n, py, *a], "quitar": lambda n: ["mcp", "remove", "-s", "user", n]},
    "antigravity": {"nombre": "Antigravity (Gemini)", "archivo": lambda: os.path.join(CASA, ".gemini", "config", "mcp_config.json"),
                    "tipo": "json", "instalado": lambda: bool(shutil.which("agy")) or os.path.isdir(os.path.join(CASA, ".gemini", "config"))},
}


# ───────────── Leer y escribir configuraciones sin romper nada ─────────────
def _leer_json(ruta):
    """{} si no existe; None si existe pero no es JSON válido (en ese caso no lo tocamos)."""
    if not os.path.exists(ruta):
        return {}
    try:
        with open(ruta, encoding="utf-8") as f:
            texto = f.read()
        return json.loads(texto) if texto.strip() else {}
    except (OSError, ValueError):
        return None


def _respaldar(ruta):
    copia = f"{ruta}.antes-de-{nombre()}"
    if os.path.exists(ruta) and not os.path.exists(copia):
        shutil.copy2(ruta, copia)


def _entrada_json(ruta):
    d = _leer_json(ruta)
    servidores = d.get("mcpServers") if isinstance(d, dict) else None
    e = servidores.get(nombre()) if isinstance(servidores, dict) else None
    return e if isinstance(e, dict) else None


def _entrada_toml(ruta):
    """Solo lo necesario para saber si está y con qué ruta: [mcp_servers.<id>] y sus líneas command y args."""
    try:
        with open(ruta, encoding="utf-8") as f:
            texto = f.read()
    except OSError:
        return None
    n = re.escape(nombre())
    m = re.search(rf"^\[mcp_servers\.(?:{n}|\"{n}\")\]\s*$(.*?)(?=^\[|\Z)", texto, re.M | re.S)
    if not m:
        return None
    a = re.search(r"^args\s*=\s*(\[.*?\])", m.group(1), re.M | re.S)
    c = re.search(r"^command\s*=\s*\"(.*?)\"", m.group(1), re.M)
    try:
        args = json.loads(a.group(1)) if a else []
    except ValueError:
        args = []
    return {"command": c.group(1) if c else "", "args": args if isinstance(args, list) else []}


def entrada(cid):
    ruta = CLIENTES[cid]["archivo"]()
    return _entrada_toml(ruta) if ruta.endswith(".toml") else _entrada_json(ruta)


def instalado(cid):
    c = CLIENTES[cid]
    return bool(shutil.which(c["cli"])) if c["tipo"] == "cli" else c["instalado"]()


def _herramientas():
    """Lo que la IA puede hacer, para mostrarlo en Ajustes (nombre visible y si lee o cambia algo)."""
    try:
        import mcp
        import mcp_servidor
        hs, _ = mcp_servidor.juntar()
        escribir = nucleo.config().get("mcp_escribir") is True
        return [{"nombre": h["nombre"], "titulo": h["titulo"], "escribe": h["escribe"], "activa": escribir or not h["escribe"]}
                for h in sorted(hs, key=lambda h: h["nombre"])], mcp.actividad(20)
    except (Exception, SystemExit) as e:  # noqa: BLE001 — un módulo de la app con un error no deja a Ajustes sin estado
        return [{"error": str(e)[:200]}], []


def estado():
    clientes = []
    for cid, c in CLIENTES.items():
        e = entrada(cid)
        clientes.append({"id": cid, "nombre": c["nombre"], "instalado": instalado(cid), "conectado": bool(e),
                         "al_dia": bool(e) and SERVIDOR in (e.get("args") or []), "nota": c.get("nota", "")})
    herramientas, act = _herramientas()
    return {"ok": True, "clientes": clientes, "herramientas": herramientas, "actividad": act,
            "escribir": nucleo.config().get("mcp_escribir") is True}


def _correr(cli, args):
    try:
        p = subprocess.run([shutil.which(cli) or cli, *args], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
                           cwd=CASA)  # sin entrada: un CLI que la espera no cuelga la app
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return p.returncode == 0, (p.stderr or p.stdout or "").strip()[-300:]


def _escribir_json(cid, valor):
    ruta = os.path.realpath(CLIENTES[cid]["archivo"]())  # si es un enlace (dotfiles), se escribe el archivo real
    if valor is None and not os.path.exists(ruta):
        return True, ""  # quitar de un archivo que no existe: nada que hacer (y no se crea)
    d = _leer_json(ruta)
    if d is None:
        return False, "Su archivo de configuración tiene un error y no lo quise tocar. Revísalo o conéctalo a mano."
    if not isinstance(d, dict) or not isinstance(d.get("mcpServers", {}), dict):
        return False, "Su archivo de configuración tiene un formato inesperado y no lo quise tocar."
    _respaldar(ruta)
    servidores = d.setdefault("mcpServers", {})
    if valor is None:
        servidores.pop(nombre(), None)
    else:
        servidores[nombre()] = valor
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    nucleo.escribir_atomico(ruta, json.dumps(d, ensure_ascii=False, indent=2) + "\n")
    return True, ""


def conectar(cid):
    c = CLIENTES.get(cid)
    if not c:
        return {"ok": False, "error": "No conozco esa IA."}
    if not instalado(cid):
        return {"ok": False, "error": "No encontré {ia} en este computador.", "valores": {"ia": c["nombre"]}}
    py, args = comando()
    if c["tipo"] == "json":
        ok, error = _escribir_json(cid, {"command": py, "args": args})
    else:
        estaba = bool(entrada(cid))
        if estaba:  # ya estaba (quizás con otra ruta): se quita y se vuelve a agregar
            _correr(c["cli"], c["quitar"](nombre()))
        ok, error = _correr(c["cli"], c["agregar"](nombre(), py, args))
        if not ok and estaba:
            error = (error + " " if error else "") + "La conexión anterior se quitó: vuelve a intentarlo."
    if not ok:
        return {"ok": False, "error": error or "{ia} no aceptó la conexión.", "valores": {"ia": c["nombre"]}}
    return {**estado(), "ok": True, "nota": c.get("nota", "")}


def quitar(cid):
    c = CLIENTES.get(cid)
    if not c:
        return {"ok": False, "error": "No conozco esa IA."}
    if c["tipo"] == "json":
        ok, error = _escribir_json(cid, None)
    else:
        ok, error = _correr(c["cli"], c["quitar"](nombre())) if entrada(cid) else (True, "")
    return {**estado(), "ok": ok, "error": error}


def reparar():
    """Si la persona movió la app (o se actualizó a otra carpeta), las conexiones viejas apuntan a una ruta que ya no existe."""
    arreglados = []
    for x in estado()["clientes"]:
        if x["conectado"] and not x["al_dia"] and x["instalado"] and conectar(x["id"]).get("ok"):
            arreglados.append(x["id"])
    return {**estado(), "ok": True, "arreglados": arreglados}


def main(a):
    if len(a) == 2 and a[0] in ("estado", "reparar"):
        res = estado() if a[0] == "estado" else reparar()
    elif len(a) == 3 and a[0] in ("conectar", "quitar") and a[1] in CLIENTES:
        res = (conectar if a[0] == "conectar" else quitar)(a[1])
    else:
        print(__doc__, file=sys.stderr)
        return 2
    nucleo.responder(a[-1], res)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:  # noqa: BLE001 — la persona ve un mensaje, no una traza
        if len(sys.argv) > 2:
            nucleo.responder(sys.argv[-1], {"ok": False, "error": str(e) or type(e).__name__})
        sys.exit(0)
