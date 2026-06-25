# Evidencia visual - Issue #68 Ordenes de carga emision e impresion

Archivo:

- `01_load_orders_emit_print_flow.png`

Validacion:

- Captura generada con PyQt5 en modo `QT_QPA_PLATFORM=offscreen`.
- Datos sinteticos: orden emitida con dos clientes/destinos, dos productos, transporte, chofer y camion demo.
- La captura documenta que la pantalla de Ordenes de carga conserva listado, detalle y acciones operativas: Nuevo, Emitir, Imprimir, Reimprimir, Anular y Buscar.

Nota:

- El backend offscreen disponible en esta maquina no renderiza texto con la misma fidelidad que una sesion interactiva. El contrato textual y operativo queda cubierto por `tests/test_load_order_desktop_ui.py` y `tests/test_load_order_operations.py`.
