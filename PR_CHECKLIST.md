# PR Checklist - FEMAG Desktop

Usar este checklist antes de abrir o marcar listo un PR.

## Alcance contra issue

- [ ] El PR tiene un issue relacionado.
- [ ] El cambio resuelve el comportamiento esperado del issue.
- [ ] No mezcla bugs, features, refactors y documentacion fuera de alcance.
- [ ] No modifica remitos reales, F150 real, importacion DBF/MySQL ni logica pesada si el issue no lo pide.
- [ ] No toca modelos, migraciones, pantallas, tests o datos demo fuera del alcance.

## Tests y validaciones

- [ ] Se ejecuto `python -m pytest` o se documento por que no aplica.
- [ ] Se ejecuto `python -m compileall app` o se documento por que no aplica.
- [ ] Se ejecuto `python -m app.main --smoke` si aplica.
- [ ] Se ejecuto `python -m app.main --demo --smoke` si aplica.
- [ ] Se ejecuto `git diff --check`.
- [ ] Los resultados reales quedaron documentados en la descripcion del PR.

## Smoke app y demo

- [ ] La app inicia en modo normal cuando el cambio lo requiere.
- [ ] La app inicia en modo demo cuando el cambio lo requiere.
- [ ] El flujo afectado puede abrirse sin error visible.
- [ ] No se usaron remitos reales ni F150 real para validar cambios no autorizados.

## UX y screenshots

- [ ] Si cambia UX, se generaron screenshots con `python scripts/generate_ux_screenshots.py`.
- [ ] Las capturas muestran estados relevantes: normal, vacio, error o permisos, segun aplique.
- [ ] No hay textos cortados, botones sin feedback ni navegacion rota.

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

## Archivos no trackeados

- [ ] Se reviso `git status --short`.
- [ ] No quedan archivos generados, temporales, secretos o capturas fuera de alcance.
- [ ] Los archivos nuevos del PR son intencionales.
