# #744 - Un comando deja la base lista para generar el F150

Registro del 20/10/2026: por que la importacion del legacy quedava en tres pasos
sueltos que hay que acordarse, que hace el comando nuevo y como se validó contra la
base real.

## El problema

Dejar la base de produccion en condiciones de emitir un F150 son **tres pasos**, y
el orden importa:

1. importar la **referencia DGR** (paises, provincias, localidades, codigos);
2. importar los **maestros** del legacy (clientes, transportistas, choferes,
   productos);
3. dejar elegido el **origen DGR**, que vive en el parametro `f150.origin`.

El paso 1 tiene que ir antes que el 2 y el modo de falla es **silencioso**: sin
`dgrlocality` cargada, `_find_locality` devuelve `None` y todos los enlaces DGR de
los maestros quedan en `NULL` **sin error ni aviso**. Cuando la referencia se
importa despues, el reimport de maestros es lo unico que los completa, y hace
falta el backfill de #688 para las direcciones de cliente.

El paso 3 tampoco lo hacia ninguna parte de la aplicacion: el origen lo elige el
operador con el boton "Configurar origen DGR" de la pantalla. Sin el, el dialogo
de validacion del remito lista "falta origen DGR (parametro f150.origin)" y no deja
emitir.

El 19/10 la base de produccion se restauro desde un dump **sin las tres tablas de
referencia DGR** y con eso el F150 quedo bloqueado para todos los remitos (16
problemas en el remito `0001-00010922`). La causa y el arreglo estan en
`docs/issue-688-importacion-dgr-f150.md`; lo que faltaba era el comando que deja
todo eso en un paso reproducible.

## Que hace

`scripts/setup_f150_data.py`:

```powershell
python scripts/setup_f150_data.py --dbf-dir "C:\ruta\del\legacy\data"
```

Hace los tres pasos en orden y **al final verifica** que quedo todo en su lugar.
Opciones:

| opcion | que hace |
|---|---|
| `--dbf-dir` | carpeta con los DBF del legacy (obligatoria) |
| `--param` | ruta del `param.dbf`; por defecto, el de `--dbf-dir` |
| `--locality-code` | fuerza el origen; por defecto, sale del `LOCORIGEN` del `param.dbf` |
| `--encoding` | encoding de los DBF, por defecto `cp1252` |
| `--source-system` | identificador del sistema origen, por defecto `legacy_dbf` |
| `--skip-dgr` / `--skip-masters` / `--skip-origin` | saltea un paso |
| `--json` | salida en JSON |

El origen sale del `LOCORIGEN` del `param.dbf`, que es el dato real de la empresa:
el legacy guarda ahi la localidad desde la que salen los remitos (CAPIOVI, `2426`).
El codigo se busca en la referencia DGR recien importada y se configura con el
mismo camino que usa la pantalla ("Configurar origen DGR").

La **verificacion** final no se limita a decir que termino: cuenta y muestra

```
referencia DGR: 3975 localidades, 255 paises, 24 provincias
transportistas: 73 de 77 con localidad DGR
choferes: 140 de 146 con localidad DGR
direcciones de cliente: 871 de 894 con localidad DGR
productos: 31 de 38 con rubros y unidad DGR
camiones: 107 de 109 con tipo de chasis
origen DGR: 0015 CAPIOVI (14 ARGENTINA)
remitos: 1 listos para generar F150, 0 bloqueados
```

y el comando sale con codigo **1** cuando la base **no** puede emitir.

### Bloqueantes y avisos: no son lo mismo

El codigo de salida lo deciden los **bloqueantes**: no hay referencia DGR cargada,
no hay origen, no quedo ningun maestro, o hay remitos bloqueados.

Los **avisos** son cosas que conviene mirar pero que no impiden emitir, y se
muestran igual. El caso real: el legacy tiene un chofer (el `0090`, sin nombre y
sin CUIT) que no se puede importar nunca. Con el codigo de salida atado a los
avisos, el comando salia con 1 aunque la base quedara lista y el remito
estuviera para emitir: un instalador que ve un 1 cree que la instalacion fallo.
Por eso los avisos no voltean el resultado.

### El modo de falla silencioso queda bloqueado a proposito

Si la referencia DGR no queda cargada (no hay DBF, o la base no tiene localidades),
el setup **no importa los maestros**: los importaria sin localidad y sin avisar,
que es exactamente el fallo que dejo bloqueado el F150 el 19/10. En ese caso
avisa y sale con codigo 1.

## Validaciones

Contra la base real (`femag_desktop` en MySQL/WSL), con los DBF de la fabrica en
`C:\Programacion\dante\sistema\contable\data`:

```
python scripts/setup_f150_data.py --dbf-dir "...\sistema\contable\data"
```

- Primera corrida: la base quedo con 3975 localidades DGR, 255 paises, 24
  provincias, 890 clientes, 77 transportistas, 146 choferes, 38 productos,
  109 camiones y el origen en CAPIOVI (`0015`). El remito `0001-00010922` quedo
  **listo para generar F150, 0 bloqueados**.
- Segunda y tercera corrida (idempotencia): mismos numeros, exit code **0**.
- La corrida en modo texto (la que ve el operador) muestra el aviso de la fila
  que no entra y aun asi sale con codigo **0**.

```
git diff --check                        -> limpio
python -m pytest tests/test_f150_setup_service.py -> 9 passed
python -m pytest                        -> 1830 passed, 3 skipped
python -m compileall app                -> OK
python -m app.main --smoke              -> FEMAG smoke OK
```

## Los tres bugs que aparecieron al escribir el comando

### El generador de DBF de los tests

`dbfread` solo lee, asi que los tests arman los DBF a mano. La primera version
escribia la cabecera mal: el numero de registros iba en el offset equivocado, la
longitud de la cabecera valia `len(header)` en el momento de escribirla (o sea,
sin los descriptores de campo) y la longitud de registro nunca se escribio. El
resultado era `struct.error: unpack requires a buffer of 32 bytes` al leer el
primer campo.

La cabecera de un DBF dBase III son 32 bytes: version (0), fecha (1-3), numero de
registros (4-7), **longitud de cabecera (8-9)**, **longitud de registro (10-11)**,
y despues un descriptor de 32 bytes por campo y el terminador `0x0D`. Los bytes 8-9
y 10-11 son los que le dicen al lector donde empiezan los datos.

### `Truck` no tiene localidad

La verificacion contaba "camiones con localidad DGR" usando `Truck.locality`, que
no existe: el camion no tiene localidad, tiene `chassis_type` y `trailer_type`.
Ahora cuenta los camiones con tipo de chasis, que es lo que el F150 exige.

### El codigo de salida confundia "no entro cada fila" con "la base no sirve"

El legacy tiene un chofer (el `0090`, sin nombre y sin CUIT) que no se puede
importar nunca. Cuando el comando empezo a avisar las filas que no entraron, el
codigo de salida paso a ser 1 con la base lista y el remito para emitir. Ahora los
bloqueantes deciden el codigo y los avisos solo se muestran.

## Lo que el setup NO hace

- **No importa la base `femagfab`** (la de la fabrica): vive en el servidor del
  cliente, no en este MySQL. La direccion de la migracion es una sola,
  legacy -> FEMAG.
- **No exporta a DBF**: no hay exportador, queda como alcance futuro.
- **No arregla el domicilio de entrega del cliente** (#743): el destino del F150
  sigue saliendo del domicilio fiscal del legacy.
- **No decide las razones sociales duplicadas**: ver pendientes.

## Pendientes

1. **#743**: el domicilio de entrega del cliente sale del fiscal. El legacy trae
   los dos separados (`C_DOMI`/`C_LOCAL` y `DOMICILIO`/`LOCALIDAD`) y 21 de 663
   clientes tienen las dos localidades distintas.
2. **8 clientes con CUIT repetido y localidades distintas** en el legacy (por
   ejemplo `SAN PATRICIO Y CIA` en 0798 y en 0149, o el par `RUIZ CLAUDIO ARIEL` /
   `RUIZ CLAUIDO ARIEL`). El importador fusiona las dos filas en un cliente y
   gana la **ultima** fila del DBF, asi que el destino del F150 de esos clientes
   depende del orden del legacy. Es el mismo grupo de las 9 razones sociales que
   quedaron con el nombre de la otra fila: hay que revisarlos a mano.
3. **Los DBF de la fabrica cambian**: hay que releerlos antes de cada instalacion
   (el 20/10 `chofer.dbf` paso de 144 a 149 filas).
4. **Al restaurar la base desde un dump**, verificar que el dump incluya
   `dgrlocality`, `dgrcountry` y `dgrprovince`, o correr este comando.
5. El comando **no esta instalado** en el producto: hay que invocarlo a mano con
   el Python del entorno. Si se quiere que el instalador lo corra solo, es otro
   issue.
