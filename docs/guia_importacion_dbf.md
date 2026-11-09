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

Desde la app de escritorio:

1. Abrir `Importación DBF` en el menú lateral.
2. Elegir los DBF disponibles para clientes, transportistas, choferes, camiones o productos.
3. Confirmar `Encoding` y `Sistema origen`.
4. Ejecutar `Importar DBF` y revisar el resumen por entidad.

Para los DBF observados del sistema anterior, `chofer.dbf` puede no informar el
transportista. En ese caso el chofer se importa con estado `Sin asignar`; su
campo `CUIT` se conserva como CUIT propio del chofer y no se usa para inferir
una relacion con `transporte.dbf`. El transportista debe asignarse manualmente
desde Maestros antes de usar ese chofer en una orden de carga.

Desde consola:

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
- No inferir transportistas por coincidencias de `CODIGO` o `CUIT`: una
  referencia explicita inexistente se informa como error y una referencia
  ausente deja al chofer sin asignar.

## Advertencias y revisión manual

Cada corrida guarda en `ImportBatch.summary` un bloque `warning_summary` con:

- `total_warnings` y `total_errors`.
- `by_code`: cantidad por código.
- `by_classification`: `expected` (conflicto esperable del DBF), `review` (requiere revisión manual) y `bug`.
- `manual_review`: lista de filas para revisar, con entidad, código, `source_id` y acción sugerida.

| Código | Clasificación | Acción |
|---|---|---|
| `client_cuit_shared_by_two_rows` | esperada | El legacy repite CUIT; el importador absorbe una fila. |
| `client_cuit_taken_by_another_row` | esperada | El CUIT ya pertenece a otro cliente; se conserva el original. |
| `carrier_code_collision` | revisar | Asignar el transportista correcto desde Maestros. |
| `carrier_not_found` | revisar | Asignar el transportista desde Maestros. |
| `carrier_cuit_ambiguous` | revisar | Definir cuál transportista corresponde. |
| `truck_trailer_conflict` | esperada | Se conservó el acoplado del operador; revisar sólo si cambió. |
| `truck_carrier_conflict` | esperada | Se conservó el transportista del camión; revisar sólo si cambió. |
| `habitual_truck_missing` | esperada | El chofer no trae patente habitual. |
| Error de fila | revisar | Dato obligatorio faltante o choque de clave; corregir el origen. |

La pantalla de Importación DBF muestra el total y separa “esperadas” de “para revisar”. El detalle por entidad y código sigue en el resumen y en el tooltip de la tabla.

## Entidades posteriores

- #166 cubre remitos historicos desde DBF.
- #167 cubre saldos iniciales legacy a cuenta corriente.
