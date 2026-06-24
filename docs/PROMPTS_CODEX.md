# Prompts Codex - FEMAG Desktop

Prompts reutilizables para pedir trabajo a Codex/agentes manteniendo alcance chico.

## Bugfix

```text
Trabaja en FEMAG Desktop.

Objetivo:
Corregir el bug descrito en el issue <NUMERO>.

Alcance:
- Reproducir o explicar la causa del bug.
- Cambiar solo los archivos necesarios.
- No tocar remitos reales, F150 real, importacion DBF/MySQL ni logica pesada salvo que el issue lo pida.
- Mantener el PR chico.

Validaciones:
- git diff --check
- python -m pytest
- python -m compileall app
- python -m app.main --smoke si aplica
- validaciones opcionales solo si el proyecto las soporta explicitamente

Entrega:
- Rama propia del issue.
- Commit claro.
- PR draft con resumen, validaciones y riesgos.
- Indicar alcance incluido, fuera de alcance y cierre o trazabilidad del issue.
```

## Tests

```text
Trabaja en FEMAG Desktop.

Objetivo:
Agregar o corregir tests para el comportamiento descrito en el issue <NUMERO>.

Alcance:
- No cambiar comportamiento productivo salvo que sea necesario para hacer testeable el caso.
- Cubrir casos normales, vacios y de error cuando apliquen.
- No tocar pantallas, modelos ni datos demo fuera del issue.

Validaciones:
- python -m pytest
- python -m compileall app
- git diff --check

Entrega:
- Explicar que comportamiento queda cubierto.
- Documentar cualquier limite de cobertura.
- Indicar alcance incluido, fuera de alcance y cierre o trazabilidad del issue.
```

## Documentacion

```text
Trabaja en FEMAG Desktop.

Objetivo:
Actualizar documentacion segun el issue <NUMERO>.

Alcance:
- Tocar solo archivos de documentacion.
- No modificar codigo de aplicacion, modelos, migraciones, pantallas, tests ni datos demo.
- Marcar como TODO cualquier comando o flujo no confirmado.

Validaciones:
- git diff --check
- Otros comandos solo si el cambio afecta scripts o configuracion.

Entrega:
- PR chico con archivos agregados o modificados.
- Resumen, validaciones y riesgos.
- Indicar alcance incluido, fuera de alcance y cierre o trazabilidad del issue.
```

## Revision de PR

```text
Revisa el PR <NUMERO> de FEMAG Desktop.

Prioridad:
- Bugs.
- Riesgos de negocio.
- Cambios fuera de alcance.
- Falta de validaciones.
- Compatibilidad PyQt y datos existentes.

Formato:
- Hallazgos primero, ordenados por severidad.
- Referencias a archivo y linea.
- Preguntas abiertas.
- Resumen breve al final.
```

## Preparar PR para ready

```text
Estamos en el repo femag_desktop.

Objetivo:
Revisar y dejar listo para ready el PR <NUMERO>, relacionado con el issue <NUMERO>.

Alcance:
- Confirmar que el PR apunta a main.
- Confirmar que el diff coincide con el issue.
- Confirmar alcance incluido y fuera de alcance.
- Confirmar que no se prometen features inexistentes.
- Confirmar que no se tocaron remitos reales, F150 real, importacion DBF/MySQL ni logica pesada salvo pedido explicito.
- Mantener fuera del commit no trackeados ajenos.

Validaciones:
- git diff --check
- git diff --cached --check si hubo cambios staged
- python -m pytest
- python -m compileall app
- python -m app.main --smoke
- validaciones demo solo si el proyecto las soporta explicitamente
- screenshots solo si hubo cambios UX

Entrega:
- Actualizar descripcion del PR con resumen, issue, alcance incluido, fuera de alcance, archivos, validaciones, screenshots y riesgos.
- Dejar comentario final de revision.
- Marcar ready solo si esta validado.
```

## Mergear PR y limpiar ramas

```text
Estamos en el repo femag_desktop.

Objetivo:
Mergear el PR <NUMERO> contra main y limpiar ramas.

Alcance:
- Confirmar que GitHub reporta el PR como mergeable.
- Confirmar que no hay conflictos.
- Confirmar que el alcance final sigue alineado al issue.
- Mergear contra main.
- Cambiar a main.
- Ejecutar git pull --ff-only origin main.
- Borrar rama remota.
- Borrar rama local si existe.
- Ejecutar git fetch --prune origin.
- Confirmar git status -sb.

No hacer:
- No tocar codigo funcional.
- No ejecutar screenshots.
- No crear issues nuevos salvo pedido explicito.

Entrega:
- PR mergeado.
- Merge commit.
- Issue cerrado o trazabilidad.
- Rama remota borrada.
- Rama local borrada.
- Estado final de main.
- No trackeados restantes.
```

## UX / screenshot review

```text
Trabaja en FEMAG Desktop.

Objetivo:
Aplicar loop UX antes de codificar o revisar screenshots del flujo <FLUJO> para el issue <NUMERO>.

Alcance:
- Validar navegacion, permisos visibles, textos, estados y layout.
- Revisar estados normal, vacio, error y sin permisos si aplican.
- No agregar features nuevas.
- No tocar logica pesada ni integraciones reales.

Validaciones:
- python scripts/generate_ux_screenshots.py
- git diff --check

Entrega:
- Capturas o rutas de capturas generadas.
- Lista corta de problemas encontrados.
- Fixes minimos si el issue lo permite.
- Indicar alcance incluido, fuera de alcance y cierre o trazabilidad del issue.
```
