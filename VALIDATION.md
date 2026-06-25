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

## Tests actuales detectados

En esta rama, `py -3 -m pytest --collect-only -q` detecta 67 tests:

- `tests/test_audit.py`: 1 test.
- `tests/test_backup.py`: 1 test.
- `tests/test_clients.py`: 2 tests.
- `tests/test_config.py`: 2 tests.
- `tests/test_load_order_desktop_ui.py`: 5 tests.
- `tests/test_load_order_multi_client_ui.py`: 3 tests.
- `tests/test_load_order_operations.py`: 4 tests.
- `tests/test_load_order_printing.py`: 2 tests.
- `tests/test_load_orders.py`: 27 tests.
- `tests/test_masters.py`: 3 tests.
- `tests/test_models.py`: 2 tests.
- `tests/test_permissions.py`: 2 tests.
- `tests/test_schema.py`: 2 tests.
- `tests/test_ui_pyqt5libs.py`: 4 tests.
- `tests/test_ui_smoke.py`: 7 tests.

No asumir una cantidad fija de tests en `main`. Si cambia la suite, actualizar esta seccion con una nueva corrida de collect-only.

## Matriz de validaciones por tipo de cambio

Usar esta matriz para elegir validaciones antes de abrir, marcar ready o mergear un PR. Siempre registrar los comandos ejecutados y su resultado real.

### Solo documentacion

Ejecutar:

```bash
git diff --check
git diff --cached --check
python -m pytest
python -m compileall app
python -m app.main --smoke
```

Screenshots: no. Dejar escrito que no se ejecutaron porque el PR solo modifica documentacion.

### Logica funcional

Ejecutar:

```bash
git diff --check
git diff --cached --check
python -m pytest
python -m compileall app
python -m app.main --smoke
```

Agregar tests enfocados del modulo si existen. Screenshots solo si el cambio tambien afecta UX.

### UX / PyQt

Ejecutar:

```bash
git diff --check
git diff --cached --check
python -m pytest
python -m compileall app
python -m app.main --smoke
python scripts/generate_ux_screenshots.py
```

Screenshots o evidencia visual: obligatorios cuando hay cambios de pantalla, layout, navegacion o estados visuales. Revisar estados vacio, con datos, error y sin permiso cuando apliquen.

Antes de codificar una pantalla nueva, completar el checklist UX previo de `docs/LOOP_ENGINEERING.md`. Para cambios solo documentales del loop UX, no ejecutar screenshots.

### Impresion / reportes

Ejecutar:

```bash
git diff --check
git diff --cached --check
python -m pytest
python -m compileall app
```

Agregar test o smoke enfocado si existe. Adjuntar evidencia de salida A4, PDF o preview cuando aplique. Screenshots o archivos de evidencia solo si ayudan a revisar el resultado.

### Datos demo / seed

Ejecutar:

```bash
git diff --check
git diff --cached --check
python -m pytest
python -m compileall app
python -m app.main --smoke
```

Agregar validacion idempotente si existe. Confirmar explicitamente que no se usaron datos reales.

### Importacion DBF/MySQL

No implementar importacion DBF/MySQL dentro de issues documentales o loops de validacion. Cuando exista un issue especifico para importacion:

- Usar fixtures demo o sinteticos.
- Nunca usar bases reales dentro del repo.
- Validar mapeos, encoding, duplicados y errores de lectura.
- Documentar riesgos de compatibilidad legacy.

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

## Validaciones minimas por PR

Cada PR debe informar:

- Comandos ejecutados.
- Resultado de cada comando.
- Validaciones no ejecutadas y motivo.
- Validacion automatica y validacion manual, si corresponde.
- Si hubo screenshots o por que no aplican.
- Si se uso alguna validacion futura/opcional, el soporte explicito que la habilita.
