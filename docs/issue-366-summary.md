# Issue #366

Implementado en la rama `feat/issue-366-auto-updates`.

- Manifest público en `vogel-releases`.
- Comparación por versión `AAAA.MM.DD.HH.MM.SS`.
- Chequeo no bloqueante al iniciar FEMAG.
- Descarga del instalador final de Inno Setup.
- Validación SHA256 antes de ejecutar.
- Workflow manual para publicar al release único `latest`.
- Requiere configurar `VOGEL_RELEASES_TOKEN` en GitHub Actions antes de la primera publicación automática.
