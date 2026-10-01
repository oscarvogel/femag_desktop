# Issue #581 — Cuenta corriente: resumen de saldos por vendedor en PDF y envío

- **GitHub:** https://github.com/oscarvogel/femag_desktop/issues/581
- **Estado:** IMPLEMENTADO (rama `feat/issue-581-resumen-cuenta-corriente-vendedor`, pendiente de PR)
- **Base auditada e implementada:** `main` @ `7f6d1dc`
- **Worktree de trabajo:** `C:\Programacion\dante\femag_581` (aislado, el repo original quedó intacto)
- **Registrado:** 2026-10-01

## Hilo al que continúa

- #547 (cerrado) — filtro por vendedor y agregados de cartera en Cuenta Corriente.
- #551 (cerrado) — eliminación del recálculo lento al filtrar por vendedor.
- #545 (cerrado) — maestro de vendedores y asignación por cliente (precedente de `Salesperson`).

Este issue agrega la **salida**: el resumen en PDF y el envío de la cartera del vendedor.

---

## Contexto

Se solicitó poder enviar un **resumen de cuenta corriente del vendedor** (por ejemplo el de Luis) con los saldos de los clientes que ese vendedor tiene asignados, en PDF.

Hoy la pantalla de Cuenta Corriente permite ver esa cartera filtrada por vendedor, pero no existía ninguna exportación ni envío a nivel cartera: el extracto (Imprimir / WhatsApp / correo) solo existía **por cliente** y exigía un cliente seleccionado.

## Comportamiento anterior

Con **Vendedor = Luis** la pantalla mostraba correctamente sus clientes con saldo y los totales de cartera, pero:

- las acciones de extracto solo se habilitaban con un cliente seleccionado y generaban el extracto de **ese** cliente;
- no había forma de obtener la **cartera completa del vendedor** en un archivo;
- no había dónde cargar el email del vendedor.

## Comportamiento implementado

Acción **“Resumen del vendedor”** en el menú **Acciones** de Cuenta Corriente, independiente de la selección de cliente:

1. Genera un **PDF** con una fila por cliente (**nombre, CUIT, saldo**) y el **total neto**, más un bloque de resumen (clientes, clientes con saldo, **deuda**, vencido, próximos 7 días y total neto).
2. **Respeta los filtros visibles** (búsqueda, “Solo con saldo”, vendedor): lo que se ve es lo que se imprime.
3. Se puede **generar/imprimir**, **enviar por WhatsApp como documento adjunto** y **enviar por correo**.
4. Envía al **vendedor destinatario**, que es externo y no usa el sistema. El que genera y envía es un usuario de la empresa.

### Dos totales, y por qué

El PDF informa **dos cifras** a propósito, porque la pantalla también las separa:

- **DEUDA** — solo saldos positivos. Es el mismo número que la barra lateral muestra como “Cartera” (`customer_ledger.py:530` suma únicamente `balance > 0.01`).
- **TOTAL NETO** — suma de todas las filas, incluidos los saldos a favor del cliente.

Sin esto, un vendedor con clientes en saldo a favor veía en el PDF un número que no coincidía con el de su pantalla. Se detectó probando contra la salida real con la captura de pantalla, no leyendo el código.

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| Destinatario | El vendedor del filtro activo |
| Naturaleza del vendedor | Agrupador de clientes, **sin acceso al sistema**; no se crea usuario ni vínculo con `User` |
| Canales | PDF + WhatsApp + correo |
| Envío por WhatsApp | Como **documento adjunto**, no como enlace |
| Nombre del archivo | `resumen_cuenta_corriente_<vendedor>_<AAAAMMDD>.pdf` |
| Contenido | Solo saldos: nombre y saldo, más el total de la cartera |
| Permisos | Cualquier usuario de la empresa que ya entre a Cuenta Corriente |
| Email del vendedor | Campo `Email` en el maestro de Vendedores |
| Alcance de saldos | Respeta los filtros de pantalla; total como suma neta |

## Archivos modificados y agregados

### Agregados
- `app/services/salesperson_portfolio_print_service.py` — genera el PDF del resumen.
- `tests/test_salesperson_portfolio_printing.py` — 9 tests del PDF y del nombre de archivo.
- `tests/test_salesperson_portfolio_sharing_ui.py` — 12 tests de filtros, estado de acciones y envíos.
- `tests/test_issue_581_salesperson_email.py` — 6 tests del campo email en el maestro.
- `docs/issue-581-resumen-cuenta-corriente-vendedor.md` — este registro.

### Modificados
- `app/models/masters.py` — nuevo `Salesperson.email` nullable.
- `app/services/master_service.py` — `email` en alta y modificación, con auditoría y validación.
- `app/ui/master_abm.py` — columna **Email** en la grilla, campo en el diálogo y búsqueda por email.
- `app/ui/customer_ledger.py` — sección “Resumen del vendedor” con tres acciones, `portfolio_summary()` y sincronización de estado.
- `app/ui/desktop_app.py` — cableado de impresión, WhatsApp (adjunto) y correo.
- `app/services/account_statement_mail_service.py` — `body` opcional para reusar el envío con otro texto; el texto del extracto de cliente no cambia.
- `tests/test_issue_545_salespeople.py` — expectativa de columnas actualizada (agrega Email).
- `tests/test_account_statement_sharing_ui.py` — incluye el `body: None` que ahora se pasa al worker.

## Criterios de aceptación

- [x] Con **Vendedor = Luis**, la acción genera un PDF con una fila por cliente (nombre, CUIT, saldo) y el total, ordenado de mayor a menor saldo.
- [x] El archivo se llama `resumen_cuenta_corriente_luis_20261001.pdf`, con nombre sanitizado para Windows y fecha `AAAAMMDD`. Con **Todos** usa `_todos_` y con **Sin asignar** `_sin_asignar_`.
- [x] El PDF respeta los filtros visibles de búsqueda, “Solo con saldo” y vendedor.
- [x] El **total neto** impreso es exactamente la suma de las filas impresas, incluidos los saldos negativos.
- [x] La **DEUDA** del PDF coincide con la “Cartera” de la barra lateral cuando hay saldos a favor.
- [x] Los saldos negativos se imprimen con signo y se incluyen en el total.
- [x] La acción no requiere cliente seleccionado.
- [x] **WhatsApp** manda el PDF como **documento adjunto** y registra el intento como `resumen_cuenta_vendedor`.
- [x] **Correo** manda el PDF adjunto al `email` del vendedor, con asunto del resumen.
- [x] Si falta el email o el teléfono, el envío avisa qué dato falta y no intenta enviar.
- [x] Con **Todos** se puede imprimir, pero los envíos quedan deshabilitados.
- [x] El ABM de Vendedores permite cargar y editar el email, con columna visible.
- [x] No se re-agregan saldos: se reutiliza la fotografía de cartera ya cargada (#551).

## Validaciones ejecutadas

| Comando | Resultado |
|---|---|
| `git diff --check` | OK (exit 0) |
| `python -m compileall app` | OK (exit 0) |
| `python -m app.main --smoke` | `FEMAG smoke OK` |
| `python -m pytest` (tests nuevos del #581) | 27 passed |
| `python -m pytest` (suite completa) | **1021 passed, 0 failed** |
| `python scripts/generate_ux_screenshots.py` | exit 0 |

### Corrección de un test durante la implementación

`tests/test_account_statement_sharing_ui.py::test_email_handler_confirms_and_sends_pdf` falló al agregar el parámetro `body` al worker de correo: el test afirmaba el diccionario de argumentos exacto. Se actualizó la expectativa a `body: None`. **El comportamiento del envío de extracto de cliente no cambia**; solo se explicita que no lleva cuerpo propio.

### Validación contra la salida real

Se generó el PDF de verdad contra una **copia** de la base demo con `client_portfolio_rows()` real y se verificó:

- `ensure_runtime_schema()` agregó la columna `salesperson.email` **automáticamente** sobre una base existente.
- La base demo original del usuario quedó **intocada** (verificado con `PRAGMA table_info`): sigue sin la columna `email`; solo la copia la recibió.
- Contenido del PDF generado (inspeccionado):

```
GRAEF HERMANOS S.R.L.        RESUMEN DE CUENTA CORRIENTE
Gestion comercial y cuenta corriente   Luis
Emitido el 01/10/2026 13:59

Resumen de cartera
CLIENTES 5 · CON SALDO 4 · VENCIDO $ 194.089.047,69 · PRÓX. 7 DIAS $ 0,00
TOTAL CARTERA -$ 20.061.268,08

Saldos por cliente
CLIENTE                CUIT          SALDO
Mayorista Ruta 12      30990000004   $ 115.079.188,12
Alimentos Guaraní      30990000003   $ 79.009.859,57
Alimentos Guarani      30700000991   $ 79.009.859,57
Sin Deuda              30700000994   $ 0,00
Distribuidora Parana   30700000993   -$ 293.160.175,34
TOTAL CARTERA                      -$ 20.061.268,08

Generado 01/10/2026 13:59 · FEMAG · Vogel Consultoría   Página 1 de 1
```

### Test con fallo fuera de la suite completa

`tests/test_master_abm_desktop_ui.py::test_truck_created_from_abm_can_be_used_in_load_order_grid` falla cuando se lo ejecuta **aislado** (`assert 2 == 1` en la grilla de órdenes de carga, por datos demo que quedan de otros tests). Se comprobó con `git stash` que **falla igual en `main` limpio**, o sea que no es una regresión de este cambio, y que **pasa dentro de la suite completa**. Queda declarado como test dependiente del orden de ejecución, pendiente de un issue aparte.

## Riesgos y dependencias

1. **Área protegida — modelo de datos.** Se agregó una columna a `Salesperson`. Mitigación: campo **nullable** y `ensure_runtime_schema()` ya la crea sola (precedente #545), verificado en ejecución real. **Validar contra la MySQL de producción antes de mergear.**
2. **Webapp:** corre con `FEMAG_AUTO_MIGRATE_SCHEMA=0` (`docs/WEBAPP_SERVER_WINDOWS.md`), por lo que en el servidor la columna hay que agregarla manualmente.
3. **Destinatario externo sin control del sistema.** El vendedor no usa FEMAG: si su email o teléfono cambian hay que actualizar el ABM a mano. El envío avisa qué dato falta y no falla en silencio.
4. **Información sensible.** El PDF expone saldos de clientes: revisar la carpeta de salida.
5. **Datos de contacto faltantes.** Hay vendedores existentes sin email ni teléfono: hay que cargarlos en el ABM para poder enviarles el resumen.

## Pendientes

- [ ] Abrir el PR y revisarlo.
- [ ] Validar la columna nueva contra la MySQL real de producción.
- [ ] Cargar el email de los vendedores existentes en el ABM (hoy la mayoría no lo tiene).
- [ ] Probar el envío real por WhatsApp y correo con un vendedor de prueba (requiere instancia configurada en el puesto).
- [ ] Considerar extraer el kit de impresión compartido (`_format_money`, `_safe_filename_component`, `_NumberedCanvas`) a un módulo propio cuando exista un tercer reporte que lo reutilice.
- [ ] Corregir el fallo preexistente de `test_truck_created_from_abm_can_be_used_in_load_order_grid` (issue aparte).

---

## Bitácora

| Fecha | Qué se hizo |
|---|---|
| 2026-10-01 | Auditoría de estado real del repo y de Cuenta Corriente. |
| 2026-10-01 | Definidas con el solicitante las 6 decisiones de alcance. |
| 2026-10-01 | Issue #581 creado en GitHub y registro local guardado en `docs/`. |
| 2026-10-01 | **Riesgo de permisos cerrado:** el vendedor no usa el sistema, es solo un agrupador de clientes. Se bajó ese riesgo y se agregó explícitamente que **no** se le da acceso ni se lo vincula con `User`. |
| 2026-10-01 | **Nombre de archivo acordado:** `resumen_cuenta_corriente_<vendedor>_<AAAAMMDD>.pdf`, con variante `_todos_` y `_sin_asignar_`. |
| 2026-10-01 | **WhatsApp definido como adjunto:** verificado que `create_attempt(pdf_path=...)` ya envía el PDF como documento, así que no requirió trabajo nuevo. |
| 2026-10-01 | Implementación en rama `feat/issue-581-resumen-cuenta-corriente-vendedor` sobre worktree aislado desde `main` limpio. |
| 2026-10-01 | Campo `Salesperson.email` con validación reutilizando el patrón de `ClientEmailService`. |
| 2026-10-01 | Servicio de PDF del resumen reutilizando el kit de impresión del extracto. |
| 2026-10-01 | Sección “Resumen del vendedor” en el menú Acciones con impresión, WhatsApp y correo. |
| 2026-10-01 | 27 tests nuevos del #581, todos en verde. |
| 2026-10-01 | Validación contra salida real: PDF generado y migración de columna verificada sobre una copia de la base demo. |
| 2026-10-01 | Identificado y documentado un fallo de test preexistente en `main`, no causado por este cambio. |
| 2026-10-01 | `main` avanzó con el #452, que tocaba los mismos dos archivos de UI. Merge automático sin conflictos; verificado que conviven las tres secciones del menú. |
| 2026-10-01 | **Desfase detectado contra la salida real:** el PDF sumaba la neta mientras la barra lateral suma solo positivos. Se agregó la cifra **DEUDA** al PDF para que coincidan, y se renombró el total a **TOTAL NETO**. |
| 2026-10-01 | Agregado `scripts/generate_issue_581_screenshot.py` para capturar la evidencia de UX con datos sintéticos. |

## Bugs y hallazgos relevantes

| Hallazgo | Impacto |
|---|---|
| `Salesperson` no tenía campo `email` y `User` no está vinculado al vendedor | Obligó a agregar columna + ABM. Mitigado: `ensure_runtime_schema()` la crea sola, verificado en ejecución real |
| El envío por WhatsApp ya soporta adjunto vía `pdf_path` | El punto 3 del pedido fue reutilización, no trabajo nuevo |
| El filtro por vendedor recalcula sobre una fotografía completa desde #551 | El resumen consume esa misma fotografía, sin re-agregar por cliente |
| El webapp corre con `FEMAG_AUTO_MIGRATE_SCHEMA=0` | La columna nueva hay que aplicarla a mano en el servidor web |
| `ClientAccountMovement` exige `description` y `source_ref` | Los tests de cartera necesitan crearlos explícitamente |
| `AuditService` solo expone `record`; los eventos se leen de `AuditLog` por `record_ref` + `action` | Afectó cómo se verifica la auditoría del vendedor |
| `QApplication` sin referencia provoca crash de Qt al liberar | Los helpers de test UI deben conservar la referencia |
