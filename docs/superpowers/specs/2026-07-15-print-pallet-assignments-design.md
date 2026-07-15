# Diseño: kilos y pallets asignados en la orden PDF

**Issue:** #181

## Objetivo

Corregir la presentación del total de mercadería y reemplazar el reparto proporcional de pallets por las asignaciones reales persistidas.

## Diseño aprobado

- Los kilos se formatean con separador decimal argentino, sin ceros finales: `300 kg`, `300,5 kg`, `1.250,75 kg`.
- Para cada fila de cliente/destino, se consultan las asignaciones de sus productos. Se muestran las secuencias de pallet distintas, ordenadas y separadas por coma: `1`, `1, 3`.
- Si una misma secuencia contiene varios productos de la fila, aparece una sola vez.
- La fila `TOTALES` muestra la cantidad de pallets que tienen asignaciones efectivas para la orden, con texto singular/plural (`1 pallet`, `3 pallets`).
- No se modifican cantidades, kilos persistidos, modelos ni composición.

## Alternativas descartadas

- Mantener el reparto proporcional: inventa una relación que ya existe en las asignaciones.
- Mostrar el total de pallets en cada fila: no identifica dónde está la mercadería.
- Sumar números de pallet en `TOTALES`: los identificadores no son magnitudes sumables.

## Validación

- Pruebas unitarias del formato de kilos.
- PDF con productos repartidos entre más de un pallet y extracción de texto.
- Suite del servicio de impresión, compileall y smoke.
