# Evidencia visual - issue #178

Capturas generadas con `python scripts/generate_ux_screenshots.py` sobre una base SQLite temporal.

- `01_nueva_orden_grilla_pallets.png`: alta de orden con dos tarjetas de pallet, total de la orden y panel de composición.
- `02_panel_lateral_pallet_mixto.png`: pallet seleccionado con mercadería de dos clientes y dos artículos.
- `03_editar_orden_reconstruida.png`: edición de una orden persistida, con pallets, asignaciones y kilos reconstruidos.
- `04_estado_rojo_excedente.png`: validación visual roja y explicación al superar la cantidad solicitada.

Datos de la prueba visual:

- Pallet 1: 825 kg, dos clientes y dos artículos.
- Pallet 2: 675 kg, un cliente y dos artículos.
- Total válido: 1.500 kg.
- Estado inválido: se agrega una unidad de cemento y el total pasa a 1.525 kg.
