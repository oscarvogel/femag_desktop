# Issue 70 - ABMs mínimos para Orden de carga

Evidencia generada con PyQt en modo `offscreen` usando datos sintéticos en SQLite en memoria.

Capturas:

- `clients.png`
- `addresses.png`
- `carriers.png`
- `drivers.png`
- `trucks.png`
- `products.png`
- `load_orders.png`

Resultado:

- `py -3 -m app.main --demo-ui` arrancó correctamente y fue detenido de forma controlada.
- Las capturas offscreen se generaron para verificar que las páginas ABM y Orden de carga abren sin error.
- Limitación conocida: el plugin Qt offscreen de este entorno no renderiza texto de forma confiable en las capturas, por eso la validación funcional principal queda cubierta por tests de widgets y flujo de servicios.
- Computer Use detectó la ventana real `FEMAG Desktop`, pero la captura falló con `SetIsBorderRequired failed: Interfaz no compatible (0x80004002)`. Por eso no se afirma validación visual real completa en este PR.
