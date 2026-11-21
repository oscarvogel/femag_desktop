# Las dos bases legacy y la cuenta de los proveedores

Este documento deja registrado lo que hay que saber antes de tocar la base
legacy de la fábrica. Es la referencia de la issue #937 (cuenta corriente de
productores/colonos).

## Hay dos bases, y se parecen en el nombre

El legacy de FEMAG son **dos bases MySQL distintas**, cada una con su archivo
de dump y su contenido:

| Base | Archivo de dump | Qué tiene | Fin del histórico |
|---|---|---|---|
| `femag` | `femag.sql` | **Comercial**: `articulo`, `remito`, `cabfact`, `clientes`, `proveedor` (con CUIT y retenciones), `ctacte`/`pctacte` (cuenta corriente **de clientes**) | 26/12/2019 |
| `femagfab` | `femag_fab.sql` | **Fábrica**: `proveedo` (maestro de colonos), `movi` (tickets de materia prima), `documentos` (pagarés), `movcaja`, `productos` | vivo (datos al 20/11/2026) |

**La cuenta corriente de los productores/colonos vive en `femagfab`.** La base
comercial no tiene `movi`, ni `documentos`, ni `proveedo`: no tiene de dónde
sacar esa posición, y su histórico está parado en 2019.

Ojo con la trampa: los dos archivos se llaman parecido y una copia "actualizada"
puede pisar la buena. Para saber cuál es cuál, mirá el esquema y la fecha
máxima, no el nombre:

```bash
# qué base es
grep -c "CREATE TABLE" <dump>.sql
grep "CREATE TABLE IF NOT EXISTS" <dump>.sql | head -5
# hasta cuándo llega
grep -o "2026-[0-9][0-9]-[0-9][0-9]" <dump>.sql | sort -u | tail -1
```

## La moneda es ARS, no guaraní

El legacy no tiene columna de moneda: es una sola moneda, la de la empresa, que
es de **Misiones, Argentina**. Evidencia verificada:

- La tabla `param` declara `EMPRESA = GRAEF HNOS S.R.L.`,
  `LOCALIDAD = CAPIOVI`, `DOMICILIO = Lote 75 "C", secc 2° Col. San Alberto`,
  teléfono `(03743) 476960`.
- Las localidades de los 1.142 proveedores de `proveedo` son de Misiones:
  Garuhapé, Puerto Rico, Jardín América, Capioví, Montecarlo, Wanda,
  Ruiz de Montoya, Aristóbulo del Valle, Salto Encantado, Dos de Mayo,
  25 de Mayo, San Vicente, Campo Grande, Puerto Piray, Aurora, San Pedro,
  San Alberto.
- Los CUITs de la base comercial usan prefijos argentinos (20-, 23-, 24-, 27-,
  30-, 33-): 1.054 CUITs, ninguno de otra jurisdicción.
- En el dump no aparece ningún token `GS`, `PYG`, "guaraní" ni "paraguay".
- FEMAG Desktop usa `ARS` por defecto en la cuenta corriente de clientes
  (`app/models/accounting.py`).

## La posición con los productores tiene dos lados

El legacy **no guarda el signo de la deuda**: guarda un `SALDO` en el ticket y
otro en el pagaré, y los suma. Pero no son la misma cosa:

- El **ticket** (`movi`) con saldo pendiente es lo que **la empresa le debe al
  productor**: la materia prima entró y todavía no se le pagó.
- El **pagaré** (`documentos`) con saldo pendiente es lo que **el productor le
  debe a la empresa**: un anticipo que se descuenta del pago de los tickets.

Sumarlos sin signo —lo que hace el ERP, que muestra 777.463.536,77 ARS— da un
número que no significa nada. Medido sobre el dump del 20/11/2026:

| | Legacy (suma de saldos) | Importado en FEMAG Desktop | Productores |
|---|---:|---:|---:|
| **A pagar** (tickets de materia prima impagos) | 746.092.698,72 | 754.559.253,72 | 31 personas (32 códigos) |
| **A cobrar** (anticipos en pagarés) | 31.370.838,05 | 30.029.752,60 | 40 personas (43 códigos) |
| **Neto a pagar** | 714.721.860,67 | 724.529.501,12 | 68 personas |
| Excluido por falta de datos (queda registrado) | — | 1.696.085,45 | 2 tickets + 4 pagarés |

La diferencia entre el legacy y lo importado está explicada: 6 tickets con el
saldo corregido (+8.821.555) menos 6 documentos excluidos.

Otros números del mismo corte:

| | Monto (ARS) |
|---|---:|
| Todo lo que la empresa debe es de 2026 | 754.559.253,72 (100%) |
| Las dos cooperativas más grandes | 562.881.842,24 (74,6% de lo que se debe) |
| Tickets pendientes **sin ningún egreso de caja** que los cancele | 750.429.590,57 (224 de 228 tickets) |

El cruce con la caja es el dato más fuerte: de los 228 tickets que el legacy
marca impagos, **224 no tienen ningún pago registrado en `movcaja`** —ni por
número de ticket ni por fecha e importe. Eso no prueba que no se hayan pagado:
prueba que el legacy no lo registró. Las dos cooperativas, que concentran el
74,6% de lo que la empresa debe, son justo las que no tienen ese registro.

## Los siete problemas del legacy

1. **No hay libro de movimientos.** La tabla `femagfab.movimientos` existe y
   está **vacía**: nunca se escribió. El saldo se recalcula mutando `SALDO`.
2. **No hay imputación pago↔documento.** En `movcaja` el `detalle` es texto
   libre ("Descuento aplicado"): no dice qué documento canceló.
3. **6 tickets con el `SALDO` mal guardado**: tienen el precio por tonelada en
   vez del total (`SALDO = PRECIO`).
4. **101 de 139 pagarés con `SALDO ≠ IMPORTE`**, sin estado ni fecha de
   cancelación; 132 de 139 con `CONCEPTO` NULL.
5. **126 tickets con `FECHA = 2002-01-01/02`** que en realidad son de junio
   2026 (bloque `COMP=000000046624`..`000000046750`).
6. **El productor no tiene identidad**: `proveedo` se identifica con un código
   de 4 caracteres, sin DNI ni CUIT, y con 23 nombres duplicados.
7. **No hay pagos parciales**: ningún ticket tiene `0 < SALDO < importe`. El
   legacy o paga el ticket entero o lo deja entero. Eso es lo que hace
   confiable la corrección del punto 3, y es una comprobación del código, no
   un supuesto.

## La política de importación (issue #939)

Se importa **solo lo confiable**, y lo que queda afuera **queda registrado**
en `supplier_document_exclusion` con su monto, su motivo y su detalle.

Los tickets y los pagarés se importan en la misma tabla pero **no significan lo
mismo**: el ticket pendiente es lo que la empresa debe, el pagaré pendiente es lo
que el productor debe. `SupplierDocument.kind` es lo que separa los dos, y todo
el que arma la posición tiene que sumarlos con signo.

| Documento | Regla | Filas |
|---|---|---:|
| Ticket (`movi`) | `SALDO != 0` y `TOTALK > 0` y `PRECIO > 0` | 228 |
| Ticket | saldo corregido (`SALDO == PRECIO`) → entra con el importe calculado | 6 de las 228 |
| Ticket | sin kilos o precio utilizable → **fuera** | 2 |
| Ticket | `SALDO = 0` → ya pagado, no es deuda | 5.084 |
| Pagaré (`documentos`) | `0 < SALDO <= IMPORTE` → anticipo a favor de la empresa | 49 |
| Pagaré | `SALDO < 0` (sobrepago) o `SALDO > IMPORTE` → **fuera** | 4 |
| Pagaré | `SALDO = 0` → ya pagado | 86 |

Las fechas heredadas se resuelven por **interpolación**: el `COMP` es
correlativo y sigue el orden de carga, así que los tickets vecinos con fecha
confiable acotan la fecha real dentro de una ventana. Los documentos
importados quedan con `date_inferred = True` y con la ventana guardada.

## Dónde está cada cosa

| Qué | Dónde |
|---|---|
| Issue de tracking | #937 |
| Maestro de proveedores (etapa 1) | #938 · PR #942 |
| Documentos de la cuenta corriente (etapa 2) | #939 · PR #943 |
| Libro de movimientos (etapa 3) | #940 |
| Pantalla de posición con el productor (etapa 4) | #941 |
| Importador de receipts que ya existía | `app/importers/femagfab.py` |
| Servicio de importación de documentos | `app/services/supplier_document_import_service.py` |
| Modelos | `app/models/suppliers.py` |
| Auditoría del legacy VFP | `docs/auditoria_adelantos_materia_prima_vfp.md` |
| Análisis de producción y stock legacy | `docs/ANALISIS_LEGACY_PRODUCCION_STOCK.md` |

La conexión a `femagfab` usa las **mismas credenciales** que la base de FEMAG
Desktop: `FemagFabSource` solo cambia el schema de origen. Es **solo lectura**:
nada del legacy se escribe desde FEMAG Desktop.
