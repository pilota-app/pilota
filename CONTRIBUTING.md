# Cómo aportar a Pilota

Pilota es gratis y abierto, y lo hacemos entre todos. Hay lugar para cualquiera, programes o no. *(English below.)*

## Sin programar
<!-- La app: lo que se puede aportar sin programar que es propio de esta app (un contenido para su catálogo, probarla con algo
de la persona —siempre con datos ficticios—…). Una viñeta por cosa, con su enlace. -->
- **Pruébalo y cuéntanos qué falla:** los issues con la etiqueta [`probar`](https://github.com/pilota-app/pilota/labels/probar) piden justo
  eso (siempre con datos ficticios).
- **Conversa:** dudas, ideas o lo que hiciste con Pilota → [Discussions](https://github.com/pilota-app/pilota/discussions).
- **Cuéntanos qué falla o qué te gustaría** en [issues](https://github.com/pilota-app/pilota/issues/new/choose).
- **Traducciones:** revisa o mejora `ui/idiomas/en.json`, o propón otro idioma.

## Programando (con o sin IA)
1. Lee [`AGENTS.md`](AGENTS.md): cómo funciona, reglas y cómo se conectan las piezas. Sirve igual para personas y para tu IA.
2. Haz un fork, una rama y tu cambio. El [README](README.md) explica cómo correrlo.
3. Corre `bash pruebas/correr.sh` (lo mismo que revisa GitHub en cada cambio).
4. Si tu cambio se nota (una función nueva, otra forma de hacer algo, otra pantalla), deja al día lo que lo cuenta: el README, la
   página (`docs/`), las capturas y [`CHANGELOG.md`](CHANGELOG.md). Si no sabes bien qué tocar, dilo en el pull request y lo
   completamos nosotros.
5. Abre un pull request contando qué cambia para quien usa Pilota y cómo lo probaste.

Reglas que importan: código, comentarios y textos en español (todo texto nuevo de la interfaz con su traducción en
`ui/idiomas/en.json`); **nunca subas datos reales ni personales**; Python solo con biblioteca estándar y la interfaz sin
dependencias.

**Archivos de piezas:** `escritorio/src/pieza/actualizaciones.rs`, `ui/bienvenida.css`, `ui/bienvenida.js`, `ui/componentes.css`, `ui/componentes.js`, `pruebas/contrato.py`, `herramientas/python.lock`, `escritorio/iconos/128x128.png`, `escritorio/iconos/128x128@2x.png`, `escritorio/iconos/32x32.png`, `escritorio/iconos/icon.icns`, `escritorio/iconos/icon.ico`, `escritorio/iconos/icono.png`, `escritorio/src/pieza/enchufe.rs`, `escritorio/src/pieza/host.rs`, `escritorio/src/pieza/mod.rs`, `escritorio/src/pieza/procesador.rs`, `escritorio/src/pieza/protocolo.rs`, `escritorio/src/pieza/sistema.rs`, `escritorio/src/pieza/vigilante.rs`, `ui/host.js`, `ui/i18n.js`, `bin/ia.py`, `bin/mcp.py`, `bin/mcp_conectar.py`, `bin/mcp_servidor.py`, `ui/mcp.js`, `bin/nucleo.py`, `docs/pagina-comunes.json`, `docs/pagina.css`, `docs/pagina.js`, `docs/sello-en.svg`, `docs/sello.svg`, `docs/tema.css`, `herramientas/pagina_capturas.mjs`, `ui/tema.css`, `ui/tema.js`, `bin/trabajos.py`, `escritorio/src/pieza/progreso.rs`, `bin/universo_formato.py`, `ui/universos.js`, `ui/universos/bosque.json`, `ui/universos/espacio.json`, `ui/universos/neon.json`, vienen de
[Pieza](https://github.com/pieza-app/pieza) (están en `piezas.json`, con el aviso de la MPL-2.0). No los cambies aquí: propón el
cambio en Pieza y llega a Pilota con «Pieza al día».

Los aportes entran con la licencia del proyecto, [AGPL-3.0](LICENSE).

## Cómo revisamos
Todo entra por pull request y lo junta alguien que mantiene el proyecto: nadie puede subir cambios directo. Revisamos:
- **Siempre:** que las pruebas de GitHub pasen, que no haya datos personales y que el cambio haga lo que dice. Si es tu primer
  aporte, GitHub espera a que aprobemos correr las pruebas (es normal).
- **Que la documentación diga la verdad:** si el cambio agrega, cambia o quita algo que se nota, revisamos que el README, la
  página, las guías y el `CHANGELOG.md` cuenten la app como queda. Lo que falte lo completamos antes de juntar.
- **Interfaz:** que funcione con teclado, a 390 px y en claro y oscuro, y que los textos tengan traducción.
- **Traducciones:** que una persona que hable el idioma revise el texto.
<!-- La app: lo que se revisa en lo propio de esta app (su formato, su catálogo, su motor…), una viñeta por cosa. -->

Si algo falta te lo pedimos con un comentario; casi nunca cerramos un aporte sin conversar.

¿Buscas por dónde empezar? Mira los issues con la etiqueta
[`good first issue`](https://github.com/pilota-app/pilota/labels/good%20first%20issue) o pregunta en Discussions.

**¿Encontraste una falla de seguridad?** No abras un issue: repórtala en privado como explica [SECURITY.md](SECURITY.md).

Al participar aceptas el [código de conducta](CODE_OF_CONDUCT.md).

---

## Contributing (English)
- **No code needed:** try Pilota and tell us what fails (label `probar`, fictional data only), chat in
  [Discussions](https://github.com/pilota-app/pilota/discussions), report bugs or ideas, and help with translations.
- **Code (with or without AI):** read [`AGENTS.md`](AGENTS.md), fork, branch, run `bash pruebas/correr.sh` and open a pull request.
  Code and comments are in Spanish; UI text needs its English entry in `ui/idiomas/en.json`; never commit real or personal data.
  If your change is visible, also update the README, the page (`docs/`), screenshots and `CHANGELOG.md`, or say so in the pull
  request and we'll do it.
- **Piece files** (listed in `piezas.json`, MPL-2.0 notice included) come from [Pieza](https://github.com/pieza-app/pieza). Don't
  change them here: propose the change in Pieza and it arrives through «Pieza al día».
- **Review:** everything goes through a pull request and a maintainer merges it. Contributions are licensed under AGPL-3.0.
- **Security issues:** don't open a public issue; report them privately as explained in [SECURITY.md](SECURITY.md).

## Aportar con los flujos de Pieza

Aportamos con los flujos de Pieza: en Claude Code, al abrir el repo te ofrece su marketplace (o instálalos como dice abajo); con otra IA, sigue `AGENTS.md`.

Esta app es parte de la familia de [Pieza](https://github.com/pieza-app/pieza). Instala sus flujos (crear, revisar aportes y las
reglas de seguridad) en tu IA:
- **Claude Code:** `/plugin marketplace add pieza-app/pieza` y `/plugin install pieza@pieza`.
- **Gemini CLI:** `gemini extensions install https://github.com/pieza-app/pieza` (comandos `/pieza:crear` y `/pieza:revisar`).
- **Codex:** clona Pieza y corre `python3 herramientas/pieza.py skills instalar codex` (quedan en `~/.agents/skills`).
- **Otra IA:** sigue `AGENTS.md` y la [tabla de equivalencias](https://github.com/pieza-app/pieza/blob/main/docs/otras-ias.md).

Si mejoras algo que sirve a todas las apps, propónlo en Pieza.
