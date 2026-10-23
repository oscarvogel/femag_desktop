# Release candidate 2026.10.23.09.06.55 — 23/10/2026

Candidate local de FEMAG publicado en el canal `candidate` de `vogel-releases`.
**No se promueve a producción todavía**: falta la prueba del operador en la PC
piloto (y la prueba física del sobre con la Epson L3250 del issue #740).

## Identidad del build

| dato | valor |
|---|---|
| version | `2026.10.23.09.06.55` |
| source_sha | `ac835923d8d499caf2c1d4924c7f9a9ea4d88fe7` (main) |
| sha256 | `811d8d0758363fbdee692e94d089113ba6b51e012303212a9e166657280a282b` |
| asset | `FEMAG_Desktop_Produccion_Setup.exe` (43.521.399 bytes) |
| release | tag `femag-candidate` en `oscarvogel/vogel-releases` |
| download_url | https://github.com/oscarvogel/vogel-releases/releases/download/femag-candidate/FEMAG_Desktop_Produccion_Setup.exe |
| publicado | 2026-10-23 12:09:49 UTC |

## Los tres puntos verificados

1. **SHA256 del instalador local** (`installer/output/FEMAG_Desktop_Produccion_Setup.exe`): `811d8d07...282b`.
2. **Digest del asset publicado** en el tag `femag-candidate`: `sha256:811d8d07...282b`.
3. **sha256 de `candidate.json`** (`apps/femag/candidate.json`): `811d8d07...282b`.

Los tres coinciden, y el tamaño del asset (43.521.399) coincide con el del
instalador local.

## Qué entra en este build

| PR | Issue | Qué trae |
|---|---|---|
| #755 | #740 | PDF de sobres automático por cliente: destinatario arriba a la izquierda con el contacto, mercadería y `(N pallets)` abajo a la derecha, presupuesto abajo a la izquierda. El logo deja de ir por omisión. |
| #760 | #705 | Importar la lista de precios desde Excel, con vista previa y sin pisar lo editado. |
| #757 | #754 | Partes de embolsado cargados desde el celular, con login y atribución del operario. |

## Validaciones ejecutadas (dentro de `release.ps1`)

```
tests                             1930 passed, 3 skipped (397,81 s)
compileall                        exit 0
smoke de la app                   FEMAG smoke OK
build del instalador de producción  OK (Inno Setup 6)
smoke del EXE congelado           OK
chequeo de recursos congelados    OK
chequeo de secretos del artefacto  OK
```

El digest se calculó sobre el instalador final, ya con los metadatos de
release dentro.

## Cómo se instala en la PC del cliente

La PC piloto va con `FEMAG_UPDATE_CHANNEL=candidate`: al abrir FEMAG, la app
consulta `candidate.json`, ve esta versión y ofrece la actualización. Descarga,
verifica el SHA256 sola, guarda el recibo en
`%LOCALAPPDATA%\FEMAG Desktop\updates\installed-candidate.json` y después
aparece el botón **"Aprobar esta versión para producción"** para el admin.

Instalar el `.exe` a mano también funciona, pero **no genera el recibo**: se
pierde el botón de aprobación. Por eso la vía del updater es la recomendada.

## Pendientes

1. **Prueba del operador en la PC piloto** (canal `candidate`). Hasta que no
   haya prueba, `latest.json` sigue apuntando a `2026.10.21.09.36.40`.
2. **Prueba física del sobre con la Epson L3250** (issue #740): define
   `rotation_deg` y los desplazamientos definitivos en `envelope.json`.
3. **Promoción a producción** con `.\release.ps1 production` desde `main`,
   una vez approved los dos puntos anteriores.

## Nota operativa: el release se frenó en el primer intento

El primer intento de este candidate abortó en el paso 2/7 (tests) **con los
tests completamente pasados** (100 %, sin F). La causa no fue el código:

```
PermissionError: [WinError 5] Acceso denegado:
'C:\Users\Usuario\AppData\Local\Temp\pytest-of-Usuario\pytest-current'
```

`pytest-current` es una junction que pytest crea en su carpeta temporal para
apuntar al último directorio numerado. La de esta máquina quedó **corrupta el
16/10/2026**: al cerrar la sesión, `cleanup_dead_symlinks` llama a
`resolve()` sobre ella y revienta con WinError 5, con lo que pytest sale con
código 1 aunque no haya ningún test fallado. `release.ps1` hace bien en frenar
(nunca desactiva tests), pero el freno era falso.

La junction está fuera del workspace, así que el borrado recuperable la
rechaza y no se debe esquivar ese límite. La salida fue correr el release con
un `TEMP` aislado, donde pytest arma su propia raíz limpia:

```powershell
$env:TEMP = "$env:TEMP\femag-release-temp"
$env:TMP  = $env:TEMP
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\release.ps1 candidate
```

Con eso el release completes sin tocar la junction corrupta. Si vuelve a
pasar, es el mismo problema: **no es un fallo del código bajo prueba**.
