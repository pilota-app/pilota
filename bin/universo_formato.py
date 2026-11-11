#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Pieza «universos»: el formato de un universo (solo datos). Solo biblioteca estándar.

Un universo cambia los colores (un tema de la pieza «tema») y los textos que la app le deja cambiar. Lo valida igual la app, el
catálogo de la comunidad (pieza «catalogo»: `"validador": "universo_formato"`) y `ui/universos.js`.

    {"id": "espacio", "categoria": "ciencia-ficcion", "nombre": "Espacio", "emoji": "🚀", "idioma": "es",
     "descripcion": "…", "autor": "…", "categorias": ["Ciencia ficción"],
     "tema": {"base": "vidrio", "colores": {"acento": "#ffb020"}},
     "textos": {"saludo": "Bienvenida a bordo"}, "listas": {"elogios": ["¡Despegue perfecto!"]}}

- `textos` y `listas`: claves que elige la app (minúsculas, números y _). Lo que la app no usa se ignora al usarlo.
- `tema.colores`: solo los tokens de «tema», en #rrggbb (el resto se descarta al usarlo; aquí se rechaza).
- Nada se ejecuta: ni HTML ni CSS. Todo texto se escapa al mostrarse.
- Sin personajes, logos ni marcas de otros: un universo de la comunidad lo revisa una persona antes de entrar al catálogo.

Uso: universo_formato.py <archivo.json>…   (sale con 1 si alguno no sirve)
"""
import json
import re
import sys
import unicodedata

FORMATO = 1
NOMBRES_CATEGORIAS = ("Espacio", "Naturaleza", "Ciudad", "Ciencia ficción", "Fantasía", "Deportes", "Música", "Clásicos",
                      "Minimalista", "Divertido")
TOKENS = ("fondo", "panel", "panel-2", "linea", "texto", "texto-suave", "tenue", "acento", "sobre-acento", "rojo", "verde")
BASES = ("claro", "oscuro", "vidrio")
CAMPOS = ("id", "categoria", "nombre", "emoji", "idioma", "descripcion", "autor", "categorias", "tema", "textos", "listas")
ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CLAVE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_TEXTOS, MAX_LISTAS, MAX_EN_LISTA = 60, 12, 30


def slug(nombre):
    t = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


CATEGORIAS = tuple(slug(c) for c in NOMBRES_CATEGORIAS)


def _texto(v, maximo):
    return isinstance(v, str) and 0 < len(v.strip()) <= maximo and "<" not in v and "\0" not in v


def validar(u):
    """Lista de problemas (vacía = sirve)."""
    if not isinstance(u, dict):
        return ["no es un objeto"]
    e = [f"campo desconocido: {k}" for k in u if k not in CAMPOS]
    if not isinstance(u.get("id"), str) or not ID.match(u["id"]) or len(u["id"]) > 40:
        e.append("id: minúsculas, números y guiones (hasta 40)")
    if not _texto(u.get("nombre"), 40):
        e.append("nombre: hasta 40 caracteres")
    if "emoji" in u and not _texto(u["emoji"], 8):
        e.append("emoji: uno solo")
    if u.get("idioma") not in ("es", "en"):
        e.append("idioma: es o en")
    if not _texto(u.get("descripcion"), 200):
        e.append("descripcion: hasta 200 caracteres")
    if "autor" in u and not _texto(u["autor"], 60):
        e.append("autor: hasta 60 caracteres")
    cats = u.get("categorias")
    if not isinstance(cats, list) or not 1 <= len(cats) <= 4 or any(c not in NOMBRES_CATEGORIAS for c in cats):
        e.append("categorias: de 1 a 4, de " + ", ".join(NOMBRES_CATEGORIAS))
    if "categoria" in u and u["categoria"] not in CATEGORIAS:
        e.append("categoria: la carpeta del catálogo")
    tema = u.get("tema")
    if not isinstance(tema, dict) or tema.get("base") not in BASES or set(tema) - {"base", "colores"}:
        e.append("tema: {base: claro|oscuro|vidrio, colores}")
    else:
        colores = tema.get("colores", {})
        if not isinstance(colores, dict) or any(k not in TOKENS or not isinstance(v, str) or not HEX.match(v) for k, v in colores.items()):
            e.append("tema.colores: solo " + ", ".join(TOKENS) + " en #rrggbb")
    textos = u.get("textos", {})
    if not isinstance(textos, dict) or len(textos) > MAX_TEXTOS or \
            any(not CLAVE.match(k) or not _texto(v, 200) for k, v in textos.items()):
        e.append(f"textos: hasta {MAX_TEXTOS}, clave en minúsculas y texto de hasta 200 caracteres sin «<»")
    listas = u.get("listas", {})
    if not isinstance(listas, dict) or len(listas) > MAX_LISTAS or any(
            not CLAVE.match(k) or not isinstance(v, list) or not 1 <= len(v) <= MAX_EN_LISTA or any(not _texto(x, 120) for x in v)
            for k, v in listas.items()):
        e.append(f"listas: hasta {MAX_LISTAS}, cada una de 1 a {MAX_EN_LISTA} textos de hasta 120 caracteres sin «<»")
    return e


def main(archivos):
    malos = 0
    for ruta in archivos:
        try:
            with open(ruta, encoding="utf-8") as f:
                problemas = validar(json.load(f))
        except (OSError, ValueError) as ex:
            problemas = [str(ex)]
        print(("✗ " if problemas else "✓ ") + ruta + "".join("\n  - " + p for p in problemas))
        malos += bool(problemas)
    return 1 if malos else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) if len(sys.argv) > 1 else print(__doc__) or 2)
