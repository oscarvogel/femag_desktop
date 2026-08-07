# Modelo de cierre de orden de entrega

Este documento fija el modelo base del tracking #219. El cierre de entrega
extiende el flujo existente de Ordenes de carga; no crea un documento paralelo
ni reemplaza la emision.

## Estado existente y decision

`LoadOrder.STATUS_CLOSED` ya existe y libera al chofer. Se conserva como unico
estado final de una entrega cerrada. La diferencia es que toda transicion nueva
a `Cerrada` debe quedar respaldada por un `LoadOrderClosure` activo.

El ciclo permitido es:

```text
Pendiente -> Emitida -> Cerrada
                ^          |
                |----------|
                   reabrir
```

Reabrir una entrega vuelve la orden a `Emitida`, no a `Pendiente`. De esta
forma no se habilita la edicion del documento ya emitido ni se duplica el
debito documental de cuenta corriente.

## Entidad base

### `LoadOrderClosure`

- `order`: orden relacionada.
- `status`: `active` o `reopened`.
- `active_marker`: `True` para el cierre vigente y `NULL` para ciclos
  historicos reabiertos.
- `closed_at`, `closed_by`, `observations`: evidencia del cierre.
- `no_payment_reason`: motivo obligatorio cuando el cierre no registra pagos.
- `reopened_at`, `reopened_by`, `reopen_reason`: evidencia de la reapertura.

El indice unico `(order, active_marker)` permite varios cierres historicos con
`active_marker = NULL`, pero impide mas de un cierre activo por orden.

## Invariantes del servicio

- Solo una orden `Emitida` puede cerrarse.
- El cierre y el cambio de estado son una unica transaccion.
- Cerrar libera al chofer usando la regla existente.
- Solo una orden `Cerrada` con cierre activo puede reabrirse.
- La reapertura exige motivo y vuelve a bloquear al chofer.
- Si el chofer esta ocupado por otra carga, toda la reapertura se revierte.
- No se permite usar `LoadOrderService.change_status(..., Cerrada)`; el cierre
  debe pasar por `LoadOrderClosureService`.
- Cierre y reapertura quedan registrados en historial y auditoria.

## Extension prevista por sub-issue

### #220 - Pagos del cierre (implementado)

`ClientPayment` incorpora una relacion opcional con `LoadOrderClosure`. El
cliente ya pertenece al pago, lo que permite soportar ordenes multicliente sin
duplicar datos. El estado `sin pago`, `parcial` o `cobrado` se deriva por cliente
y para el cierre completo a partir de:

- total documental de la orden para ese cliente;
- pagos activos relacionados con el cierre;
- creditos por devolucion cuando existan.

No se guardara un saldo agregado que pueda quedar desactualizado.

El dialogo de cierre muestra los renglones emitidos y permite preparar varios
pagos con cliente, fecha, monto, medio y referencia. La confirmacion crea el
cierre, los recibos, sus movimientos y el cambio de estado en una sola
transaccion. Los movimientos de pago guardan la OC y una referencia al cierre.

El indice contable usa `source_ref`, cliente, tipo y marca de reverso. Asi se
mantiene la proteccion contra movimientos documentales duplicados y se admiten
varios recibos para la misma OC/cliente.

Mientras #222 no genere reversos automaticos, una entrega con pagos activos no
puede reabrirse. Primero deben anularse esos pagos con el flujo administrativo.

### #221 - Devoluciones por renglon

Se agregara `LoadOrderReturnLine` con relacion a:

- `LoadOrderClosure`;
- `LoadOrderProduct`;
- cantidad devuelta;
- motivo obligatorio;
- usuario y fecha de registro.

La combinacion cierre/renglon sera unica. La cantidad debe ser mayor a cero y
no superar la cantidad original. La orden y sus pallets no se modifican.

### #222 - Nota de credito

Se agregaran tipos contables de credito por devolucion y reverso. Cada
movimiento quedara relacionado con la orden y referenciado al cierre/cliente.
Al reabrir un cierre se generaran reversos; no se borraran movimientos ni
devoluciones historicas.

## Compatibilidad y esquema

- SQLite demo y MySQL usan la misma entidad Peewee.
- `ensure_runtime_schema` crea la tabla y su indice de forma segura.
- El arranque productivo continua validando el esquema sin ejecutar DDL.
- Las ordenes cerradas historicas anteriores a #219 pueden existir sin un
  `LoadOrderClosure`; no se inventan cierres ni usuarios retroactivamente. Si
  se intenta reabrir una de ellas, el servicio informa que falta el cierre
  activo y exige tratamiento operativo explicito.

## Fuera de alcance de este corte

- Registro de devoluciones.
- Generacion o reverso de notas de credito.
- Cambios de stock.
- Remitos, F150 o importaciones legacy.
