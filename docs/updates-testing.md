# Prueba manual de actualizaciones

1. Instalar una build con este mecanismo.
2. Publicar una build posterior mediante `Publish FEMAG production release`.
3. Abrir la build anterior.
4. Verificar aviso de nueva versión.
5. Descargar.
6. Confirmar que se valida SHA256.
7. Ejecutar el Setup y verificar que FEMAG se cierra antes de instalar.
8. Verificar que la nueva instalación conserva la configuración MySQL del puesto.
9. Reabrir FEMAG y confirmar que ya no vuelve a ofrecer la misma actualización.

## Prueba E2E 2026-08-28

Release de prueba destinado exclusivamente a validar el circuito completo del actualizador en un puesto real: detección de versión, descarga, validación SHA256, cierre de FEMAG, ejecución del instalador y conservación de la configuración existente.
