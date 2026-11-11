"""Lo que tu IA puede consultar de Pilota (pieza «mcp» de Pieza). Desde aquí es de la app: «pieza.py actualizar» no lo toca.

Cada herramienta es una función que recibe sus argumentos (ya validados contra su esquema) y devuelve un dict. La IA de la persona
las ve con su descripción: escríbela pensando en cuándo usarla («Úsala para “¿cómo voy este mes?”»).

Reglas (las mismas de la app):
- Solo lectura por defecto. Una herramienta que cambia algo lleva escribe=True (y borra=True si quita algo): solo aparece si la
  persona lo permite en Ajustes → Conectar a tu IA.
- Devuelve resúmenes, no todo: con un límite por defecto y un máximo (lo que lee la IA viaja a su proveedor con su cuenta).
- Nada que no necesite la respuesta: ni rutas, ni ids internos, ni claves.
- Un error que la IA puede corregir: raise mcp.ErrorHerramienta("…") (otro error le llega solo como su tipo).
- Nunca imprimas datos: lo que se imprime va a stderr, y algunas IA lo guardan en sus registros.
"""
import mcp
import nucleo

# La app: qué guarda Pilota y cómo leer sus datos (unidades, fechas, qué significa cada campo). La IA lo lee una vez.
INSTRUCCIONES = """Pilota guarda los datos de la persona en su computador. Responde en el idioma de la persona."""


def sobre_la_app(args):
    """Ejemplo: qué app es y su versión. La app: reemplázala por herramientas que lean sus datos."""
    a = nucleo.app()
    return {"app": a.get("nombre"), "version": a.get("version")}


# La app: suma aquí sus herramientas, p. ej.
#   mcp.herramienta("buscar", "Busca … por texto. Devuelve hasta 30 (o `limite`, máximo 200).", buscar,
#                   {"texto": {"type": "string", "maxLength": 200}, "limite": {"type": "integer", "minimum": 1, "maximum": 200}})
HERRAMIENTAS = [
    mcp.herramienta("sobre_la_app", "Qué app es y su versión. Úsala si no sabes qué datos hay.", sobre_la_app),
]
