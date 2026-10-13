# Análisis de recompra por cliente y producto

Responde: "¿Qué clientes compraron entre el 1 y el 12 de septiembre y todavía no
volvieron a comprar entre el 1 y el 12 de octubre?" — para cualquier producto y período.

## Reglas

- Períodos equivalentes obligatorios vía `ReportPeriod.previous_equivalent()`:
  01–12/10 vs 01–12/09 (nunca 12 días contra mes completo). Ambas fechas siempre visibles.
- Fuente única: `ManagerialDashboardService._dispatch_breakdown` — órdenes efectivas
  `Emitida`/`Cerrada` (se excluyen pendientes/anuladas), kilos físicos de pallets +
  mercadería suelta con fallback a peso configurado, sin duplicar por destinos,
  agrupado por `client_id`/`product_id`. Devoluciones viven en `LoadOrderReturnLine`
  y hoy no descuentan KPI ni kilos (piso 0): no existen netos negativos; si aparecieran,
  actual ≤ 0,5 kg con anterior > 0,5 kg clasifica `sin_recompra`.
- Criterio: kilos/toneladas. El valorizado es contexto, no clasifica (un precio mayor
  con menos kilos es `compro_menos`).
- `nuevo` = nuevo *en el período comparado*, no cliente nuevo de FEMAG.
- Vendedor: `LoadOrder` no guarda histórico; se informa la asignación actual
  `Client.salesperson` como proxy operativo (documentado en UI y Excel).
- `sin_recompra` es alerta comercial, no pérdida confirmada.

## Servicio (`app/reports/managerial_dashboard.py`)

- `product_client_repurchase(current, previous, product_id, client_id, salesperson_id,
  client_query, limit, order_by)`: por cliente-producto devuelve vendedor actual,
  últimas fechas anterior/actual, kg/TN, diferencia, variación %, importes, n° órdenes
  y clasificación (`sin_recompra`, `compro_menos`, `igual`, `compro_mas`, `nuevo`).
  Orden por defecto: sin recompra primero por TN anterior desc.
- `product_repurchase_summary(...)`: TN/ valorizado anterior-actual, variación,
  compradores, conteos por grupo y conciliación exacta:
  `neta = −sin_recompra + reducciones + aumentos + incorporaciones` (`reconciliation_ok`).

## UI (`app/ui/managerial_repurchase_dialog.py`)

Sección "Análisis de recompra por producto" (botón "Comparar recompra" del dashboard
gerencial, mismo permiso `Dashboard Gerencial`). Filtros: producto, ambos períodos,
situación comercial, orden (TN no repetida/variación/cliente), búsqueda. Muestra tarjetas
TN + valorizado, barra de variación, gráfico de dos barras (SVG en HTML, QPainter en
diálogo) y tabla con vendedor y última compra. Sin recompra primero, con fondo de alerta.

## Excel (`app/reports/managerial_repurchase_export.py`)

`export_repurchase_xlsx`: hojas Resumen (con gráfico PNG incrustado si se pasa
`chart_image`), Sin_recompra, Reduccion, Aumento, Incorporados, Detalle verificable
(orden × destino × producto, sin duplicar). `export_repurchase_html`: informe
autocontenido con gráfico SVG inline + tablas por grupo.

## Resumen diario (`app/services/managerial_summary_service.py`)

`commercial_followup(summary, min_drop_percent=15, min_lost_tonnes=1.0, ...)`: une tops
actual+anterior (un fugado total tiene 0 TN actual y no saldría solo con el top actual),
filtra caída + sin recompra y devuelve hasta 3 alertas (sin producto fijo). WhatsApp agrega
1 bloque 📉 (producto, %, sin recompra, mayor oportunidad, fechas, "Consultar informe
completo en FEMAG"); el correo agrega sección con top 5 fugados por producto. Sin datos o
sin criterio cumplido no se inventan conclusiones. Reutiliza el envío/historial/
idempotencia existentes (`record_delivery`); no hay segundo proceso.

## Validación artículo 1002 (referencia, no constante)

Excel gerencial de referencia: sep 72,75 TN → oct 49,50 TN (−23,25 TN, −31,96 %),
36,75 TN sin recompra (Cagnoli 24, Buenos Alimentos 4,5, Bema Rio 3, etc.). Si la base
actual difiere, se documenta la discrepancia sin alterar resultados.

## Permisos y rendimiento

- UI, servicio y exportaciones exigen `Inicio → ver → Dashboard Gerencial`.
- Agregaciones en Python sobre `_dispatch_breakdown` (2 consultas de líneas + 2 de
  asignaciones por período); sin N+1 adicional (vendedor vía LEFT JOIN). Sin migraciones.
