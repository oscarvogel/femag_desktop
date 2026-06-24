# Loop Engineering - FEMAG Desktop

Este documento define loops de trabajo para ordenar futuras intervenciones con Codex y otros agentes.

## Bug loop

### Cuando usarlo

Usar este loop cuando un issue describe un error reproducible, una regresion o un comportamiento inesperado.

### Entrada esperada

- Issue con contexto, pasos para reproducir y comportamiento esperado.
- Rama propia del issue.
- Area afectada identificada.

### Pasos

1. Reproducir o entender el error con el menor alcance posible.
2. Identificar archivos involucrados sin modificar areas protegidas.
3. Agregar o ajustar test si el bug es cubrible.
4. Implementar el fix minimo.
5. Ejecutar validaciones.
6. Documentar riesgo y resultado en el PR.

### Salida esperada

- Bug corregido.
- PR chico con explicacion del fix.
- Validaciones reales registradas.

### Validaciones minimas

```bash
git diff --check
python -m pytest
python -m compileall app
```

Agregar smoke checks si el bug afecta arranque, navegacion o modo demo.

## Test loop

### Cuando usarlo

Usar este loop cuando el issue pide cobertura, estabilizar pruebas o proteger una logica ya existente.

### Entrada esperada

- Comportamiento a cubrir.
- Archivos o modulo objetivo.
- Criterios de aceptacion verificables.

### Pasos

1. Leer la logica existente.
2. Definir casos normales, vacios y de error.
3. Agregar tests chicos y especificos.
4. Ejecutar tests focalizados si existen.
5. Ejecutar validacion general.
6. Documentar cobertura y limites.

### Salida esperada

- Tests relevantes agregados o corregidos.
- Sin cambios funcionales fuera del issue.

### Validaciones minimas

```bash
python -m pytest
python -m compileall app
git diff --check
```

## Docs loop

### Cuando usarlo

Usar este loop para ordenar procesos, decisiones tecnicas, alcance o handoffs.

### Entrada esperada

- Tema documentable.
- Audiencia esperada.
- Archivos de documentacion a crear o actualizar.

### Pasos

1. Revisar documentacion existente.
2. Escribir contenido accionable y corto.
3. Evitar prometer comportamientos que no esten implementados.
4. Marcar como TODO lo que no este confirmado.
5. Ejecutar validaciones de diff.
6. Abrir PR de documentacion sin tocar codigo.

### Salida esperada

- Documentacion clara para trabajo futuro.
- PR sin cambios de aplicacion.

### Validaciones minimas

```bash
git diff --check
```

Ejecutar tests adicionales si el PR tambien toca codigo, scripts o configuracion.

## PR review loop

### Cuando usarlo

Usar este loop antes de pedir revision humana o al revisar feedback de un PR.

### Entrada esperada

- PR abierto.
- Diff actualizado.
- Validaciones ejecutadas o limitaciones documentadas.

### Pasos

1. Comparar el diff contra el issue.
2. Verificar que no haya archivos fuera de alcance.
3. Revisar riesgos de negocio.
4. Revisar checklist de PR.
5. Aplicar cambios de review en commits chicos.
6. Actualizar descripcion del PR si cambian validaciones o riesgos.

### Salida esperada

- PR revisable, chico y alineado al issue.
- Feedback resuelto o preguntas claras.

### Validaciones minimas

```bash
git diff --check
python -m pytest
python -m compileall app
```

Ajustar segun el tipo de cambio.

## UX loop

### Cuando usarlo

Usar este loop cuando el issue cambia pantallas, navegacion, permisos visibles, textos, estados o layout.

### Entrada esperada

- Flujo de usuario afectado.
- Estados a revisar.
- Criterios visuales o capturas esperadas.

### Pasos

1. Identificar la pantalla y permisos involucrados.
2. Validar estados normal, vacio, error y sin permisos cuando apliquen.
3. Generar screenshots.
4. Revisar textos cortados, botones sin feedback y navegacion.
5. Corregir solo lo necesario para el issue.
6. Adjuntar o mencionar capturas en el PR.

### Salida esperada

- UX validada visualmente.
- Capturas disponibles si el cambio lo requiere.
- Riesgos de PyQt documentados.

### Validaciones minimas

```bash
python scripts/generate_ux_screenshots.py
python -m app.main --demo --smoke
git diff --check
```

Documentar TODO si algun comando no existe o falla.

## Release loop futuro

### Cuando usarlo

Usar este loop cuando el proyecto defina empaquetado, instaladores o entrega a usuarios finales.

### Entrada esperada

- Version o tag objetivo.
- Lista de PRs incluidos.
- Ambiente de validacion.
- Procedimiento de rollback.

### Pasos

1. Congelar alcance de release.
2. Ejecutar suite completa de validacion.
3. Verificar modo normal y demo.
4. Generar artefactos definidos por el proyecto.
5. Probar instalacion o ejecucion en ambiente objetivo.
6. Documentar notas de release, riesgos y rollback.

### Salida esperada

- Release reproducible.
- Artefactos versionados.
- Evidencia de validacion.

### Validaciones minimas

```bash
git diff --check
python -m pytest
python -m compileall app
python -m app.main --smoke
python -m app.main --demo --smoke
```

Agregar validaciones de instalador cuando existan.
