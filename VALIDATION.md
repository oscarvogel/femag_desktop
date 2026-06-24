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

## Validaciones futuras u opcionales

No listar comandos inexistentes como obligatorios. Si en una rama futura existe soporte explicito para modo demo, documentar el comando exacto en el PR y en este archivo junto con su resultado real.

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

## Validaciones para cierre de PR

Antes de marcar un PR como ready o mergearlo, usar resultados frescos. No reutilizar salidas antiguas si hubo commits posteriores.

Validacion documental:

```bash
git diff --check
git diff --cached --check
```

Validacion general recomendada:

```bash
python -m pytest
python -m compileall app
python -m app.main --smoke
```

Screenshots:

- Ejecutar `python scripts/generate_ux_screenshots.py` solo si hay cambios UX, pantallas o estados visuales.
- No ejecutar screenshots en PRs solo documentales.
- Si no se ejecutan, dejar el motivo en la descripcion del PR y en el comentario final de revision.

Limpieza:

```bash
git status -sb
git fetch --prune origin
```

Despues del merge, confirmar que `main` esta actualizado con `origin/main` y que no quedan cambios pendientes fuera de no trackeados explicitamente informados.
