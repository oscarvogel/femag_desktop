# Candidates del 23/10/2026 — FEMAG Desktop

Cuatro candidates publicados el mismo día en el canal `candidate` de `vogel-releases`.
**Ninguno está promovido a producción**: falta la prueba del operador en la PC
piloto (y la prueba física del sobre con la Epson L3250 del issue #740).

| candidate | qué trae | estado |
|---|---|---|
| **2026.10.23.15.07.23** | todo lo anterior + la mercadería suelta en la pantalla de pallets (#767) | **vigente** |
| 2026.10.23.14.26.30 | Fase B del envío de lista de precios (#763) | superado |
| 2026.10.23.10.28.13 | todo lo del anterior + el fix #761 del import | superado |
| 2026.10.23.09.06.55 | sobres (#740), import de lista (#705), partes de embolsado (#754) | superado |

Producción (`latest.json`) sigue en **2026.10.21.09.36.40** (`source_sha 0b2d2f4`),
que es lo que tiene instalado la PC del cliente hoy.

---

## Candidate vigente: 2026.10.23.10.28.13

### Identidad del build

| dato | valor |
|---|---|
| version | `2026.10.23.10.28.13` |
| source_sha | `d0c61424a61d275dab62d770ebe63c44a75b44ce` (main) |
| sha256 | `b719d2785df3d48a6fef59ec673b580f921a740531a69e3be548708df18101cb` |
| asset | `FEMAG_Desktop_Produccion_Setup.exe` (43.519.956 bytes) |
| release | tag `femag-candidate` en `oscarvogel/vogel-releases` |
| download_url | https://github.com/oscarvogel/vogel-releases/releases/download/femag-candidate/FEMAG_Desktop_Produccion_Setup.exe |
| publicado | 2026-10-23 13:31:06 UTC |

### Los tres puntos verificados

1. **SHA256 del instalador local** (`installer/output/FEMAG_Desktop_Produccion_Setup.exe`):
   `b719d278...8101cb` (43.519.956 bytes).
2. **Digest del asset publicado** en el tag `femag-candidate`: descargado y hasheado
   de nuevo → `b719d278...8101cb` (43.519.956 bytes).
3. **sha256 de `candidate.json`** (`apps/femag/candidate.json`): `b719d278...8101cb`.

Los tres coinciden, y el tamaño del asset coincide con el del instalador local.

### Qué entra en este build

| PR | Issue | Qué trae |
|---|---|---|
| #755 | #740 | PDF de sobres automático por cliente: destinatario arriba a la izquierda con el contacto, mercadería y `(N pallets)` abajo a la derecha, presupuesto abajo a la izquierda. El logo deja de ir por omisión. |
| #760 | #705 | Importar la lista de precios desde Excel, con vista previa y sin pisar lo editado. |
| #757 | #754 | Partes de embolsado cargados desde el celular, con login y atribución del operario. |
| #762 | **#761** | El import aplica la lista del archivo al cliente duplicado en la base, en vez de bloquearse. |

### Validaciones ejecutadas (dentro de `release.ps1`)

```
tests                             1933 passed, 3 skipped (401,99 s)
compileall                        exit 0
smoke de la app                   FEMAG smoke OK
build del instalador de producción  OK (Inno Setup 6)
smoke del EXE congelado           OK
chequeo de recursos congelados    OK
chequeo de secretos del artefacto  OK
CANDIDATE_STATUS                   OK
```

Además, fuera del release: `python -m pytest` (1933 passed / 3 skipped),
`python -m compileall app`, `git diff --check` y los 22 tests de
`tests/test_issue_705_price_list_import.py`.

### Verificación contra los datos reales del cliente (#761)

El dump de la base del cliente (`femag_desktop.sql`, 884 clientes, 20/10/2026) se
cargó en una base aislada de MariaDB (`femag_cliente_761`, en el WSL de desarrollo;
**no se tocó ninguna base de producción**) y se corrió la vista previa real del
import, con el código de antes del fix y con el de ahora:

| | antes (`1b46f98`) | ahora (`d0c6142`) |
|---|---|---|
| listas a cambiar | **0** | **1** (GIMENEZ ROMINA JAQUELINE, id 850, lista 1 → 2) |
| teléfonos a completar | 8 | 9 |
| sin cambio | 876 | 877 |
| conflictos | 3 | 3 |
| filas sin aplicar | 8 | 8 |

El cambio real: antes, el cliente duplicado en la base (mismo CUIT guardado en
dos formatos) bloqueaba el cambio con *"El CUIT corresponde a varias filas del
cliente con listas distintas en la base. Hay que unificar las filas antes de
importar"*. Ahora la lista del archivo se aplica a todas sus filas, con el aviso
*"Se actualizaron todas con la lista del archivo; conviene unificarlas"*.

**Lo que el import no arregla** (y no es un bug):

- `PANYMAX S.A.` y `PRINWEY ALIMENTOS S.A.` comparten el CUIT `30693299930`:
  son dos empresas distintas, así que el import no aplica nada y avisa
  *"El CUIT corresponde a más de un cliente en la base"*. Eso hay que
  corregirlo a mano en la base.
- El `UNIQUE KEY client_cuit` de la tabla `client` está sobre el **texto** del
  CUIT, así que el mismo cliente convive en dos filas cuando una viene del
  legacy (sin guiones) y la otra de la carga manual (con guiones). Normalizar el
  CUIT al guardar es un arreglo **distinto y más grande**: queda fuera de #761.

### Qué archivo hay que importar en la PC del cliente

El Excel de Gabriela (`docs/clientes_20261021.xlsx`, 901 filas) tiene **6 clientes
duplicados dentro del archivo** (el mismo CUIT con lista 1 y lista 2). Eso lo
bloquea el import, y está bien que así sea.

Por eso hay que usar el archivo unificado, `docs/clientes_20261021_unificado.xlsx`
(895 filas, una por cliente). Con el archivo original el diálogo muestra
`0 listas a cambiar` y 8 conflictos; con el unificado muestra los cambios de
lista y solo un conflicto bloqueante real (PANYMAX/PRINWEY).

---

## Candidate superado: 2026.10.23.09.06.55

| dato | valor |
|---|---|
| version | `2026.10.23.09.06.55` |
| source_sha | `ac835923d8d499caf2c1d4924c7f9a9ea4d88fe7` (main) |
| sha256 | `811d8d0758363fbdee692e94d089113ba6b51e012303212a9e166657280a282b` |
| asset | `FEMAG_Desktop_Produccion_Setup.exe` (43.521.399 bytes) |
| publicado | 2026-10-23 12:09:49 UTC |

Traía los PR #755 (#740), #760 (#705) y #757 (#754). Tests: 1930 passed,
3 skipped. Fue superado por el candidate vigente, que además lleva el fix #761.

---

## Cómo se instala en la PC del cliente

La PC piloto va con `FEMAG_UPDATE_CHANNEL=candidate`: al abrir FEMAG, la app
consulta `candidate.json`, ve esta versión y ofrece la actualización. Descarga,
verifica el SHA256 sola, guarda el recibo en
`%LOCALAPPDATA%\FEMAG Desktop\updates\installed-candidate.json` y después
aparece el botón **"Aprobar esta versión para producción"** para el admin.

Instalar el `.exe` a mano también funciona, pero **no genera el recibo**: se
pierde el botón de aprobación. Por eso la vía del updater es la recomendada.

Si la PC está con el canal `latest` (producción), hay que cambiar
`FEMAG_UPDATE_CHANNEL=candidate` en la configuración del puesto antes de abrir
FEMAG; si no, la app sigue buscando `latest.json` y no ve este candidate.

## Pendientes

1. **Prueba del operador en la PC piloto** (canal `candidate`): instalar y correr
   el import con `docs/clientes_20261021_unificado.xlsx`. Hasta que no haya
   prueba, `latest.json` sigue apuntando a `2026.10.21.09.36.40`.
2. **Prueba física del sobre con la Epson L3250** (issue #740): define
   `rotation_deg` y los desplazamientos definitivos en `envelope.json`.
3. **Promoción a producción** con `.\release.ps1 production` desde `main`,
   una vez approved los dos puntos anteriores.

---

## Candidate superado: 2026.10.23.14.26.30 (Fase B del envío de lista de precios)

Quedó superado por `2026.10.23.15.07.23` (la mercadería suelta), que se construyó
desde un `main` que ya incluye toda la Fase B. Sigue **sin promover a producción**.

| dato | valor |
|---|---|
| version | `2026.10.23.14.26.30` |
| source_sha | `7940e662e81e984479d4cc09c48ea231ba323ef8` (main) |
| sha256 | `503c7f8561b2f7c4480dcdbd46fa3e88fdb053dbf3e3c864528a8adbe1754103` |
| asset | `FEMAG_Desktop_Produccion_Setup.exe` (43.553.847 bytes) |
| release | tag `femag-candidate` en `oscarvogel/vogel-releases` |
| download_url | https://github.com/oscarvogel/vogel-releases/releases/download/femag-candidate/FEMAG_Desktop_Produccion_Setup.exe |
| publicado | 2026-10-23 17:28:54 UTC |

### Los tres puntos verificados

1. **SHA256 del instalador local** (`installer/output/FEMAG_Desktop_Produccion_Setup.exe`):
   `503c7f85...54103` (43.553.847 bytes).
2. **Digest del asset publicado** en el tag `femag-candidate`:
   `sha256:503c7f85...54103` (43.553.847 bytes).
3. **sha256 de `candidate.json`** (`apps/femag/candidate.json`):
   `503c7f85...54103`.

Los tres coinciden, y el tamaño del asset coincide con el del instalador local.

### Qué entra en este build

| PR | Issue | Qué trae |
|---|---|---|
| #764 | #763 | Configuración por lista (PDF + mensaje) y cálculo de la audiencia con el clasificador de teléfonos |
| #765 | #763 | Motor de la campaña: cola secuencial, intervalo con jitter, tope diario, pausa/cancelar, reintentos, circuit breaker, idempotencia y auditoría |
| #766 | #763 | Pantalla "Envío de lista de precios" en Maestros, con los 4 pasos del spec §4.2 |
| #768 | #763 | Fix: la zona horaria del tope diario no depende de `zoneinfo` (ver abajo) |

La bitácora completa de la Fase B está en `docs/fase-b-envio-lista-precios.md`.

### Validaciones ejecutadas (dentro de `release.ps1`)

```
tests                               1966 passed, 3 skipped (527,49 s)
compileall                          exit 0
smoke de la app                     FEMAG smoke OK
build del instalador de producción  OK (Inno Setup 6)
smoke del EXE congelado             OK
chequeo de recursos congelados      OK
chequeo de secretos del artefacto   OK
CANDIDATE_STATUS                    OK
```

Además, fuera del release: la suite completa con el **venv** del release
(`.venv\Scripts\python.exe`, que es el que arma el instalador de Windows) con
**1966 passed, 3 skipped** (421 s), `python -m compileall app` exit 0,
`git diff --check` limpio y `python -m app.main --smoke` con `FEMAG smoke OK`.

### El fix de la zona horaria (PR #768): por qué hacía falta

El primer release con la Fase B **abortó en los tests (19 fallos) y no publicó nada**. La
causa no era la lógica de la campaña: `zoneinfo.ZoneInfo("America/Argentina/Buenos_Aires")`
exige el paquete **`tzdata`**, que no está en `requirements.txt`. En el venv limpio del
release (y en la PC del cliente) **la app no arrancaba**: `ZoneInfoNotFoundError` al
instalar la extensión.

El CI en Linux no lo ve (ahí `tzdata` está en el sistema) y el Python del sistema de esta
máquina también lo tiene, pero el `.venv` que arma el instalador no.

La corrección (`ecb220e`) usa el desplazamiento fijo de Argentina, que es UTC-3 sin horario
de verano desde 2009:

```python
ZONA = timezone(timedelta(hours=-3))
```

Así que no hace falta ninguna dependencia nueva y **no se tocó `requirements.txt`**.
Evidencia antes/después con el venv: `ZoneInfoNotFoundError` → `extension OK`.

### Verificación del contenido del instalador

El instalador es Inno Setup con compresión lzma2, así que no se puede abrir con 7-Zip ni
buscar cadenas dentro. Lo que sí se puede verificar es el **build congelado de
PyInstaller** que va dentro (`dist/FEMAG Desktop/FEMAG Desktop.exe`): se lee el PYZ
embebido (1259 módulos) y se mira el bytecode de `app.services.price_list_send_service`.

```
app.services.price_list_send_service: usa zoneinfo (código VIEJO, bug): False
app.services.price_list_send_service: usa timedelta (fix):              True
app.ui.price_list_send_extension:      zoneinfo=False
app.services.whatsapp_envio_service:    zoneinfo=False
```

O sea: **el instalador publicado lleva el fix**, no el código que reventaba en Windows.

### La audiencia real (base del cliente, dump del 20/10 con el import unificado aplicado)

Medida con el código de la app (`PriceListCampaignService.calcular_audiencia`) contra la
base aislada `femag_cliente_761` (**no se tocó ninguna base de producción**):

| lista | clientes | celulares | posibles | inválidos | sin teléfono | inactivos | marcados por defecto |
|---|---|---|---|---|---|---|---|
| 1 | 874 | 25 | 145 | 35 | 669 | 1 | **25** |
| 2 | 8 | 2 | 5 | 0 | 1 | 1 | **2** |

**"Enviar la lista 1" son 25 mensajes seguros, no 875.** El cuello de botella real es el
dato de contacto del maestro, no el motor de envío: 669 clientes de la lista 1 no tienen
teléfono.

Los "posibles" (un local de 10 u 11 dígitos puede ser una línea fija o un móvil escrito sin
el "15") **no se mandan solos**: aparecen en la vista previa con el número exacto y los
tilda el operador.

### Lo que falta para darlo por verificado

1. **La prueba real contra el gateway**: el código nunca habló con la API de WhatsApp.
   Son 3-5 mensajes de prueba, intervalo de 10 s, **instancia de prueba**, con la
   autorización expresa del operador (el riesgo real es que el proveedor bloquee la línea).
2. **La prueba física del sobre con la Epson L3250** (issue #740).
3. **La promoción a producción** (`.
elease.ps1 production`) una vez probados los dos.

Mientras tanto, `latest.json` sigue en **2026.10.21.09.36.40** (`source_sha 0b2d2f4`).

---

## Nota operativa: el release se frenó en el primer intento

El primer intento del candidate del 23/10 abortó en el paso 2/7 (tests) **con los
tests completamente pasados** (100 %, sin F). La causa no fue el código:

```
PermissionError: [WinError 5] Acceso denegado:
'C:\Users\Usuario\AppData\Local\Temp\pytest-of-Usuario\pytest-current'
```

`pytest-current` es una junction que pytest crea en su carpeta temporal para
apuntar al último directorio numerado. La de esta máquina quedó **corrupta el
16/10/2026**: al cerrar la sesión, `cleanup_dead_symlinks` llama a `resolve()`
sobre ella y revienta con WinError 5, con lo que pytest sale con código 1
aunque no haya ningún test fallado. `release.ps1` hace bien en frenar (nunca
desactiva tests), pero el freno era falso.

La junction está fuera del workspace, así que el borrado recuperable la
rechaza y no se debe esquivar ese límite. La salida fue correr el release con
un `TEMP` aislado, donde pytest arma su propia raíz limpia:

```powershell
$env:TEMP = "$env:TEMP\femag-release-temp"
$env:TMP  = $env:TEMP
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\release.ps1 candidate
```

Con eso el release completa sin tocar la junction corrupta. Si vuelve a
pasar, es el mismo problema: **no es un fallo del código bajo prueba**.

---

## Candidate vigente: 2026.10.23.15.07.23 (mercadería suelta en la pantalla de pallets)

Este es el **candidate vigente**: el anterior (`2026.10.23.14.26.30`, Fase B del
envío de lista de precios) queda superado. Sigue **sin promover a producción**.

| dato | valor |
|---|---|
| version | `2026.10.23.15.07.23` |
| source_sha | `da9f368d5aaa643253f76e7be519c98207bf0647` (main) |
| sha256 | `7e658424be928be50710c3d0a2b55d831a56a663124b186821b1acc62967cfd9` |
| asset | `FEMAG_Desktop_Produccion_Setup.exe` (43.556.925 bytes) |
| release | tag `femag-candidate` en `oscarvogel/vogel-releases` |
| download_url | https://github.com/oscarvogel/vogel-releases/releases/download/femag-candidate/FEMAG_Desktop_Produccion_Setup.exe |

### Los tres puntos verificados

1. **SHA256 del instalador local** (`installer/output/FEMAG_Desktop_Produccion_Setup.exe`):
   `7e658424...67cfd9` (43.556.925 bytes).
2. **Digest del asset publicado** en el tag `femag-candidate`:
   `sha256:7e658424...67cfd9` (43.556.925 bytes).
3. **sha256 de `candidate.json`** (`apps/femag/candidate.json`):
   `7e658424...67cfd9`.

Los tres coinciden, y el tamaño del asset coincide con el del instalador local.

### Qué entra en este build

| PR | Issue | Qué trae |
|---|---|---|
| #769 | **#767** | La mercadería suelta (bolsas que viajan en el camión sin ir en ningún pallet) se puede marcar desde la pantalla de "Preparación de pallets", con cantidad parcial, y se la ve y se la quita desde un panel propio. Sin cambios de modelo, migraciones ni servicios. |

Trae además **todo lo del candidate anterior** (Fase B del envío de lista de precios,
#763), porque se construyó desde `da9f368`, que ya incluye los PR #764 a #768. El
único commit posterior (`92d064a`) es documentación.

### Validaciones ejecutadas (dentro de `release.ps1`)

```
tests                               1975 passed, 3 skipped (333,73 s)
compileall                          exit 0
smoke de la app                     FEMAG smoke OK
build del instalador de producción  OK (Inno Setup 6.7.3)
smoke del EXE congelado             OK
chequeo de secretos del artefacto   OK
CANDIDATE_STATUS                    OK
```

El CI del PR #769 también dio verde en los dos jobs ("Tests, compile and smoke" y
"Windows frozen EXE and installer smoke", run 39998849626).

### Cómo sale impresa la mercadería suelta

Verificado con los servicios de impresión reales sobre el caso LULEMU (4 bolsas de
25 kg):

| Escenario | Columna Pallet | TOTALES |
|---|---|---|
| las 4 bolsas sueltas | **SUELTO** (celda fusionada sobre las dos filas) | **0 pallets** |
| 2 en 1 pallet + 2 sueltas | **1 pallet** y **SUELTO** | **1 pallet** |

Sale con la etiqueta **SUELTO** en el informe de pallets, en el remito de carga, en el
consolidado con QR y en el Excel de armado de pallets, y **no suma al total de pallets**:
la carga deja de consumir un pallet de mentira. El peso sí va a `TOTAL MERCADERIA`.

### Lo que falta para darlo por verificado

1. **La prueba del operador en la PC piloto**: marcar mercadería suelta en una carga
   real y revisar el remito impreso.
2. **La prueba física del sobre con la Epson L3250** (issue #740).
3. **La promoción a producción** (`.\release.ps1 production`) una vez probados los dos.

Mientras tanto, `latest.json` sigue en **2026.10.21.09.36.40** (`source_sha 0b2d2f4`).

---

## Nota operativa: el release deja un `.env.release-bak` sin restaurar

El release del 23/10 terminó con `CANDIDATE_STATUS=OK` pero avisó:

```
ADVERTENCIA: .env ya existe y .env.release-bak no se restauro: revise ambos archivos a mano.
```

El script aparta el `.env` a `.env.release-bak` antes del stash y lo restaura al final.
Como durante el release el `.env` vuelve a existir (lo regenera el build), la restauración
se saltea y queda el backup. **No se perdió nada**: se compararon los dos archivos y
tienen el mismo contenido, clave por clave; lo único que difiere son los finales de
línea (`.env` quedó con LF, el backup con CRLF). El `.env` que usa la app es el que
tiene los valores correctos.

El `.env.release-bak` es un resto que aparece en cada release: **no hay que actingar
contra él a mano**, se puede borrar cuando se quiera porque es una copia del `.env`.
