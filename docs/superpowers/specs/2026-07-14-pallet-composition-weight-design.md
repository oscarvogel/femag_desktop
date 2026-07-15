# Diseño: composición de pallets y cálculo de kilos

**Issue:** [#178](https://github.com/oscarvogel/femag_desktop/issues/178)
**Estado:** diseño aprobado
**Alcance:** artículos, composición de pallets y alta/modificación de órdenes de carga

## Objetivo

Conocer qué mercadería lleva cada pallet y calcular de manera confiable los kilos por pallet y el total transportado por una orden de carga. El total representa exclusivamente el peso neto de la mercadería; no incluye tara de pallets.

## Decisiones funcionales

- El artículo guarda el peso neto en kg de una unidad.
- El peso puede ser `0 kg` para mantener compatibilidad con artículos existentes o importados; ese valor significa «peso pendiente».
- Cada pallet representa una unidad física individual y recibe un número secuencial dentro de la orden.
- Un pallet puede contener uno o varios artículos de uno o varios clientes y destinos.
- Una línea de mercadería puede distribuirse entre varios pallets.
- Una orden pendiente puede guardarse con distribución incompleta.
- Una orden no puede emitirse mientras tenga cantidades pendientes, cantidades excedidas o artículos asignados con peso cero.

## Modelo de datos

### Artículo

`Product` incorpora `peso_unitario_kg`, decimal no negativo con valor inicial cero. El ABM de artículos permite cargarlo y modificarlo, y el listado lo muestra con una indicación clara cuando está pendiente.

### Pallet individual

`LoadOrderPallet` deja de representar una cantidad agregada de pallets y representa un pallet físico individual. Incluye un número secuencial único dentro de la orden. La presentación al usuario es `Pallet 1`, `Pallet 2`, etc.

La compatibilidad de datos existentes debe resolverse durante la evolución del esquema sin perder registros. Las filas agregadas existentes deben transformarse o interpretarse de forma explícita en la implementación; no se aceptará una conversión silenciosa que altere cantidades.

### Composición

Se agrega una entidad normalizada de asignación de mercadería a pallet. Cada asignación contiene:

- pallet;
- destino de la orden, que determina cliente y lugar de entrega;
- artículo;
- cantidad asignada;
- peso unitario en kg usado al asignar;
- kilos calculados.

El peso unitario se copia a la asignación para preservar la consistencia histórica si la ficha del artículo cambia posteriormente. La línea de mercadería de la orden continúa siendo la fuente de verdad de la cantidad solicitada; las asignaciones solo distribuyen esa cantidad.

## Cálculos

- Kilos de una asignación: `cantidad asignada × peso unitario en kg`.
- Kilos de un pallet: suma de los kilos de sus asignaciones.
- Kilos de una orden/camión: suma de los kilos de todos sus pallets.
- Cantidad pendiente: cantidad solicitada menos cantidad asignada, agrupada por destino y artículo.

Los cálculos de peso y cantidad usan tipos decimales para evitar errores acumulativos de punto flotante. El peso físico del pallet no interviene.

## Reglas de integridad

- El peso unitario del artículo no puede ser negativo.
- La cantidad de una asignación debe ser mayor que cero.
- Una asignación debe referenciar un destino y artículo presentes en la orden.
- La suma asignada para cada combinación destino/artículo no puede superar la cantidad solicitada.
- Una distribución puede quedar incompleta únicamente mientras la orden sea editable y no emitida.
- La emisión requiere que cada combinación destino/artículo esté completamente asignada.
- La emisión se bloquea si cualquier asignación usa un peso unitario igual a cero.
- Si se modifica la mercadería solicitada, las asignaciones válidas se conservan y cualquier excedente queda marcado para corrección antes de emitir.

## Flujo de usuario

1. El usuario carga clientes, destinos y mercadería solicitada.
2. Agrega pallets; el sistema los numera automáticamente.
3. Selecciona un pallet y asigna cliente/destino, artículo y cantidad.
4. La pantalla recalcula kilos de línea, pallet, pendientes y total de orden en tiempo real.
5. Puede guardar la orden pendiente aunque la distribución no esté completa.
6. Para emitir, debe corregir pendientes, excedentes y pesos en cero.

## Interfaz aprobada

La pantalla de alta y modificación usa una grilla de tarjetas cuadradas, una por pallet. Cada tarjeta muestra:

- número del pallet;
- kilos en tipografía dominante;
- cantidad de artículos y clientes;
- estado visual.

Estados:

- verde: composición completa y válida;
- amarillo: incompleta o con pesos pendientes;
- rojo: excedida o inválida.

Una tarjeta `+ Agregar pallet` crea el siguiente número. Al seleccionar una tarjeta se abre un panel lateral sin ocultar el resto de la carga. El panel permite elegir destino, artículo y cantidad, y muestra la composición completa, kilos del pallet y cantidades pendientes.

El total de kilos de la orden permanece siempre visible, grande y destacado mientras se crea o modifica. Junto al total se muestra el resumen `X pallets · Y completos · Z pendientes`.

## Errores y mensajes

Los mensajes deben identificar la combinación concreta que requiere corrección, por ejemplo:

- `Cliente A / Depósito / Artículo X: faltan asignar 12 unidades`.
- `Pallet 3 excede en 4 unidades lo solicitado para Artículo X`.
- `Artículo X tiene peso pendiente (0 kg)`.

Guardar un borrador incompleto informa el estado sin tratarlo como error. Intentar emitir una orden incompleta presenta el resumen de bloqueos y mantiene la pantalla editable.

## Compatibilidad y límites

- Artículos existentes e importados reciben `0 kg` cuando la fuente no aporta peso.
- Los importadores legacy conservan su comportamiento fuera del nuevo valor por defecto.
- No se modifica lógica fiscal, remitos reales, F150 ni integraciones legacy ajenas a la compatibilidad necesaria.
- No se agrega tara o peso propio del pallet.
- No se reemplaza `pyqt5libs` ni se modifica esa dependencia externa.

## Validación

La implementación debe cubrir:

- peso del artículo y compatibilidad con cero;
- varios clientes y artículos en un pallet;
- una línea distribuida entre varios pallets;
- cálculos por asignación, pallet y orden;
- pendientes, excedentes y pesos en cero;
- guardado de borrador incompleto;
- bloqueo de emisión incompleta;
- creación y modificación de órdenes;
- smoke visual con grilla, panel lateral y total destacado.

Comandos mínimos:

```powershell
git diff --check
python -m pytest
python -m compileall app
python -m app.main --smoke
python scripts/generate_ux_screenshots.py
```

Si el generador de capturas no cubre la pantalla nueva, se debe extender dentro del alcance o documentar evidencia visual manual equivalente.

## Fuera de alcance

- Peso o capacidad máxima configurada por camión.
- Tara de pallet, camión o acoplado.
- Optimización automática de distribución.
- Reordenamiento automático de pallets por ruta.
- Cambios fiscales o de facturación.
