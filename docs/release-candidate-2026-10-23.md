# Candidates del 23/10/2026 — FEMAG Desktop

Dos candidates publicados el mismo día en el canal `candidate` de `vogel-releases`.
**Ninguno está promovido a producción**: falta la prueba del operador en la PC
piloto (y la prueba física del sobre con la Epson L3250 del issue #740).

| candidate | qué trae | estado |
|---|---|---|
| **2026.10.23.10.28.13** | todo lo del anterior + el fix #761 del import | **vigente** |
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
