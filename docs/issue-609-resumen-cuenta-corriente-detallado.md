# Issue #609 - Cuenta corriente: reporte por vendedor resumido o detallado

- **GitHub:** https://github.com/oscarvogel/femag_desktop/issues/609
- **Estado:** IMPLEMENTADO (rama `feat/issue-609-resumen-vendedor-detallado`, pendiente de PR)
- **Base auditada e implementada:** `main` @ `26f435f`
- **Worktree de trabajo:** `C:\Programacion\dante\femag_desktop-609` (aislado; el checkout principal quedo intacto)
- **Registrado:** 2026-10-02

## Hilo al que continua

- #581 (cerrado) - accion "Resumen de cartera (PDF)" por vendedor en PDF + WhatsApp + correo.
- #547 / #551 (cerrados) - fotografia de cartera y filtros por vendedor sin recalcular.
- #602 (cerrado) - columna Saldo con ancho fijo en la grilla.

Este issue **agrega la segunda lectura del mismo reporte**: el detalle que explica
como se compone cada saldo.

---

## Contexto

La accion de Cuenta Corriente que resume la cartera de un vendedor imprime una
fila por cliente (nombre, CUIT, saldo) y un total. Al compartir ese PDF, el
vendedor ve **cuanto** se le debe, pero no **por que**.

Se pidio poder generar el mismo reporte en dos versiones:

- **Resumido**: exactamente el reporte de hoy.
- **Detallado**: vendedor > cliente > movimientos, con la composicion del saldo.

## Auditoria: como funciona realmente hoy

Antes de escribir codigo se leyo el circuito existente. Esto es lo que hay:

| Pieza | Ubicacion real |
|---|---|
| Accion en la UI | `app/ui/customer_ledger.py:315` "Resumen de cartera (PDF)", dentro de la seccion `Resumen del vendedor` (`customer_ledger.py:301`) del menu que abre el boton **Acciones ▾** (`customer_ledger.py:124`) |
| Generador del PDF resumido | `app/services/salesperson_portfolio_print_service.py` |
| Generador del PDF por cliente | `app/services/account_statement_print_service.py` |
| Datos que ve la pantalla | `app/services/ledger_query_service.py` -> `client_portfolio_rows()` (filas de cartera) y `movements_for_client()` + `running_balance()` (detalle) |
| Cableado de impresion/envio | `app/ui/desktop_app.py:788` `_export_salesperson_portfolio` |

**Fuente de verdad de los saldos:** `ledger_query_service`. El resumen del #581
ya consumia `client_portfolio_rows()` y **no** recalculaba nada. El detalle de la
fila y el extracto usan `movements_for_client()` + `running_balance()`. Eso es lo
que reutiliza este issue.

### Diferencias entre lo que dice el issue y lo que hace el codigo

No son errores del issue, pero cambian el alcance. Quedan documentadas para que
el PR no prometa algo que el sistema no hacia.

1. **Ruta del menu.** El issue dice `Más acciones > Resumen por vendedor`. En el
   codigo el boton es **Acciones ▾** y la accion se llama **"Resumen de cartera
   (PDF)"**, dentro de la seccion "Resumen del vendedor". Se extendio esa accion;
   no se creo una nueva.

2. **El resumen tiene DOS totales, no uno.** Informa **DEUDA** (solo saldos
   positivos, el mismo numero que la "Cartera" de la barra lateral) y **TOTAL
   NETO** (suma de todas las filas, incluidos saldos a favor). La conciliacion
   "suma de clientes == total del vendedor" se hace contra **TOTAL NETO**; contra
   DEUDA no podria cerrar cuando hay clientes con saldo a favor.

3. **El reporte actual no agrupa por vendedor.** Con el filtro "Todos los
   vendedores" o "Sin asignar" imprime una sola lista de clientes. El detallado
   **si** agrupa, usando el `salesperson` real de cada cliente (dato que ya viene
   en la fila). No es un calculo nuevo: es presentacion del mismo filtro.

4. **La pantalla muestra el saldo por dos caminos.** La grilla izquierda usa
   `client_portfolio_rows()` (SUM en SQL con ROUND por movimiento) y el detalle de
   la fila usa el acumulado de `running_balance()`. El issue pide que el ultimo
   acumulado del PDF coincida con "el saldo que muestra la pantalla": los tests
   comparan contra **las dos** y exigen igualdad exacta. Ademas
   `client_portfolio_rows(as_of=...)` **no** filtra movimientos por fecha: `as_of`
   solo afecta `overdue` y `due_7`.

5. **Nombre de archivo.** El detallado lleva su propio nombre
   (`..._detallado_AAAAMMDD.pdf`) porque generar las dos versiones el mismo dia
   con el nombre anterior hacia que una pisara a la otra. El resumen conserva su
   nombre intacto.

### Hallazgo lateral: hay dos mapas de etiquetas de tipo de movimiento

- `customer_ledger.py:36` `MOVEMENT_TYPE_LABELS` - grilla, 10 tipos, textos cortos
  ("Orden de carga").
- `account_statement_print_service.py:37` `MOVEMENT_TYPE_LABELS` - extracto, 15
  tipos, mas descriptivos ("Orden de carga (facturado hoy)").

El detallado reutiliza **el del extracto**, que es el mas completo, para no sumar
una tercera lista. **No se unificaron**: quedaria fuera de alcance y tocaria la
pantalla.

---

## Regla critica: una sola fuente de verdad

No hay una segunda logica de saldos. El camino es:

```
client_portfolio_rows()            <- filas de la pantalla (resumen y detalle)
        |
        +--> movements_for_client()        <- movimientos cronologicos (con joins)
        |         |
        |         +--> running_balance_decimals()   <- UNICO acumulado
        |
        +--> running_balance()  = [float(x) for x in running_balance_decimals()]
```

`running_balance_decimals()` es la unica implementacion del saldo acumulado.
`running_balance()` -la que usa la grilla- ahora **delega** en ella y solo convierte
a `float` para pintar. Antes cada una tenia su propio bucle.

Sobre esa base se agrega `ledger_statement_detail.client_statement_detail()`, que
arma las filas del detalle en `Decimal` (debe, haber, saldo, vencimiento) sin
tocar los importes: los pide al mismo acumulado.

Lo que **no** se duplico:

| Regla | Donde vive | Que usa el detallado |
|---|---|---|
| Saldo acumulado | `running_balance_decimals()` | el ultimo valor de la lista |
| Saldo inicial, OC, pagos, debitos/creditos, notas | `ClientAccountMovement` | los movimientos que trae la pantalla |
| Vencimiento | `movement.due_date` | el mismo campo |
| Redondeo | `money_decimal()` (`ROUND_HALF_UP` a centimos) | el mismo |
| Etiqueta de tipo, referencia, descripcion | `_movement_type_label()`, `_reference()`, `_description()` del extracto | importadas, no reescritas |
| Formato de importes | `_format_money()` | importado |
| Reglas de debe/haber | `movement_debit_credit()` (signo, como la grilla) | unico lugar en el backend |

---

## Comportamiento implementado

### 1. Selector

La accion "Resumen de cartera (PDF)" abre un dialogo con `Resumido` / `Detallado`.
Cancelar no genera nada. Los filtros vigentes (busqueda, "Solo con saldo",
vendedor) se respetan igual que antes.

La eleccion queda en la pagina y la usan **los tres canales** (imprimir, WhatsApp y
correo), que comparten `_export_salesperson_portfolio()`. Arranca en `resumido`,
o sea el comportamiento actual. El asunto del correo agrega "(detallado)" solo en
ese caso; el resumen no cambia su asunto.

### 2. Resumido

Sin cambios de calculo, columnas ni semantica. El nombre del archivo y el
contenido son los de siempre.

### 3. Detallado

`VENDEDOR > CLIENTE > MOVIMIENTOS` con: fecha, tipo, referencia, descripcion,
debe, haber, saldo acumulado y vencimiento.

- El **encabezado del cliente viaja dentro de la tabla** (`repeatRows=2`), con su
  saldo actual. Por eso se repite en cada pagina y nunca queda un cliente al final
  de una pagina con sus movimientos en la siguiente.
- Al pie de cada vendedor, `TOTAL <VENDEDOR>`; al final, `TOTAL NETO CARTERA` con
  el **mismo** numero que el resumen, para que la conciliacion se vea en el papel.
- Los anchos de columna estan calculados para que no se partan ni un importe con
  miles, ni una referencia de pago, ni el rotulo "VENCIMIENTO".

### Caso de regresion obligatorio

Fixture de **FRIGORIFICO EL BIERZO SA** con 7 movimientos (debito manual, cuatro
ordenes de carga, dos pagos). Secuencia de saldos acumulados verificada:

| # | Fecha | Movimiento | Debe | Haber | Saldo |
|---|---|---|---|---|---|
| 1 | 31/08/2026 | Debito manual | 50.100.000,00 | | 50.100.000,00 |
| 2 | 04/09/2026 | OC-000006 | 9.300.000,00 | | 59.400.000,00 |
| 3 | 11/09/2026 | OC-000017 | 18.972.000,00 | | 78.372.000,00 |
| 4 | 14/09/2026 | Pago REC-00000117 | | 9.300.000,00 | 69.072.000,00 |
| 5 | 17/09/2026 | OC-000026 | 11.383.200,00 | | 80.455.200,00 |
| 6 | 25/09/2026 | OC-000042 | 11.952.400,00 | | 92.407.600,00 |
| 7 | 25/09/2026 | Pago REC-00000118 | | 9.300.000,00 | **83.107.600,00** |

El test verifica la **secuencia completa en orden**, no solo el saldo final, en el
servicio y en el texto del PDF.

---

## Archivos

### Agregados
- `app/services/ledger_statement_detail.py` - detalle por cliente en `Decimal`
  sobre el flujo de la pantalla.
- `app/services/salesperson_portfolio_detail_service.py` - PDF detallado.
- `tests/test_issue_609_ledger_statement_detail.py` - 9 tests del servicio comun.
- `tests/test_issue_609_portfolio_detail_report.py` - 16 tests del PDF, conciliaciones
  y regresion.
- `tests/test_issue_609_portfolio_report_type_ui.py` - 9 tests del selector.
- `docs/issue-609-resumen-cuenta-corriente-detallado.md` - este registro.

### Modificados
- `app/services/ledger_query_service.py` - `running_balance_decimals()` (acumulado
  unico), `running_balance()` ahora delega; `money_decimal()` y
  `movement_debit_credit()`.
- `app/services/salesperson_portfolio_print_service.py` - constantes de tipo de
  reporte y `export_salesperson_portfolio_report()` (unico punto de entrada). El
  resto intacto.
- `app/services/account_statement_print_service.py` - `_balance_block()` acepta
  `label` (default "SALDO ACTUAL"): el comportamiento del extracto no cambia.
- `app/ui/customer_ledger.py` - selector Resumido/Detallado y `report_type` en el
  resumen. No se toco la grilla de movimientos.
- `app/ui/desktop_app.py` - el export unico y el asunto de correo.

---

## Criterios de aceptacion

- [x] `Resumido` equivale al reporte actual (nombre de archivo y contenido iguales).
- [x] `Detallado` lista clientes agrupados por vendedor.
- [x] Cada cliente muestra los movimientos que explican su saldo.
- [x] Los pagos aparecen y bajan el saldo acumulado.
- [x] Debitos y creditos manuales aparecen.
- [x] Las ordenes de carga aparecen con referencia `OC-000000` y vencimiento.
- [x] El ultimo acumulado de cada cliente coincide **exacto** con la pantalla
      (contra `client_portfolio_rows()` y contra `running_balance()`).
- [x] La suma de saldos por cliente coincide **exacta** con el TOTAL NETO del
      vendedor en el resumen.
- [x] Sin diferencias de redondeo y sin `float` en importes del detalle.
- [x] PDF multipagina legible, con encabezado de cliente y columnas repetidos.
- [x] No se duplico la implementacion de las reglas de cuenta corriente.

---

## Bugs y hallazgos durante la implementacion

| Hallazgo | Como se detecto | Como se resolvio |
|---|---|---|
| `Decimal.quantize(-2)` con exponente entero **redondea a multiplo de -2**, no a 2 decimales: `detail_total` devolvia `-210052575` en vez de `-210052575.34` | Test de conciliacion fallo con la diferencia de 34 centavos | Los helpers usan `money_decimal()`, el redondeo compartido del proyecto |
| La columna VENCIMIENTO (15 mm) partia el rotulo en dos lineas y rompia la lectura del PDF | Test multipagina: `'VENCIMIENTO' in page` fallo | Anchos recalculados (182 mm utiles) y celda a 6,2 pt |
| Una referencia larga (`AJUSTE-2026-08`) se partia en dos lineas | Inspección del PDF real generado, no del código | Columna REFERENCIA a 22 mm |
| La busqueda del "primer importe del saldo" en el texto del PDF media el bloque de arriba, que ya imprime el TOTAL NETO | Test de la secuencia fallo con posiciones desordenadas | El test ancla la busqueda en el primer movimiento |
| `client_portfolio_rows(as_of=...)` no filtra movimientos por fecha: `as_of` solo afecta `overdue` y `due_7` | Lectura del codigo durante la auditoria | Documentado; el detallado no usa `as_of` |

---

## Validaciones ejecutadas

| Comando | Resultado |
|---|---|
| `git diff --check` | OK (exit 0) |
| `python -m compileall app` | OK (exit 0) |
| `python -m app.main --smoke` | `FEMAG smoke OK` |
| `python scripts/femag_operational_smoke.py` | `Smoke operativo FEMAG ejecutado`, orden cerrada, saldo final 0.00 |
| `python -m pytest` (tests nuevos del #609) | **34 passed** |
| `python -m pytest` (cuenta corriente / reportes / cartera) | **93 passed** |
| `python -m pytest` (suite completa) | **1111 passed, 0 failed** (4m46s) |
| `python scripts/generate_ux_screenshots.py` | no ejecutado: el cambio no agrega UI estatica (el selector es un dialogo modal) |

### Test que no se pudo ejecutar

`tests/test_webapp_qr_orders.py` no colecta en este entorno:
`ModuleNotFoundError: No module named 'flask'`. **Es previo a este cambio**: se
reprodujo igual en el checkout de `main` sin modificar. La suite completa se
corrio con `--ignore=tests/test_webapp_qr_orders.py`. Instalar `flask` y correr
ese archivo queda pendiente.

### Validacion contra la salida real

Se genero el PDF detallado de verdad y se inspecciono el texto extraido (no la
lectura del codigo). Secuencia de saldos acumulada del caso BIERZO:

```
31/08/2026  Debito manual        AJUSTE-2026-08  $ 50.100.000,00  $ 50.100.000,00
04/09/2026  Orden de carga       OC-000006       $  9.300.000,00  $ 59.400.000,00   04/09/2026
11/09/2026  Orden de carga       OC-000017       $ 18.972.000,00  $ 78.372.000,00   11/09/2026
14/09/2026  Pago                 REC-00000117    $  9.300.000,00  $ 69.072.000,00
17/09/2026  Orden de carga       OC-000026       $ 11.383.200,00  $ 80.455.200,00   17/09/2026
25/09/2026  Orden de carga       OC-000042       $ 11.952.400,00  $ 92.407.600,00   25/09/2026
25/09/2026  Pago                 REC-00000118    $  9.300.000,00  $ 83.107.600,00
TOTAL LUIS                        $ 83.107.600,00
TOTAL NETO CARTERA                 $ 83.107.600,00
```

Tambien se genero el PDF de 120 movimientos (6 paginas) para verificar que el
encabezado de cliente y las columnas se repiten en cada pagina con movimientos.

### Artefactos que la validacion toco y se restauraron

`docs/SMOKE_OPERATIVO_FEMAG.md` y
`docs/prints/issue_131_load_order_footer_cutoff/load_order_footer_at_min_height.png`
los regeneran los scripts de validacion; se restauraron con `git restore` para
que no entren en el PR.

---

## Riesgos

1. **Areas protegidas:** no se toco logica contable, saldos historicos, generacion
   de ordenes, presupuestos, pagos ni el informe gerencial diario. `running_balance()`
   keeps su firma y su resultado.
2. **Carga por cliente:** el detallado hace una consulta de movimientos por cliente
   del reporte. Es una accion explicita del operador (imprimir), no el render de la
   pantalla, asi que no toca el problema de rendimiento del #551. Con carteras de
   cientos de clientes el PDF puede tardar.
3. **Datos sensibles:** el PDF expone movimientos, no solo saldos. Revisar carpeta
   de salida antes de compartir.
4. **Envio por WhatsApp/correo:** ahora respetan el tipo elegido. Si se elige
   Detallado, el archivo enviado es el detallado.
5. **`_balance_block` compartido:** se le agrego un parametro `label` con default
   igual al texto anterior; el extracto no cambia.

## Pendientes

- [ ] Abrir y revisar el PR.
- [ ] Probar con la base demo real un vendedor con cartera grande (paginas y tiempo).
- [ ] Probar el envio real por WhatsApp y correo en modo Detallado.
- [ ] Unificar los dos mapas de etiquetas de tipo de movimiento (pantalla vs
      extracto) en un issue aparte.
- [ ] Corregir el fallo preexistente de `test_webapp_qr_orders.py` (falta `flask`
      en el entorno de pruebas).

---

## Bitacora

| Fecha | Que se hizo |
|---|---|
| 2026-10-02 | Auditoria de la accion real, el generador, la fuente de saldos y los tests. |
| 2026-10-02 | Detectado que el issue describe la ruta del menu con otro nombre y que el resumen tiene dos totales. Documentado. |
| 2026-10-02 | Worktree aislado desde `main` limpio en `femag_desktop-609`. |
| 2026-10-02 | TDD: `running_balance_decimals()` y `ledger_statement_detail` con 9 tests. |
| 2026-10-02 | TDD: PDF detallado con 16 tests, incluida la regresion de BIERZO. |
| 2026-10-02 | TDD: selector y despacho con 9 tests. |
| 2026-10-02 | PDF real generado e inspeccionado para ajustar anchos de columna. |
