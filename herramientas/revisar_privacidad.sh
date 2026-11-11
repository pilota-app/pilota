#!/bin/bash
# Revisa que lo que se va a subir no tenga datos personales.
# Uso: bash herramientas/revisar_privacidad.sh [--todo | --generico]   (por defecto: lo que está en stage; --todo: todo lo versionado)
# Los términos a buscar están en .terminos-privados (local, NUNCA se versiona): nombres, empresas, correos y rutas reales, uno por
# línea, sin distinguir mayúsculas. --generico (lo que corre GitHub) revisa solo correos personales, rutas de usuario y RUT.
cd "$(dirname "$0")/.." || exit 1
LISTA=.terminos-privados
GENERICO="[A-Za-z0-9._%+-]+@(gmail|hotmail|outlook|yahoo|icloud|live)\.(com|cl)|/Users/[a-z]|/home/[a-z]+/|C:\\\\Users\\\\|[0-9]{1,2}\.?[0-9]{3}\.?[0-9]{3}-[0-9kK]\b"
if [ "$1" = "--generico" ]; then
  HALLAZGOS=$(git ls-files -z | grep -zv '^LICENSE$' | xargs -0 grep -InE "$GENERICO" 2>/dev/null | grep -v 'users.noreply.github.com' | head -40)
  if [ -n "$HALLAZGOS" ]; then echo "✗ Posibles datos personales:"; printf '%s\n' "$HALLAZGOS"; exit 1; fi
  echo "✓ Sin correos personales ni rutas de usuario."; exit 0
fi
if [ ! -s "$LISTA" ]; then
  echo "⚠️  Falta $LISTA (nombres, empresas, correos y rutas reales, uno por línea). Créalo antes de commitear." >&2
  exit 2
fi
if [ "$1" = "--todo" ]; then
  CONTENIDO=$(git ls-files -z | xargs -0 cat 2>/dev/null)
  CONTENIDO="$CONTENIDO
$(git log --format='%an %ae %cn %ce %B' 2>/dev/null)"
else
  CONTENIDO=$(git diff --cached -U0 | grep '^+' | grep -v '^+++')
fi
PATRON=$(grep -v '^\s*#' "$LISTA" | grep -v '^\s*$' | sed 's/[.[\*^$|]/\\&/g' | paste -sd'|' -)
PATRON="${PATRON}|${GENERICO}"
HALLAZGOS=$(printf '%s\n' "$CONTENIDO" | grep -inE "$PATRON" | grep -v 'users.noreply.github.com' | head -40)
if [ -n "$HALLAZGOS" ]; then
  echo "✗ Posibles datos personales:"; printf '%s\n' "$HALLAZGOS"; exit 1
fi
echo "✓ Sin datos personales en lo revisado."
