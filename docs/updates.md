# Actualizaciones de FEMAG

FEMAG consulta el manifest público:

`https://raw.githubusercontent.com/oscarvogel/vogel-releases/main/apps/femag/latest.json`

El instalador publicado es siempre el resultado final de Inno Setup:

`FEMAG_Desktop_Produccion_Setup.exe`

## Primer despliegue

La versión que incorpora este mecanismo debe distribuirse una última vez por el procedimiento manual actual. Las instalaciones anteriores no conocen el canal de actualización.

Desde esa versión en adelante, FEMAG consulta el manifest al iniciar, avisa si existe una versión superior, descarga el instalador público, valida SHA256 y permite ejecutarlo.

## Publicación

El workflow `Publish FEMAG production release` se ejecuta manualmente desde GitHub Actions. Requiere el secret `VOGEL_RELEASES_TOKEN`, con permiso de escritura sobre `oscarvogel/vogel-releases`.

El workflow:

1. ejecuta tests;
2. compila con PyInstaller;
3. genera el Setup con `installer/FEMAG_Desktop.iss`;
4. calcula SHA256;
5. reemplaza `FEMAG_Desktop_Produccion_Setup.exe` dentro del único release `latest`;
6. actualiza `apps/femag/latest.json`.

No se conservan instaladores históricos.

## Fallos de red

Una falla de Internet, GitHub o del manifest no debe impedir el inicio ni el uso de FEMAG. El chequeo se ejecuta en segundo plano y se omite silenciosamente si no puede completarse.
