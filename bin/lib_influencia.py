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
        return {"eventos": [], "personas": {}, "ranking": [], "al": None}
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
    ranking = []
    for r in d.get("ranking") or []:
        puntaje = r.get("puntaje") if isinstance(r, dict) else None
        if isinstance(r, dict) and r.get("id") in personas and isinstance(puntaje, (int, float)) and 0 <= puntaje < 1000:
            ranking.append({"nombre": personas[r["id"]], "puntaje": float(r["puntaje"]),
                            "eventos": int(r.get("eventos") or 0), "ultimo": r.get("ultimo_evento") if FECHA.match(str(r.get("ultimo_evento"))) else None,
                            "duro": _numero(r.get("duro_20d"))})
    return {"eventos": eventos, "personas": personas, "ranking": ranking[:10],
            "al": d.get("al") if FECHA.match(str(d.get("al"))) else None}


def recientes(ms, activos, dias=30, datos=None):
    """Los eventos de personas de la lista sobre esos activos en los últimos `dias`, el más nuevo primero, y la fecha de
    los datos (para decir de cuándo son)."""
    d = datos or cargar()
    activos = set(activos)
    lista = [e for e in d["eventos"] if e["persona"] and e["activo"] in activos and ms - dias * DIA_MS <= e["ms"] <= ms]
    return {"eventos": lista[::-1][:5], "al": d["al"], "dias": dias, "ranking": d["ranking"][:5]}


def negativas(ms, pares, dias=5, datos=None):
    """Las malas noticias que frenan la compra: por par, la noticia más nueva de una persona de la lista que bajó el precio
    de esa moneda (o de BTC, que arrastra a todas) y que pasó en los últimos `dias` antes de `ms`. Es lo que pesa en la
    decisión del perfil tendencia (`lib_tendencia.filas_cruce`): en el estudio de nov 2026, esperar en USDT esos días
    mejoró la regla en el tramo de elegir y en el de probar."""
    d = datos or cargar()
    salida = {}
    for par in pares:
        moneda = par[:-len("USDT")] if par.endswith("USDT") else par
        for e in reversed(d["eventos"]):
            if (e["persona"] and e["activo"] in (moneda, "BTC") and e["dia"] is not None and e["dia"] < 0
                    and e["ms"] < ms <= e["ms"] + dias * DIA_MS):
                salida[par] = {"persona": e["persona"], "que": e["que"], "fecha": e["fecha"], "dia": e["dia"],
                               "activo": e["activo"]}
                break
    return salida
