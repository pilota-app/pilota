#!/usr/bin/env bash
# Abre Pilota de verdad (Linux, con una pantalla virtual) y revisa que la interfaz cargue y hable con el host: la página
# manda «listo» por el puente y recibe el estado. Con un HOME temporal: nada de la persona se toca.
# Uso: bash escritorio/pruebas/arranque.sh [ejecutable]   (sin ejecutable, compila el de desarrollo)
# Necesita: xvfb-run y dbus-run-session. Generado por Pieza («host-tauri»): si lo cambias, desde ahí es de la app.
set -euo pipefail
# La ruta del ejecutable se resuelve antes del cd (llega relativa a la raíz del repo).
if [ $# -ge 1 ]; then BIN="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; fi
cd "$(dirname "$0")/.."
if [ $# -ge 1 ]; then :; else cargo build --quiet; BIN="${CARGO_TARGET_DIR:-$PWD/target}/debug/pilota"; fi
casa=$(mktemp -d)
trap 'kill "$pid" 2>/dev/null || true; rm -rf "$casa" 2>/dev/null || true' EXIT
registro="$casa/puente.txt"
HOME="$casa" XDG_CONFIG_HOME="$casa/.config" PIEZA_REGISTRO="$registro" APPIMAGE_EXTRACT_AND_RUN=1 \
  xvfb-run -a dbus-run-session -- "$BIN" >"$casa/salida.txt" 2>&1 &
pid=$!
for _ in $(seq 1 40); do
  sleep 1
  # La página mandó «listo» y el host le respondió con el estado (el registro anota lo que va y lo que vuelve).
  if grep -q "^principal listo$" "$registro" 2>/dev/null && grep -q "^→ principal estado$" "$registro" 2>/dev/null; then
    echo "✓ Pilota abrió y la interfaz habla con el host ($(grep -c "^principal " "$registro") mensajes por el puente)"
    exit 0
  fi
  kill -0 "$pid" 2>/dev/null || break
done
echo "✗ Pilota no abrió, la interfaz no mandó «listo» o no recibió el estado" >&2
echo "Registro:" >&2; cat "$registro" >&2 2>/dev/null || echo "  (nada)" >&2
tail -20 "$casa/salida.txt" >&2 || true
exit 1
