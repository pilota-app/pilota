# Pilota

<!-- La app: una frase con qué hace Pilota y para quién, y otra con lo que la hace distinta. En español y, abajo, en inglés. -->

**[Descargar](https://github.com/pilota-app/pilota/releases/latest) · [Página](https://pilota-app.github.io/pilota/) · [Probar en el navegador](https://pilota-app.github.io/pilota/demo/) ·
[Cómo aportar](CONTRIBUTING.md)**

- **Mac** (Apple Silicon, macOS 15): `curl -fsSL https://raw.githubusercontent.com/pilota-app/pilota/main/instalar.sh | bash`

Cada instalador baja la última versión de los Releases de este repo y revisa su huella SHA-256 antes de instalar.

## Cómo está hecha

Una sola interfaz web (`ui/`) para todas las plataformas, la app de Mac en `app/` y los scripts en `bin/` (Python, solo biblioteca estándar). Lo común viene de
[Pieza](https://github.com/pieza-app/pieza): ver `AGENTS.md` (la guía para personas y para cualquier IA) y `piezas.json`.

```bash
bash pruebas/correr.sh                       # todas las pruebas (contrato, Python, interfaz con Playwright, privacidad)
cd ui && python3 -m http.server 8765         # la vista previa: http://localhost:8765/?bienvenida · ?idioma=en · ?tema=oscuro
```

## Pilota in English

<!-- La app: the same two sentences in English. -->

Free and open source (AGPL-3.0). [Download](https://github.com/pilota-app/pilota/releases/latest) · [Website](https://pilota-app.github.io/pilota/).

[![Hecho con Pieza](https://pieza-app.github.io/pieza/sello.svg)](https://pieza-app.github.io/pieza/)
