Estamos en el repo `femag_desktop`.

Quiero trabajar FEMAG con un loop operativo repetible, no con prompts aislados.

A partir de ahora, para cada issue técnico del proyecto usá este flujo estándar:

# LOOP FEMAG — Issue → PR → Validación → Merge

## Principios generales

* Trabajar siempre desde `main` actualizado.
* Crear una rama por issue.
* Mantener cambios chicos, revisables y testeables.
* No mezclar issues.
* No implementar fuera de alcance.
* No tocar no trackeados fuera de alcance:

  * `.codegraph/`
  * `.cursor/`
  * `.github/`
* Si el issue es de documentación, no modificar código funcional.
* Si el issue es de modelo/servicio, no implementar UI.
* Si el issue es de UI, reutilizar servicios existentes y no duplicar reglas de negocio.
* Si el issue es de documento/impresión, no modificar flujo de carga salvo que sea estrictamente necesario.
* Todo PR debe abrirse primero como draft.
* No mergear si hay tests rotos, conflicto real o validación visual pendiente cuando aplique.

## Antes de empezar cada issue

1. Verificar estado local:
   `git status -sb`

2. Confirmar rama actual:
   `main`

3. Actualizar main:
   `git fetch --prune origin`
   `git pull --ff-only origin main`

4. Confirmar que `main` está alineado con `origin/main`.

5. Revisar el issue asignado y sus dependencias.

6. Si depende de otro issue/PR no mergeado, frenar y reportar.

7. Crear rama con formato:
   `codex/issue-NN-descripcion-corta`

## Implementación

1. Revisar modelos, servicios, tests y documentación relacionada.
2. Implementar sólo lo necesario para el issue.
3. Agregar tests o actualizar los existentes.
4. Mantener commits chicos.
5. Evitar refactors grandes no pedidos.
6. No cambiar UX aprobada salvo que el issue lo pida.
7. No introducir datos productivos reales.
8. No tocar archivos fuera de alcance.

## Validaciones obligatorias

Ejecutar siempre:

* `git diff --check`
* `git diff --cached --check`
* `py -3.12 -m pytest`
* `py -3.12 -m compileall app`
* `py -3.12 -m app.main --smoke`

Si el issue toca UI, ejecutar además:

* `py -3.12 -m app.main --demo-ui`

Y validar con Computer Use:

* abrir ventana `FEMAG Desktop`
* navegar a la pantalla modificada
* tomar screenshots reales
* documentar evidencia

## Evidencia visual para issues UI

Si el issue modifica o agrega pantallas, crear carpeta:

`docs/screenshots/<nombre_issue>/`

Agregar:

* PNGs reales tomados con Computer Use
* `README.md` explicando capturas
* reporte visual si corresponde:
  `docs/<NOMBRE_ISSUE>_VISUAL_REVIEW.md`

El reporte debe incluir:

* fecha
* rama/commit validado
* comandos ejecutados
* resultado de tests
* flujo probado
* screenshots
* hallazgos
* veredicto:

  * aprobado visualmente
  * aprobado con observaciones
  * no aprobado

No aprobar visualmente una pantalla si:

* no se pudo abrir la app
* Computer Use no pudo targetear la ventana
* hay tracebacks visibles
* hay errores técnicos para usuario final
* no hay screenshots reales

## PR

Abrir PR draft contra `main`.

La descripción del PR debe incluir:

* Issue relacionado con `Closes #NN`
* Objetivo
* Cambios realizados
* Archivos principales modificados
* Tests agregados o actualizados
* Validaciones ejecutadas
* Evidencia visual si aplica
* Fuera de alcance
* Riesgos o pendientes

## Revisión final del PR

Antes de pasar a ready:

1. Actualizar rama con `main` si hace falta.
2. Revisar diff completo contra `main`.
3. Confirmar que el alcance coincide con el issue.
4. Repetir validaciones obligatorias.
5. Si es UI, repetir validación visual con Computer Use.
6. Corregir errores reales con commits chicos.
7. Si todo está OK, pasar PR a ready.

## Merge

Sólo mergear si:

* PR está limpio.
* Checks pasan.
* Validaciones locales pasan.
* No hay conflictos.
* El issue está correctamente referenciado.
* En UI, hay evidencia visual real.

Después de mergear:

1. Verificar que el issue se cerró automáticamente.
2. Si no se cerró, cerrarlo manualmente indicando el PR.
3. Actualizar `main` local.
4. Borrar rama local y remota si corresponde.
5. Ejecutar `git status -sb`.
6. Reportar estado final.

## Reporte final esperado

Al terminar cada issue, reportar:

* Issue trabajado.
* PR creado o mergeado.
* Estado del PR.
* Merge commit si aplica.
* Estado del issue.
* Archivos modificados.
* Validaciones ejecutadas.
* Evidencia visual si aplica.
* Estado local final.
* Siguiente issue recomendado.