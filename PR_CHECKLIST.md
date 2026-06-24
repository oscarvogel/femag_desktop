# PR Checklist - FEMAG Desktop

Usar este checklist para abrir, revisar, marcar ready, mergear y cerrar PRs de FEMAG Desktop.

## Antes de abrir el PR

- [ ] El trabajo parte de un issue chico, con objetivo y criterio de aceptacion.
- [ ] La rama es especifica del issue, por ejemplo `codex/issue-45-loop-pr`.
- [ ] El objetivo del PR esta declarado en una o dos frases.
- [ ] El alcance incluido esta declarado.
- [ ] El fuera de alcance esta declarado.
- [ ] No mezcla UX, logica, docs, datos reales y refactors si el issue no lo pide.
- [ ] No toca remitos reales, F150 real, importacion DBF/MySQL ni logica pesada sin issue explicito.
- [ ] No incluye archivos generados, temporales, secretos o no trackeados ajenos.

## Durante el PR

- [ ] Los cambios se mantienen enfocados en el issue.
- [ ] Se actualiza documentacion si el cambio modifica flujo, alcance, validaciones o decisiones.
- [ ] Se ejecutan validaciones segun el tipo de cambio.
- [ ] La evidencia visual se genera solo si hay cambios UX o screenshots pedidos por el issue.
- [ ] Si no hay cambio UX, se deja escrito: "No se ejecutaron screenshots porque el PR solo modifica documentacion/codigo sin cambios visuales."
- [ ] No se incorporan `.codegraph/`, `.cursor/`, `.github/` ni otros no trackeados fuera de alcance.

## Descripcion del PR

- [ ] Resumen claro del cambio.
- [ ] Issue relacionado, con `Closes #NN` si el PR lo cierra.
- [ ] Alcance incluido.
- [ ] Fuera de alcance.
- [ ] Archivos principales modificados.
- [ ] Validaciones ejecutadas con resultados reales y frescos.
- [ ] Screenshots o nota de que no aplican.
- [ ] Riesgos, notas o limitaciones.

## Tests y validaciones

- [ ] Se identifico el tipo de cambio: documentacion, logica, UX/PyQt, impresion/reportes, datos demo/seed o importacion.
- [ ] Se uso la matriz de `VALIDATION.md` para elegir comandos.
- [ ] Se ejecuto `git diff --check`.
- [ ] Se ejecuto `git diff --cached --check` antes de commitear.
- [ ] Se ejecuto `python -m pytest` o se documento por que no aplica.
- [ ] Se ejecuto `python -m compileall app` o se documento por que no aplica.
- [ ] Se ejecuto `python -m app.main --smoke` si aplica.
- [ ] Se documento cualquier validacion futura u opcional que no exista todavia, sin exigirla como obligatoria.
- [ ] Los resultados reales quedaron documentados en la descripcion del PR.
- [ ] Se separo validacion automatica de validacion manual cuando correspondia.

## Smoke app y demo

- [ ] La app inicia en modo normal cuando el cambio lo requiere.
- [ ] La app inicia en modo demo solo si existe soporte explicito para ese comando o flujo.
- [ ] El flujo afectado puede abrirse sin error visible.
- [ ] Si no hay smoke automatico suficiente, se documento una validacion manual concreta.
- [ ] No se usaron remitos reales ni F150 real para validar cambios no autorizados.

## UX y screenshots

- [ ] Si cambia UX, se generaron screenshots con `python scripts/generate_ux_screenshots.py`.
- [ ] Si no cambia UX, no se ejecutaron screenshots y se documento el motivo.
- [ ] Las capturas muestran estados relevantes: normal, vacio, error o permisos, segun aplique.
- [ ] No hay textos cortados, botones sin feedback ni navegacion rota.

## Revision

- [ ] El diff no contiene cambios fuera de alcance.
- [ ] El PR no promete features inexistentes ni estados no implementados.
- [ ] Las validaciones son frescas y corresponden al cambio.
- [ ] La documentacion queda alineada con el comportamiento real.
- [ ] El PR cierra el issue o lo referencia con trazabilidad clara.
- [ ] El comentario final de revision indica decision: listo para merge o requiere cambios.

## Compatibilidad PyQt

- [ ] El cambio respeta patrones existentes de widgets, layouts y senales.
- [ ] No bloquea el hilo principal con trabajo pesado.
- [ ] No introduce dependencias nuevas sin justificarlas.
- [ ] Los errores visibles al usuario son claros y no exponen trazas internas.

## Riesgo de negocio

- [ ] Se evaluo impacto sobre operaciones reales.
- [ ] Se indico si el cambio puede afectar carga, impresion, permisos, datos o reportes.
- [ ] Se documentaron riesgos conocidos y rollback esperado si aplica.

## Documentacion

- [ ] Se actualizo documentacion cuando cambio el flujo de trabajo.
- [ ] El PR explica validaciones no ejecutadas como TODO real, no como resultado inventado.
- [ ] Las decisiones tecnicas nuevas quedaron registradas si afectan trabajos futuros.
- [ ] El merge cierra el issue o deja trazabilidad clara.

## Archivos no trackeados

- [ ] Se reviso `git status --short`.
- [ ] No quedan archivos generados, temporales, secretos o capturas fuera de alcance.
- [ ] Los archivos nuevos del PR son intencionales.

## Merge y limpieza

- [ ] El PR apunta a `main`.
- [ ] GitHub reporta el PR como mergeable.
- [ ] No hay conflictos.
- [ ] Se confirma que el alcance final sigue alineado al issue.
- [ ] Se mergea contra `main`.
- [ ] Se cambia a `main`.
- [ ] Se ejecuta `git pull --ff-only origin main`.
- [ ] Se borra la rama remota.
- [ ] Se borra la rama local si existe.
- [ ] Se ejecuta `git fetch --prune origin`.
- [ ] Se confirma `git status -sb`.
- [ ] Se informan no trackeados fuera de alcance si aparecen.

## Plantilla de comentario final de revision

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

## Plantilla de resumen post-merge

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
