# Diseño: cargar lote y fecha de elaboración a un grupo de pallets (web QR)

- **Issue**: #873 (hijo de #364)
- **Fecha**: 2026-11-03
- **Alcance de este documento**: el diseño completo. Se entrega en dos PRs: PR 1 (webapp) y PR 2 (escritorio).

## 1. Contexto

La ficha de orden de la web móvil QR (`/orden/<token>`) pide el lote y las fechas **una vez por pallet**. Una orden de 19 pallets son 19 formularios en el celular, cada uno con lote, fecha de elaboración, fecha de envasado y un botón "Escanear".

El problema real no es la cantidad de formularios, es que **se pide el dato con la granularidad equivocada**:

| Dato | Dónde vive hoy | Cómo lo consume |
|---|---|---|
| Lote y fecha de elaboración | `LoadOrderPalletAllocation` (contenido del pallet) | la ficha web, un renglón por pallet |
| Lote y fecha de elaboración | `LoadOrderProduct` (línea de despacho) | la hoja de despacho y el informe de trazabilidad |

Como la carga del celular nunca completa la **línea**, la columna "Lote" de la hoja de despacho sale vacía y el operador la escribe a mano. En la orden 0107 hay 6 líneas y 19 pallets; el operador escribe a mano 6 celdas con hasta 2 lotes cada una.

Y la fecha de elaboración **pertenece al lote, no al pallet**: hoy se escribe hasta 19 veces la misma fecha por orden.

## 2. Decisiones de negocio (confirmadas con el usuario)

1. La captura es **100% en el celular**. El escritorio no captura lotes: los recibe por sync y los muestra.
2. Un **lote y una fecha se asignan a varios pallets** de la orden, no a uno solo.
3. Un **pallet puede llevar más de un producto**, y cada producto del pallet lleva su propio lote y fecha.
4. Una línea puede tener **varios lotes**: a veces uno, a veces dos.
5. La carga **completa también la línea de despacho**, para que la hoja de despacho y el informe de trazabilidad dejen de salir con la columna vacía.
6. El reparto de pallets dentro de una línea se **corrige a mano** (se toca el pallet y se lo mueve de grupo).

## 3. Modelo de datos

No cambia. El modelo ya soporta las dos granularidades:

- `LoadOrderProduct` (línea de despacho): `lote`, `fecha_elaboracion`, `fecha_envasado`.
- `LoadOrderPalletAllocation` (contenido de pallet): `lote`, `fecha_elaboracion`, `fecha_envasado`.
- `LoadOrderLooseAllocation` (mercadería suelta): igual.

Índice único `LoadOrderPalletAllocation(pallet, destino, producto)`: un pallet puede llevar varios productos, cada uno con su lote, pero **no puede llevar dos lotes del mismo producto**. Ese límite ya existe y no se modifica en este trabajo (queda anotado en #364).

## 4. Contrato fábrica → nube

Hoy el payload de la nube (`app/services/sync_order_publisher.py`) publica los contenidos de pallet con `product_name`, `quantity`, `unit`, `lote`, `fecha_*`, `client_name` y `destination`, pero **sin decir a qué línea de despacho pertenecen**. Sin ese dato la nube no puede agrupar por línea.

**Cambio:** cada contenido publica `line_uid` (el `global_uid` de su `LoadOrderProduct`), resuelto con la misma regla que ya usa la impresión: la línea de `(destination_id, product_id)` del pedido.

**Compatibilidad:** si el payload no trae `line_uid` (fábrica sin actualizar), la nube agrupa por `product_name` + `client_name` + `destination`, que es lo único disponible, y no completa la línea. La pantalla no rompe.

El contrato de ida (nube → fábrica) **no cambia**: el consumidor de sync ya acepta `order_lote_fecha_updated` (línea) y `order_content_lote_fecha_updated` (contenido).

## 5. La pantalla

Una tarjeta por **línea de despacho** (producto + cliente + destino). Dentro de la línea, los pallets de esa línea como botones (P1, P2, …) y uno o más **grupos** de lote.

```
BOLSAS DE FECULA MOD · 600 u · 10 pallets
DITAS S.A. · DEAN FUNES 1535 - 7-12 HS - VILLA MADERO

Pallets de esta línea:  [P1][P2][P3][P4][P5][P6][P7][P8][P9][P10]   ← todos marcados

Lote                 [ 08 ]            [ Escanear ]
Fecha de elaboración [ 19/10/2026 ]
Fecha de envasado    [        ]

Se aplica a los 10 pallets marcados.        [+ otro lote para otros pallets]
```

Con dos lotes:

```
Lote 08 · Fecha [19/10/2026]  →  P1 P2 P3 P4 P5 P6 P7 P8
Lote 09 · Fecha [19/10/2026]  →  P9 P10
```

Reglas de interacción:

- La línea arranca con **un grupo con todos sus pallets marcados**.
- El operador desmarca los pallets del segundo grupo, pulsa **"+ otro lote para otros pallets"** y carga el segundo lote con su fecha.
- Cada chip muestra el lote que tiene: se ve qué se cargó y qué falta.
- El botón "Escanear" del grupo escribe el lote leído en el input del grupo (mismo comportamiento que hoy).
- Un pallet con 2 productos aparece en las 2 tarjetas, con su propio lote.

### 5.1 Por qué la fecha va con el lote

La fecha de elaboración es un dato del lote de producción. Cargarla una vez por grupo —y no una vez por pallet— es la reducción real de trabajo: en la orden 0107 se pasa de 19 fechas a 6 (una por línea) o menos si hay menos lotes.

## 6. Guardado

Al guardar, por cada línea:

1. Cada **contenido** de los pallets de la línea queda con el lote y las fechas de su grupo → un evento `order_content_lote_fecha_updated` por contenido (como hoy).
2. La **línea** queda con el lote y las fechas del **grupo más grande** → un evento `order_lote_fecha_updated`.

El grupo más grande se desempata por el orden en que aparecen los grupos en la pantalla.

### 6.1 Validaciones

- La suma de los pallets marcados de todos los grupos tiene que ser igual a la cantidad de pallets de la línea. Si no, no se guarda y se avisa.
- Un pallet no puede estar en dos grupos.
- El lote no puede superar los 255 caracteres.
- Las fechas tienen que estar en formato `AAAA-MM-DD`; se aceptan vacías.
- Un grupo sin lote no se guarda (se ignora), pero los pallets que quedan sin ningún grupo con lote se avisan.

### 6.2 Auditoría

Se mantiene `audit.ACTION_LOTE` con el detalle por línea y por contenido, como hoy.

## 7. Lo que recibe el escritorio (PR 2)

Sin captura: el escritorio solo lee lo que llegó por sync.

- **Hoja consolidada** (`app/services/consolidated_load_order_print_service.py`): hoy agrupa por `(producto, unidad, lote, elab)` tomando el lote de la **línea**, así que una línea con 2 lotes sale como un solo renglón con la celda de lote vacía. Con el cambio, la fila del pallet usa el lote de su **contenido** (si falta, el de la línea) y la línea de 10 pallets sale en 2 renglones:

  | Producto | Pallets | Cantidad | Lote | Elab. |
  |---|---|---|---|---|
  | BOLSAS DE FECULA MOD | 8 | 480 | 08 | 19/10/26 |
  | BOLSAS DE FECULA MOD | 2 | 120 | 09 | 19/10/26 |

- **Informe de trazabilidad** (`app/reports/lot_traceability.py`): cada fila de pallet muestra el lote de ese pallet, en lugar del lote de la línea repetido.

## 8. Pruebas

**Webapp**
- Una línea de N pallets se guarda con un solo formulario: la línea y sus N contenidos quedan con el lote y la fecha.
- Una línea con 2 grupos: cada pallet queda con el lote de su grupo.
- Los conteos que no cierran se rechazan con mensaje.
- Un pallet no puede quedar en dos grupos.
- Payload sin `line_uid`: la pantalla agrupa por producto + cliente + destino y no completa la línea.
- Fecha inválida: se rechaza.
- La fecha de envasado se carga y se sincroniza.

**Publisher**
- El contenido publicado incluye `line_uid`.

**Escritorio**
- La hoja consolidada separa la línea en 2 renglones por lote.
- El informe de trazabilidad muestra el lote por pallet.

**Validación general**
- `python -m pytest`
- `python -m compileall app`
- Evidencia visual de la pantalla con una línea de 10 pallets y 2 grupos.

## 9. Fuera de alcance

- Editar lotes desde FEMAG Desktop (issue #864).
- Permitir dos lotes del mismo producto dentro de un pallet (índice único del modelo; queda en #364).
- Recordar el último lote usado para autocompletar la fecha.
- Cambiar cantidades, stock, precios, remitos o F150.
