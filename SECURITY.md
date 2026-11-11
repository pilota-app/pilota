# Seguridad

Pilota es gratis y abierto, y tus datos nunca salen de tu computador. Si encuentras una falla de seguridad, gracias por avisar:
la arreglamos antes de contarla. *(English below.)*

## Cómo reportar una falla (en privado)
**No abras un issue público ni lo cuentes en Discussions.** Usa el reporte privado de GitHub:
[**Reportar una vulnerabilidad**](https://github.com/pilota-app/pilota/security/advisories/new) (pestaña *Security* → *Report a
vulnerability*). Solo lo ven quienes mantienen el proyecto.

Cuéntanos qué pasa, cómo repetirlo (pasos y un ejemplo **con datos ficticios**), qué versión o commit usas y en qué sistema. Nunca
mandes datos reales tuyos ni de otras personas.

Qué puedes esperar:
- Respuesta en **7 días** como máximo, diciendo si lo pudimos repetir.
- Mientras lo arreglamos te contamos cómo va. Cuando salga la versión con el arreglo publicamos un aviso (GitHub Security Advisory)
  y, si quieres, te damos el crédito.
- Pedimos no publicar detalles hasta que el arreglo esté disponible (como regla general, 90 días como máximo).

## Qué cuenta
- Que algo que viene de afuera (un archivo que abre la persona, contenido de un catálogo, una traducción o una respuesta de la IA)
  logre ejecutar código en la interfaz (XSS), leer o escribir archivos donde no debe o hacer que la app pida algo a internet.
- Que la IA reciba más de lo que se le pide o pueda usar herramientas.
- Cualquier cosa que saque datos del computador sin que la persona lo pida.
- Problemas en los workflows de GitHub, en cómo se arma la app o en sus actualizaciones que permitan colar código.
<!-- La app: suma lo propio (p. ej. «que un diagrama…», «que una cartola…»), una viñeta por cosa. -->

No cuentan: fallas de tu IA (Claude Code, Codex, Gemini; repórtalas a ellos, salvo que Pilota las exponga de más); ataques que
ya necesitan control total del computador; o encabezados que GitHub Pages no deja configurar en la página pública.

## Cómo nos protegemos
- Todo entra por pull request y lo junta quien mantiene el proyecto, después de leer el diff completo ([CONTRIBUTING.md](CONTRIBUTING.md)).
- Las GitHub Actions están fijadas por SHA, con permisos mínimos, `persist-credentials: false` y sin `pull_request_target`; Dependabot
  propone actualizaciones con unos días de espera (`.github/dependabot.yml`).
- Python solo con biblioteca estándar; la interfaz sin dependencias (ni npm ni CDN) y con una Content-Security-Policy estricta
  (`script-src 'self'`, sin scripts en línea). Todo lo que viene de afuera se valida y se escapa antes de mostrarse.
- La app nativa es la genérica de [Pieza](https://github.com/pieza-app/pieza): la ventana solo carga la interfaz que viene dentro, el
  puente solo atiende a su marco principal, cada acción que corre un script se declara con sus datos y su tipo (lo que no calza se
  rechaza) y todo script tiene **límite de tiempo**; al salir no queda nada corriendo. Lo que escribe la persona nunca va como
  argumento de un proceso.
- La IA es la de la persona, corre en una carpeta temporal vacía, sin herramientas ni MCP y sin las variables de la app.
- Las actualizaciones se bajan solo de los Releases de `pilota-app/pilota` y se instalan si su SHA-256 coincide; todo lo que se descarga al
  armar la app tiene su huella fija.
<!-- La app: suma cómo se protege lo propio (qué lee y escribe, qué ve la IA, qué sale a internet y por qué), una viñeta por cosa. -->

---

## Security policy (English)
**Please don't open a public issue.** Report vulnerabilities privately through GitHub:
[**Report a vulnerability**](https://github.com/pilota-app/pilota/security/advisories/new). Include what happens, how to reproduce it (with
**fictional data only**), the version or commit and your OS. We reply within **7 days**, keep you posted, publish a GitHub Security
Advisory with the fix and credit you if you want. Please don't disclose details until a fix is out (90 days at most).

In scope: code execution or XSS through anything that comes from outside (files, catalog content, translations, AI responses); file
access where the app shouldn't; the app reaching the internet on its own; the AI receiving more than it should or getting tools;
CI, build or update issues that let code slip in. Out of scope: bugs in your own AI CLI, attacks that already require full control
of the device, and headers GitHub Pages can't set.
