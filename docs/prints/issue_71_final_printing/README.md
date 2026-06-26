# Evidencia Issue #71 - Impresion A4 Orden de carga

Archivos generados desde `LoadOrderPrintService` sin abrir la UI grafica:

- `orden_carga_1.html`: Orden de carga A4 con cabecera logistica y detalle por cliente/destino.
- `hoja_resumen_1.html`: Hoja resumen / sobre de carga A4.
- `orden_y_resumen_1.html`: Documento combinado con salto de pagina y marca de reimpresion.

## Revision manual del HTML

Se reviso el HTML generado abriendo los archivos como texto y verificando:

- La cabecera dice `Documento logistico interno` y `No fiscal`.
- No hay cabecera comercial/fiscal ni datos de factura/remito/F150.
- La orden separa `Cliente / destino 1` y `Cliente / destino 2`.
- Cada destino muestra cliente, domicilio, ciudad, provincia, productos, presentaciones, cantidades y observaciones.
- Los totales por destino y el total general aparecen en el documento.
- La hoja/sobre resume los clientes/destinos sin convertir una carga multi-cliente en un cliente unico.
- El combinado incluye salto A4 entre orden y hoja/sobre, y marca `Reimpresion operativa - Copia para reimpresion`.

Comando usado para validar la generacion sin UI:

```powershell
py -3 -m pytest tests/test_load_order_printing.py -q
```
