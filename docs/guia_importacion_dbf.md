# Guia de importacion DBF legacy

Este documento cubre el primer corte de importacion DBF de maestros vinculado a #165.

## Alcance

El importador inicial acepta DBF legacy para:

- Clientes.
- Transportistas.
- Choferes.
- Camiones.
- Productos.

Quedan fuera de este corte remitos historicos, F150 real, saldos iniciales y cualquier conexion a datos productivos.

## Ejecucion

Configurar la base destino de FEMAG con las variables habituales y ejecutar solo las entidades disponibles:

```bash
python scripts/import_legacy_dbf_masters.py --clients C:\legacy\clientes.dbf --products C:\legacy\productos.dbf
```

Opciones utiles:

```bash
python scripts/import_legacy_dbf_masters.py --encoding cp1252 --source-system legacy_dbf --carriers C:\legacy\transportistas.dbf
```

El comando imprime un resumen JSON con creados, actualizados, omitidos y errores por entidad.

## Trazabilidad

Los maestros importados guardan:

- `source_system`.
- `source_id`.
- `imported_at`.
- `updated_from_source_at`.
- `last_import_batch_id`.

Cada corrida crea un `ImportBatch` con estado y resumen.

## Validacion segura

- Usar primero fixtures sinteticos o copias anonimizadas fuera del repo.
- Confirmar encoding real de los DBF antes de produccion.
- Confirmar nombres de campos legacy antes de una corrida operativa.
- No guardar DBF reales en el repositorio.

## Entidades posteriores

- #166 cubre remitos historicos desde DBF.
- #167 cubre saldos iniciales legacy a cuenta corriente.
