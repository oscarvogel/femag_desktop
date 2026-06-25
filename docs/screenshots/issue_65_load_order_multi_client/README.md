# Evidencia visual - Issue #65 Ordenes de carga multi-cliente

Archivo:

- `01_load_orders_multi_client.png`

Validacion:

- Captura generada con PyQt5 en modo `QT_QPA_PLATFORM=offscreen`.
- Datos sinteticos: dos clientes, dos destinos, dos productos y un transporte demo.
- La pantalla corresponde al modulo `Ordenes de carga` con acciones visibles para agregar/quitar cliente, agregar/quitar producto, guardar, emitir e imprimir.

Nota:

- En esta rama no existe `scripts/generate_ux_screenshots.py`; por eso la evidencia se genero con un snippet PyQt controlado.
- El backend offscreen disponible en esta maquina no renderiza texto con la misma fidelidad que una sesion interactiva, por lo que la validacion textual del contrato UI queda cubierta por `tests/test_load_order_multi_client_ui.py`.
