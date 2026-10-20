# #688 - La reimportacion de los maestros del legacy completa los datos del F150

Registro de la operacion del 20/10/2026: por que el F150 salia bloqueado, que se
corrijo, que quedo importado en la base de produccion y que queda pendiente.

## El sintoma

El remito `0001-00010922` (REM-00000001) no dejaba generar el F150. El dialogo
de validacion listaba 16 problemas:

```
falta origen DGR (parametro f150.origin)
destino: falta localidad DGR
transportista: falta tipo
transportista: falta codigo
transportista: falta domicilio
transportista: falta localidad DGR
camion: falta tipo de chasis
camion: falta tipo de acoplado
chofer: falta domicilio
chofer: falta localidad DGR
detalle: BOLSAS FECULA NATIVA X 1 KG. sin rubros DGR
detalle: BOLSAS FECULA NATIVA X 1 KG. sin unidad DGR
detalle: BOLSAS FECULA X 10KG. sin rubros DGR
detalle: BOLSAS FECULA X 10KG. sin unidad DGR
detalle: PACK 10 UNID. FECULA X 1 KG sin rubros DGR
detalle: PACK 10 UNID. FECULA X 1 KG sin unidad DGR
```

## La causa

La base de produccion (`femag_desktop` en MySQL/WSL) se restauro desde un dump
el 19/10 y con ella se perdio la importacion de la **referencia DGR**:

| tabla | filas |
|---|---|
| `dgrlocality` | 0 |
| `dgrcountry` | 0 |
| `dgrprovince` | 0 |

Sin `dgrlocality`, el importador de los maestros no puede resolver la localidad
de ningun registro: `_find_locality` devuelve `None` y todos los enlaces DGR
quedan en `NULL` **de forma silenciosa**, sin error ni aviso.

Los maestros (transportistas, choferes, productos, camiones) seguian cargados,
pero con `locality`, `tipo`, `codigo`, `address`, `rh1..rh4`, `unidad_dgr` y
`chassis_type` en `NULL`: se importaron el 6/8 y el 26/8 con un importador
anterior al que los trae.

## Los dos bugs de fondo

### #688 - `clientaddress.locality` no se backfillea al reimportar

`ClientService.ensure_imported_shared_address` **reutiliza** la direccion que ya
existe cuando el cliente ya tenia una, y al reutilizarla no toca `locality`. Las
direcciones importadas cuando `dgrlocality` estaba vacia quedan con
`locality_id = NULL` y el F150 no puede emitir: el destino sale sin provincia
ni pais.

El backfill quedo **en el importador** y no en el servicio: el servicio lo
comparte con el ABM de clientes (#264) y ahi una reimportacion no tiene por que
tocar lo que el operador edito a mano. En el importador el backfill es
explicito, cuenta lo que hizo (`localidad_backfill`, `localidad_actualizada`) y
el legacy manda cuando el dato cambio.

### #741 - el importador le sacaba el CUIT a otro cliente

`client.cuit` es unico y el legacy tiene filas que comparten CUIT (el mismo
cliente con dos codigos). La fila que ya existia por `source_id` recibia el CUIT
de la otra y el guardado reventaba:

```
peewee.IntegrityError: (1062, "Duplicate entry '30716551780' for key 'client_cuit'")
```

Como `import_rows` solo captura `ValueError`, el `IntegrityError` abortaba
**toda** la importacion: camiones, choferes, productos y direcciones se
quedaban sin importar.

Ahora el CUIT no se le saca a quien lo tiene (se avisa con
`client_cuit_taken_by_another_row`) y un choque puntual con un indice unico se
anota como error de esa fila y la importacion continua.

## La operacion

1. Respaldo de la base: `backups/femag-backup-20261020-172128.sql`.
2. Importacion de la referencia DGR con los DBF de la fabrica.
3. Reimportacion de los maestros: clientes, transportistas, choferes y productos.
4. Origen DGR: **CAPIOVI** (`0015`), el `LOCORIGEN` del `param.dbf` del legacy,
   configurado con `F150BatchService.set_origin` (el mismo camino que usa la
   pantalla "Configurar origen DGR").

## Estado de la base

| dato | antes | despues |
|---|---|---|
| `dgrlocality` | 0 | 3975 |
| `dgrcountry` | 0 | 255 |
| `dgrprovince` | 0 | 24 |
| transportistas con localidad | 0 | 73 de 77 |
| choferes con localidad | 0 | 140 de 146 |
| direcciones con localidad | 0 | 871 de 894 |
| productos con rubros DGR | 0 | 33 de 38 |
| productos con unidad DGR | 0 | 31 de 38 |
| camiones con tipo de chasis | 0 | 107 de 109 |

El remito `0001-00010922` paso de **16 problemas a 0** y el F150 se genera con la
cabecera C1 completa.

## Validaciones

```
git diff --check                                  -> limpio
python -m pytest                                  -> 1821 passed, 3 skipped
python -m compileall app                          -> OK
python -m app.main --smoke                         -> FEMAG smoke OK
FEMAG Desktop.exe --production-health-check       -> FEMAG production health OK
```

Contra la base real se reprodujeron los dos bugs **antes** de corregirlos (con
rollback, sin dejar rastro) y despues se verifico que la importacion de los
cuatro DBF termina sin errores y es idempotente: `localidad_backfill: 0`,
`localidad_actualizada: 10`.

## Publicacion

- PR #742 mergeado en `main` (`97c35a6`).
- Candidate `2026.10.20.15.56.57` publicado y promovido a produccion (run
  `39480695186`). `latest.json` con sha256
  `cda8a0a132ce2e17a607fdd7fe07e63ea369474021a761bb934a6bd858e5e8a9`.

## Pendientes

1. **#743**: el domicilio de entrega del cliente sigue saliendo del domicilio
   **fiscal**. El legacy trae los dos separados (`C_DOMI`/`C_LOCAL` y
   `DOMICILIO`/`LOCALIDAD`) y 21 de 663 clientes tienen las dos localidades
   distintas: para esos, el destino del F150 va a la localidad equivocada.
2. **Al restaurar la base desde un dump**, verificar que el dump incluya
   `dgrlocality`, `dgrcountry` y `dgrprovince`. Sin esas tres tablas el F150
   vuelve a quedar bloqueado para todos los remitos, y la app no avisa: el
   fallo es silencioso.
3. **Orden al importar**: la referencia DGR primero, los maestros despues. Al
   reves, los maestros se importan sin ninguna localidad y quedan en `NULL`.
4. Los DBF de la fabrica se copian a `C:\Programacion\dante\sistema\contable\data`
   y **cambian** (el 20/10 `chofer.dbf` paso de 144 a 149 filas y trajo el
   domicilio y la localidad de choferes que antes venian vacios). Releer los
   DBF antes de importar.
