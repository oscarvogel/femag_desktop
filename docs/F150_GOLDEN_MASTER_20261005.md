# F150 contra la muestra real - informe comparativo (#681)

Fecha: 2026-10-09
Rama: `fix/f150-golden-master-20261005` (base `rebuild/issue-11-f150-clean`, commit `19a70af`)

## 1. Muestra usada como autoridad

**La muestra real del issue, `F.150-05-10-2026B.TXT` (05/10/2026), fue provista
y validada.** Esta es la seccion que quedaba pendiente en la primera entrega.

Como segunda referencia se uso el archivo real del mismo generador que la
empresa tiene en `C:\Programacion\dante\contable`: **119 archivos F150 de
produccion de 2019**, 314 registros `C` y 339 registros `D`.

| | Muestra del issue | Corpus 2019 |
|---|---|---|
| Archivo | `F.150-05-10-2026B.TXT` | 119 archivos `F150-AAAAMMDD[ABC].TXT` |
| Bytes | 2680 | 2642 (`F150-20190708.TXT`) |
| Registros | **5 `C` + 6 `D`** | 314 `C` + 339 `D` |
| Renglones por remito | 1, 2, 1, 1, 1 | hasta 7 |
| Termina con CRLF | **no** | no (119/119) |

La muestra y el corpus coinciden en todos los puntos del contrato, incluida la
forma (5 `C` + 6 `D` con un remito de dos renglones) que describe el issue.

## 2. Metodo

1. Se parsearon la muestra real y los 119 archivos reales a snapshots
   `F150Remittance`, se re-codificaron con `F150Encoder` y se compararon
   **byte a byte**.
2. Se anonimizo la muestra real en `tests/fixtures/f150/golden_master_sample_20261005.*`.
3. En CI quedan dos validaciones independientes: el codificador contra el
   golden master, y un formateador del contrato escrito a mano que no usa
   `F150Encoder`.

**Resultados:**

- **Muestra real `F.150-05-10-2026B.TXT`: identico byte a byte (2680 bytes).**
- **Corpus 2019: 119 de 119 archivos identicos byte a byte.**

### Que se anonimizo y que no

Del golden master versionado se sustituyeron **solo los 19 campos de identidad
de la cabecera** (CUIT de transporte/chofer/cliente, nombres, domicilios, DNI y
patentes). **Los seis renglones son identicos byte a byte al archivo real**, con
sus codigos DGR, cantidades, precios e importes (`28,050.00`, `1,683,000.00`,
`16,601.00`, `1,743,105.00`, `19,814.00`, `297,210.00`, `33,201.00`,
`1,992,060.00`, `43,000.00`, `2,580,000.00`, `9,000.00`, `7,560,000.00`), y los
numeros de formulario de 8 digitos (`00010874` a `00010878`).

Los caracteres CP1252 del original (`°` cinco veces, `º` cinco veces) se
conservan en el fixture para que CI siga ejercitando la codificacion.

El original **no se versiona**: quedo fuera del repositorio por `.gitignore`
(`docs/F.150-*.TXT`) y se compara en la maquina del operador con
`scripts/compare_f150_golden_master.py`, que reporta offset, linea, campo y una
huella del valor sin exponer PII.

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

**La muestra real del issue confirma los seis puntos corregidos**: el campo de 50
espacios en los 6 renglones, el punto de venta `0001`, los numeros de formulario
de 8 digitos (`00010875`), la ausencia de CRLF final, el CP1252 con `°` y `º`, y
el formato `28,050.00` / `1,683,000.00` citado en el issue.

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
| `python -m pytest tests/test_f150_*.py tests/test_issue_40{3,4b,5}_*.py` | **47 passed** |
| `python -m pytest` (rama de este PR) | 799 passed, 15 failed |
| `python -m pytest` (base del PR, worktree limpio) | 773 passed, 15 failed |
| `python -m pytest` (`main`, worktree limpio) | 1499 passed, 7 failed |
| `python -m compileall -q app` | OK |
| `python -m app.main --smoke` | `FEMAG smoke OK` |
| `git diff --check` | OK |
| `python scripts/verify_f150_corpus.py` | **119/119 identicos** |
| Round-trip contra `F.150-05-10-2026B.TXT` | **identico byte a byte** |

### El PR no introduce regresiones

La rama del PR agrega **26 pruebas que pasan** (773 -> 799) y conserva
**exactamente los mismos 15 fallos** que la base. Ninguno toca F150.

### Los 15 fallos son de una base atrasada, no de este PR

`rebuild/issue-11-f150-clean` esta **412 commits y un mes atrasada** de `main`
(ultimo commit 2026-09-08 contra 2026-10-06). Al correr en `main` esos mismos
archivos de prueba dan **1 solo fallo**:

| | base del PR | `main` |
|---|---|---|
| `test_remittance_service` | 5 fallos | pasa |
| `test_load_order_returns` | 2 fallos | pasa |
| `test_load_order_return_credits` | 3 fallos | pasa |
| `test_payment_receipts` | 1 fallo | pasa |
| `test_account_statement_printing` | 1 fallo | pasa |
| `test_customer_ledger_ui` | 2 fallos | pasa |
| `test_update_service` | 1 fallo | **1 fallo** |

O sea: **14 de los 15 ya estan resueltos en `main`**. El unico que sigue rojo
en `main` es `test_update_service::test_fetch_update_info_returns_newer_valid_manifest`,
que no tiene relacion con F150.

Esto no se corrige en este PR, pero condiciona el avance: antes de llevar el
trabajo F150 hacia `main` hay que rebasar o mergear `main` en la rama y volver a
correr la suite.

## 6. Estado de la habilitacion

- **Compatibilidad tecnica del formato**: verificada byte a byte contra la
  muestra real y contra 119 archivos reales.
- **Habilitacion fiscal**: **pendiente de homologacion con el destinatario**.
  Que el archivo sea identico a la muestra demuestra compatibilidad con ese
  ejemplo, no que el organismo receptor acepte todos los casos.

## 7. Pendientes que requieren definicion de FEMAG

1. **`B` del nombre de archivo**: la muestra se llama `F.150-05-10-2026B.TXT` y
   el corpus usa `F150-AAAAMMDD[ABC].TXT`. En el corpus conviven
   `F150-20190412.TXT` y `F150-20190412A.TXT`, y `20191111`, `20191111A`,
   `20191111B`, lo que sugiere un correlativo por reemision del mismo dia. La
   muestra confirma el formato del contenido pero **no explica que significa `B`**,
   asi que **no se asumio** ni se implemento, y **no se cambio** el nombre que
   sugiere la UI (`f150-YYYYMMDD.TXT`). Queda pendiente confirmarlo con quien
   recibe el F150.
2. **Remitos manuales sin orden**: con el bloqueo, un remito cargado a mano no se
   puede emitir a F150 porque no tiene precio congelado. Se mantiene el bloqueo
   por ahora y se sigue en issue propio. **No se reconstruyen importes con
   precios actuales.**
3. **`rh1..rh4`, `unidad_dgr` y `codigo`**: se siguen leyendo del maestro vivo y
   tienen el mismo desvio historico que el precio. No se tocaron.
4. **Fecha de entrega**: hoy la fecha del registro es `remittance.date`; no se
   modifico.
