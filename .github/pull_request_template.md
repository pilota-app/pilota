## Qué cambia / What changes

<!-- En una o dos frases, desde el punto de vista de quien usa Pilota. -->

## Cómo lo probaste / How you tested it

- [ ] `bash pruebas/correr.sh` pasa
- [ ] Probé la interfaz en español e inglés, a 390 px y en claro y oscuro (si cambié la interfaz)
- [ ] Todo texto nuevo de la interfaz tiene su traducción en `ui/idiomas/en.json`
- [ ] Si agregué una acción del puente: si solo corre un script, está en `app.json` → `acciones` (con `pieza.py acciones .`); si es nativa, registrada en la app de cada sistema; y en la simulación del navegador
- [ ] No cambié archivos de piezas (están en `piezas.json`: el cambio va a [Pieza](https://github.com/pieza-app/pieza))
- [ ] Sin dependencias nuevas (Python solo biblioteca estándar; la interfaz sin npm ni CDN)
- [ ] No agregué datos reales ni personales (`bash herramientas/revisar_privacidad.sh`)
- [ ] Si el cambio se nota: dejé al día «Lo que rodea a un cambio» de `AGENTS.md` (README, página, capturas y `CHANGELOG.md`), o lo
      digo aquí para que lo completen quienes mantienen / If it's visible: updated README, page, screenshots and `CHANGELOG.md` (or said so here)

<!-- Si usaste una IA para programarlo, perfecto: AGENTS.md tiene las reglas del proyecto. -->
