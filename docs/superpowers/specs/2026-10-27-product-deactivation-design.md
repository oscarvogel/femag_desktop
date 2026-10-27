# Baja de productos desde el ABM — Issue #809

## Intención
Permitir que Administración inactive y reactive productos desde Maestros > Productos, sin editar SQL y sin borrar referencias históricas.

## Estado actual y causa
`Product.active` ya existe y la grilla muestra Activo/Inactivo. Los selectores operativos ya filtran por `active=True`, pero `MasterService` no tiene un cambio de estado para Product y el ABM de Productos no presenta una acción para ejecutarlo. El ABM de Clientes ofrece un patrón equivalente de baja lógica y auditoría.

## Alcance y límites
- Agregar una acción separada y contextual para el producto seleccionado: “Dar de baja” o “Reactivar”.
- Exigir permiso de modificación de Productos, selección de fila y confirmación antes de persistir.
- Persistir solo `Product.active`, registrar auditoría con valor anterior/nuevo y actualizar la grilla.
- Conservar los registros de órdenes/remitos históricos y el producto en los informes históricos.
- No modificar costos, precios, modelos, migraciones, datos, reportes ni los flujos de remitos.

## Enfoques considerados
1. **Acción separada en la pantalla (elegido):** “Dar de baja” para activos y “Reactivar” para inactivos. La acción es visible y explícita, y una confirmación reduce errores.
2. **Estado editable dentro del diálogo del producto:** comparte el formulario de edición, pero la baja queda menos visible y se mezcla con cambios de ficha.

Se elige el primer enfoque, de acuerdo con lo conversado con el usuario.

## Criterios de aceptación
- Sin producto seleccionado, la acción avisa y no modifica datos.
- Para activo, el botón dice “Dar de baja”; para inactivo, “Reactivar”.
- Cancelar la confirmación no escribe ni audita.
- Confirmar actualiza el estado, deja auditoría y refresca la fila.
- Productos inactivos siguen fuera de nuevos selectores operativos y permanecen en los antecedentes históricos.

## Validación
Tests enfocados de servicio y UI del ABM; `git diff --check`; `python -m pytest`; `python -m compileall app`; `python -m app.main --smoke`. Revisar visualmente la pantalla si el entorno de UI lo permite.

## Riesgo y decisión aprobada
La baja afecta la disponibilidad en futuras operaciones; no corrige ni elimina datos de ventas pasadas. El usuario aprobó el botón separado de baja/reactivación antes de implementar.
