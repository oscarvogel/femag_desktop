# Inventario de tablas y módulos sin uso

**Fecha:** 9 de noviembre de 2026
**Base auditada:** copia `femag_desktop.sql` del 7/11/2026
**Alcance:** 17 tablas sin registros. No se elimina estructura ni datos.

## Criterio

“Tabla vacía” significa **0 filas** en la copia auditada. No significa que el módulo sobre o que se pueda borrar. La decisión es documental y de producto:

- **Activar 90 días:** hace falta para cerrar el circuito operativo.
- **Activar condicional:** depende de una decisión de calidad, negocio o roadmap.
- **Roadmap:** la funcionalidad existe, pero todavía no se adoptó.
- **Sistema:** tabla de infraestructura, no módulo de negocio.
- **Deprecar:** no tiene uso ni issue asociado; se documenta y **no se borra**.

Las decisiones marcadas “confirmar” requieren firma del área responsable antes de activar, deprecar o dar de baja una funcionalidad.

## Inventario

| Tabla(s) | Módulo | Qué guarda | Estado | Decisión propuesta | Responsable | Issue |
|---|---|---|---|---|---|---|
| `production_part` | Producción real | Parte de embolsado por fecha y turno | Vacía | **Activar 90 días** | Producción / Sistemas | #575 |
| `production_bag` | Producción real | Bolsas embolsadas por producto y parte | Vacía | **Activar 90 días** | Producción / Sistemas | #575 |
| `production_consumption` | Producción real | Kilos de materia prima consumidos por parte | Vacía | **Activar 90 días** | Producción / Sistemas | #575 |
| `stock_count` | Inventario físico | Sesión de conteo de depósito | Vacía | **Activar 90 días** | Depósito / Sistemas | #575 |
| `stock_count_line` | Inventario físico | Línea de conteo y diferencia contra el libro | Vacía | **Activar 90 días** | Depósito / Sistemas | #575 |
| `raw_material_intake` | Ingreso de materia prima | Ingreso propio de big bags de almidón | Vacía | **Activar con producción** (confirmar si la planta compra big bags) | Producción / Sistemas | #575 |
| `raw_material_intake_line` | Ingreso de materia prima | Big bags y kilos del ingreso | Vacía | **Activar con producción** | Producción / Sistemas | #575 |
| `clientfiscalcertificate` | Clientes | Certificados de exclusión de Rentas/IVA con vigencia | Vacía | **Activar según #871** | Administración | #871 |
| `syncconflict` | Sync nube | Eventos que no se pudieron aplicar | Vacía | **Activar según #804** | Sistemas | #804 |
| `syncoutbox` | Sync nube | Eventos locales pendientes de enviar | Vacía | **Activar según #804** | Sistemas | #804 |
| `syncprojection` | Sync nube | Copia de lectura de recursos en la nube | Vacía | **Activar según #804 / #806** | Sistemas | #804, #806 |
| `pallettype` | Pallets | Tipo, medida y peso del pallet | Vacía | **Roadmap**: activar si Logística tipifica pallets | Logística / Sistemas | Sin issue |
| `remittanceseries` | Remitos | Talonario físico y numeración preimpresa | Vacía | **Mantener/Roadmap**: activar si se emite remito desde FEMAG | Administración / Sistemas | Sin issue |
| `clientemail` | Clientes | Múltiples emails por cliente | Vacía | **Roadmap**: hoy se usa `client.email`; activar si se necesitan varios destinatarios | Comercial / Sistemas | #280 (cerrado) |
| `loadorderreturnline` | Devoluciones | Cantidad devuelta al cierre de la orden | Vacía | **Mantener/Roadmap**: activar cuando se registren devoluciones | Logística / Sistemas | #221 (cerrado) |
| `backuplog` | Sistema | Log de backups | Vacía | **Sistema**: revisar por qué no registra; no es módulo de negocio | Sistemas | #15 |
| `operationalservice` | Servicios operativos | Maestro de servicios operativos | Vacía y sin referencias de código | **Deprecar** (no borrar) | Sistemas | Sin issue |

## Decisiones que requieren confirmación

1. **Producción, stock y materia prima:** confirmar que es prioridad de los próximos 90 días.
2. **Big bags:** confirmar si la planta compra almidón en big bags además de recibir mandioca. Si no, `raw_material_intake` queda en roadmap.
3. **Certificados fiscales:** activar con #871.
4. **Sync/web:** activar con #804/#806.
5. **Pallets, series de remito, multi-email y devoluciones:** decidir si se activan en el roadmap o se dejan como funcionalidad disponible sin uso.
6. **`operationalservice`:** confirmar deprecación. No hay referencias de código ni issue asociado.
7. **`backuplog`:** revisar con #15; la tabla vacía puede significar que el backup no se está ejecutando o no está registrando.

## Próximos pasos

- Firmar la decisión de cada fila con el área responsable.
- Abrir un issue sólo cuando un módulo de roadmap pase a activo.
- No borrar tablas, columnas ni datos en este trabajo.
- Referenciar este documento desde el roadmap y la documentación de arquitectura.

## Referencias

- `docs/PRODUCCION_STOCK_DISENO.md`
- `docs/FEMAG_LOOP_PLAN.md`
- Issues: #15, #221, #280, #575, #804, #806, #871
