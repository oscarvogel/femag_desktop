# AGENTS.md - FEMAG Desktop

Este archivo define como deben trabajar Codex y otros agentes en FEMAG Desktop. Loop Engineering es una metodologia de trabajo para ordenar issues, ramas, PRs y validaciones; no es una feature productiva del sistema.

## Principios de trabajo

- Antes de modificar archivos, entender el pedido, el issue y el area afectada.
- Todo cambio debe entrar por un issue con alcance, contexto y criterio de aceptacion.
- Cada issue debe tener una rama propia. No reutilizar ramas para trabajos no relacionados.
- Cada rama debe abrir un PR, aunque el cambio sea chico.
- No mezclar bugs, features, refactors y documentacion en el mismo PR salvo que el issue lo pida explicitamente.
- Mantener PRs chicos, revisables y con una sola intencion.
- No modificar archivos no relacionados con la tarea.
- No borrar codigo, pantallas, modelos, migraciones, scripts o datos demo sin justificarlo en el issue y en el PR.
- Preferir soluciones simples, explicitas y faciles de validar.

## Loop base de trabajo

Antes de iniciar cualquier tarea, el agente debe auditar el estado real del repositorio.

### Regla 1 - No crear trabajo duplicado

Antes de crear issue, rama, PR o implementacion:

- revisar issues abiertos relacionados;
- revisar PRs abiertos relacionados;
- revisar PRs recientes mergeados;
- revisar commits recientes;
- identificar si existe issue padre, milestone o tracking issue;
- continuar el hilo existente si corresponde.

No crear issues nuevos si el trabajo ya esta representado por un issue abierto o por un tracking issue.

### Regla 2 - Estado real antes de planificacion

El agente debe informar:

- repo;
- rama base;
- rama de trabajo si existe;
- issue relacionado;
- PR relacionado si existe;
- estado de main;
- que esta hecho;
- que esta roto;
- que falta validar.

No proponer nuevas tareas sin esta auditoria.

### Regla 3 - Bug/regresion antes que feature

Si una funcionalidad ya fue implementada pero no funciona, debe tratarse como bug o reparacion funcional, no como feature nueva.

Ejemplos:

- boton existente que no ejecuta accion;
- pantalla que muestra datos demo pero no opera;
- impresion declarada como lista pero no imprime;
- busqueda visual sin filtros reales;
- anulacion sin persistencia;
- tests OK pero smoke manual fallido.

### Regla 4 - Un solo hilo vivo por funcionalidad

Cada funcionalidad importante debe tener un issue padre o tracking issue.

Todo PR relacionado debe vincularse a ese issue.
Todo estado debe comentarse ahi.
No abrir lineas paralelas sin justificarlo.

### Regla 5 - Validacion obligatoria

Antes de marcar una tarea como lista:

- ejecutar tests del proyecto;
- ejecutar compile/build correspondiente;
- ejecutar smoke funcional;
- si hay UI, validar la pantalla manualmente o con evidencia visual;
- documentar comandos y resultado;
- declarar explicitamente que no se pudo validar.

### Regla 6 - PR chico, pero completo

Los PRs deben ser chicos, pero no incompletos.

Un PR no puede dejar botones visibles sin accion real.
Un PR no puede declarar un flujo terminado si no se valido de punta a punta.
Un PR no puede cerrar un issue si quedan criterios de aceptacion sin cumplir.

### Regla 7 - Comentario de cierre operativo

Al terminar un PR, comentar en el issue padre:

- que cambio;
- que se valido;
- comandos ejecutados;
- screenshots/evidencia si aplica;
- pendientes reales;
- proximo paso recomendado.

### Regla 8 - Prohibido avanzar a la siguiente feature si el flujo actual esta roto

Si el flujo actual tiene acciones basicas rotas, se debe reparar antes de avanzar.

Prioridad:

1. reparar roto;
2. validar flujo;
3. recien despues mejorar UX o agregar features.

## Flujo obligatorio

1. Leer el issue o pedido completo.
2. Auditar el estado real del repositorio segun el Loop base de trabajo.
3. Identificar archivos y modulos involucrados.
4. Proponer un plan breve antes de tocar archivos.
5. Crear o cambiar a una rama propia del issue.
6. Implementar el cambio minimo necesario.
7. Agregar o actualizar tests solo cuando correspondan al alcance.
8. Ejecutar validaciones antes de cerrar el trabajo.
9. Revisar `git diff` y archivos no trackeados.
10. Abrir o actualizar un PR chico con resumen, validaciones y riesgos.
11. Comentar el estado operativo en el issue padre o tracking issue.

## Como usar este workflow en FEMAG

- Cada cambio debe partir de un issue chico y revisable.
- Cada issue debe elegir un loop principal: bug, tests, documentacion, revision de PR, UX o release futuro.
- Cada PR debe incluir validaciones ejecutadas y resultados reales.
- Cada PR debe elegir validaciones desde la matriz de `VALIDATION.md` segun el tipo de cambio.
- Cada pantalla nueva debe pasar por el checklist UX previo antes de codificarse.
- Cada PR debe diferenciar alcance incluido y fuera de alcance.
- Cada merge debe cerrar el issue relacionado o dejar trazabilidad clara.
- No avanzar a features pesadas sin dividirlas en etapas chicas.
- No avanzar a la siguiente feature si el flujo actual tiene acciones basicas rotas.

## Areas protegidas

No tocar estas areas si el issue no lo pide de forma explicita:

- Remitos reales.
- F150 real.
- Importacion DBF/MySQL.
- Logica pesada de liquidaciones.
- Integracion con sistemas legacy o sistema anterior.
- Datos demo usados para validacion.
- Modelos, migraciones o estructura de base de datos.
- Pantallas existentes fuera del flujo pedido.

Si un issue toca una de estas areas, documentar el riesgo de negocio, definir validaciones concretas y evitar cambios colaterales.

## Issues

Cada issue debe incluir:

- Contexto del problema o necesidad.
- Comportamiento actual.
- Comportamiento esperado.
- Archivos o areas probablemente involucradas.
- Criterios de aceptacion.
- Validaciones requeridas.
- Riesgos o dependencias.
- Prioridad.

Antes de abrir un issue nuevo, revisar si el trabajo ya esta cubierto por un issue abierto, un issue padre, un milestone, un tracking issue o un PR existente.

## Pull requests

Todo PR debe incluir:

- Resumen claro del cambio.
- Issue relacionado.
- Alcance incluido.
- Fuera de alcance.
- Archivos agregados o modificados.
- Validaciones ejecutadas.
- Riesgos conocidos.
- Capturas si cambia UX.
- Nota explicita si no se pudieron ejecutar tests o smoke checks.
- Comentario final de revision antes de mergear.
- Limpieza post-merge: rama remota, rama local, `git fetch --prune origin` y `git status -sb`.

El PR debe ser chico, pero completo: no debe dejar acciones visibles sin comportamiento real, ni cerrar criterios de aceptacion pendientes.

## Validacion minima

Antes de cerrar un PR, intentar ejecutar lo que aplique:

```bash
git diff --check
python -m pytest
python -m compileall app
python -m app.main --smoke
python scripts/generate_ux_screenshots.py
```

Si un comando no existe o falla por una causa conocida, documentarlo como TODO o riesgo en el PR. No inventar resultados. Validaciones futuras, como un smoke demo, solo deben agregarse cuando exista soporte explicito en el proyecto.

## Criterio de listo

Un cambio esta listo cuando:

- Resuelve el issue.
- Mantiene el alcance chico.
- No toca areas protegidas sin permiso.
- Tiene validacion automatica o manual razonable.
- Si habia un flujo roto, queda reparado o se declara como pendiente real.
- El PR deja claro que se cambio, como se valido y que riesgo queda.
- El issue padre o tracking issue queda actualizado con el cierre operativo.
