# Presupuestos separados por cliente

El botón **Presupuesto** de Órdenes de carga debe generar un PDF independiente por cada cliente de la orden.

Cada archivo conserva su número interno `PRES-xxxxxx`, incluye únicamente la mercadería de ese cliente y mantiene la referencia a la Orden de Carga asociada.

La UI usa `LoadOrderOperationService.export_budgets(order)` y no el bundle combinado.
