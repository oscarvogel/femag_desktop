# #790 - Destino DGR, correccion desde F150 y recuperacion de TXT

Implementacion del issue **#790** y cierre funcional de **#786**, tomando como
base el PR **#787** (recuperacion por SHA) sin duplicar su codigo.

- Rama: `fix/issue-790-f150-dgr-recovery`
- Base: `main` (`9dcf405`)
- Alcance: F150, domicilios de cliente, importacion de maestros y correccion
  controlada desde PyQt5.
- Fuera de alcance: ordenes de carga, cuentas corrientes, importes, numeracion,
  promocion automatica a produccion.

## Que se corrigio

### 1. Fiscal vs. entrega y ciudad/provincia

El legacy trae dos domicilios:

| DBF | Uso |
|---|---|
| `DOMICILIO` / `CODPOS` / `LOCALIDAD` | domicilio legal/fiscal |
| `C_DOMI` / `C_CODPOS` / `C_LOCAL` | domicilio comercial/de entrega, el que usa el remito impreso |

El importador anterior tomaba solo `DOMICILIO` como una direccion compartida y
dejaba `province = "Sin especificar"` aunque `LOCALIDAD` tuviera un codigo DGR
valido. Ahora:

- crea una direccion **fiscal** y una **de entrega** cuando los dos domicilios
  difieren;
- conserva una sola direccion **compartida** cuando son iguales;
- deriva ciudad y provincia desde la localidad DGR (`localidad.name` y
  `dgrprovince.name`), sin inventar codigos;
- en modo `patch` solo completa vacios o `Sin especificar` y **nunca pisa** una
  ciudad, provincia, calle o localidad editada por el operador;
- es idempotente: la segunda corrida no crea direcciones ni vuelve a completar
  los mismos campos.

Caso real **ASTICOMAR S.A. (`0830`)**, remito `0001-00010942`:

- `DOMICILIO`: `ESPINOSA NEGRETE 701`
- `LOCALIDAD`: `1030` -> `CORDOBA` / provincia `04`
- `C_DOMI`: `TOMAS DE IROBI 83`

La reimportacion sobre la base real dejo la direccion compartida existente con
`ESPINOSA NEGRETE 701`, `city=CORDOBA`, `province=CORDOBA`, `locality=1030`,
sin cambiar la calle. Tambien creo/completo la direccion de entrega de
`TOMAS DE IROBI 83` con los mismos codigos.

### 2. Bloqueo antes de emitir y antes del TXT

- Al **emitir un remito** se refresca el snapshot de entrega desde el domicilio
  maestro y se rechazan calle/ciudad/provincia vacias o `Sin especificar`, y una
  provincia que no corresponda a la localidad DGR elegida.
- Al **generar el F150** se valida el domicilio maestro y el snapshot congelado
  del remito. Un remito historico con `delivery_city`/`delivery_province`
  invalido queda bloqueado con mensajes por campo.
- Inmediatamente antes de escribir el TXT se vuelve a validar el lote dentro de
  la transaccion. Si otro puesto cambio un dato, el lote se revierte.
- Los remitos ya emitidos no se mutan automaticamente. La correccion es manual,
  auditada y con confirmacion.

### 3. UI PyQt5 `Corregir datos DGR`

En **Generar F150** hay una accion nueva, `Corregir datos DGR`:

- pestana **Destino**: calle, ciudad, provincia y localidad DGR buscable;
- la localidad se elige de la tabla DGR y la etiqueta muestra nombre, codigo,
  codigo DGR, provincia y pais (desambigua ciudades homonimas como
  `JUSTINIANO POSSE` 1058/1503, `RIO CUARTO` 1099/1327 o `CORDOBA` 1030/1153);
- pestana **Productos**: `RH1..RH4` y `unidad_dgr` de los productos del remito;
- valida que los rubros sean numericos y que la unidad no este vacia, sin
  valores por defecto;
- exige administrador o permiso `Operaciones / Generar F150 / configurar`;
- registra auditoria antes/despues por domicilio y por producto;
- actualiza el snapshot del remito **solo** si no pertenece a un lote F150. Si
  ya fue incluido, corrige el maestro pero no toca el snapshot ni el TXT
  presentado;
- al guardar, la pantalla se refresca y muestra los pendientes restantes.

El ABM de domicilios tambien incorpora la localidad DGR, completa ciudad y
provincia desde ella y rechaza `Sin especificar`.

### 4. Recuperar/regenerar TXT (#786)

- Cada generacion nueva deja una copia inmutable del TXT en
  `%LOCALAPPDATA%\FEMAG Desktop\outputs\f150\archive`, identificada por lote y
  SHA-256.
- `Recuperar TXT del lote seleccionado` busca, en orden:
  1. la copia inmutable de FEMAG;
  2. el TXT original en la ruta registrada;
  3. una reconstruccion desde los remitos del lote.
- En los tres casos exige que el SHA-256 coincida con el del lote. Si no hay
  evidencia suficiente, informa explicitamente y **no escribe** un TXT
  divergente desde maestros actuales.
- No crea `F150Batch`, no crea `F150BatchRemittance`, no mueve correlativos,
  fechas, usuario, estado ni archivos existentes. El guardado es exclusivo
  (`xb`) y nunca sobrescribe.
- Registra auditoria `F150 / recuperar_txt` indicando la fuente usada.

### 5. Health-check

`--production-health-check` agrega un diagnostico no destructivo
`f150-dgr: N listos, M bloqueados`. Los remitos emitidos con destino incompleto
se informan como warning; no impiden abrir la aplicacion ni se corrigen solos.

## Validaciones ejecutadas

```
python -m pytest -q
    2051 passed, 3 skipped (429 s)

python -m compileall -q app tests
    OK

python -m app.main --smoke
    FEMAG smoke OK

python -m app.main --production-health-check   (contra copia real en MariaDB/WSL)
    FEMAG production health OK: ..., f150-dgr: 0 listos, 3 bloqueados
    WARNING: 3 remitos emitidos con destino DGR incompleto

git diff --check
    limpio
```

### Contra la copia real de produccion (MariaDB/WSL)

Se importo `Downloads/femag_desktop.sql` en la instancia de prueba (puerto
3308, base `femag_desktop`) y se corrio la reimportacion de `clientes.dbf`:

- 890 clientes actualizados, 73 direcciones de entrega creadas.
- 1327 ciudades/provincias completadas desde localidad DGR.
- ASTICOMAR: `ESPINOSA NEGRETE 701` / `CORDOBA` / `CORDOBA` / `1030`.
- Segunda corrida: `direcciones_creadas=0`, `ciudad_provincia_completadas=0`,
  `localidad_backfill=0` -> idempotente.

Se corrigieron los tres remitos del incidente desde el mismo servicio que usa la
UI y se genero el F150:

| remito | localidad usada | resultado |
|---|---|---|
| 0001-00010940 | JUSTINIANO POSSE 1058 | F150 generado y recuperado byte a byte |
| 0001-00010941 | RIO CUARTO 1099 | F150 generado y recuperado byte a byte |
| 0001-00010942 | CORDOBA 1030 | F150 generado y recuperado byte a byte |

Recuperacion de lotes historicos sin archivo original en esa PC:

- `F150-00000001`, `F150-00000003` y `F150-00000007`: recuperados con SHA exacto.
- `F150-00000002`, `-4`, `-5`, `-6`: error explicito porque el snapshot
  historico tiene ciudad/provincia incompletos. No se escribio ningun TXT
  divergente. En produccion esos lotes se recuperan del archivo original si
  todavia existe.

Golden master `docs/F.150-05-10-2026B.TXT`: se reconstruye byte a byte con el
encoder actual (test automatizado).

## Pruebas agregadas

`tests/test_issue_790_f150_dgr.py` cubre:

- ASTICOMAR 10942, 10940/10941, separacion fiscal/entrega, import idempotente;
- no pisar cambios humanos de ciudad/provincia;
- bloqueo al emitir y al generar F150;
- correccion desde servicio y desde el dialogo PyQt5;
- permisos administrativos y auditoria antes/despues;
- no modificar snapshots de remitos ya incluidos en un lote;
- recuperacion doble byte a byte, archivo alterado, ruta invalida, archivo
  existente, historico sin evidencia y no duplicacion del lote;
- golden master F150.

## Release Windows en produccion

Publicado como candidate con `scripts/publish_femag_release.ps1 candidate` y
promovido a produccion el 27/10/2026 con
`scripts/publish_femag_release.ps1 promote -Confirmation PROMOTE`, despues de la
prueba en planta.

| dato | valor |
|---|---|
| version | `2026.10.26.18.13.37` |
| source_sha | `4b9d62d82da7ed4bd22794b84723ba5b88e52687` (`4b9d62d`) |
| sha256 | `f25daf93d73532a8fc49e45446b05b0f9ec47c78883d8a1664de5634686b0f92` |
| asset | `FEMAG_Desktop_Produccion_Setup.exe` (43.584.812 bytes) |
| download_url produccion | https://github.com/oscarvogel/vogel-releases/releases/download/latest/FEMAG_Desktop_Produccion_Setup.exe |
| download_url candidate | https://github.com/oscarvogel/vogel-releases/releases/download/femag-candidate/FEMAG_Desktop_Produccion_Setup.exe |
| release produccion | https://github.com/oscarvogel/vogel-releases/releases/tag/latest |
| latest.json | `oscarvogel/vogel-releases/apps/femag/latest.json` |
| candidate.json | `oscarvogel/vogel-releases/apps/femag/candidate.json` |
| version anterior | `2026.10.23.17.21.29` (`femag-previous`) |

El manifest declara `source_dirty=false`: el build se hizo sobre el commit
`4b9d62d` de la rama del PR, con todos los checks de CI en verde. `latest.json`
quedo en esta version y la anterior quedo archivada en `previous.json`.

### Prueba sugerida en planta (27/10)

1. Descargar el instalador y verificar el SHA256:
   `Get-FileHash .\FEMAG_Desktop_Produccion_Setup.exe -Algorithm SHA256`.
2. Instalar y abrir FEMAG con la base real.
3. Ir a **Generar F150**, seleccionar el remito `0001-00010942` (ASTICOMAR).
4. Usar **Corregir datos DGR**: localidad `CORDOBA` codigo `1030`, ciudad y
   provincia `CORDOBA`, y completar `RH1..RH4` / unidad del producto
   `BOLSAS ALM. DE MAIZ X 10 KG.` con los valores autorizados.
5. Guardar y verificar que el remito quede sin pendientes; generar el F150.
6. Repetir para `0001-00010940` (JUSTINIANO POSSE `1058`) y `0001-00010941`
   (RIO CUARTO `1099`).
7. Desde **Historial de lotes**, seleccionar un lote ya presentado y usar
   **Recuperar TXT del lote seleccionado**. Elegir otra carpeta y confirmar que
   el archivo se recupera sin crear un lote nuevo.

## Riesgos y pendientes

- El candidate **no se promueve a produccion** hasta que FEMAG lo pruebe en
  planta.
- Los remitos historicos `10940`, `10941` y `10942` deben corregirse desde la UI
  antes de generar un F150 nuevo. El fix no modifica snapshots historicos solo.
- La copia inmutable del TXT vive en el puesto que genero el lote. Si se
  recupera desde otro puesto y no existe el original, la reconstruccion exige
  que los datos sigan coincidiendo con el SHA del lote; si no, se informa el
  bloqueo.
- El deploy del candidate en una base existente no requiere cambios de esquema:
  la persistencia de bytes es un archivo administrado, no una columna nueva.
