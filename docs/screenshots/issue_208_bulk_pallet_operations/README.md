# Evidencia visual — issue #208

Capturas reproducibles de las operaciones masivas del compositor de pallets:

1. `01_19_tarjetas_agregadas.png`: alta de 19 tarjetas vacías en una acción.
2. `02_asignacion_masiva_previa.png`: vista previa de 10 pallets y cantidad por pallet.
3. `03_10_pallets_asignados.png`: asignación aplicada a los pallets 1 a 10.
4. `04_asignaciones_limpiadas.png`: asignaciones vaciadas conservando las 19 tarjetas.

Comando:

```powershell
python scripts/generate_issue_208_screenshots.py
```

Los datos se crean en una SQLite en memoria y no se conectan a bases reales.
