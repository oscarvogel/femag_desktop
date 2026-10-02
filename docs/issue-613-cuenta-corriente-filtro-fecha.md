# Issue #613 - Cuenta corriente: filtro por fecha en los movimientos

- **GitHub:** https://github.com/oscarvogel/femag_desktop/issues/613
- **Estado:** IMPLEMENTADO (rama `feat/issue-613-cuenta-corriente-filtro-fecha`, pendiente de PR)
- **Base auditada e implementada:** `main` @ `26f435f`
- **Worktree de trabajo:** `C:\Programacion\dante\femag_desktop-613` (aislado)
- **Registrado:** 2026-10-02

## Contexto

La grilla de movimientos de Cuenta corriente no tenia forma de acotar el periodo:
los unicos filtros (busqueda, "Solo con saldo", Vendedor) aplican a la **lista de
clientes** de la izquierda, no a los **movimientos** de la derecha. Para un cliente
con movimientos a lo largo de un ano no se podia responder "cuanto me debio el
trimestre pasado" sin recorrer la tabla a mano.

## La regla que define el diseno

**El filtro acota filas, no recalcula saldos.**

Si se filtrara "Desde 01/04/2026" y el saldo se recalculara desde cero dentro del
rango, la primera fila visible mostraria un saldo que **no existe en la contabilidad
del cliente** y dejaria de cuadrar con el saldo del encabezado.

Con la regla elegida, la columna Saldo de cada fila visible es el **acumulado real
del cliente a esa fecha**, y el saldo del encabezado no se mueve al filtrar. Por
eso el filtro devuelve el indice original del movimiento: el saldo ya estaba
calculado por `running_balance()` y no se toca.

Implementacion en `app/ui/customer_ledger.py`:

```python
def _visible_movements(movements):
    # devuelve (movimiento, indice_original) -> el saldo sale de balances[indice]
```

## Decisiones

| Tema | Decision |
|---|---|
| Alcance | Solo la grilla de movimientos. La lista de clientes, la Cartera, el Vencido y los reportes de #609 no cambian |
| Semantica del Saldo | Se sigue acumulando desde el origen. No se recalcula |
| Patron de UI | `QCheckBox` + `QDateEdit` con `calendarPopup`, formato `dd/MM/yyyy`, etiquetas Desde/Hasta: el mismo de `collection_due_report.py`, `daily_collections.py` y `audit_query_page.py` |
| Estado inicial | Desactivado. Sin filtro la pantalla se ve identica a hoy |
| Movimientos sin `movement_date` | Se filtran por `created_at`, la misma regla que usa la columna Fecha |
| Contador | Con filtro activo: "N de M movimientos" |
| Costo | Filtrar repinta sobre el cache. No vuelve a consultar la base, igual que la busqueda y el vendedor |

## Archivos

### Agregados
- `tests/test_issue_613_ledger_movement_date_filter.py` - 15 tests.
- `scripts/generate_issue_613_screenshot.py` - evidencia visual (ver limitacion abajo).
- `docs/issue-613-cuenta-corriente-filtro-fecha.md` - este registro.

### Modificados
- `app/ui/customer_ledger.py` +137 / -9. Un solo archivo de aplicacion.

El unico cambio de comportamiento fuera del filtro es la extraccion del dibujado
de la grilla a `_render_movements()`, necesaria para repintar sin recargar. No se
toco la grilla de saldos, la cartera ni los reportes.

## Criterios de aceptacion

- [x] Filtro Desde / Hasta sobre la grilla de movimientos.
- [x] Sin filtro, la pantalla se ve exactamente como hoy.
- [x] Con filtro, solo se ven los movimientos del periodo.
- [x] La columna Saldo no se recalcula (test que compara contra el acumulado completo).
- [x] El saldo del encabezado no cambia al filtrar.
- [x] Movimientos sin `movement_date` se filtran por `created_at`.
- [x] Cambiar de cliente conserva el filtro.
- [x] Limpiar el filtro restituye todas las filas.
- [x] Periodo sin movimientos muestra el estado vacio.
- [x] El filtro no altera la lista de clientes ni los totales.
- [x] Filtrar no vuelve a consultar los movimientos.
- [x] Sin `float` nuevo: el saldo sigue viniendo del acumulado de la pantalla.

## Tests

- `tests/test_issue_613_ledger_movement_date_filter.py` - **15 passed**
- Suite completa: ver la medicion de abajo

## Medicion: el cambio es neutro

La suite de este proyecto tiene fallas preexistentes y dependientes del orden de
ejecucion. Se midio el antes y el despues **en el mismo worktree, con el mismo
entorno**, guardando los cambios con `git stash`:

| Medicion | Resultado |
|---|---|
| `main` limpio, suite completa | 46 failed / 1031 passed |
| `main` + este cambio, suite completa | 46 failed / **1046** passed |
| `main` limpio, 3 archivos de UI isolados | 18 failed / 45 passed |
| `main` + este cambio, los mismos 3 archivos | 18 failed / 45 passed |

La diferencia de la suite completa son exactamente los **15 tests nuevos, todos en
verde**, y las mismas 46 fallas antes y despues. En isolé se reproducen igual sin el
cambio: son preexistentes.

Ademas, el worktree del #609 dio **1111 passed / 0 failed** a las 08:5x y
**46 failed / 1065 passed** a las 09:2x **sin que su codigo cambiara**. Las 46 no
son una propiedad de ningun branch: son contaminacion por orden de ejecucion.

- Las fallas de la suite completa se reparten en 20 archivos de UI
  (`test_load_order_desktop_ui` 14, `test_customer_ledger_ui` 5, y 18 mas).
- Aisladas son reproducibles y estables, con y sin este cambio.

**Candidatos、住宅** (medidos, no confirmados):
`conftest.db` reutiliza una `SqliteDatabase(":memory:")` a nivel de modulo entre tests
(`create_tables` / `drop_tables` por test), lo que deja estado compartido; y el bug de
fechas de abajo rompe la inicializacion de paginas de UI.

**No se afirma** que la suite este verde en esta maquina: no lo estaba antes de este
cambio tampoco.

## Bug preexistente encontrado (NO lo causa #613)

Al correr los tests y los scripts de captura aparecieron fallas que se
reprodujeron igual en `main` limpio:

**`created_at` vuelve como `str` desde SQLite.**

`BaseModel.created_at` es `DateTimeField(default=utc_now)` y `utc_now()` devuelve un
datetime **aware** (`datetime.now(timezone.utc)`). peewee lo persiste como
`2026-06-15 10:00:00+00:00`; al releerlo, sus formatos por defecto
(`'%Y-%m-%d %H:%M:%S.%f'`, `'%Y-%m-%d %H:%M:%S'`) no contemplan el offset, el parseo
falla y el campo queda como `str`. Entonces:

- `customer_ledger._display_datetime()` revienta con
  `AttributeError: 'str' object has no attribute 'tzinfo'`.
- Lo mismo en `app/utils/datetime_utils.py:14` (`utc_datetime_to_local`).

Alcance real: **solo cuando un objeto se relee de la base y su `movement_date` es
NULL** (por ahi se cae a `created_at`). En la app de verdad casi no se nota porque
los movimientos de la base demo tienen `movement_date`. En los tests y en los
scripts de captura, que releen de la base, se dispara siempre.

Efectos observados, **todos preexistentes en `main`**:

1. Seis tests de `test_customer_ledger_ui.py` y `test_issue_512_ledger_document_detail.py`
   fallan al correrlos aislados y pasan en la suite completa (dependientes del orden).
2. `scripts/generate_issue_581_screenshot.py` no corre en este entorno.

**No se corrigio en este issue**: es otro defecto, en otra area, y meterlo aqui
mezclaria dos cosas en un PR chico. La evidencia visual del #613 tampoco se pudo
generar por esto; el script queda en el worktree siguiendo el precedente del #581.

## Validaciones ejecutadas

| Comando | Resultado |
|---|---|
| `python -m pytest tests/test_issue_613_ledger_movement_date_filter.py` | **15 passed** |
| `git diff --check` | exit 0 |
| `python -m compileall app` | exit 0 |
| `python -m app.main --smoke` | `FEMAG smoke OK` |
| `python -m pytest` (suite completa, antes/despues) | ver la medicion de arriba |

## Riesgos

1. **Los reportes de #609 siguen imprimiendo todos los movimientos.** El filtro es de
   pantalla, no de impresion. Decision consciente del solicitante: el reporte es una
   foto de la cartera, no de un periodo.
2. **Rendimiento:** ninguno. Filtrar repinta el cache; hay un test que lo verifica
   interceptando `movements_for_client`.
3. **Sin evidencia visual** por el bug preexistente de arriba. La garantia de que el
   saldo no se recalcula esta cubierta por test automatizado, que es mas fuerte que
   una captura.

## Pendientes

- [ ] Abrir y revisar el PR.
- [ ] Probar en el puesto con un cliente que tenga movimientos de varios meses.
- [ ] Issue aparte: corregir la lectura de `created_at` / `occurred_at` desde SQLite.
- [ ] Issue aparte: los seis tests dependientes del orden de la lista de arriba.
- [ ] Corregir el fallo preexistente de `test_webapp_qr_orders.py` (falta `flask`).

---

## Bitacora

| Fecha | Que se hizo |
|---|---|
| 2026-10-02 | Auditoria: no habia ningun filtro por `movement_date` ni `due_date`. |
| 2026-10-02 | Consultada la decision de alcance: el filtro acota solo los movimientos, no la cartera. |
| 2026-10-02 | Issue #613 creado y worktree aislado desde `main` limpio. |
| 2026-10-02 | TDD: 15 tests antes de implementar. |
| 2026-10-02 | Implementacion: widgets, `_visible_movements()` y `_render_movements()`. |
| 2026-10-02 | Dos expectativas de test propias estaban mal (hora en la columna Fecha y visibilidad en offscreen); se corrigieron, no el codigo. |
| 2026-10-02 | Confirmado que 6 tests de la suite existente fallan igual en `main` limpio. |
| 2026-10-02 | Hallazgo del bug preexistente de `created_at` como `str`. |
| 2026-10-02 | Medido el antes/despues de la suite completa con `git stash`: mismas 46 fallas, +15 tests en verde. |
| 2026-10-02 | Se descarto la hipotesis de que las 46 fallas venian de la base demo ausente: se reproducen con y sin ella, y tambien en el worktree del #609 sin cambios de codigo. |
| 2026-10-02 | Se confirmo que en isolé las fallas son preexistentes y estables (18/45 antes y despues). |
