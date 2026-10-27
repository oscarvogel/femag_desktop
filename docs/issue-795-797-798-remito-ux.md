# Remitos: orden de transporte, combos F2 y total general

Bitácora de la línea de trabajo que integra los issues #795, #797 y #798 sobre
`app/ui/remittances.py` y `app/ui/desktop_app.py`.

- Rama: `fix/issue-795-remito-orden-transporte`
- PR: #796 hacia `main`
- Base actualizada: `origin/main` al merge del PR #799 (`8aa642a`)
- Sin merge ni generación de instalador en esta etapa.

## #795 - Chofer primero y transporte agrupado

### Cambio

En `RemittanceDialog` el bloque de transporte quedó en el orden visual y de
tabulación pedido:

`Chofer -> Transportista -> Camión -> Acoplado`

- `Chofer` es el primer control del bloque.
- `Acoplado` salió de la fila de Fecha / N.º remito y quedó agrupado con el
  transporte.
- Se fijó el orden de Tab con `QWidget.setTabOrder`.
- Se mantuvo la cascada del PR #758: al elegir chofer se completan transportista,
  camión habitual (o único del transportista) y patente del acoplado. La patente
  escrita a mano sigue prevaleciendo.

### Pruebas

- `tests/test_remittance_ui.py`: orden visual en la grilla, ubicación del
  acoplado fuera de la fila de fecha/número y navegación con Tab.
- Evidencia: `docs/screenshots/issue-795-remito-orden-transporte/`.

## #797 - Combos con escritura inmediata y búsqueda F2

### Componente reutilizable

`app/ui/combo_autocomplete.py` incorpora `SearchableComboBox`, que extiende el
autocompletado existente y agrega:

- selección de todo el texto al recibir foco o al hacer clic, para escribir
  directamente sin borrar;
- separación estricta entre texto de búsqueda e ID confirmado: `currentData()`
  devuelve `None` si el texto visible no coincide con el ítem del índice;
- restauración del valor confirmado al salir del campo sin elegir una opción;
- búsqueda alfabética con F2 en `ComboSearchDialog`, con filtro incremental,
  orden sin tildes/mayúsculas, columnas contextuales, selección con Enter o
  doble clic y cancelación con Escape sin cambiar el valor anterior;
- opción `preserve_unmatched` para el domicilio de Órdenes de carga, donde el
  texto nuevo se conserva para el alta de un destino.

### Integración inicial

- Remitos: cliente, domicilio, chofer, transportista, camión y producto por
  renglón. Los combos nuevos arrancan sin preselección arbitraria; «Sin asignar»
  sigue disponible en la lista pero ya no ocupa el campo.
- Órdenes de carga: chofer, transportista, camión, acoplado, cliente, domicilio
  y producto del diálogo de alta/edición.
- Se conservaron IDs, dependencias y cascadas existentes. Una selección
  programática o confirmada sí dispara las reglas de negocio; un clic que solo
  selecciona texto no modifica datos.
- Al abrir un borrador se conservan exactamente los IDs guardados hasta que el
  operador confirme otro valor.
- No se extendió el componente al resto de los combos de FEMAG.

### Pruebas

`tests/test_issue_797_combo_search.py` (11 pruebas):

- placeholder sin selección arbitraria;
- clic que selecciona todo y escritura que no expone el ID anterior;
- restauración del valor confirmado al salir con texto no confirmado;
- confirmación de texto exacto;
- orden alfabético, filtro por columna y aceptación con Enter en F2;
- Escape/F2 cancelado sin cambios;
- remitos y órdenes nuevos sin preselección;
- F2 de chofer en Remitos y Órdenes con cascada de transporte;
- edición de borrador que conserva los IDs guardados.

### Evidencia

- `docs/screenshots/issue-797-798-remito-ux/01_remito_nuevo_sin_preseleccion.png`
- `docs/screenshots/issue-797-798-remito-ux/03_busqueda_f2_chofer.png`
- `docs/screenshots/issue-797-798-remito-ux/06_orden_nueva_sin_preseleccion.png`
- `docs/screenshots/issue-797-798-remito-ux/07_orden_busqueda_f2_chofer.png`

## #798 - Total general en vivo

### Cambio

En el diálogo de remitos se agregó una franja fija debajo del detalle:

- `TOTAL GENERAL` con importe grande y alineado a la derecha;
- columna `Subtotal` por renglón;
- cálculo `cantidad × precio unitario` por renglón con `Decimal`, cuantizado a
  dos decimales con el criterio del sistema (`quantize_money`, `ROUND_HALF_UP`)
  y suma con `money_sum`;
- actualización inmediata al editar cantidad, precio, agregar o quitar renglones;
- cálculo correcto al abrir un borrador;
- los renglones incompletos o inválidos se marcan como `Revisar` y el total
  general muestra `$ —` con un aviso, para no enseñar una cifra engañosa;
- sin cambios en PDF, impresión, F150, modelos ni emisión.

### Pruebas

`tests/test_issue_798_remittance_total.py` (5 pruebas):

- total inicial `$ 0.00` y columna Subtotal;
- actualización por cantidad, precio, alta y baja de renglones;
- caso 2 × $1.500 + 3 × $2.000 = $9.000;
- redondeo monetario con `Decimal`;
- renglón incompleto señalizado;
- borrador abierto con total y subtotales correctos.

### Evidencia

- `docs/screenshots/issue-797-798-remito-ux/01_remito_nuevo_sin_preseleccion.png`
- `docs/screenshots/issue-797-798-remito-ux/02_remito_total_en_vivo.png`
- `docs/screenshots/issue-797-798-remito-ux/04_remito_total_tema_oscuro.png`
- `docs/screenshots/issue-797-798-remito-ux/05_remito_borrador_total.png`

## Validaciones ejecutadas

| comando | resultado |
|---|---|
| `python -m pytest tests/test_remittance_ui.py tests/test_combo_autocomplete.py tests/test_load_order_desktop_ui.py tests/test_issue_272_load_order_trailer.py tests/test_issue_319_product_code.py tests/test_issue_522_client_deactivation.py tests/test_issue_797_combo_search.py tests/test_issue_798_remittance_total.py tests/test_issue_793_price_list_selection.py -q` | `166 passed` |
| `python -m pytest -q` | `2091 passed, 3 skipped` (7:22) |
| `python -m compileall app webapp` | exit 0 |
| `python -m app.main --smoke` | `FEMAG smoke OK` |
| `python scripts/generate_issue_797_798_remito_ux_screenshot.py` | 7 capturas |

Las validaciones se repitieron después de integrar el `main` actualizado del
PR #799, sin conflictos en los archivos de remitos, combos ni órdenes.

## Fuera de alcance

- No se modificaron impresión de remitos, PDF, F150, emisión ni bases de datos.
- No se cambió la lógica de liquidaciones ni otros módulos.
- No se hizo merge del PR #796 ni se generó instalador.
