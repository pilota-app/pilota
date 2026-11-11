#!/bin/bash
# Empaqueta Pilota para este sistema (o el que digas) con su host de Tauri («host-tauri»): la app nativa en Rust, Python
# portátil y el código (en recursos/: bin/, ui/, app.json, acciones.json y lo de app.json → empaquetado.carpetas). Deja en dist/ los archivos
# de nombre fijo que usan el Release, instalar.sh, instalar.ps1 y el actualizador, cada uno con su .sha256:
#   mac      Pilota-macOS.zip
#   windows  Pilota-Windows.exe            (instalador por usuario, /S silencioso)
#   linux    Pilota-Linux.AppImage  Pilota-Linux.tar.gz
# Uso: bash herramientas/empaquetar.sh [mac|windows|linux]     Necesita: cargo (Rust) y, la primera vez, internet.
# Generado por la pieza «empaquetado» de Pieza (MPL-2.0, https://mozilla.org/MPL/2.0/) desde app.json: si lo cambias, desde ahí
# es de la app y Pieza ya no lo toca. Lo propio va en app.json → empaquetado o en herramientas/empaquetar-extra.sh.
set -euo pipefail
RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"
case "${1:-$(uname -s)}" in
  mac | Darwin) SO=mac; V=mac ;;
  windows | MINGW* | MSYS* | CYGWIN*) SO=windows; V=win ;;
  linux | Linux) SO=linux; V=linux ;;
  *) echo "sistema desconocido: $1" >&2; exit 1 ;;
esac
VERSION=$(python3 -c "import json;print(json.load(open('app.json'))['version'])" 2>/dev/null || echo 0.1.0)
mkdir -p dist
huella() { if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
firmar() { (cd dist && printf '%s  %s\n' "$(huella "$1")" "$1" > "$1.sha256"); }

# Lo que va adentro: Python portátil y los programas de app.json (cada uno verificado con su huella).
bash escritorio/herramientas/preparar.sh "$SO"
# La CLI de Tauri, con versión fija (sin npm).
command -v cargo-tauri >/dev/null || cargo install tauri-cli --version "^2" --locked
# Los íconos de todos los sistemas, desde uno solo de 1024×1024.
if [ -f escritorio/iconos/icono.png ] && [ ! -f escritorio/iconos/icon.icns ]; then (cd escritorio && cargo tauri icon iconos/icono.png -o iconos); fi
# La versión de app.json y, para empaquetar, también Python y las herramientas (en desarrollo se usa el Python del sistema).
cat > escritorio/LICENCIAS-TERCEROS.txt <<'TXT'
Pilota se distribuye con la licencia AGPL-3.0 (https://github.com/pilota-app/pilota). Dentro de la app va, como programa aparte:

- Python 3.13 de python-build-standalone (https://github.com/astral-sh/python-build-standalone), licencia PSF y las de sus partes.
- Tauri (https://tauri.app) y los crates de Rust de escritorio/Cargo.lock, con licencias MIT, Apache-2.0 y otras compatibles.
TXT
cat > escritorio/tauri.empaquetar.json <<JSON
{ "version": "$VERSION", "bundle": { "resources": { "vendor/$V/python/": "python/", "vendor/$V/herramientas/": "herramientas/", "LICENCIAS-TERCEROS.txt": "LICENCIAS-TERCEROS.txt" } } }
JSON
# La app usa los datos de la persona, nunca la demo de la vista previa.
QUITAR=(ui/demo.json)
GUARDADO=$(mktemp -d)
for q in "${QUITAR[@]}"; do if [ -e "$q" ]; then mkdir -p "$GUARDADO/$(dirname "$q")"; mv "$q" "$GUARDADO/$q"; fi; done
devolver() { for q in "${QUITAR[@]}"; do if [ -e "$GUARDADO/$q" ]; then mv "$GUARDADO/$q" "$q"; fi; done; rm -rf "$GUARDADO" escritorio/tauri.empaquetar.json escritorio/LICENCIAS-TERCEROS.txt; }
trap devolver EXIT

B=escritorio/target/release/bundle
case "$SO" in
  mac)
    (cd escritorio && cargo tauri build --bundles app --config tauri.empaquetar.json)
    APP="$B/macos/Pilota.app"
    if [ -f herramientas/empaquetar-extra.sh ]; then bash herramientas/empaquetar-extra.sh "$APP" "$SO"; fi
    # Firma ad hoc (sin cuenta de Apple), con requisito por identificador: el Llavero y los permisos siguen a la app al actualizar.
    find "$APP/Contents/Resources" -type f \( -name "*.so" -o -name "*.dylib" -o -perm -u+x \) -exec codesign --force --sign - {} \; 2>/dev/null || true
    codesign --force --deep --sign - --requirements '=designated => identifier "app.pilota.mac"' "$APP"
    rm -rf "dist/Pilota.app" && ditto "$APP" "dist/Pilota.app"
    (cd dist && rm -f Pilota-macOS.zip && ditto -c -k --keepParent Pilota.app Pilota-macOS.zip)
    firmar Pilota-macOS.zip ;;
  windows)
    (cd escritorio && cargo tauri build --bundles nsis --config tauri.empaquetar.json)
    cp "$(ls "$B"/nsis/*.exe | head -1)" dist/Pilota-Windows.exe
    firmar Pilota-Windows.exe ;;
  linux)
    (cd escritorio && cargo tauri build --bundles appimage --config tauri.empaquetar.json)
    cp "$(ls "$B"/appimage/*.AppImage | head -1)" dist/Pilota-Linux.AppImage && chmod +x dist/Pilota-Linux.AppImage
    firmar Pilota-Linux.AppImage
    # El tar.gz de instalar.sh (~/.local/share/Pilota): el ejecutable, el código en recursos/ y Python, todo junto.
    T=$(mktemp -d); D="$T/Pilota"; mkdir -p "$D/recursos"
    cp escritorio/target/release/pilota "$D/"
    for d in app.json acciones.json bin ui; do cp -R "$d" "$D/recursos/"; done
    cp escritorio/LICENCIAS-TERCEROS.txt "$D/"
    for q in "${QUITAR[@]}"; do rm -rf "$D/recursos/$q"; done
    cp -R escritorio/vendor/linux/python "$D/python"; cp -R escritorio/vendor/linux/herramientas "$D/herramientas"
    if [ -f escritorio/iconos/128x128.png ]; then cp escritorio/iconos/128x128.png "$D/pilota.png"; fi
    tar -czf dist/Pilota-Linux.tar.gz -C "$T" Pilota && rm -rf "$T"
    firmar Pilota-Linux.tar.gz ;;
esac
echo "Listo: $(ls dist | tr '\n' ' ')"
