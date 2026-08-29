# FEMAG Desktop - candidate, piloto y promoción a producción

Este documento describe el flujo del issue #378. No cambia la identidad histórica del producto ni el instalador:

- `APP_ID`: `femag`
- Inno Setup `AppId`: `{10F03F3B-BA11-4F61-88DA-14DD2AA30EF4}`
- instalación: `%LOCALAPPDATA%\Programs\FEMAG Desktop`
- asset: `FEMAG_Desktop_Produccion_Setup.exe`
- repositorio público: `oscarvogel/vogel-releases`

## Canales

- Producción normal: `apps/femag/latest.json` -> release tag `latest`.
- Piloto: `apps/femag/candidate.json` -> release tag `femag-candidate`.
- Rollback: `apps/femag/previous.json` -> release tag `femag-previous`.
- Auditoría: `apps/femag/history.jsonl`.

Una PC normal no consulta `candidate.json`. El updater usa `latest` salvo que el Windows de esa instalación tenga explícitamente `FEMAG_UPDATE_CHANNEL=candidate`.

## Configurar una única PC piloto

Ejecutar una vez con el usuario de Windows que usará FEMAG:

```powershell
[Environment]::SetEnvironmentVariable('FEMAG_UPDATE_CHANNEL', 'candidate', 'User')
```

Cerrar FEMAG por completo y volver a abrirlo. Para devolver esa PC al canal normal:

```powershell
[Environment]::SetEnvironmentVariable('FEMAG_UPDATE_CHANNEL', $null, 'User')
```

El valor no es un secreto y no otorga permisos de publicación. Sólo cambia qué manifest consulta ese puesto.

## Flujo después de cada merge a main

`.github/workflows/publish-production.yml`:

1. ejecuta tests y `compileall`;
2. genera EXE e instalador;
3. ejecuta `--smoke` sobre el EXE congelado;
4. ejecuta `--production-health-check`;
5. verifica que no se empaqueten INIs, `.env`, credenciales, claves o secretos;
6. instala silenciosamente en un directorio limpio del runner Windows;
7. ejecuta el health-check sobre el EXE realmente instalado;
8. reinstala/actualiza y comprueba que el área runtime de `%LOCALAPPDATA%\FEMAG Desktop` no fue alterada;
9. calcula SHA256;
10. publica exactamente ese archivo en `femag-candidate`;
11. actualiza sólo `apps/femag/candidate.json`.

Ese workflow nunca sube el instalador a `latest` ni modifica `apps/femag/latest.json`.

## Validación en la PC piloto

Cuando candidate tiene una versión superior, sólo la PC piloto recibe el aviso normal del updater. La descarga:

- usa HTTPS;
- valida SHA256;
- guarda en `%LOCALAPPDATA%\FEMAG Desktop\updates\installed-candidate.json` un recibo con canal, versión y SHA256;
- recién después ofrece ejecutar el instalador.

Luego de instalar candidate, un administrador verá el botón **Aprobar esta versión para producción**.

Antes de permitir continuar, FEMAG vuelve a ejecutar un health-check no destructivo y exige:

- canal local `candidate`;
- usuario administrador;
- versión instalada exactamente igual a candidate;
- SHA256 del recibo local exactamente igual al manifest candidate;
- health-check local exitoso.

La acción muestra versión y SHA, pide confirmación explícita, copia ambos al portapapeles y abre el workflow seguro de GitHub. FEMAG no contiene PAT, tokens ni credenciales de GitHub.

## `--production-health-check`

El comando valida sin escribir datos de negocio:

- configuración;
- logging;
- imports/modelos críticos;
- componentes principales de UI;
- inicialización PyQt;
- conexión a DB;
- `SELECT 1`;
- validación read-only del esquema MySQL en una instalación real.

Exit code `0` significa saludable. Cualquier error devuelve exit code distinto de cero.

## Promoción

`.github/workflows/promote-production.yml`, operación `promote_candidate`:

1. requiere `PROMOTE`;
2. recibe versión y SHA esperados desde la validación piloto;
3. vuelve a leer `candidate.json`;
4. rechaza si versión o SHA cambiaron;
5. descarga el asset existente de `femag-candidate`;
6. vuelve a calcular SHA256;
7. archiva el `latest` actual como `femag-previous` + `previous.json`;
8. sube los mismos bytes de candidate al tag `latest`, sin recompilar;
9. escribe `latest.json` con actor, fecha y run de aprobación;
10. agrega el evento a `history.jsonl`.

La operación es idempotente: si `latest` ya tiene exactamente versión y SHA de candidate, termina correctamente sin duplicar la promoción. El workflow usa concurrency para evitar dos promociones simultáneas.

## Rollback

En el mismo workflow seleccionar `rollback_previous` y escribir `ROLLBACK`.

El job descarga y valida por SHA tanto `latest` como `previous`, intercambia los assets y manifiestos sin recompilar y registra la operación en `history.jsonl`.

## Seguridad de configuración

Los archivos INI/configuración real continúan fuera de GitHub, releases e instalador. El proceso de candidate/promoción no copia, reemplaza ni elimina INIs. El instalador conserva el mismo `AppId` y la misma ruta histórica, por lo que se comporta como actualización de la instalación existente.
