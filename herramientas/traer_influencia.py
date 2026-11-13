#!/usr/bin/env python3
"""Copia las personas y los eventos del repo pilota-app/influencia en bin/influencia.json (lo que viaja en la app).

  python3 herramientas/traer_influencia.py <carpeta del repo influencia>

Se corre a mano antes de armar una versión: Pilota no sale a GitHub.
"""
import datetime
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    origen = sys.argv[1]
    personas = json.load(open(os.path.join(origen, "personas.json"), encoding="utf-8"))
    eventos = json.load(open(os.path.join(origen, "eventos.json"), encoding="utf-8"))
    salida = {"formato": 1, "al": datetime.date.today().isoformat(), "fuente": "https://github.com/pilota-app/influencia",
              "personas": [{"id": p["id"], "nombre": p["nombre"]} for p in personas],
              "eventos": [{k: e[k] for k in ("persona", "fecha", "que", "activo", "movimiento")} for e in eventos]}
    with open(os.path.join(RAIZ, "bin", "influencia.json"), "w", encoding="utf-8") as f:
        json.dump(salida, f, indent=1, ensure_ascii=False)
    print(len(personas), "personas,", len(eventos), "eventos")
