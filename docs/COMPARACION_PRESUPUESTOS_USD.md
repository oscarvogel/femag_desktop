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
- detalle por presupuesto.

Tambien se puede exportar un Excel con **todos los tipos** desde el mismo
dialogo.

## Excel

Hojas:

1. `Resumen`: una fila por tipo con totales y cobertura.
2. `Oficial`, `Blue`, `MEP`, `CCL`, `Mayorista`, `Tarjeta`, `Banco Nacion`:
   detalle por presupuesto.
3. `Productos`: detalle por item de presupuesto con cantidad, precio unitario
   ARS, cotizacion, precio unitario USD y total USD. Permite comparar productos
   y cantidades equivalentes.
4. `Sin_cotizacion`: presupuestos que no pudieron convertirse.
5. `Criterio`: rango, fuente, punta, formula y regla de faltantes.

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

## Pendiente

- #974: indicadores gerenciales mas amplios en ARS/USD.
- Pantalla web del dashboard gerencial: por ahora el acceso es la app de
  escritorio.
