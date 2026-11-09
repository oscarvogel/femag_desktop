# Anexo interno — issues técnicos detectados

**NO compartir con el dueño.** Este documento es para el equipo de sistemas: contiene bugs, deudas técnicas y tareas de implementación que debemos resolver nosotros, no el negocio.

**Fuente:** copia `femag_desktop.sql` del 7/11/2026. **Informe para el dueño:** `docs/INFORME_CALIDAD_DATOS_2026-11.md`.

**Estado al 9/11/2026:** #894, #895, #896, #897, #898 y #899 cerrados. **Versión en producción:** `2026.11.09.14.59.41`.

| # | Tema | Evidencia | Acción | Prioridad | Issue | Estado |
|---|---|---|---|---|---|---|
| 1 | Generación/vinculación de presupuestos | 30 de 120 órdenes sin presupuesto: 29 de septiembre (antes del 17/09) y 1 pendiente; OC-104 con ARS 4.755.240 de más; OC-26 con ARS 33.690.600 de menos | Separar histórico de bug actual; reparar huérfanos | Alta | #894 | **Cerrado.** Prevención ya estaba en #726; OC-104 reparada con `repair_stale_load_order_budgets`. En producción `2026.11.07.14.56.41` |
| 2 | Dinero en `FLOAT` | El dump del 7/11 ya tiene las columnas monetarias en `DECIMAL(18,2)`; PRES-000073 reparado en #641 | Verificar entornos viejos | — | #641 | **Resuelto** |
| 3 | Identidad de usuarios y auditoría | `gabriela`, `GABRIELA`, `gabreila`, `gabriela2026`, `femag`, `femag_admin`, `admin_prueba`, `sql:root@localhost` | Identidad estable, alias y filtros | Media | #896 | **Cerrado.** En producción `2026.11.07.14.56.41` |
| 4 | Job gerencial por WhatsApp | 49 en `processing`, 5 fallidas, 42 enviadas, 1 en cola | Normalizar estados, limpiar trabados, reintento y alarma | Media | #895 | **Cerrado.** En producción `2026.11.07.14.56.41` |
| 5 | Importación legacy | 173 advertencias y 1 error: 63 colisiones de código, 56 transportistas no encontrados, 34 CUIT compartidos, 16 conflictos de acoplado, etc. | Clasificar y dejar revisión manual | Media | #897 | **Cerrado.** 54 esperadas, 119 para revisar, 0 bugs de mapeo. En producción `2026.11.09.14.59.41` |
| 6 | Tablas/módulos sin uso | 17 tablas vacías | Inventario y decisión por módulo | Media | #898 | **Cerrado.** Documento `docs/INVENTARIO_TABLAS_SIN_USO.md`; decisiones de negocio pendientes de firma. En producción `2026.11.09.14.59.41` |
| 7 | Conciliación de pagos | 9 recibos con diferencia cabecera/detalle por ARS 1.536, de septiembre y previos a #439; el caso grande es el recibo anulado de #867 | Sin issue nuevo | — | #439/#867 | **Histórico** |
| 8 | Fechas extremas | Movimiento 414 con fecha 31/08/2027 | Corregir y validar fechas | Baja | #899 | **Cerrado.** Movimiento 414 corregido a 31/08/2026 en producción; validación de 180 días. En producción `2026.11.09.14.04.04` |
| 9 | Remito independiente | 26/26 remitos sin `source_order_id` y sin lote | Documentar que es un documento legal independiente | — | — | **No es un bug** |
| 10 | IVA 0% | 562/564 ítems y 315/317 presupuestos con IVA 0% | Documentar que la facturación se emite en Holistor | — | — | **No es un bug** |
| 11 | Rinde estimado | 405/610 recepciones con 22,33% fijo; `yield_source` distingue medido/estimado | Marcar estimado/medido en reportes | — | — | **Regla aceptada** |
| 12 | Conciliación FEMAG ↔ Holistor | 42 comprobantes en texto libre, 35 débitos de IVA/percepciones, 112 SALDO por ARS 1.602 M | Referencia estructurada y reporte mensual de diferencias | Media | #906 | **Abierto** |

## Notas

- La tanda de calidad de datos quedó cerrada con los seis issues (#894, #895, #896, #897, #898 y #899).
- Queda abierto **#906** para la conciliación estructurada con Holistor.
- Los puntos 9, 10 y 11 son decisiones de diseño o reglas aceptadas: el riesgo es que alguien los interprete como faltantes.
- Ninguno de estos puntos debe figurar en el informe del dueño.
