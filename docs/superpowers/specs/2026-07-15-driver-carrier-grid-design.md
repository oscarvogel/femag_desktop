# Diseño: transportista asignado en la grilla de choferes

## Contexto

El ABM guarda correctamente el transportista seleccionado al crear o editar un chofer, pero la grilla muestra `Sin asignar`. La consulta actual usa un `LEFT JOIN` sin incluir las columnas de `Carrier` en la selección. Peewee materializa entonces la relación unida sin el identificador del transportista.

## Alcance

- Corregir únicamente la consulta que alimenta la grilla de choferes.
- Mostrar el nombre del transportista cuando existe una asignación.
- Mantener `Sin asignar` para choferes legacy cuyo `carrier_id` sea nulo.
- No modificar modelos, migraciones, formularios ni otras pantallas.

## Diseño

`_driver_rows()` seleccionará explícitamente ambos modelos mediante `Driver.select(Driver, Carrier)` y conservará el `LEFT OUTER JOIN`. De esta forma Peewee hidrata tanto la clave foránea del chofer como el nombre del transportista, sin excluir registros legacy.

Se descarta quitar el join porque produciría una consulta adicional por cada fila. También se descarta reescribir la grilla con tuplas o aliases SQL porque amplía innecesariamente el cambio.

## Validación

La prueba existente `test_drivers_abm_page_creates_edits_with_carrier_combo` debe fallar antes del cambio y pasar después. También debe continuar pasando `test_driver_abm_lists_and_opens_unassigned_driver`. Finalmente se ejecutarán la suite completa, `compileall`, el smoke de la aplicación y `git diff --check`.

## Riesgo

Bajo. El cambio afecta solamente la lectura de la grilla del ABM de choferes y no altera datos persistidos.
