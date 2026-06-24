# VALIDATION.md - FEMAG Desktop

Comandos conocidos para validar cambios en FEMAG Desktop. Ejecutar solo lo que aplique al alcance del issue y documentar resultados reales en el PR.

## Validaciones base

```bash
git diff --check
```

Verifica espacios en blanco problematicos y errores basicos del diff.

```bash
python -m pytest
```

Ejecuta la suite de tests del proyecto.

```bash
python -m compileall app
```

Compila los modulos Python dentro de `app` para detectar errores de sintaxis o imports basicos.

## Smoke checks

```bash
python -m app.main --smoke
```

Smoke check de la app en modo normal.

TODO: confirmar en cada PR si este comando existe y si no requiere configuracion local adicional.

```bash
python -m app.main --demo --smoke
```

Smoke check de la app en modo demo.

TODO: confirmar en cada PR si este comando existe y si no requiere configuracion local adicional.

## Screenshots UX

```bash
python scripts/generate_ux_screenshots.py
```

Genera capturas para revision visual cuando el PR cambia pantallas, navegacion o estados de UI.

TODO: si el script falla o no existe en una rama, documentar el resultado real y no inventar capturas.

## Regla de documentacion

Si un comando no existe, falla o no aplica:

- Registrar el comando ejecutado.
- Registrar el resultado real.
- Explicar si queda como TODO, riesgo o validacion no aplicable.
- No reemplazarlo por una validacion equivalente sin aclararlo.

## Validacion manual

Cuando un issue no quede cubierto por tests, compileall o smoke checks, documentar una validacion manual concreta:

- Que pantalla, comando o flujo se reviso.
- Con que modo se valido: normal, demo o dato controlado.
- Que resultado se esperaba.
- Que resultado se obtuvo.

No usar remitos reales, F150 real, importacion DBF/MySQL ni logica pesada como validacion manual salvo que el issue lo pida explicitamente.
