# Actualización automática de FEMAG Desktop

## Identidad

- APP_ID productivo: `femag`.
- APP_ID en desarrollo: `development`.
- Manifest: `apps/femag/latest.json` en `oscarvogel/vogel-releases`.
- Asset estable: `FEMAG_Desktop_Produccion_Setup.exe`.
- Release/tag compartido: `latest`.
- Ejecutable instalado: `FEMAG Desktop.exe`.
- AppId histórico de Inno Setup: `{10F03F3B-BA11-4F61-88DA-14DD2AA30EF4}`.
- Ruta histórica: `%LOCALAPPDATA%\Programs\FEMAG Desktop`.

No cambiar el AppId ni la ruta histórica sin una migración explícita.

## Configuración local

La configuración productiva NO forma parte del instalador. Vive fuera de `{app}`, en:

`%LOCALAPPDATA%\FEMAG Desktop`

Los archivos `connection.json` y `connection.credential` son datos locales del puesto. La credencial está protegida con Windows DPAPI/CurrentUser.

Regla de release: nunca copiar, empaquetar, reemplazar, borrar ni modificar INI, `.env`, credenciales o secretos. Una actualización debe dejar la configuración byte-a-byte intacta.

## Build

`scripts/build_production_installer.ps1` genera versión UTC/local de build con formato:

`yyyy.MM.dd.HH.mm.ss`

Durante el build se hidratan:

```python
APP_ID = "femag"
BUILD_VERSION = "yyyy.MM.dd.HH.mm.ss"
```

en `app/build_info.py`. En el árbol de desarrollo permanecen los defaults inertes `development` / `0.0.0.0.0.0`.

Se conserva el spec real `installer/FEMAG_Desktop.spec`, incluidos `pyqt5libs`, datos de ReportLab, barcode, branding e icono. No simplificar el bundle sin validar el ejecutable congelado.

## Updater

Al iniciar una build productiva, FEMAG consulta únicamente:

`https://raw.githubusercontent.com/oscarvogel/vogel-releases/main/apps/femag/latest.json`

El manifest válido requiere:

- `schema_version == 1`;
- `app_id == "femag"`;
- versión timestamp válida;
- `download_url` HTTPS;
- SHA256 hexadecimal de 64 caracteres;
- UTF-8 sin BOM.

Si la versión remota no es superior, no se muestra nada.

Si existe una versión superior, el usuario ve versión actual/nueva. La descarga se hace en TEMP mediante archivo `.part`, se calcula SHA256 mientras se descarga y sólo después de validarlo se hace `os.replace` al nombre final. Ante cualquier error se elimina `.part`, se registra el fallo y FEMAG continúa funcionando.

El updater no contiene PAT ni token de GitHub.

## Workflow

`.github/workflows/publish-production.yml` corre en Windows para:

- cada `push` a `main`;
- ejecución manual `workflow_dispatch`.

Los PR no publican en `vogel-releases`. El CI normal del PR sólo valida código/tests.

El workflow productivo:

1. instala dependencias;
2. corre tests;
3. valida `VOGEL_RELEASES_TOKEN`;
4. genera build info/version;
5. compila con PyInstaller;
6. genera installer Inno;
7. ejecuta smoke del EXE congelado;
8. inspecciona artefactos para impedir configuración/secrets;
9. calcula SHA256;
10. reemplaza `FEMAG_Desktop_Produccion_Setup.exe` en release `latest`;
11. escribe `apps/femag/latest.json` UTF-8 sin BOM;
12. verifica que sólo ese manifest esté staged;
13. commit `release(femag): <version>` y push a `vogel-releases`.

El único secreto requerido es `VOGEL_RELEASES_TOKEN`, almacenado como GitHub Actions secret en `femag_desktop`.

## E2E previo al merge

En una PC real FEMAG:

1. calcular `Get-FileHash` SHA256 de la configuración real relevante;
2. instalar build A;
3. abrir y validar operación básica;
4. confirmar SHA de configuración sin cambios;
5. publicar build B de prueba;
6. abrir A y confirmar detección de B;
7. descargar, validar e instalar;
8. abrir B y confirmar versión/operación;
9. volver a abrir y confirmar silencio;
10. confirmar SHA de configuración idéntico;
11. alterar/publicar manifest de otro producto y confirmar que FEMAG no reacciona.

No mergear el PR hasta completar este E2E.

## Rollback

El release usa un asset estable reemplazable. Para rollback operativo se debe volver a publicar un installer FEMAG previamente validado y un manifest coherente con su SHA256 y versión. No reutilizar una versión inferior esperando downgrade automático: el cliente sólo instala versiones superiores. Si fuese necesario un rollback distribuido, publicar el código anterior con una nueva versión timestamp superior.
