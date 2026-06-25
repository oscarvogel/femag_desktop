# Evidencia visual - Issue #65 Ordenes de carga multi-cliente

Archivo:

- `01_load_orders_multi_client.png`
- `02_load_orders_operational_form.png`
- `03_load_orders_modal_main.png`
- `04_load_order_entry_dialog.png`

Validacion:

- Captura generada con PyQt5 en modo `QT_QPA_PLATFORM=offscreen`.
- Datos sinteticos: dos clientes, dos destinos, dos productos y un transporte demo.
- Las primeras capturas documentan el contrato multi-cliente original y el formulario operativo inicial.
- Las capturas `03` y `04` documentan la correccion UX posterior: la pantalla principal queda enfocada en listado/detalle y el alta de orden se realiza desde un modal con cabecera logistica, bloque cliente/destino y grilla de productos del destino seleccionado.

Nota:

- En esta rama no existe `scripts/generate_ux_screenshots.py`; por eso la evidencia se genero con un snippet PyQt controlado.
- El backend offscreen disponible en esta maquina no renderiza texto con la misma fidelidad que una sesion interactiva, por lo que la validacion textual del contrato UI queda cubierta por `tests/test_load_order_multi_client_ui.py`.
