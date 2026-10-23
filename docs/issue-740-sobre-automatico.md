# Issue #740 - PDF de sobres automático por cliente

## Estado

**implementado**, pendiente la prueba física con la Epson L3250.

El layout se ajustó el 21/10/2026 con el uso real de FEMAG: el sobre lleva el
destinatario arriba a la izquierda, la mercadería y la cantidad de pallets abajo
a la derecha y la referencia del presupuesto abajo a la izquierda, como lo
escribe Secretaría a mano. En ese mismo pedido, el sobre dejó de llevar el logo
por omisión (queda disponible para los puestos que lo pidan).

## Qué resuelve

Secretaría copiaba a mano del presupuesto el cliente, la dirección, el teléfono
y la cantidad de pallets para rotular el sobre. Ahora la aplicación genera el
PDF del sobre con esos datos, uno por presupuesto, en la misma operación en la
que genera los presupuestos.

## Dónde está

| Pieza | Archivo | Qué hace |
|---|---|---|
| Datos y render | `app/services/envelope_print_service.py` | Saca los datos del presupuesto y dibuja el PDF |
| Configuración del puesto | `app/config/envelope_settings.py` | Medidas, rotación, desplazamientos, impresora |
| Orquestación | `app/services/load_order_operation_service.py` | `export_envelopes(order, timing)` |
| Pantalla de órdenes | `app/ui/load_order_workspace_restore_extension.py` | El botón "Presupuesto" genera presupuestos **y** sobres |
| Cuenta corriente | `app/ui/customer_ledger.py` | Acción "Imprimir sobre" sobre un presupuesto guardado |
| Calibración | `scripts/generate_envelope_calibration_sheet.py` | Hoja de prueba con regla en milímetros |

## Cómo se usa

1. En **Órdenes de carga**, seleccionar la orden y apretar **Presupuesto**.
   Salen los PDF de presupuesto (como antes, sin cambios) y, en la misma
   operación, un PDF de sobre por presupuesto. Los sobres se abren junto con
   los presupuestos, listos para imprimir.
2. Para reimprimir **un** sobre: en **Cuenta corriente**, seleccionar el
   movimiento y usar **Más acciones → Imprimir sobre**. No toca el presupuesto,
   ni el stock, ni la cuenta corriente.

Los archivos se escriben en la carpeta de impresiones de la orden, con nombre
`sobre_<cliente>_<presupuesto>.pdf` (por ejemplo `sobre_12_000073.pdf`), para
que la asociación cliente ↔ presupuesto ↔ sobre sea inequívoca. Una
reexportación vuelve al mismo archivo; un archivo ajeno con ese nombre no se
pisa.

## De dónde salen los datos

- **Cliente y teléfono**: del cliente del presupuesto.
- **Contacto**: del contacto del cliente, que va junto al teléfono
  (`Tel: 0371 4000001 - PERSONA DE CONTACTO`).
- **Domicilio**: del destino de la orden de carga para ese cliente. En un
  presupuesto manual, del domicilio principal del cliente.
- **Mercadería**: de los **renglones de la orden de carga** de ese destino:
  cantidad, unidad y producto (`100 kg Fecula A`). Es la mercadería
  despachada, la misma que usan el remito, los pallets y la liberación de
  costos. Se imprimen como máximo 6 renglones; si la orden tiene más, se avisa.
- **Pallets**: la cantidad de **pallets distintos** con mercadería asignada a
  un destino de ese cliente. No es la cantidad de renglones ni el id del pallet.
  Se escribe como `(1 pallet)` o `(3 pallets)`. Si un pallet comparte
  mercadería con otro cliente, se avisa.
- Si no hay domicilio, el sobre **no se genera** y se informa qué cliente es y
  por qué. No se inventa ningún dato: el teléfono o los pallets que falten se
  avisan y el sobre sale con lo que hay.

## Cómo queda el sobre

| Zona | Qué lleva |
|---|---|
| Arriba a la izquierda | Cliente, domicilio y teléfono con el contacto |
| Arriba a la derecha | Logo de FEMAG, solo si el puesto lo pide (`show_logo`) |
| Abajo a la derecha | Mercadería y `(N pallets)`, la mercadería subiendo desde el margen inferior |
| Abajo a la izquierda | `Presupuesto` y el número del presupuesto |

## Geometría del sobre

- Tamaño real: **235 × 120 mm** (23,5 × 12 cm), confirmado por FEMAG el
  20/10/2026. No es un sobre N.º 10.
- Página del PDF: 235 × 120 mm en horizontal, que es el sobre visto en
  horizontal. Con rotación 90°/270° la página pasa a 120 × 235 mm, que es el
  mismo papel descrito en el otro sentido.
- El contenido se dibuja siempre en horizontal y después se rota, así que el
  texto queda legible al retirar el sobre, sin importar la rotación.
- Desplazamientos X/Y en milímetros, independientes entre sí.

## Configuración del puesto

Archivo `%LOCALAPPDATA%\FEMAG Desktop\envelope.json`:

```json
{
  "version": 1,
  "envelope_width_mm": 235.0,
  "envelope_height_mm": 120.0,
  "rotation_deg": 0,
  "offset_x_mm": 0.0,
  "offset_y_mm": 0.0,
  "margin_mm": 12.0,
  "printer_name": "",
  "copies": 1,
  "show_logo": false,
  "show_budget_reference": true,
  "show_pallet_count": true
}
```

Es un archivo del puesto, como el de apariencia (`appearance.json`): se escribe
de forma atómica y un archivo a medias no impide que la aplicación abra (vuelve
a los valores de fábrica).

## Calibración con la Epson L3250

1. Generar la hoja de calibración:

   ```powershell
   python scripts/generate_envelope_calibration_sheet.py
   ```

   Sale `outputs/envelopes/sobre_calibracion.pdf`, con el contorno del sobre,
   los márgenes, una regla en milímetros y un bloque de dirección de ejemplo.

2. En la Epson L3250, cargar el sobre **235 × 120 mm** por la bandeja trasera,
   centrado, **por el borde corto**, e imprimir a **escala 100 %** (nunca
   "ajustar a página").

3. Si el texto sale girado o corrido, ajustar `rotation_deg` (0/90/180/270) y
   `offset_x_mm` / `offset_y_mm` en `envelope.json`, y volver a imprimir la
   hoja hasta que coincida.

4. Cerrar el issue recién con la prueba física hecha: hasta entonces la
   rotación y los desplazamientos quedan como configuración, no como un valor
   comprobado.

## Lo que falta (pendiente real)

- **Prueba física con la Epson L3250 y el sobre real.** Es la condición de
  cierre del issue. La geometría está implementada y probada por software
  (página de 235 × 120 mm, rotaciones 90/270 y desplazamientos en mm), pero la
  rotación y el offset definitivos los define el equipo real.
- **Vista previa editable en la pantalla** (el issue la menciona como
  "vista previa editable solo para impresión cuando falten datos"). Hoy la
  vista previa es el PDF mismo, que se abre en el visor; si faltan datos se
  avisa por pantalla en vez de permitir corregirlos en un formulario.
- **Impresión directa a la impresora.** Hoy la app genera el PDF y lo abre; no
  manda trabajos a la impresora ni abre diálogos de impresión, a propósito
  (el issue pide que no se manden trabajos sin acción de Secretaría).
