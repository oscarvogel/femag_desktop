# Revision visual - Ordenes de carga

Fecha de revision: 2026-06-24
Rama validada: `codex/visual-review-load-orders-computer-use`
Commit validado: `931e21d`
Sistema operativo: Microsoft Windows 10 Pro 10.0.19045, sesion de escritorio local via Codex Desktop
Tipo de revision: UX / operativa, sin cambios funcionales

## Alcance

Se intento validar visual y operativamente la pantalla de Ordenes de carga como la usaria una secretaria u operador de FEMAG.

Incluido:

- Revision de documentacion de ejecucion del proyecto.
- Validaciones automaticas base.
- Intento de ejecutar la app localmente.
- Conexion con Computer Use y busqueda de ventana targeteable de FEMAG.
- Revision del contrato UI existente para Ordenes de carga.
- Documentacion de hallazgos accionables.

Nota de rama: durante la revision se detecto tambien la rama local `codex/issue-55-load-order-model-validations` apuntando al mismo commit base `931e21d`. La modificacion no commiteada existente en `tests/test_load_orders.py` no forma parte de esta revision documental.

Fuera de alcance:

- Implementar features nuevas.
- Redisenar la UI.
- Tocar remitos, F150, cuenta corriente, importaciones o logica pesada de liquidaciones.
- Modificar codigo funcional.
- Tocar no trackeados existentes en `.codegraph/`, `.cursor/` o `.github/`.

## Comandos ejecutados

| Comando | Resultado |
| --- | --- |
| `git status -sb --untracked-files=all` | Repo en `main` inicialmente con no trackeados fuera de alcance: `.codegraph/`, `.cursor/`, `.github/`. |
| `git switch -c codex/visual-review-load-orders-computer-use` | OK. Rama documental creada. |
| `python -m pytest` | Falla de entorno: el alias `python` apunta a Microsoft Store y no encuentra Python real. |
| `python -m compileall app` | Falla de entorno por el mismo alias `python`. |
| `python -m app.main --smoke` | Falla de entorno por el mismo alias `python`. |
| `.\.venv\Scripts\python.exe -m pytest` | Falla de entorno: el venv referencia `C:\Python313\python.exe`, inexistente. |
| `py -3.12 -m pytest` | OK: 27 passed, 2 warnings por cache de pytest sin permiso en `.pytest_cache`. |
| `py -3.12 -m compileall app` | Falla por permisos al escribir `app\config\__pycache__\settings.cpython-312.pyc` en el share. |
| `$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'femag_compileall_pycache'; py -3.12 -m compileall app` | OK. Compilacion validada con cache externo. |
| `py -3.12 -m app.main --smoke` | OK: `FEMAG smoke OK`. |
| `py -3.12 -m app.main` | No abre ventana. Imprime `FEMAG Desktop UI requires a workstation session.` y termina con codigo 0. |

## Resultado de tests

- `py -3.12 -m pytest`: 27 tests pasados.
- Warnings: pytest no pudo crear cache en `O:\dante\femag_desktop\.pytest_cache` por `WinError 5 Acceso denegado`.
- `compileall` directo no pudo escribir `__pycache__` en el share; la misma validacion paso con `PYTHONPYCACHEPREFIX` fuera del repo.
- Smoke OK con `py -3.12 -m app.main --smoke`.

## Evidencia visual

Carpeta de evidencia: `docs/screenshots/load_orders_visual_review/`

No se generaron screenshots de la pantalla de Ordenes de carga porque la app no expuso una ventana grafica targeteable:

- Computer Use se conecto correctamente al escritorio y listo aplicaciones/ventanas abiertas.
- No aparecio ninguna aplicacion o ventana FEMAG.
- `py -3.12 -m app.main` no abre UI: solo informa que la UI requiere una sesion de puesto de trabajo y finaliza.
- No existe `scripts/generate_ux_screenshots.py` en esta rama.

Por este motivo, la ausencia de capturas es parte del hallazgo bloqueante y no una omision de la revision.

## Flujo probado

1. Abrir la app: bloqueado. El entrypoint normal no abre ventana.
2. Entrar a Ordenes de carga: no validable visualmente.
3. Ver pantalla sin datos o con datos demo: no validable visualmente.
4. Intentar guardar una orden incompleta: no validable visualmente.
5. Verificar mensajes de validacion: no validable visualmente.
6. Seleccionar transportista/camion/chofer: no validable visualmente.
7. Intentar combinacion invalida: no validable visualmente.
8. Crear orden valida: no validable visualmente.
9. Confirmar listado/detalle: no validable visualmente.
10. Cerrar y reabrir modulo: no validable visualmente.

## Contexto tecnico observado

El modulo declara un contrato UI en `app/ui/load_orders.py`:

- Titulo: `Ordenes de carga`.
- Campos: numero, fecha, cliente, domicilio de entrega, transportista, chofer, camion, estado, observaciones, productos y pallets.
- Acciones: ver, crear, modificar, imprimir, reimprimir, anular y cerrar.

La suite valida que Ordenes de carga aparece como modulo real en el menu, mientras Remitos y Hoja resumen siguen como placeholders.

## Hallazgos bloqueantes

### Bloqueante - No hay ventana operativa para revisar Ordenes de carga

Pantalla o paso: apertura de la app.

Descripcion: el comando normal `py -3.12 -m app.main` no abre una ventana grafica. El proceso termina con el mensaje `FEMAG Desktop UI requires a workstation session.`. Computer Use no encontro ninguna ventana de FEMAG ya abierta o targeteable.

Evidencia: salida del comando `py -3.12 -m app.main`; inventario de Computer Use sin ventanas FEMAG; no hay screenshots porque no hay superficie visual.

Recomendacion concreta: agregar o documentar un launcher local de UI para revision en desktop, por ejemplo un comando explicito de modo demo/desarrollo que abra login/menu/dashboard y permita entrar a Ordenes de carga con datos controlados.

Issue sugerido: `UX: habilitar launcher demo para revisar visualmente Ordenes de carga con Computer Use`.

## Hallazgos importantes no bloqueantes

### Alta - Entorno local inconsistente para validaciones

Pantalla o paso: validaciones base.

Descripcion: el alias `python` falla porque apunta a Microsoft Store. El `.venv` existe, pero referencia `C:\Python313\python.exe`, que no existe.

Evidencia: `python -m pytest` falla; `.\.venv\Scripts\python.exe -m pytest` falla; `py -3.12 -m pytest` pasa.

Recomendacion concreta: documentar en README/VALIDATION el launcher real para esta maquina o regenerar el `.venv` con un Python instalado y accesible.

Issue sugerido: `DX: normalizar entorno Python local de FEMAG Desktop`.

### Media - `compileall app` directo puede fallar por permisos en el share

Pantalla o paso: validacion automatica.

Descripcion: `py -3.12 -m compileall app` fallo al escribir pyc dentro de `app\config\__pycache__`. La compilacion paso usando `PYTHONPYCACHEPREFIX` en `%TEMP%`.

Evidencia: `PermissionError: [WinError 5] Acceso denegado`.

Recomendacion concreta: para checkouts en recurso compartido, documentar la variante con `PYTHONPYCACHEPREFIX` o corregir permisos de `__pycache__`.

Issue sugerido: `DX: hacer compileall reproducible en checkout UNC`.

## Mejoras UX recomendadas

Estas recomendaciones quedan pendientes de validar cuando exista una ventana operativa:

- Confirmar que el estado vacio oriente al operador y no parezca un error tecnico.
- Validar que cliente, domicilio de entrega, transportista, camion, chofer, producto, cantidad, pallets, kilos, observaciones y estado sean visibles sin desplazamientos confusos.
- Confirmar que los campos obligatorios sean claros antes de guardar.
- Validar que los combos carguen datos legibles y no expongan nombres internos.
- Confirmar que el chofer se filtre o valide de forma coherente con transportista/camion.
- Revisar tabulacion completa desde el primer campo hasta los botones principales.
- Verificar jerarquia de acciones: nuevo, guardar, cancelar, imprimir/reimprimir, anular y cerrar.
- Confirmar que los errores de validacion sean entendibles para usuario no tecnico y no muestren tracebacks.

## Veredicto final

No aprobado para validacion visual.

Motivo: el proyecto tiene contrato UI y tests verdes para Ordenes de carga, pero este checkout no expone una ventana grafica ejecutable para que Computer Use pueda validar el flujo real con mouse/teclado ni capturar screenshots de la pantalla.

La recomendacion es no avanzar esta revision como aprobada hasta contar con un launcher desktop/demo documentado o una rama de PR que ya abra la UI de Ordenes de carga.
