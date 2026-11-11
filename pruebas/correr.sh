#!/usr/bin/env bash
# Todas las pruebas de Pilota. Córrelas antes de cada commit; GitHub las corre en cada cambio (.github/workflows/revisar.yml).
# Sin dependencias: Python con la biblioteca estándar y Node (y Rust para la app nativa, si lo tienes). La interfaz en un navegador de verdad necesita Playwright
# (PLAYWRIGHT=/ruta/a/node_modules/playwright); sin él se avisa y se sigue.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "Sintaxis"
python3 -m py_compile bin/*.py
node --check ui/app.js
# La app nativa (host-tauri, Rust): si hay cargo, que compile y pasen sus pruebas (sin cargo, lo revisa GitHub).
if [ -f escritorio/Cargo.toml ] && command -v cargo >/dev/null && [ "${SIN_RUST:-0}" != "1" ]; then
  echo "App nativa (Rust)"
  (cd escritorio && cargo test --quiet 2>&1 | tail -3)
fi
echo "Contrato del puente (pieza «contrato»)"
python3 pruebas/contrato.py
echo "Python"
python3 -W ignore -m unittest discover -q -s pruebas -p 'test_*.py'
if PLAYWRIGHT="${PLAYWRIGHT:-playwright}" node -e 'require(process.env.PLAYWRIGHT)' 2>/dev/null; then
  echo "Interfaz (Chromium)"
  node pruebas/interfaz.mjs
  echo "Página pública (pieza «pagina»)"
  node herramientas/pagina_capturas.mjs revisar ${CAPTURAS:+"$CAPTURAS/pagina"}
else
  echo "Interfaz: sin Playwright, no la pruebo aquí (PLAYWRIGHT=/ruta/a/playwright)"
fi
echo "Privacidad"
bash herramientas/revisar_privacidad.sh --generico
if [ -s .terminos-privados ]; then bash herramientas/revisar_privacidad.sh --todo; fi
echo "Todo bien"
