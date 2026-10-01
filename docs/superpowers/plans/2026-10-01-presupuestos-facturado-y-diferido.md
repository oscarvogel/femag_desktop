# Dos presupuestos por renglón: facturado ahora y a facturar después

Fecha: 2026-10-01
Rama prevista: `feat/issue-NNN-dos-presupuestos-orden-carga`
Hilo: reemplaza el experimento #553 / PR #554, que se cierran como experimento descartado.

## Contexto

Hoy la Orden de Carga tiene **una sola cantidad** por renglón
(`LoadOrderProduct.quantity`, `app/models/load_orders.py:86`). Esa cantidad genera **un solo
presupuesto por cliente** (`BudgetService.ensure_for_load_order_client`,
`app/services/budget_service.py:66`), y ese presupuesto genera **un solo movimiento en cuenta
corriente** (`AccountLedgerService.generate_for_load_order`,
`app/services/account_ledger_service.py:20`).

El pedido operativo es que cada renglón pueda tener **dos cantidades**: una que se factura
inmediatamente y otra que se factura a posterior. Cada parte debe salir como **un presupuesto
independiente, con su propio número, su propio movimiento en cuenta corriente y su propio
vencimiento**, y poder enviarse por separado.

## Decisiones tomadas

1. **Esquema A: los dos presupuestos se generan al emitir la orden.** Cada uno con número, total
   y vencimiento propios. La parte inmediata vence al contado (vencimiento = fecha de la orden)
   y la diferida vence con el plazo de pago del cliente (`dias_plazo_pago`).
   Consecuencia aceptada: el precio de la parte diferida queda congelado al día del despacho.
2. **El corte es por renglón.** El mismo producto se divide en dos cantidades dentro del mismo
   destino.
3. **Solo afecta la facturación.** Remito, pallets, kilos, Excel y totales logísticos de la
   orden siguen usando la cantidad total.
4. **El experimento #553 y el PR #554 se cierran como descartados** y este trabajo abre su
   propio issue. El PR #554 resolvía la versión informativa (un presupuesto, un total, un solo
   débito); su decisión de fondo es incompatible con este pedido.

### Descartado explícitamente

- **Un solo número con elección al enviar.** El mismo `PRES-xxxxxx` podía terminar con dos
  importes distintos según cuándo se imprimiera, rompiendo el invariante de
  `assert_monetary_integrity` (`app/services/budget_service.py:293`) y el flujo de re-impresión
  de presupuestos (#452).
- **Proveedores, materia prima y pagarés.** Fuera de alcance; no se tocan (área protegida).
- **Dos precios distintos para las dos partes de un mismo renglón.** Se mantiene el precio
  único del renglón para las dos partes. Queda anotado como posible necesidad futura.

## Terminología

- **Facturado ahora**: la parte de la cantidad que se factura al contado.
- **A facturar después**: la parte de la cantidad que queda pendiente de facturación.

## Diseño técnico

### 1. Modelo de datos

**`LoadOrderProduct`** (`app/models/load_orders.py:82`)

- `quantity` **se mantiene como cantidad total**. No se renombra ni se cambia de tipo, para no
  tocar remito, pallets, Excel, retornos, liberación de costos ni rentabilidad.
- Nuevo campo `cantidad_facturar_ahora` (`FloatField`, `null=True`).
  `null` significa "sin reparto explícito" y equivale a "todo va a la parte facturado ahora":
  es la compatibilidad con las órdenes ya emitidas.

**`Budget`** (`app/models/budgets.py:10`)

- Nuevo campo `timing` (`CharField`) con los valores `immediate` y `deferred`, default
  `immediate`. Los presupuestos existentes quedan en `immediate` sin migración de datos.
- **Índice único nuevo:** `(load_order, client, origin, timing)` en lugar del actual
  `(load_order, client, origin)` (`app/models/budgets.py:41`). Es el bloqueo principal: sin
  este discriminante la base no admite dos presupuestos para el mismo cliente de la misma orden.

**`BudgetItem`** (`app/models/budgets.py:44`)

- Sin cambios de esquema. Un mismo `LoadOrderProduct` puede referenciar dos ítems distintos (uno
  en el presupuesto inmediato y otro en el diferido) porque hoy no hay unicidad sobre
  `source_order_product`. La parte se deduce de `item.budget.timing`.

**`LoadOrderBudgetStatus`** (`app/models/load_orders.py:205`)

- Nuevo campo `timing` para que el estado exista por parte y no solo por cliente.

**`ClientAccountMovement`** (`app/models/accounting.py:10`)

- El índice único actual es `(source_ref, client, movement_type, is_reversal)`
  (`app/models/accounting.py:47`) y `source_ref` ya vale `Budget:{id}` por presupuesto, así que
  **admite los dos movimientos sin cambio de índice**.
- Sí hacen falta dos tipos de movimiento nuevos, para que el estado de cuenta y los informes de
  cobranza distingan las dos partes sin joins:
  - `TYPE_LOAD_ORDER_IMMEDIATE` = `load_order_documental` (se reaprovecha el valor actual, para
    no cambiar el histórico).
  - `TYPE_LOAD_ORDER_DEFERRED` = `load_order_documental_deferred`.
  - Sus reversos, para que anular la orden dé de baja las dos partes.
- Etiquetas en `app/services/account_statement_print_service.py:47`.

### 2. Porcentajes de reparto por renglón

Un renglón de 1200 unidades a 14.200 neto, 21% IVA, se reparte así:

| Parte | Cantidad | Neto | IVA | Total |
|---|---|---|---|---|
| Facturado ahora | 800 | 11.360.000,00 | 2.385.600,00 | 13.745.600,00 |
| A facturar después | 400 | 5.680.000,00 | 1.192.800,00 | 6.872.800,00 |
| Renglón | 1200 | 17.040.000,00 | 3.578.400,00 | 20.618.400,00 |

**Restricción: el precio unitario es el mismo en las dos partes.** Con la misma cantidad, precio
y porcentaje de descuento, el reparto proporcional de quantities es exacto hasta la última
unidad. Si alguna vez se quisiera un precio distinto para la parte diferida, el reparto por
porcentaje dejaría de cuadrar al centavo y habría que agregar un segundo precio unitario en el
renglón. Queda fuera de alcance y anotado como riesgo.

Para repartir se usa `compute_line_amounts` de `app/services/money.py`, que es la única rutina
monetaria del proyecto, y el reparto se hace sobre la línea completa, nunca línea por línea con
aritmética propia.

### 3. Servicios

`BudgetService` (`app/services/budget_service.py`)

- `ensure_for_load_order` y `ensure_for_load_order_client` reciben `timing`.
- Nuevo helper `_line_amounts_for_timing(row, timing)` que devuelve la línea, sus importes y el
  porcentaje de reparto.
- Nuevo `ensure_deferred_for_load_order_client(order, client)`: crea la parte diferida solo si
  hay renglones con residuo. Si el residuo es 0, no crea nada.
- Un presupuesto diferido no se regenera ni se pisa: si ya existe, se devuelve el existente.
  Por lo tanto, editar un renglón después de emitir no modifica un presupuesto ya emitido; el
  ajuste se hace anulando y re-emitiendo, que es el comportamiento actual.

`AccountLedgerService` (`app/services/account_ledger_service.py`)

- `generate_for_load_order` crea, por cliente, el movimiento inmediato (vencimiento = fecha de
  orden) y, si hay residuo, el diferido (vencimiento = fecha de orden + `dias_plazo_pago`).
- `reverse_for_load_order` (`app/services/account_ledger_service.py:59`) debe incluir también
  los movimientos diferidos, con su tipo de reverso.
- `_load_order_totals_for_client` (`:104`) pasa a recibir `timing` y sigue tomando los importes
  del presupuesto ya emitido, que es la fuente única de la cuenta corriente.
- `_update_budget_status` (`:118`) incluye `timing`.

`LoadOrderService._replace_destinations` (`app/services/load_order_service.py:1230`)

- Ojo: esta función **borra y recrea todos los renglones** en cada guardado. El campo
  `cantidad_facturar_ahora` tiene que viajar en `product_item` y persistirse en el
  `LoadOrderProduct.create` (`:1246`), o el reparto se pierde al editar la orden.

`LoadOrderOperationService` (`app/services/load_order_operation_service.py`)

- `export_budgets` (`:106`) sigue siendo la puerta de la UI y ahora exporta los presupuestos
  que existen; el botón de presupuesto permite elegir cuál enviar.
- `issue` (`:48`) dispara los dos movimientos a través de `generate_for_load_order`.

`LoadOrderPrintService.export_budgets` (`app/services/load_order_print_service.py:517`) y
`BudgetPrintService` (`app/services/budget_print_service.py:75`) trabajan por presupuesto, así
que la separación por documento ya sale sin cambios. Al presupuesto diferido se le agregan las
observaciones que lo identifican como parte pendiente de la orden.

### 4. Interfaz

`LoadOrderProductDialog` (`app/ui/desktop_app.py:3587`)

- `Cantidad` pasa a ser **Cantidad total**.
- Se agrega **Cantidad a facturar ahora** (editable) y **Cantidad a facturar después**
  (calculada, no editable).
- Validación: `0 <= cantidad a facturar ahora <= cantidad total`.
- Por defecto, sin tocar nada, la cantidad a facturar ahora queda igual a la total, que es el
  comportamiento actual.
- El resumen monetario muestra los dos totales, para que el operador vea el reparto antes de
  guardar.

Grillas de la pantalla de carga

- `product_table` (`:2928`) y `review_table` (`:2953`) agregan las columnas de la parte a
  facturar ahora y de la parte a facturar después, y los totales de la orden quedan
  desagregados en total / facturado ahora / a facturar después.

Envío

- El botón de presupuesto ofrece enviar el presupuesto facturado ahora, el de a facturar
  después, o ambos. El envío por presupuesto ya existe (WhatsApp y PDF), no hay que construir
  un canal nuevo.

### 5. Migración

`app/config/schema.py`

- `ensure_runtime_schema` (`:133`) valida tablas, columnas **e índices**, así que la migración
  tiene que crear el índice nuevo además de agregar las columnas.
- Se sigue el patrón de los helpers existentes `_ensure_account_movement_source_index` (`:243`),
  `_ensure_pallet_sequence_index` (`:230`) y `_ensure_sqlite_index_integrity` (`:215`):
  un helper dedicado que quita el índice único viejo y crea el nuevo con el discriminante, en
  SQLite y en MySQL.
- Agregar columnas: `_ensure_model_columns` (`:390`) ya cubre columnas nuevas, pero el
  índice único sobre cuatro columnas requiere el helper explícito.
- La migración tiene que ser **idempotente** y seguro sobre bases ya instaladas con datos.

## Plan de entrega

Cuatro PRs chicos, cada uno con una sola intención y su propia validación.

**PR 1 — Modelo, migración y compatibilidad** (sin UI)

- Modelos, índices, migración idempotente y tests de esquema.
- Test explícito de compatibilidad: orden histórica sin `cantidad_facturar_ahora` genera un
  solo presupuesto, idéntico a hoy.
- Cierra con la suite completa en verde.

**PR 2 — Captura de las dos cantidades en la UI**

- Diálogo de producto, grilla de productos, grilla de revisar, validaciones.
- Sin tocar presupuestos ni cuenta corriente todavía.
- Evidencia visual con `scripts/generate_ux_screenshots.py`.

**PR 3 — Presupuesto facturado ahora y cuenta corriente**

- `timing` en el servicio de presupuestos, emisión de la parte inmediata, movimiento de cuenta
  corriente al contado, etiqueta en el estado de cuenta, tests de integridad monetaria.
- Caso clave: el total de los dos presupuestos debe sumar exactamente el total del renglón.

**PR 4 — Presupuesto a facturar después, envío separado y anulación**

- Parte diferida, movimiento con plazo de pago, botón de envío independiente, reverso de ambos
  movimientos al anular la orden, tests de anulación.

## Validaciones

Obligatorias antes de cerrar cada PR:

```bash
git diff --check
python -m compileall app
python -m pytest
python -m app.main --smoke
python scripts/generate_ux_screenshots.py
```

Casos de negocio que hay que cubrir con tests:

1. Renglón 100% facturado ahora: comportamiento idéntico a hoy, un solo presupuesto.
2. Renglón 0% facturado ahora: en la pantalla aparece solo la parte diferida.
3. Reparto parcial: los dos presupuestos suman el total del renglón al centavo.
4. Dos clientes en la misma orden: cada uno con sus dos presupuestos.
5. Anulación de la orden: reversa de los dos movimientos.
6. Orden histórica sin el campo nuevo: un solo presupuesto, como antes.
7. Impresión y envío por separado de cada presupuesto.

Validación manual con el operador, que es la misma puerta que quedó esperando el experimento
#553: cargar una orden real, emitir, ver los dos números en la cuenta corriente, imprimir y
mandar solo el de la parte facturada.

## Riesgos

1. **Devoluciones sobre un renglón partido.** Resuelto por regla de negocio: una
   devolución **solo consume la parte que estaba a facturar después** y nunca cruza a la
   parte ya facturada. El caso no necesita reparto entre las dos partes, sino un límite
   duro. Ver la sección "Regla de devoluciones".
2. **Integidad monetaria.** Cada presupuesto tiene que cuadrar por separado y los dos juntos
   tienen que cuadrar contra el renglón. Hay que apoyarse en `assert_monetary_integrity` y no
   en sumas propias.
3. **Índices en bases instaladas.** El índice único viejo tiene que caer de verdad; si queda, el
   segundo presupuesto falla en tiempo de ejecución y no en desarrollo.
4. **Edición posterior a emitir.** Si el reparto se cambia con la orden ya emitida, el
   presupuesto diferido ya no se recalcula. Tiene que quedar explícito en pantalla para el
   operador, no ser una sorpresa.
5. **Puertas de línea Log en `desktop_app.py`.** Es un archivo grande; el cambio tiene que ser
   quirúrgico y no mezclar el refactor con la funcionalidad.

## Regla de devoluciones

Decidido con el operador: una devolución **solo consume mercadería de la parte a facturar
después**. Nunca cruza a la parte ya facturada.

- **Efecto en la cuenta corriente:** la devolución genera la nota de crédito de siempre,
  pero aplicada contra el presupuesto diferido. La deuda del cliente baja por el importe
  devuelto y el movimiento queda identificado como devolución sobre la parte que estaba a
  facturar después.
- **Límite duro:** la cantidad devuelta no puede superar la cantidad diferida del renglón.
  Si la supera, la operación se rechaza con un mensaje claro al operador.

Consecuencias para la implementación:

- No hace falta repartir proporcionalmente una devolución entre dos presupuestos, que era
  el punto más delicado del diseño original.
- El precio unitario no cambia: las dos partes comparten el precio del renglón, así que
  el cálculo de `unit_price` que hoy hace `load_order_closure_service.py:311` sirve igual.
  Lo que cambia es contra qué cantidad se limita la devolución.
- La validación del límite va en el servicio de cierre, antes de crear el
  `LoadOrderReturnLine`, con su propio test.
- La agrupación por cliente de `LoadOrderReturnCreditService` se mantiene; lo que se
  identifica es contra qué presupuesto se aplica el crédito.

## Pendientes y decisiones abiertas

- **Política de precio de la parte diferida.** En el esquema A queda congelada al día del
  despacho. Si mañana se quiere repacturar, hace falta un segundo precio unitario en el renglón.
- **Devoluciones sobre mercadería ya facturada.** No existe el flujo: por regla, una
  devolución solo consume la parte diferida. Si algún día hace falta, es un flujo nuevo
  con nota de crédito clásica, no una extensión del actual.
- **Comportamiento al editar una orden ya emitida con presupuesto diferido emitido.** Definir
  si se bloquea el campo o se permite con aviso.
- **Si el reparto de dos partes y un mismo cliente necesita otro eje** (por ejemplo, facturar a
  dos sucursales distintas). Fuera de alcance actual.
