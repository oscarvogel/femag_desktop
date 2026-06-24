# Loop Engineering - FEMAG Desktop

Este documento define loops de trabajo para ordenar futuras intervenciones con Codex y otros agentes. Loop Engineering es una metodologia de trabajo para FEMAG Desktop; no agrega funcionalidad productiva por si misma.

## Como usar este workflow en FEMAG

1. Crear o elegir un issue chico.
2. Definir el loop principal del issue: bug, tests, documentacion, revision de PR, UX o release futuro.
3. Separar alcance incluido y fuera de alcance antes de modificar archivos.
4. Trabajar en una rama propia y abrir un PR chico.
5. Registrar validaciones ejecutadas con resultados reales.
6. Hacer merge solo si el PR cierra el issue o deja trazabilidad clara.
7. Dividir features pesadas en etapas chicas antes de avanzar.

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
6. Documentar riesgo, validacion manual si aplica y resultado en el PR.

### Salida esperada

- Bug corregido.
- PR chico con explicacion del fix.
- Validaciones reales registradas.
- Issue cerrado o trazabilidad clara para el cierre.

### Validaciones minimas

```bash
git diff --check
python -m pytest
python -m compileall app
```

Agregar smoke checks si el bug afecta arranque o navegacion. Validaciones demo solo aplican cuando exista soporte explicito para ese flujo.

## Test loop

### Cuando usarlo

Usar este loop cuando el issue pide cobertura, estabilizar pruebas, proteger una logica existente o definir que validaciones corresponden segun el tipo de cambio.

### Entrada esperada

- Comportamiento a cubrir.
- Archivos o modulo objetivo.
- Criterios de aceptacion verificables.
- Tipo de cambio: documentacion, logica, UX/PyQt, impresion/reportes, datos demo/seed o importacion.

### Pasos

1. Leer la logica o documentacion existente.
2. Elegir la fila de la matriz de `VALIDATION.md`.
3. Definir casos normales, vacios y de error cuando haya comportamiento a cubrir.
4. Agregar tests chicos y especificos solo si el issue lo pide.
5. Ejecutar tests focalizados del modulo si existen.
6. Ejecutar validacion general.
7. Documentar cobertura, validaciones manuales y limites.

### Salida esperada

- Tests relevantes agregados o corregidos.
- Sin cambios funcionales fuera del issue.
- Matriz de validacion aplicada y resultados reales registrados.

### Validaciones minimas

```bash
python -m pytest
python -m compileall app
git diff --check
```

No exigir `python -m app.main --demo --smoke` mientras `--demo` no exista en `app.main`. Screenshots solo son obligatorios para cambios UX/PyQt o cuando el issue pida evidencia visual.

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

## Validacion manual loop

### Cuando usarlo

Usar este loop cuando el cambio requiere revisar un flujo que no queda cubierto por tests, compileall o smoke automatico.

### Entrada esperada

- Issue con flujo a validar.
- Modo de validacion definido: normal, demo o dato controlado.
- Resultado esperado.

### Pasos

1. Definir el caso manual antes de validar.
2. Usar datos demo o controlados.
3. Evitar remitos reales, F150 real, importacion DBF/MySQL y logica pesada salvo pedido explicito.
4. Registrar pasos ejecutados y resultado observado.
5. Documentar limitaciones en el PR.

### Salida esperada

- Evidencia manual clara y reproducible.
- Riesgo residual documentado.

### Validaciones minimas

```bash
git diff --check
python -m compileall app
```

Agregar `python -m pytest` y smoke checks cuando el cambio toque codigo o arranque.

## PR review loop

### Cuando usarlo

Usar este loop para preparar, revisar, marcar ready, mergear y cerrar PRs de FEMAG Desktop.

### Entrada esperada

- Issue chico con objetivo y criterio de aceptacion.
- Rama especifica del issue.
- Diff actualizado y enfocado.
- Validaciones ejecutadas o limitaciones documentadas con resultado real.

### Pasos

1. Antes de abrir el PR, declarar objetivo, alcance incluido y fuera de alcance.
2. Verificar que la rama sea especifica del issue.
3. Comparar el diff contra el issue.
4. Confirmar que no se mezclen UX, logica, docs, datos reales o refactors fuera de alcance.
5. Revisar que el PR no prometa features inexistentes.
6. Ejecutar validaciones frescas segun el tipo de cambio.
7. Generar evidencia visual solo si hubo cambios UX.
8. Actualizar documentacion si el cambio modifica flujo, alcance, validaciones o decisiones.
9. Completar descripcion del PR con resumen, issue, alcance, fuera de alcance, archivos, validaciones, screenshots y riesgos.
10. Dejar comentario final de revision con decision: listo para merge o requiere cambios.
11. Mergear solo si GitHub reporta el PR como mergeable y apunta a `main`.
12. Despues del merge, limpiar ramas, ejecutar `git fetch --prune origin` y confirmar `git status -sb`.

### Salida esperada

- PR revisable, chico y alineado al issue.
- Validaciones frescas registradas.
- Fuera de alcance declarado.
- Issue cerrado o trazabilidad clara.
- Limpieza post-merge documentada.

### Validaciones minimas

```bash
git diff --check
git diff --cached --check
python -m pytest
python -m compileall app
python -m app.main --smoke
```

Ajustar segun el tipo de cambio. No exigir comandos inexistentes; validaciones demo son futuras/opcionales hasta que el proyecto las soporte. No ejecutar screenshots si el PR no modifica UX.

### Plantilla de comentario final

```md
## Revision final

Resultado: aprobado / requiere cambios

### Alcance revisado
- ...

### Fuera de alcance confirmado
- ...

### Validaciones ejecutadas
- `python -m pytest` -> ...
- `python -m compileall app` -> ...
- `python -m app.main --smoke` -> ...
- Validaciones opcionales/futuras -> no aplican / ...

### Evidencia visual
- Screenshots ejecutados: si/no
- Motivo: ...

### Riesgos / notas
- ...

### Decision
Listo para merge / No mergear todavia
```

### Plantilla post-merge

```md
PR mergeado:
- PR:
- Merge commit:
- Issue cerrado:
- Rama remota borrada:
- Rama local borrada:
- Estado final de `main`:
- No trackeados restantes:
- Validaciones previas al merge:
```

## UX loop

### Cuando usarlo

Usar este loop antes de codificar nuevas pantallas y cuando el issue cambia pantallas, navegacion, permisos visibles, textos, estados o layout. No codificar una pantalla si el flujo, permisos, datos minimos, estados y acciones no estan definidos.

### Entrada esperada

- Flujo de usuario afectado.
- Objetivo de la pantalla.
- Usuario principal.
- Permisos necesarios.
- Datos minimos necesarios.
- Acciones principales y secundarias.
- Estados visuales a revisar.
- Criterios visuales o capturas esperadas.
- Fuera de alcance.
- Evidencia esperada antes de implementar.

### Pasos

1. Identificar objetivo, usuario principal y permisos.
2. Definir datos minimos, acciones principales y acciones secundarias.
3. Definir estados visuales: vacio, con datos, cargando, error, sin permiso y sin conexion o error de base si aplica.
4. Definir validaciones manuales y criterios visuales minimos.
5. Separar alcance incluido y fuera de alcance.
6. Confirmar evidencia esperada antes de implementar: checklist completo, mockup textual, wireframe o screenshots si ya existen.
7. Recien despues, pasar a implementacion en un issue o PR separado.
8. Si hubo cambio visual real, generar screenshots y revisar textos cortados, botones sin feedback y navegacion.

### Salida esperada

- Checklist UX previo completo.
- Pantalla marcada como lista o no lista para implementacion.
- Estados y permisos definidos.
- Riesgos de UX/PyQt documentados antes de tocar codigo.
- Capturas disponibles solo si hubo cambio visual o el issue lo pide.

### Validaciones minimas

```bash
python scripts/generate_ux_screenshots.py
git diff --check
```

Documentar TODO si algun comando no existe o falla. Agregar validaciones demo solo cuando exista soporte explicito.

### Checklist UX previo

```md
## Checklist UX previo

Pantalla:
Issue relacionado:

### Objetivo
-

### Usuario principal
-

### Permisos
-

### Datos minimos
-

### Acciones principales
-

### Acciones secundarias
-

### Estados requeridos
- [ ] Vacio
- [ ] Con datos
- [ ] Cargando
- [ ] Error
- [ ] Sin permiso
- [ ] Sin conexion / error de base si aplica

### Validaciones manuales
-

### Criterios visuales
-

### Fuera de alcance
-

### Lista para implementacion
- [ ] Si
- [ ] No, falta definir:
```

### Reglas UX para FEMAG Desktop

- Mantener el estilo profesional ya aprobado.
- Priorizar lectura clara para secretarias y administracion.
- Evitar pantallas saturadas.
- No usar demasiadas acciones primarias.
- Mantener acciones principales visibles.
- Mover acciones secundarias a menu o zona menos prominente.
- Respetar permisos en menu y acciones.
- Prever impresion si la pantalla genera documentos.
- Prever busqueda y filtros si la pantalla lista datos.
- Prever estados vacios utiles, no pantallas muertas.
- No codificar una pantalla si no esta claro el flujo.

### Pantallas candidatas para loop UX

Estas pantallas deben pasar por checklist UX antes de implementarse o ampliarse. Esta lista no implica implementacion en este issue.

- Ordenes de carga.
- Remitos.
- Sobres / hoja resumen.
- Cuenta corriente clientes.
- Ingresos de pago.
- Choferes.
- Transportistas.
- Clientes.
- Productos.
- Importacion de saldos/datos iniciales.

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
```

Agregar validaciones de instalador cuando existan.
