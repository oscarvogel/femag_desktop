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
- smoke app o demo smoke si aplica

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
- python -m app.main --demo --smoke
- git diff --check

Entrega:
- Capturas o rutas de capturas generadas.
- Lista corta de problemas encontrados.
- Fixes minimos si el issue lo permite.
- Indicar alcance incluido, fuera de alcance y cierre o trazabilidad del issue.
```
