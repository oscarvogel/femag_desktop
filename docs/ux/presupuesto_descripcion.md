# UX - Descripción de presupuesto por cliente/destino

Issue relacionado: #231. Antecedente: #215.

## Objetivo

Permitir que administración cargue condiciones comerciales distintas para cada
cliente/destino dentro de la orden de carga. Cada página del presupuesto debe
usar sólo la descripción que corresponde a ese destino.

## Usuario principal

- Administración o secretaría que prepara presupuestos para clientes.

## Flujo

1. Seleccionar una orden de carga.
2. En el paso `Destinos`, agregar un cliente y su lugar de entrega.
3. Con el destino seleccionado, escribir su `Descripción del presupuesto`.
4. Repetir para cada cliente/destino de la carga.
5. Guardar la orden y generar el presupuesto desde el listado.

## Estados y validaciones

- Con texto: la página del destino imprime su propio bloque `Observaciones:`.
- Vacío: esa página no imprime el bloque.
- Cambio de selección: el campo carga la descripción del destino seleccionado.
- Edición: el texto queda persistido en `LoadOrderDestination.observations`.
- La observación general de la orden conserva su uso operativo y no se imprime
  como condición comercial común.

## Criterios visuales

- Campo multilínea dentro del paso `Destinos`.
- Grilla con una columna visible `Descripción presupuesto`.
- La selección de la grilla determina qué descripción se está editando.
- Layout legible en la altura mínima soportada por la orden.

## Fuera de alcance

- Descripciones por producto.
- Cambios de modelo o esquema.
- Edición de órdenes ya emitidas.

## Evidencia

- `docs/screenshots/issue_231_budget_description/load_order_destination_descriptions.png`
