#!/bin/bash
# Compila Pilota y la instala en ~/Applications/Pilota.app (para desarrollo en este Mac).
# El checkout va en ~/Developer/pilota (macOS no distingue mayúsculas: ~/pilota podría chocar con una carpeta de datos ~/Pilota).
# El empaquetado está en herramientas/empaquetar.sh (el mismo que usa GitHub para publicar cada versión, con «host-tauri»).
# Generado por la pieza «empaquetado» de Pieza (MPL-2.0, https://mozilla.org/MPL/2.0/) desde app.json: si lo cambias, desde ahí
# es de la app y Pieza ya no lo toca. Lo propio de la app va en app.json → empaquetado o en herramientas/antes-de-instalar.sh.
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:$PATH
RAIZ="$(cd "$(dirname "$0")" && pwd)"
# Cerrar la app en medio de un trabajo lo cortaría: no se instala mientras corre (FORZAR=1 instala igual).
if [ "${FORZAR:-0}" != "1" ]; then
  # Lo que no se ve con pgrep (p. ej. «hay una grabación en curso»): la app lo revisa aquí; si sale con un error, no se instala.
  if [ -f "$RAIZ/herramientas/antes-de-instalar.sh" ]; then bash "$RAIZ/herramientas/antes-de-instalar.sh" || exit 3; fi
fi
bash "$RAIZ/herramientas/empaquetar.sh" mac
APP="$HOME/Applications/Pilota.app"
mkdir -p "$HOME/Applications"
osascript -e 'tell application id "app.pilota.mac" to quit' 2>/dev/null || true
sleep 1
pkill -x pilota 2>/dev/null || true
rm -rf "$APP"
ditto "$RAIZ/dist/Pilota.app" "$APP"
# La app sabe que viene de este checkout (fuera de la app, para no romper su firma): la pieza «actualizaciones» la pone al día con
# git pull + herramientas/empaquetar.sh.
DATOS="$HOME/Library/Application Support/Pilota"
mkdir -p "$DATOS" && chmod 700 "$DATOS" && printf '%s\n' "$RAIZ" > "$DATOS/desarrollo"
echo "Instalada en $APP ($(du -sh "$APP" | cut -f1))"
open "$APP"
