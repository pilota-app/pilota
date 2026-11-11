#!/bin/bash
# Arma lo que la app (Mac, Windows o Linux) lleva adentro, para que la persona no instale nada:
#   vendor/<mac|linux|win>/python        Python portátil (python-build-standalone, verificado por SHA-256; ../herramientas/python.lock)
#   vendor/<mac|linux|win>/herramientas  Los programas de app.json → empaquetado.<mac|escritorio>.binarios (cada uno con su huella),
#                                    whisper-cli si empaquetado.whisper (compilado aquí) y lo que
#                                    arme herramientas/preparar-extra.sh (opcional, de la app).
# Uso: bash herramientas/preparar.sh mac|linux|windows      Necesita: curl, tar y gzip. Corre en Linux o macOS.
# Generado por la pieza «empaquetado» de Pieza (MPL-2.0, https://mozilla.org/MPL/2.0/) desde app.json: si lo cambias, desde ahí
# es de la app y Pieza ya no lo toca.
set -euo pipefail
cd "$(dirname "$0")/.."

SO="${1:?uso: preparar.sh mac|linux|windows}"
case "$SO" in mac) OS=mac; EXE="" ;; linux) OS=linux; EXE="" ;; windows | win) OS=win; EXE=".exe" ;; *) echo "sistema desconocido: $SO"; exit 1 ;; esac
DESTINO="vendor/$OS"
CACHE_VAR=PILOTA_CACHE
CACHE="${!CACHE_VAR:-$HOME/.cache/pilota-escritorio}"
mkdir -p "$CACHE" "$DESTINO/herramientas"

huella() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
bajar() { # url sha destino
  if [ -f "$3" ] && [ "$(huella "$3")" = "$2" ]; then return; fi
  echo "→ $(basename "$3")"
  curl -fL --proto '=https' --retry 3 -o "$3.tmp" "$1"
  [ "$(huella "$3.tmp")" = "$2" ] || { echo "✗ Huella distinta: $1 (no se usa)"; rm -f "$3.tmp"; exit 1; }
  mv "$3.tmp" "$3"
}

# ── Python portátil: el mismo que la app de Mac y que las demás apps de la familia ──
LOCK=../herramientas/python.lock
case "$OS" in mac) CLAVE=mac ;; linux) CLAVE=linux ;; *) CLAVE=windows ;; esac
read -r _ PY_URL PY_SHA < <(grep "^$CLAVE " "$LOCK")
PY_VER=$(sed -n 's/^version //p' "$LOCK")
bajar "$PY_URL" "$PY_SHA" "$CACHE/python-$PY_VER-$OS.tar.gz"
rm -rf "$DESTINO/python" "$DESTINO/python.tmp"; mkdir -p "$DESTINO/python.tmp"
tar -xzf "$CACHE/python-$PY_VER-$OS.tar.gz" -C "$DESTINO/python.tmp"
mv "$DESTINO/python.tmp/python" "$DESTINO/python"; rmdir "$DESTINO/python.tmp"
# Más liviano: sin pruebas, tkinter, idle, pip ni encabezados (la app solo usa la biblioteca estándar).
for d in lib/python3.13/test lib/python3.13/idlelib lib/python3.13/tkinter lib/python3.13/turtledemo lib/python3.13/ensurepip lib/python3.13/site-packages \
         lib/tcl9.0 lib/tk9.0 Lib/test Lib/idlelib Lib/tkinter Lib/turtledemo Lib/ensurepip Lib/site-packages Lib/venv include share tcl libs; do rm -rf "$DESTINO/python/$d"; done
find "$DESTINO/python" \( -name "*.pdb" -o -name "__pycache__" -o -name "libtcl*" -o -name "libtk*" -o -name "_tkinter*" \) -prune -exec rm -rf {} +
rm -f "$DESTINO/python/bin/"{idle3*,pip*,pydoc3*,python3*-config} 2>/dev/null || true

# Lo que la app arma a su manera (p. ej. compilar un programa): recibe el sistema, el destino y el caché.
if [ -f herramientas/preparar-extra.sh ]; then bash herramientas/preparar-extra.sh "$OS" "$DESTINO" "$CACHE"; fi
if [ "$OS" != win ]; then chmod +x "$DESTINO/herramientas/"* 2>/dev/null || true; fi
echo "Listo: $DESTINO ($(du -sh "$DESTINO" | cut -f1))"
