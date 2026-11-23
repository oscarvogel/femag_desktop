# #946 — Choferes y transportistas: Localidad DGR y domicilio fiscal (Rentas), y aviso previo del F150

## Contexto

Cristina (operadora de planta) reportó tres cosas juntas, con capturas del ABM de
Choferes y de la ficha del chofer:

1. En la **ficha** del chofer GIMENEZ JORGE ARIEL (ID 149) la fila **Localidad DGR**
   dice *"Sin asignar"*, aunque el domicilio está cargado (`L. N. ALEM`).
2. En el **formulario de edición** del chofer **no hay ninguna celda** para cargar
   *"el domicilio que figura en Rentas"*. El único campo de domicilio dice
   *"Lo que va al F150"*, que para la operadora es otra cosa.
3. Al **generar el F150** el flujo no avisa que al chofer le falta el dato:
   - el remito se emite y aparece el diálogo de guardado del TXT;
   - el TXT **no** se genera, pero el error sale recién después de elegir la
     ruta y dice *"Remito 0001-712: chofer: falta localidad DGR"*, que no dice
     dónde se corrige (el único mensaje de concurrencia, *"El F150 cambió antes
     de generarse"*, queda para otro caso y se presta a confusión);
   - al volver al remito, el error vuelve a aparecer contra el domicilio del
     chofer, aunque el domicilio **sí** está cargado;
   - la parte de Rentas (localidad DGR) nunca sale.

## Comportamiento actual

- `Driver` y `Carrier` ya tienen `locality` (FK nullable) y `address`
  (`app/models/masters.py:237` y `:270`). El importador legacy los puebla
  (`chofer.dbf`/`transporte.dbf` → `DOMICILIO` + `LOCALIDAD`,
  `app/importers/legacy_dbf.py:595`).
- La ficha muestra `Localidad DGR` y `Domicilio`
  (`app/ui/master_detail_dialogs.py:760` y `:873`).
- **El formulario de edición no tiene ni localities ni domicilio fiscal**
  (`app/ui/master_abm.py:1247` para transportista, `:1318` para chofer): no hay
  forma de asignar la localidad desde la UI.
- El F150 exige la localidad del chofer y del transportista
  (`app/services/f150_batch_service.py:523` y `:510`): sin ella la generación
  falla. El operador que ve *"chofer: falta localidad DGR"* **no tiene dónde
  corregirlo**: la pantalla F150 solo permite corregir el **destino** del
  cliente (`F150DgrCorrectionService`), no el chofer ni el transportista.
- El flujo de emisión (`app/ui/remittances.py:1106`) abre el diálogo de guardado
  **antes** de validar; el error aparece después de elegir la ruta.

## Comportamiento esperado

1. El ABM de Choferes y de Transportistas tiene celda **Localidad DGR**
   (selector buscable) y celda **Domicilio fiscal (Rentas)**.
2. El F150 usa el **domicilio fiscal (Rentas)** del chofer y del transportista;
   si no está cargado, usa el domicilio actual como respaldo (regla ya escrita
   para los clientes en #792).
3. El F150 **avisa antes** de pedir la ruta de guardado, diciendo qué falta, de
   quién, y dónde corregirlo. El mensaje de datos faltantes no se presenta como
   un cambio concurrente.

## Archivos o áreas probablemente involucradas

- `app/models/masters.py` (columna nullable nueva en `Driver` y `Carrier`).
- `app/ui/master_abm.py` (`CarrierEntryDialog`, `DriverEntryDialog`).
- `app/ui/master_detail_dialogs.py` (fichas de transportista y chofer).
- `app/ui/dgr_locality_combo.py` (selector buscable, ya existe).
- `app/services/f150_batch_service.py` (domicilio efectivo y validación).
- `app/ui/remittances.py` y `app/ui/f150.py` (aviso previo y mensaje).
- `app/services/master_service.py` (alta de chofer/transportista).

## Criterios de aceptación

- [ ] El ABM de Choferes tiene combo **Localidad DGR** buscable y campo
      **Domicilio fiscal (Rentas)**; los carga, los guarda y los relee al editar.
- [ ] El ABM de Transportistas tiene las mismas dos celdas.
- [ ] La ficha de chofer y de transportista muestra Localidad DGR, domicilio
      fiscal y el domicilio vigente.
- [ ] El F150 escribe el domicilio fiscal del chofer y del transportista; si no
      hay domicilio fiscal, escribe el domicilio actual (sin regresión).
- [ ] La validación del F150 exige el domicilio **efectivo**: un chofer con
      domicilio fiscal cargado y sin domicilio actual no queda bloqueado, y un
      chofer sin ninguno de los dos sigue bloqueado nombrando el campo.
- [ ] La generación avisa **antes** del diálogo de guardado qué falta, con el
      nombre del chofer/transportista y el campo a completar.
- [ ] El mensaje de datos faltantes no se presenta como un cambio concurrente.
- [ ] Tests: ABM (chofer y transportista), prioridad fiscal/respaldo en el F150,
      validación con domicilio fiscal, y aviso previo.
- [ ] `python -m pytest`, `python -m compileall app` y smoke sin errores.

## Validaciones requeridas

- `python -m pytest -q`
- `python -m compileall app`
- `python -m app.main --smoke`
- Validación visual de las dos pantallas (1638x969 y 1366x768).

## Riesgos o dependencias

- **Área protegida (modelo de datos)**: se agregan dos columnas nullable
  (`fiscal_address`). `ensure_runtime_schema()` las crea sola sobre una base
  existente (precedente #545/#581). Nullable: no se pisa nada.
- **Área protegida (F150)**: el cambio de qué domicilio se escribe sigue la regla
  ya escrita en #792 para los clientes. **No** se modifica el layout DGR ni se
  reescriben presentaciones históricas.
- **Importación DBF**: fuera de alcance. El legacy `DOMICILIO` sigue entrando en
  el campo `address` actual (respaldo). Queda documentado como pendiente.
- No se toca Remitos reales ni la base de producción en este PR.

## Prioridad

P1 — el operador queda bloqueado para emitir F150 y no tiene dónde corregir el
dato.

---

# Bitácora de implementación

## Qué se cambió

| Pieza | Antes | Ahora |
|---|---|---|
| ABM Choferes | Transportista, Nombre, Camión habitual, Documento, Teléfono, Domicilio (*"Lo que va al F150"*) | + **Localidad DGR** (selector buscable) y + **Domicilio fiscal (Rentas)**; el domicilio actual queda rotulado como respaldo |
| ABM Transportistas | Nombre, CUIT, Teléfono, Domicilio | + **Localidad DGR** y + **Domicilio fiscal (Rentas)** |
| Ficha de chofer / transportista | Localidad DGR y Domicilio | + Domicilio fiscal (Rentas) y **Domicilio que va al F150** (el que se escribe en el TXT) |
| F150 (campos 13 y 31) | `address` del maestro | `fiscal_address` y, si está vacío, `address` |
| Validación del F150 | *"chofer: falta domicilio"* / *"chofer: falta localidad DGR"* | *"chofer: falta domicilio fiscal (Rentas) y no hay domicilio de respaldo — GIMENEZ JORGE ARIEL"* / *"chofer: falta localidad DGR — GIMENEZ JORGE ARIEL"* |
| Generación del F150 | El error salía **después** de elegir la ruta y decía *"El F150 cambió antes de generarse"* | El aviso sale **antes** de pedir la ruta y dice qué falta y dónde se corrige |

## Bugs que encontró el reporte

1. **El modelo tenía el dato y la UI no.** `Driver.locality` y `Carrier.locality`
   existen, la ficha los muestra, el importador los puebla… y el formulario de
   edición no tenía la celda. El dato era inaccesible para el operador.
2. **El F150 bloqueaba con un error sin salida.** La pantalla F150 solo sabe
   corregir el **destino** del cliente (`F150DgrCorrectionService`): no hay forma de
   corregir la localidad del chofer desde ahí. El operador veía el error y no
   tenía dónde arreglarlo. Eso es lo que reportaba Cristina como *"me dice error en
   el domicilio del chofer"* y *"no tengo ni una celdita"*.
3. **El aviso llegaba tarde y era inaccionable.** El error *"Remito 0001-712:
   chofer: falta localidad DGR"* salía **después** de que el operador eligiera
   dónde guardar el TXT, y no decía dónde corregir el dato. El mensaje de
   concurrencia *"El F150 cambió antes de generarse"* (que aparece cuando otro
   puesto modificó los datos entre la selección y la escritura) se prestaba a
   confusión. Ahora el aviso sale **antes** de pedir la ruta y nombra el campo
   faltante y el registro.
4. **El mensaje confundía domicilio con localidad.** Decía *"falta domicilio"*
   aunque el domicilio estaba cargado: lo que faltaba era la localidad DGR. Ahora
   los dos mensajes son distintos.

## Regla que se aplica

El F150 escribe el **domicilio fiscal (Rentas)** del chofer y del transportista; si
no está cargado, usa el domicilio actual como respaldo. Es la misma regla que
#792 ya fijó para los clientes (el F150 usa el domicilio fiscal y separa el de
entrega). La regla vive en un solo lugar: `effective_f150_address()` y la propiedad
`f150_address` de `Driver` y `Carrier`.

## Pendientes que quedan

1. **Importador DBF**: `DOMICILIO` de `chofer.dbf`/`transporte.dbf` sigue entrando al
   campo `address` (respaldo). Mapearlo a `fiscal_address` es área protegida: issue
   aparte.
2. **Validación contra la base real**: la regla se probó con escenarios SQLite
   controlados. Falta correrla contra el MySQL de producción con el chofer GIMENEZ
   JORGE ARIEL (ID 149) antes del deploy.
3. **Corrección desde la pantalla F150**: el botón *Corregir datos DGR* sigue
   corrigiendo solo el destino del cliente. Corregir el chofer desde esa pantalla
   queda para otro issue.
4. **Grilla de Maestros**: la grilla de choferes no muestra la localidad DGR, así que
   hay que abrir cada chofer para ver quién la tiene.
5. **Hallazgo colateral (no se toca en este PR)**: el combo de localidades del
   formulario de **Domicilios de cliente** (`ClientAddressEntryDialog`) se crea **sin
   opción vacía**, así que cuando el domicilio no tiene localidad el combo queda en la
   primera de la lista y se **guarda una localidad que el operador no eligió**. En este
   PR el parámetro nuevo `include_empty` queda en `False` para ese diálogo (no se
   cambia el comportamiento de una pantalla fuera del pedido), pero el bug sigue ahí:
   necesita su propio issue.

## Nota de entorno

En esta máquina el `python` del sistema tiene un paquete `tests` en
`%APPDATA%\Python\Python312\site-packages\tests` que tapa el directorio `tests/` del
repo y la suite aborta en la recolección (`ModuleNotFoundError: No module named
'tests.conftest'`). La suite se tiene que correr con el intérprete del proyecto:

```powershell
$env:QT_QPA_PLATFORM="offscreen"
.\.venv\Scripts\python.exe -m pytest -q
```
