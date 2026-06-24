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

## Flujo obligatorio

1. Leer el issue o pedido completo.
2. Identificar archivos y modulos involucrados.
3. Proponer un plan breve antes de tocar archivos.
4. Crear o cambiar a una rama propia del issue.
5. Implementar el cambio minimo necesario.
6. Agregar o actualizar tests solo cuando correspondan al alcance.
7. Ejecutar validaciones antes de cerrar el trabajo.
8. Revisar `git diff` y archivos no trackeados.
9. Abrir PR chico con resumen, validaciones y riesgos.

## Como usar este workflow en FEMAG

- Cada cambio debe partir de un issue chico y revisable.
- Cada issue debe elegir un loop principal: bug, tests, documentacion, revision de PR, UX o release futuro.
- Cada PR debe incluir validaciones ejecutadas y resultados reales.
- Cada PR debe diferenciar alcance incluido y fuera de alcance.
- Cada merge debe cerrar el issue relacionado o dejar trazabilidad clara.
- No avanzar a features pesadas sin dividirlas en etapas chicas.

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
- El PR deja claro que se cambio, como se valido y que riesgo queda.
