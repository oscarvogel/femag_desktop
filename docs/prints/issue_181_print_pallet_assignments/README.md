# Evidencia operativa - issue #181

PDF generado contra la SQLite de validación usada para reproducir el reporte del usuario.

## Datos comprobados

- Mercadería solicitada: 100 kg de fécula de maíz y 200 kg de fécula de mandioca.
- Pallets persistidos: 20, numerados del 1 al 20.
- Asignaciones efectivas: ambos productos están únicamente en el pallet 1.
- Kilos persistidos del pallet 1: 300.000 kg.

## Resultado extraído del PDF

- `TOTAL MERCADERIA`: `300 kg`.
- Columna `Pallet` de la fila: `1`.
- Fila `TOTALES`: `1 pallet` utilizado.

Archivo: `orden_carga_1.pdf`.

La cobertura automatizada adicional valida una fila repartida entre pallets 1 y 3 y espera `1, 3`, sin duplicados, con `2 pallets` en el total.
