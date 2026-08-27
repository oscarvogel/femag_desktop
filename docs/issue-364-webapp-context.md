# Issue 364 — contexto operativo en carga de lote

La webapp móvil debe seguir el mismo criterio de la orden de despacho real de fábrica.

## Unidad operativa

La unidad editable es el **renglón de despacho** (`LoadOrderProduct`), no el pallet individual.

Cada renglón identifica una combinación concreta de:

- cliente;
- lugar de entrega;
- producto/presentación;
- cantidad.

El lote y la fecha de elaboración pertenecen a ese renglón y se guardan en `LoadOrderProduct.lote` y `LoadOrderProduct.fecha_elaboracion`.

## Pallets

Los pallets son contexto del renglón. La webapp obtiene los números de pallet desde `LoadOrderPalletAllocation` filtrando por destino y producto.

Si un renglón participa en varios pallets, se muestran todos en el mismo bloque, por ejemplo `1, 2, 3`, sin duplicar los campos de lote/fecha.

Si la asignación corresponde a mercadería suelta, la pantalla lo indica explícitamente.

## Objetivo de UX

Antes de escanear o ingresar el lote, el operario de depósito debe poder reconocer sin ambigüedad:

1. para qué cliente trabaja;
2. cuál es el lugar de entrega;
3. qué producto/presentación y cantidad está preparando;
4. qué pallet o pallets están relacionados.

Este criterio se tomó de una orden real de despacho de fábrica, donde cada fila contiene destino/presentación, cantidad, pallet, detalle, lote y fecha de elaboración.
