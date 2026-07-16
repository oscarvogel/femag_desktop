# Clasificación y peso de artículos legacy

## Objetivo

Separar mercadería cargable de servicios, conceptos financieros e insumos internos, e inferir el peso unitario total desde la presentación incluida en el nombre del artículo. Las decisiones automáticas deben ser visibles, editables y preservarse frente a reimportaciones.

## Modelo de producto

`Product` incorpora los siguientes datos:

- `product_kind`: `producto`, `servicio`, `financiero`, `interno` o `revisar`;
- `classification_source`: `inferido` o `manual`;
- `weight_source`: `inferido` o `manual`;
- `review_required`: indica que falta confirmar clasificación o peso.

`peso_unitario_kg` continúa siendo el peso total de una unidad comercial expresado en kilogramos. No se agrega otra unidad de peso.

Los productos existentes con clasificación nula se analizan una vez al iniciar. Un peso existente mayor que cero se considera manual y no se reemplaza. Un peso cero o nulo puede completarse por inferencia.

## Clasificación automática

Las reglas son deterministas, normalizan mayúsculas y acentos, y se aplican en este orden:

1. `financiero`: nombres con `CREDITO`, `DIFERENCIA`, `AJUSTE`, `CHEQUE DEVUELTO`, `GASTOS ADMINISTRATIVOS` o `SIN CARGO POR REPOSICION`;
2. `servicio`: nombres con `FLETE`, `ALQUILER`, `LABORES` o `CARGA` cuando no describan un envase o presentación de mercadería;
3. `interno`: nombres con `CONSUMO`, `BOBINA` o `BANDA FILTRO`;
4. `producto`: nombres con `FECULA`, `ALMIDON`, `ALMID.` `BOLSA`, `BOL.`, `BOL ` o `PACK`;
5. `revisar`: cualquier caso restante.

La clasificación por precio, costo, IVA o código queda prohibida porque esos campos no distinguen de forma confiable mercadería y conceptos.

`YERBA MATE PUESTA EN PLANTA/ARBOL` queda inicialmente en `revisar`; `CARGA YERBA H.V. PUESTA EN SECADERO` queda como `servicio`.

Sólo `producto` puede seleccionarse en una orden de carga. `servicio`, `financiero`, `interno` y `revisar` quedan excluidos tanto de los combos como de la validación del servicio, aunque permanezcan disponibles para futuros flujos de facturación.

## Inferencia de peso

El analizador trabaja sobre el nombre normalizado y devuelve kilogramos:

- `10 UNIDADES X 1 KG` y variantes abreviadas `10 UNID. X 1 KG` -> `10.000` kg;
- `X 25 KG`, `X25KG` o `X 10KG.` -> el número indicado en kg;
- `X 900 GR`, `X900 GMS`, `X 500 GRS` -> gramos divididos por 1000;
- `X KG` sin número -> `1.000` kg, interpretado como venta por kilogramo;
- `X UNIDAD` o ausencia de presentación reconocible -> `0.000` kg y `review_required = true` para productos físicos.

En expresiones de paquete se calcula primero cantidad por peso individual. No se multiplica dos veces una presentación simple.

Servicios, financieros e internos mantienen peso cero y no requieren revisión por peso. Los artículos `revisar` mantienen peso inferido si la presentación es inequívoca, pero conservan `review_required = true` por clasificación.

## Corrección manual y reimportación

El ABM permite editar clasificación y peso. Al guardar:

- `classification_source` pasa a `manual` si se confirmó la clasificación;
- `weight_source` pasa a `manual` si se confirmó el peso;
- `review_required` se recalcula y queda falso cuando clasificación y peso aplicables están confirmados.

El importador sólo vuelve a inferir un campo cuya fuente no sea `manual`. Nombre, precios y demás datos legacy mantienen el comportamiento actual. Una reimportación nunca reemplaza peso o clasificación corregidos por el usuario.

## Interfaz

La grilla de Productos muestra, además de los datos actuales:

- `Clasificación` con etiquetas `Producto`, `Servicio`, `Financiero`, `Interno` y `Revisar`;
- `Peso unitario` en kg;
- `Órdenes` con `Sí` únicamente para `producto`;
- `Revisión` con `Pendiente` o `Confirmado`.

El diálogo de alta y edición ofrece la clasificación y el peso. Las opciones usan las etiquetas anteriores y validan que el peso no sea negativo.

## Migración y seguridad

Las nuevas columnas se agregan mediante `ensure_runtime_schema`. El backfill se ejecuta de manera idempotente sobre productos con fuentes nulas. No se borran productos ni se cambian referencias existentes.

La validación contra la base DEMO se realiza primero sobre una copia. Se informa un resumen por clasificación, pesos inferidos y pendientes de revisión antes de ejecutar el instalador sobre la base real.

## Pruebas y entrega

- Pruebas unitarias del analizador con variantes `KG`, `GR`, `GMS`, `GRS`, paquetes y nombres sin presentación.
- Pruebas de clasificación para las cinco categorías y casos prioritarios del DBF real.
- Pruebas de preservación manual en reimportación.
- Pruebas de selector y validación de órdenes.
- Pruebas y captura del ABM de productos.
- Suite completa, `compileall`, smoke, importación del DBF real sobre SQLite temporal e integridad.
- Nuevo instalador DEMO con versión posterior a `2026.07.16-demo.2`, smoke empaquetado y publicación de todo el código mediante issue, rama y PR.

## Fuera de alcance

- Implementar facturación de servicios o conceptos financieros.
- Inferir peso desde precio, costo o IVA.
- Modificar remitos, F150 o liquidaciones.
- Clasificación mediante inteligencia artificial o servicios externos.
