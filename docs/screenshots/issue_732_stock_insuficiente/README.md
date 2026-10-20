# Evidencia visual issue #732

Emitir una orden de carga descontaba del stock **siempre**, sin preguntar por el saldo. En la base real eso se ve: 53 despachos, ninguna entrada de stock, y los 38 productos con saldo negativo.

Desde #732, si la orden pide más mercadería de la que hay, aparece este aviso con el faltante por producto, y el operador tiene que confirmar "Despachar igual" escribiendo un motivo. El motivo queda en la auditoría y en los movimientos del libro.

## Que muestra la captura

`aviso_stock_insuficiente.png`: el aviso para la orden OC-000073.

- La tabla lista, por producto, el **stock en el libro**, lo que **pide la orden** y lo que **falta**.
- Debajo, el motivo: es obligatorio, sin motivo el dialogo no se acepta.
- Los botones: "Despachar igual" y "Cancelar". Cancelar deja la orden como estaba, sin tocar ningun libro.

## La distincion que hace que el aviso sea util

El aviso sale solo de los productos que **ya tienen stock conocido** en el libro (inventario inicial, compra o produccion). De un producto que nunca se conto no se puede afirmar que falte: se estaria avisando que el inventario todavia no esta cargado, que es otra cosa. Sin esa distincion el aviso aparece en cada despacho hasta que se carga el inventario inicial, y a la larga el operador lo deja de leer.

## Como se genero

Con `python scripts/generate_issue_732_screenshot.py`. Base SQLite en memoria con datos sinteticos: ningun dato real entra en la evidencia. La plataforma es `windows` en vez de `offscreen` para que el texto se dibuje (#652).
