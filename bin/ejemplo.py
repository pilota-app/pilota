#!/usr/bin/env python3
"""ejemplo — la acción de ejemplo de Pilota: cuenta las palabras y las letras de un texto. Solo biblioteca estándar.

  ejemplo.py contar <entrada.json {"texto": "…"}> <salida.json>

La app: reemplázalo por lo propio (y la acción «ejemplo» de app.json → acciones, ui/app.js y pruebas/test_app.py con él). Lo que
escribe la persona llega en el archivo de entrada, nunca como argumento, y el último argumento es siempre el JSON de salida (pieza
«nucleo»). El host lo corre con su límite de tiempo y responde window.Pilota.ejemploListo(salida).
"""
import nucleo


def contar(d):
    texto = d.get("texto") if isinstance(d.get("texto"), str) else ""
    return {"ok": True, "palabras": len(texto.split()), "letras": sum(c.isalpha() for c in texto)}


if __name__ == "__main__":
    nucleo.script({"contar": contar}, __doc__)
