# F150 contra la muestra real - informe comparativo (#681)

Fecha: 2026-10-09
Rama: `fix/f150-golden-master-20261005` (base `rebuild/issue-11-f150-clean`, commit `19a70af`)

## 1. Muestra usada como autoridad

El issue pide comparar contra `F.150-05-10-2026B.TXT` (05/10/2026). **Ese archivo
no estaba en la maquina** y el issue aclarea que no se reconstruya de memoria.

Se busco en todo el disco (`C:\`) y no aparece. La autoridad usada en su lugar
es el archivo real del mismo generador que la empresa tiene en
`C:\Programacion\dante\contable\`: **119 archivos F150 de produccion de 2019**,
314 registros `C` y 339 registros `D`, todos decodificables como CP1252.

| | Muestra del issue | Corpus usado |
|---|---|---|
| Archivo | `F.150-05-10-2026B.TXT` | 119 archivos `F150-AAAAMMDD[ABC].TXT` |
| Registros | 5 `C` + 6 `D` | 314 `C` + 339 `D` |
| Procedencia | conversacion de revision | salida del sistema anterior |

El corpus contiene `F150-20190708.TXT` con exactamente la misma forma de la
muestra del issue (**5 `C` + 6 `D`, con un remito de dos renglones**), asi que
todos los casos de la muestra quedan cubiertos. **Pendiente**: repetir la
comparacion contra `F.150-05-10-2026B.TXT` cuando FEMAG haga llegar el archivo
(con `scripts/compare_f150_golden_master.py`, sin versionar el original).

## 2. Metodo

1. Se parsearon los 119 archivos reales a snapshots `F150Remittance`.
2. Se re-codificaron con `F150Encoder` y se compararon **byte a byte**.
3. Se anonimizaron dos archivos de produccion (5C/6D y 2C/3D) conservando estructura,
   cantidad de campos, anchos, espacios, CRLF y los caracteres CP1252, sin
   publicar CUIT, DNI, domicilios ni patentes.
4. En CI quedan dos validaciones independientes: el codificador contra el
   golden master, y un formateador del contrato escrito a mano contra el mismo
   golden master.

**Resultado: 119 de 119 archivos reales reproducidos byte a byte.**

## 3. Diferencias encontradas

| # | Campo / aspecto | Legacy (autoridad) | Codificador antes | Estado |
|---|---|---|---|---|
| 1 | `D` campo 10, entre la 4a clasificacion y la unidad | campo de ancho fijo de **50 caracteres**, siempre espacios (337/339 renglones) | **no existia**: mandaba `item_code` (codigo de producto) | **Corregido** |
| 2 | `D` codigo de producto | **no viaja al F150** | `item_code` ocupaba el lugar del campo fijo | **Corregido** |
| 3 | `C`/`D` punto de venta | 4 digitos con ceros (`1` -> `0001`, `0000` tambien) | se escribia tal cual | **Corregido** |
| 4 | `D` numero de remito fisico | 8 digitos con ceros (`10875` -> `00010875`) | se escribia tal cual | **Corregido** |
| 5 | Fin de archivo | **sin CRLF final** (119/119 de produccion) | agregaba `line_ending` al final | **Corregido** |
| 6 | Precio del renglon | precio congelado de la operacion | `product.precio_neto_base` **vigente** | **Corregido** |
| 7 | Cantidad y monto | `1,250`, `15,625.00` (separador de miles) | identico | Sin cambio |
| 8 | `C` con 49 campos, sin `@` final; `D` con `@` final | confirmado en los 119 | identico | Sin cambio |
| 9 | Encoding CP1252 con `°`, `º`, `Ñ` | presentes en 21 archivos | identico | Sin cambio |

Sobre el punto 1: los dos archivos de referencia que circulaban antes
(`C:\Programacion\ceramica\F150.txt` y `C:\Programacion\dante\f150-dos-item.txt`,
ambos editados a mano) tienen ese campo **vacio**, y de ahi venia el
`LEGACY_DETAIL` del test. Los 119 archivos de produccion lo traen con 50
espacios. Se corrigio el golden master del test contra produccion.

## 4. Precio historico: el hallazgo

`F150BatchService._to_document` tomaba `product.precio_neto_base`, el precio
**vigente del maestro**, y calculaba `cantidad x precio`. Es un error fiscal:
si la lista de precios cambia despues de emitir el remito, el F150 declara un
importe que nunca se opero.

Investigacion:

- El legacy **si** lo congelaba: `detalleremito.unitario` y `detalleremito.untotal`.
- La reescritura **no tiene ningun precio en `RemittanceItem`** (`app/models/remittances.py:78-87`).
- La unica fuente congelada que existe hoy es `LoadOrderProduct.precio_neto_unitario`
  (`app/models/load_orders.py:89`), que la orden de carga calcula una vez y ya
  incluye la lista de precios correcta del cliente.
- `Remittance.source_order` (`app/models/remittances.py:43`) enlaza el remito con esa orden.
- `remittance_service.create_from_order` (`app/services/remittance_service.py:341-352`)
  **descartaba los ocho campos de precio** del renglón de la orden al copiarlo al remito.
- No hay `ProductPrice`, `PriceHistory` ni `Tarifa` en el modelo, y `AuditLog`
  no guarda `old_value` de los cambios de precio, asi que el precio anterior
  no es recuperable.

**Decision aplicada**: el generador toma el precio de la operacion
(`_frozen_unit_prices`) y **bloquea la generacion** cuando no lo encuentra,
en vez de inventar el importe o usar el del maestro. Se bloquea cuando:

- el remito no tiene orden de origen;
- el renglon no tiene precio congelado, o es cero;
- el mismo producto aparece con dos precios distintos en la orden;
- el precio viene de un destino distinto al del remito.

Tests: `tests/test_f150_batch_service.py::test_price_comes_from_the_operation_not_the_master`
y los cuatro casos de bloqueo.

**Riesgo residual conocido**: la orden de carga no es una foto inmutable.
`LoadOrderService._replace_destinations` (`app/services/load_order_service.py:791-792`)
borra los renglones de `LoadOrderProduct` y los vuelve a crear con el precio
recalculado en cada edicion de la orden, y `Remittance.source_order` es
`ON DELETE SET NULL`. Si la orden se edita o se borra despues de emitir el remito,
el precio congelado tambien se pierde y el remito vuelve a bloquear. Es una
limitacion del modelo de datos, no del generador, y se resuelve persistiendo el
precio en `RemittanceItem`.

## 5. Verificaciones ejecutadas

| Comando | Resultado |
|---|---|
| `python -m pytest tests/test_f150_*.py tests/test_issue_40{3,4b,5}_*.py` | **45 passed** |
| `python -m pytest` (suite completa) | 797 passed, 15 failed |
| `python -m compileall -q app` | OK |
| `python -m app.main --smoke` | `FEMAG smoke OK` |
| `git diff --check` | OK |
| Round-trip contra 119 archivos reales | **119/119 identicos** |

Los 15 fallos de la suite completa **son preexistentes**: se reprodujeron igual
sobre `origin/rebuild/issue-11-f150-clean` en un worktree limpio
(`test_remittance_service`, `test_load_order_returns`, `test_load_order_return_credits`,
`test_payment_receipts`, `test_account_statement_printing`, `test_customer_ledger_ui`,
`test_update_service`). Ninguno toca F150.

## 6. Pendientes que requieren definicion de FEMAG

1. **`F.150-05-10-2026B.TXT`**: hace falta el archivo para confirmar la comparacion
   contra la muestra exacta. El nombre `F.150-DD-MM-YYYY` difiere de la convencion
   observada (`F150-AAAAMMDD`), asi que **no se cambio** el nombre sugerido.
2. **Sufijo `B`**: en el corpus conviven `F150-20190412.TXT` y `F150-20190412A.TXT`,
   y `20191111`, `20191111A`, `20191111B`, lo que sugiere un correlativo por
   reemision del mismo dia, pero **no se asumio** ese significado ni se implemento.
3. **Remitos manuales sin orden**: con el bloqueo, un remito cargado a mano no se
   puede emitir a F150 porque no tiene precio congelado. Resolverlo requiere
   persistir el precio en `RemittanceItem`, que es una migracion y quedó fuera de
   este PR.
4. **`rh1..rh4`, `unidad_dgr` y `codigo`**: se siguen leyendo del maestro vivo y
   tienen el mismo desvío historico que el precio. No se tocaron para no ampliar
   el alcance.
5. **Fecha de entrega**: hoy la fecha del registro es `remittance.date`; el issue no
   pide cambiarla y no se modifico.
