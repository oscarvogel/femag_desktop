# La base del cliente: por que el F150 no sale y que hay que hacer

Registro del 20/10/2026. Diagnostico hecho sobre el **dump real de la base del
cliente** (`Downloads/femag_desktop.sql`, export de HeidiSQL de MySQL 5.7 en
Windows), restaurado en una base de pruebas aparte (`femag_demo_726` en el
MariaDB de WSL) para no tocar ni la base de desarrollo ni la del cliente.

## Que tiene la base del cliente

| tabla | filas |
|---|---|
| `dgrlocality` | 3975 |
| `dgrcountry` | 255 |
| `dgrprovince` | 24 |
| `client` | 884 |
| `clientaddress` | 880 |
| `carrier` | 77 |
| `driver` | 144 |
| `product` | 38 |
| `truck` | 105 |
| `remittance` | 1 (`REM-00000001`) |
| `loadorder` | 89 |
| `f150batch` | 0 |

El origen DGR **ya esta configurado** (`f150.origin` = CAPIOVI `0015`, el
20/10 a las 17:02) y el remito `REM-00000001` existe con sus 3 items
(fecula, destino COLON, Entre Rios).

## El problema: los maestros son anteriores a la referencia DGR

El historial de `importbatch` lo dice:

| id | fecha | que se importo |
|---|---|---|
| 1 | 2026-08-06 18:13 | los maestros (846 clientes creados) |
| 2 | 2026-08-26 16:31 | los maestros de nuevo |
| 3 | 2026-10-20 16:30 | la **referencia DGR** (3975 localidades) |

Las importaciones 1 y 2 son de **agosto**: en ese momento no habia ninguna
localidad DGR cargada, asi que `_find_locality` devolvia `None` y **todos** los
enlaces DGR quedaron en `NULL`, sin error ni aviso. La importacion 3 (la
referencia DGR) llego despues, pero **nadie volvio a importar los maestros**,
y la referencia sola no completa los maestros: el reimport es lo unico que los
completa.

Como quedo:

| dato | valor |
|---|---|
| transportistas con localidad DGR | **0 de 77** |
| choferes con localidad DGR | **0 de 144** |
| direcciones de cliente con localidad DGR | **0 de 880** |
| productos con rubros y unidad DGR | **0 de 38** |
| camiones con tipo de chasis | **0 de 105** |
| transportistas con tipo | **0 de 77** |
| transportistas con domicilio | **0 de 77** |

Por eso el remito `REM-00000001` estava con **15 problemas**:

```
destino: falta localidad DGR
transportista: falta tipo
transportista: falta codigo
transportista: falta domicilio
transportista: falta localidad DGR
camion: falta tipo de chasis
camion: falta tipo de acoplado
chofer: falta domicilio
chofer: falta localidad DGR
detalle: BOLSAS DE FECULA NATIVA sin rubros DGR
detalle: BOLSAS DE FECULA NATIVA sin unidad DGR
detalle: BOLSAS FECULA X 10KG. sin rubros DGR
detalle: BOLSAS FECULA X 10KG. sin unidad DGR
detalle: PACK 10 UNID. FECULA  X 1 KG sin rubros DGR
detalle: PACK 10 UNID. FECULA  X 1 KG sin unidad DGR
```

Es el mismo sintoma del 19/10 en la base de desarrollo (#688), y la causa es la
misma: **maestros importados antes de que existiera la referencia DGR**.

## La prueba: el setup contra la base del cliente

Con el dump restaurado, se corrio el setup de #744
(`scripts/setup_f150_data.py`) con los DBF de la fabrica:

```
referencia DGR: 3975 localidades, 255 paises, 24 provincias
transportistas: 73 de 77 con localidad DGR
choferes: 140 de 146 con localidad DGR
direcciones de cliente: 871 de 895 con localidad DGR
productos: 31 de 38 con rubros y unidad DGR
camiones: 105 de 107 con tipo de chasis
origen DGR: 0015 CAPIOVI (14 ARGENTINA)
remitos: 1 listos para generar F150, 0 bloqueados
```

```
remito REM-00000001: 15 problemas  ->  0 problemas
```

Con el mismo exit code de antes: 0, con un solo aviso (el chofer `0090` del
legacy, sin nombre ni CUIT, que no entra nunca).

## Que hay que hacer en la maquina del cliente

**La app tiene que estar actualizada.** Con la version anterior a #746, la
importacion **pisa** lo que el operador edito a mano (nombre, telefono,
domicilio, rubros) y con la version nueva no: la importacion solo completa lo
que esta vacio.

El release con #746, #748 y #749 ya se publico y **ya esta en produccion**
(version `2026.10.21.09.36.40`, SHA256
`59fbbb0fd9fb5118f0f88ecd47229e24ec2c79292f5464aab7c6cea832b624df`):

<https://github.com/oscarvogel/vogel-releases/releases/download/latest/FEMAG_Desktop_Produccion_Setup.exe>

Esa version trae las tres cosas que hacen falta para este paso:

- **#746**: la importacion no pisa lo que el operador edito a mano.
- **#748**: la pantalla *Importacion -> Importacion DBF* ya no se aplasta en
  pantallas bajas (la del cliente mide 1638x969). Antes las filas del formulario
  quedaban superpuestas y no se podia elegir ningun archivo.
- **#749**: *Ingreso de materia prima* y *Partes de produccion* tampoco se
  aplastan, y sus textos largos ya no cortan la pantalla.

asi que hay dos caminos:

- **Con la app actualizada** (recomendado): se instala el instalador de arriba y
  la pantalla *Importacion -> Importacion DBF* hace el trabajo, con el orden ya
  corregido y sin pisar lo editado.
- **Sin app actualizada**: se puede correr el comando a mano, pero con el
  importador viejo, que **si** pisa lo editado. Ojo con esto.

Los pasos con la app actualizada:

1. Abrir **Importacion -> Importacion DBF**.
2. Poner los cuatro DBF de maestros de la carpeta del legacy de la maquina del
   cliente: `clientes.dbf`, `transporte.dbf`, `chofer.dbf`, `productos.dbf`.
3. **Importar DBF**. La referencia DGR ya esta, asi que no hace falta
   importarla de nuevo (si se importa, es idempotente).
4. Abrir el remito y generar el F150: deberian dar 0 problemas.

Si en la maquina del cliente hay Python y el repo, el comando hace los tres
pasos y ademas verifica:

```powershell
python scripts/setup_f150_data.py --dbf-dir "C:\ruta\del\legacy\data"
```

Por defecto hace las cosas en modo `patch`: **solo completa lo vacio** y
respeta lo que el operador edito. Con `--mode overwrite` el legacy manda en
todo, que es lo que hay que usar para una recarga deliberada, no para una
base viva.

## La importacion no pisa lo que el operador edito (#746)

La base del cliente es una base **viva**. Antes de #746, la importacion
escribia todos los valores del legacy encima de la fila existente, asi que una
reimportacion deshacia los cambios del operador.

Ahora hay dos modos:

- **`patch` (por defecto)**: solo completa los campos **vacios**. Lo que el
  operador corrigio a mano se respeta.
- **`overwrite`**: el legacy manda en todos los campos, como antes. A
  proposito, para una carga limpia o una recarga deliberada.

De algunos campos la importacion es **duena** y los corrige siempre, porque el
operador no los edita en el ABM y son los que el F150 exige: la localidad DGR
del transportista, del chofer y de la direccion del cliente, el tipo de chasis
y de acoplado del camion, y los rubros y la unidad DGR de los productos.

Comprobado contra esta misma base (restaurada del dump, con ediciones
simuladas del operador):

| edicion del operador | despues del setup |
|---|---|
| telefono del cliente `343-500-0000` | `343-500-0000` (respetado) |
| razon social del cliente | respetada |
| domicilio del transportista | respetado |
| domicilio del cliente | respetado |
| rubro DGR del producto (campo de la importacion) | corregido al del legacy |
| localidad de la direccion (vacia) | completada (COLON) |
| remito `REM-00000001` | **14 problemas -> 0** |

## Pendientes

1. **#743**: el domicilio de entrega del cliente sale del fiscal. El legacy trae
   los dos separados (`C_DOMI`/`C_LOCAL` y `DOMICILIO`/`LOCALIDAD`) y 21 de 663
   clientes tienen las dos localidades distintas.
2. **8 clientes con CUIT repetido y localidades distintas** en el legacy: el
   importador fusiona las dos filas y gana la ultima, asi que el destino del
   F150 de esos clientes depende del orden del DBF. Hay que revisarlos a mano.
3. **Los remitos del legacy (`remito.dbf`, `detaremi.dbf`) no se importan.** En
   la base del cliente hay 1 remito, cargado a mano en FEMAG. Si hay remitos
   pendientes de emitir en el legacy, la migracion de remitos es un issue
   aparte.
4. **Verificacion dentro de la app**: la pantalla de importacion no dice si la
   base quedo lista para emitir. El servicio de #744 ya la tiene
   (`F150SetupService.verify()`): agregar un boton "Verificar base para F150"
   seria un release nuevo, pero no es bloqueante.
5. La base de pruebas `femag_demo_726` quedo con el dump del cliente mas la
   importacion. Se recrea vacia en cada promocion, asi que no afecta el flujo.
