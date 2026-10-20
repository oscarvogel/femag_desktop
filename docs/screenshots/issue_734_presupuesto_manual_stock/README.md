# #734 — El presupuesto manual descuenta el stock

El presupuesto manual es la segunda puerta por la que la mercadería sale de la
planta, después del despacho de la orden de carga. Antes no tocaba el libro de
stock: en la base real hay **19 presupuestos manuales** (14 clientes, del 21/09
al 14/10) y ninguno dejó rastro en el libro. Toda esa mercadería salió de la
planta y el aviso de stock insuficiente de #732 no la veía.

Desde #734, el presupuesto manual descuenta el stock de la mercadería, y si no
alcanza aparece **el mismo aviso** que en el despacho: el faltante por producto
y un motivo obligatorio. Con el motivo, el presupuesto se crea y la decisión
queda asentada en la auditoría y en los movimientos del libro.

## Qué muestra cada captura

- `presupuesto_manual_stock.png` — el diálogo de "Nuevo presupuesto manual" con
  la nota que dice qué renglones **no** descuentan stock: el FLETE no sale del
  depósito, y un producto sin peso de bolsa cargado no se puede convertir a
  kilos. La mercadería que sí descuenta, lo hace.
- `aviso_stock_insuficiente_presupuesto.png` — el aviso de faltante, el mismo
  que en el despacho de la orden de carga: stock en el libro, lo que pide la
  operación, lo que falta, y el motivo obligatorio.

## Cómo se generaron

```bash
python scripts/generate_issue_734_screenshot.py
```

Base SQLite en memoria con datos sintéticos: **ningún dato real entra en la
evidencia**. La plataforma es `windows` y no `offscreen` para que el texto se
dibuje (#652).
