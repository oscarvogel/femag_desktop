# Producción y stock — diseño funcional y técnico

## Objetivo

Incorporar a FEMAG Desktop el circuito de recepción de materia prima proveniente del sistema legacy `femagfab` y, a partir de snapshots propios, construir producción teórica, producción real, movimientos de stock, ajustes e información gerencial.

El sistema legacy queda como **fuente de solo lectura** para la recepción. FEMAG Desktop no debe escribir en `femagfab`.

## Fuente legacy confirmada

La recepción se registra en `femagfab.movi`. El ticket `COMP` es PK y contiene proveedor, fecha, producto, bruto, tara, neto, descuentos, `TOTALK`, tres rindes, promedio, `FECULA`, precio/saldo y fecha de pago.

Maestros relacionados:
- `proveedo(CODIGO, NOMBRE, ...)`
- `productos(CODIGO, NOMBRE, PRECIO, minimo_kg)`
- `producto_proveedor`
- `valores`
- `lote`

El análisis del VFP detectó que `FECULA` no es confiable como producción teórica: puede haberse calculado con el `TOTALK` anterior al cierre del ticket. Por ello debe conservarse como valor legacy/auditoría y calcularse en FEMAG:

```
fecula_teorica_kg = TOTALK_final * PROMEDIO / 100
```

## Arquitectura objetivo

```
femagfab.movi (solo lectura)
        |
        v
Recepciones importadas / snapshots
        |
        +--> producción teórica
        |
        v
Producción real por turno/lote
        |
        v
Libro de movimientos de stock
        |
        +--> producción / compras / importaciones
        +--> despachos
        +--> ajustes / inventario
        |
        v
Reportes gerenciales
```

## Etapa 1 — Importación de recepciones

Crear una segunda conexión MySQL configurable y estrictamente read-only hacia `femagfab`.

Pantalla: **Producción > Importar recepciones**.

El usuario selecciona fecha y obtiene una previsualización con ticket, proveedor, producto, kg liquidables, rindes, promedio, fécula legacy, fécula teórica calculada y estado de importación.

Candidato inicial:
- `TARA > 0`
- `TOTALK > 0`
- `PROMEDIO > 0`
- producto/proveedor existentes

No exigir `FECULA > 0`, `SALDO > 0` ni ausencia de pago.

Persistir un snapshot propio, sin FK directa al origen. Identidad externa propuesta:
`<source_instance>:femagfab:movi:<COMP>`.

Guardar un hash del contenido relevante. Reimportación:
- misma clave + mismo hash: sin cambios;
- clave nueva: nuevo;
- misma clave + hash distinto: modificado en origen, requiere conciliación explícita.

Nunca borrar ni sobrescribir silenciosamente por cambios/desapariciones del legacy.

Totales de previsualización:
- cantidad de tickets;
- kg netos/liquidables;
- kg teóricos;
- rinde ponderado = SUM(TOTALK * PROMEDIO) / SUM(TOTALK).

## Etapa 2 — Producción real

Registrar fecha, turno, producto terminado, lote, presentación, cantidad producida y kg reales. La producción real, no la teórica, será la que origine una entrada física de stock.

Comparar producción teórica con producción real. Antes de cerrar este diseño debe confirmarse si la materia prima recibida se procesa siempre el mismo día; si existe arrastre/WIP, vincular recepciones a una corrida/orden/lote de producción en vez de comparar solamente por fecha.

## Etapa 3 — Libro de stock

Crear movimientos inmutables/auditables. Tipos iniciales:
- INVENTARIO_INICIAL
- PRODUCCION
- COMPRA
- IMPORTACION
- DESPACHO
- AJUSTE_POSITIVO
- AJUSTE_NEGATIVO

El saldo se deriva de movimientos; no se mantiene como único número mutable.

Los despachos existentes deberán descontar stock únicamente al alcanzar el evento operativo definido (no al crear presupuesto/borrador).

## Etapa 4 — Inventario y ajustes

Permitir conteo físico por producto/lote. El ajuste registra stock de sistema, conteo físico, diferencia, motivo, observación, usuario y fecha. Nunca reescribir movimientos históricos para hacer coincidir el saldo.

## Etapa 5 — Gerencial y costos

Indicadores:
- materia prima recibida;
- rinde teórico ponderado;
- producción teórica;
- producción real;
- diferencia y porcentaje de desvío;
- rinde real;
- stock por producto/lote;
- ajustes;
- evolución histórica.

Luego podrá incorporarse costo fabril por kg real producido. No confundirlo con el costo comercial aplicado que FEMAG Desktop ya utiliza en rentabilidad.

## Decisiones y límites

1. `femagfab` es origen de lectura, no base compartida de trabajo.
2. No reutilizar automáticamente códigos de `proveedo` como proveedores FEMAG ni `productos` como productos comerciales: requieren mapeo explícito cuando sea necesario.
3. Conservar `FECULA` legacy, pero no usarla como verdad productiva.
4. Producción teórica no aumenta stock físico.
5. Producción real sí aumenta stock.
6. El MVP inicial no modifica órdenes, remitos ni el circuito comercial.
7. Implementar por PRs pequeños y verificables, sin mezclar etapas.

## Validación del MVP de importación

Antes de avanzar a producción real, seleccionar al menos un día operativo real y cotejar:
- tickets contra VFP;
- bruto/tara/neto/TOTALK;
- rindes/promedio;
- cálculo teórico;
- proveedor/producto;
- reimportación idéntica;
- ticket modificado;
- ticket incompleto.

La etapa 1 se considera validada cuando FEMAG reproduce correctamente los datos de recepción y sus totales sin modificar `femagfab`.
