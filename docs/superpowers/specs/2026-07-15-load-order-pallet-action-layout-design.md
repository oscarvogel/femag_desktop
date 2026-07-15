# Diseño: acción de pallets compacta y consulta de solo lectura

**Issue:** #180

**Alcance:** pantalla de Órdenes de carga y diálogo de preparación de pallets.

## Problema

La tabla inserta una fila expandida con `setSpan()` para mostrar el detalle de la orden seleccionada. Al reconstruir el contenido, los spans anteriores pueden sobrevivir y convertir una fila operativa posterior en una celda de ancho completo. Cuando esa fila contiene la acción `Ver pallets`, el botón aparece como una franja gigante debajo del detalle.

Además, el texto `Ver pallets` se usa cuando la composición está completa, pero el botón solo está habilitado para órdenes pendientes. En órdenes emitidas, cerradas o anuladas la interfaz promete una consulta que no permite abrir.

## Diseño aprobado

1. Antes de reconstruir las filas, la tabla eliminará sus spans y widgets anteriores. Cada orden volverá a ocupar una fila normal y solo la fila de detalle seleccionada abarcará todas las columnas.
2. La acción seguirá dentro de la columna `Acción`:
   - `Armar pallets`: orden pendiente sin pallets; abre edición.
   - `Continuar`: orden pendiente con preparación incompleta; abre edición.
   - `Ver pallets`: orden con pallets y estado no editable; abre consulta.
3. `LoadOrderPalletDialog` aceptará un modo explícito de solo lectura. En ese modo:
   - mostrará la composición persistida;
   - no permitirá agregar, quitar ni modificar pallets o mercadería;
   - no mostrará una acción de guardado;
   - ofrecerá únicamente cerrar la ventana.
4. Las órdenes sin pallets y no editables no ofrecerán una acción engañosa.

## Alternativas descartadas

- **Ocultar pallets en estados finales:** evita cambios, pero impide consultar información operativa histórica.
- **Abrir siempre el editor:** mantiene una sola ruta, pero permitiría alterar órdenes emitidas, cerradas o anuladas.
- **Mover la acción a un panel inferior:** repite el problema de jerarquía observado y duplica controles existentes.

## Pruebas

- Regresión que cambia la selección y refresca la tabla, verificando que ninguna fila operativa conserve un span completo.
- Acción compacta y habilitada como `Ver pallets` para una orden final con composición existente.
- Diálogo de consulta sin controles mutables ni guardado.
- Conservación de `Armar pallets` y `Continuar` para órdenes pendientes.
- Suite completa, `compileall`, smoke y captura visual de la tabla reparada.

## Fuera de alcance

- Modelos, migraciones y estructura de base de datos.
- Cálculo de kilos y reglas de composición.
- Remitos, F150, importación legacy y lógica fiscal.
- Rediseño general de la pantalla de Órdenes de carga.
