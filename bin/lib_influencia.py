"""Las noticias de las personas que mueven el precio (repo pilota-app/influencia), copiadas en `bin/influencia.json`.

No toca la red: el archivo viaja dentro de la app y se pone al día con `herramientas/traer_influencia.py`. Cada evento se
revisa antes de mostrarlo (fecha, activo y números): lo que no se entiende se salta. No decide nada: en el estudio de nov
2026, sumar estas noticias no cambió la probabilidad de que el precio suba (el salto pasa en minutos). Se muestran como
contexto. No es una acción.
"""
import datetime
import json
import os
import re

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "influencia.json")
DIA_MS = 86_400_000
ACTIVO = re.compile(r"^[A-Z]{2,6}$")
FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ms(fecha):
    return int(datetime.datetime.fromisoformat(fecha).replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)


def _numero(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and abs(x) < 10 else None


def cargar(ruta=RUTA):
    try:
        with open(ruta, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {"eventos": [], "personas": {}, "al": None}
    personas = {p["id"]: p["nombre"] for p in d.get("personas") or [] if isinstance(p, dict)
                and isinstance(p.get("id"), str) and isinstance(p.get("nombre"), str)}
    eventos = []
    for e in d.get("eventos") or []:
        if not isinstance(e, dict) or not FECHA.match(str(e.get("fecha"))) or not ACTIVO.match(str(e.get("activo"))):
            continue
        mov = e.get("movimiento") if isinstance(e.get("movimiento"), dict) else {}
        eventos.append({"ms": _ms(e["fecha"]), "fecha": e["fecha"], "activo": e["activo"],
                        "persona": personas.get(e.get("persona")), "que": str(e.get("que") or "")[:160],
                        "dia": _numero(mov.get("dia")), "d20": _numero(mov.get("d20"))})
    eventos.sort(key=lambda e: e["ms"])
    return {"eventos": eventos, "personas": personas, "al": d.get("al") if FECHA.match(str(d.get("al"))) else None}


def recientes(ms, activos, dias=30, datos=None):
    """Los eventos de personas de la lista sobre esos activos en los últimos `dias`, el más nuevo primero, y la fecha de
    los datos (para decir de cuándo son)."""
    d = datos or cargar()
    activos = set(activos)
    lista = [e for e in d["eventos"] if e["persona"] and e["activo"] in activos and ms - dias * DIA_MS <= e["ms"] <= ms]
    return {"eventos": lista[::-1][:5], "al": d["al"], "dias": dias}
