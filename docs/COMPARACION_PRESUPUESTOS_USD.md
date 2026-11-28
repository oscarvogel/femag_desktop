# Comparacion de presupuestos ARS/USD (#973)

Informe de solo lectura que convierte los presupuestos a dolares usando la
cotizacion de su fecha. No modifica `budget`, no crea asientos y no toca
remitos, F150 ni ordenes de carga.

## Regla

```text
USD = total ARS / cotizacion (ARS por 1 USD)
```

- Cada hoja usa **un solo tipo** (`oficial`, `blue`, `mep`, `ccl`, `mayorista`,
  `tarjeta`, `bna`) y **una sola fuente**.
- La punta es seleccionable: venta, compra o promedio.
- Se usa la cotizacion exacta de la fecha del presupuesto.
- Si no existe, se puede usar la inmediata anterior; queda marcada como
  `Anterior` con su fecha efectiva, fuente y version.
- Si no hay ninguna, el presupuesto queda `Sin cotizacion`, no se convierte a
  cero y se excluye del total USD, informando la cobertura.
- Los presupuestos anulados se excluyen por defecto; hay un check para
  incluirlos.

## Acceso

En **Dashboard gerencial** hay una tarjeta **Presupuestos USD** con el total
convertido y la cobertura para `blue`, y un boton **Comparacion USD**.

Abre una ventana con:

- tipo de dolar;
- fuente;
- punta;
- rango de fechas;
- incluir anulados;
- permitir cotizacion anterior;
- resumen de ARS, USD, cotizacion promedio ponderada y cobertura;
- evolucion mensual en ARS y USD, con variacion contra el mes anterior;
- comparativo por tipo contra `blue` (diferencia USD y %);
- detalle por presupuesto.

Tambien se puede exportar un Excel con **todos los tipos** y generar un
**HTML autocontenido con graficos** para abrirlo directamente en el navegador
o guardarlo como archivo, desde el mismo dialogo.

El HTML incluye:

- grafico de barras de presupuestos ARS por mes;
- grafico de barras de presupuestos USD por mes;
- grafico horizontal de total USD por tipo;
- tablas de evolucion, comparativo, resumen y detalle;
- faltantes.

Es un archivo `.html` con CSS y SVG embebidos: no necesita Internet ni
dependencias para abrirse. El boton **Ver informe en el navegador** genera el
archivo en la carpeta temporal de FEMAG y lo abre automaticamente, sin pedir
ruta ni guardado manual. **Guardar HTML** conserva la opcion de elegir donde
guardarlo.

## Excel

Hojas:

1. `Resumen`: una fila por tipo con totales y cobertura.
2. `Evolucion_mensual`: ARS y USD por mes, variacion ARS/USD contra el mes anterior y cobertura.
3. `Comparativo_tipos`: total USD de cada tipo y diferencia contra `blue`.
4. `Oficial`, `Blue`, `MEP`, `CCL`, `Mayorista`, `Tarjeta`, `Banco Nacion`:
   detalle por presupuesto.
5. `Productos`: detalle por item de presupuesto con cantidad, precio unitario
   ARS, cotizacion, precio unitario USD y total USD. Permite comparar productos
   y cantidades equivalentes.
6. `Sin_cotizacion`: presupuestos que no pudieron convertirse.
7. `Criterio`: rango, fuente, punta, formula y regla de faltantes.

Columnas del detalle: fecha, numero, cliente, estado, origen, total ARS,
cotizacion, fecha efectiva, fuente, version, fallback, cobertura, total USD y
observacion.

## Pruebas

- Exacta, anterior y sin cotizacion.
- Compra, venta y promedio.
- Independencia de fuentes.
- Presupuestos anulados incluidos/excluidos.
- Precision `Decimal`.
- Exportacion Excel con resumen y una hoja por tipo.
- Dialogo y acceso desde el dashboard.

## Dashboard web

El snapshot gerencial de la fabrica incluye un bloque opcional `budget_usd` con
los mismos agregados del informe: rango analizado, totales ARS/USD, cobertura,
evolucion mensual y total USD por tipo contra `blue`. Se muestra en `/gerencia`
como **Presupuestos en dolares**.

Solo viajan agregados: no se publican clientes ni numeros de presupuesto. Si el
bloque no esta presente (snapshot viejo o fabrica sin presupuestos/rates), la
seccion no se renderiza.

## Pendiente

- Deploy de la webapp con el bloque `budget_usd`.
- Validacion en fabrica del dashboard web y del informe HTML.
