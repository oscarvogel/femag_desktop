# Evidencia visual - issue #178

Capturas generadas con `python scripts/generate_ux_screenshots.py` sobre una base SQLite temporal.

- `01_nueva_orden_grilla_pallets.png`: estado inicial de una orden guardada, con resumen pendiente, editor deshabilitado y acción `Agregar primer pallet`.
- `02_panel_lateral_pallet_mixto.png`: listado de órdenes con estado `Sin preparar` y acción contextual `Armar pallets`.
- `03_editar_orden_reconstruida.png`: preparación independiente reabierta, con asignaciones y kilos reconstruidos.
- `04_estado_rojo_excedente.png`: validación visual roja y explicación al superar la cantidad solicitada.

Datos de la prueba visual:

- La orden comercial se guarda antes de preparar los pallets.
- La preparación se abre luego desde la acción `Armar pallets` del listado de órdenes.

- Pallet 1: 825 kg, dos clientes y dos artículos.
- Pallet 2: 675 kg, un cliente y dos artículos.
- Total válido: 1.500 kg.
- Estado inválido: se agrega una unidad de cemento y el total pasa a 1.525 kg.
