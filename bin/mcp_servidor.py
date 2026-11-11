# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""El servidor MCP de la app (pieza «mcp»): es lo que abre la IA de la persona. No hay que escribirlo en cada app.

Junta las herramientas de los módulos que dice `app.json` → `"mcp": {"modulos": ["mcp_herramientas"]}` (por defecto ese), cada
uno en `bin/`, con su lista `HERRAMIENTAS` y, si quiere, su texto `INSTRUCCIONES`. Así una pieza o una parte de la app suma sus
herramientas con una línea en `app.json`, sin tocar este archivo.

Conectarlo: la app lo hace sola en Ajustes («Conectar a tu IA», con mcp_conectar.py). A mano, con la ruta de este archivo:
  claude mcp add --scope user <id> -- python3 /ruta/a/bin/mcp_servidor.py
  codex mcp add <id> -- python3 /ruta/a/bin/mcp_servidor.py
  gemini mcp add -s user <id> python3 /ruta/a/bin/mcp_servidor.py
  Claude Desktop: "mcpServers": {"<id>": {"command": "python3", "args": ["/ruta/a/bin/mcp_servidor.py"]}}
"""
import importlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcp  # noqa: E402
import nucleo  # noqa: E402

MODULO = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def modulos():
    seccion = nucleo.app().get("mcp")
    lista = seccion.get("modulos") if isinstance(seccion, dict) else None
    lista = lista if isinstance(lista, list) and lista else ["mcp_herramientas"]
    malos = [m for m in lista if not isinstance(m, str) or not MODULO.match(m) or m in ("mcp", "mcp_servidor", "mcp_conectar")]
    if malos:
        raise SystemExit(f"app.json → mcp.modulos: nombres inválidos {malos!r}")
    return lista


def juntar():
    herramientas, instrucciones = [], []
    aqui = os.path.dirname(os.path.abspath(__file__))
    for nombre in modulos():
        if not os.path.isfile(os.path.join(aqui, nombre + ".py")):  # solo módulos de bin/, nunca del sistema
            raise SystemExit(f"Falta bin/{nombre}.py (app.json → mcp.modulos)")
        m = importlib.import_module(nombre)
        herramientas += mcp._normalizar(getattr(m, "HERRAMIENTAS", []))
        if isinstance(getattr(m, "INSTRUCCIONES", None), str):
            instrucciones.append(m.INSTRUCCIONES.strip())
    return herramientas, "\n\n".join(x for x in instrucciones if x)


def main():
    herramientas, instrucciones = juntar()
    mcp.servir(herramientas, instrucciones=instrucciones)


if __name__ == "__main__":
    main()
