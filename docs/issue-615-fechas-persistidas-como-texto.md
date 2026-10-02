# Issue #615 - Las fechas persistidas llegan como texto y hay que coerciarlas

- **GitHub:** https://github.com/oscarvogel/femag_desktop/issues/615
- **Estado:** IMPLEMENTADO (rama `fix/issue-615-fechas-persistidas-como-texto`, pendiente de PR)
- **Base auditada e implementada:** `main` @ `26f435f`
- **Worktree:** `C:\Programacion\dante\femag_desktop-615` (aislado)
- **Registrado:** 2026-10-02

## Contexto

Apareció al trabajar el #613: los scripts de captura de UX no corren y varios tests
de UI fallan con `AttributeError: 'str' object has no attribute 'tzinfo'`.

## Causa raiz

`BaseModel.created_at` / `updated_at` son `DateTimeField(default=utc_now)` y
`utc_now()` devuelve `datetime.now(timezone.utc)`, o sea un datetime **aware**.

peewee 3 serializa ese valor como texto **con el offset**:

```
peewee 3.17.8 -> created_at vuelve como str = '2026-10-02 12:44:59.974192+00:00'
```

peewee 3 no lo parsea al leerlo, asi que el atributo llega como `str`. Todos los
call sites que le hacen `.tzinfo`, `.astimezone()` o `.strftime()` reventan.

**No es deriva de version:** el proyecto pide `peewee>=3.17` y hay 3.17.8. peewee 3
simplemente no parsea offsets UTC. peewee 4 si lo hace (ver #616).

## Decision: coerce en el borde, no tocar el modelo

Se agrega `as_datetime()` en `app/utils/datetime_utils.py` y se aplica en los
lugares que dan formato a una fecha persistida.

La alternativa descartada: cambiar `utc_now()` para devolver naive. No sirve, porque
las filas ya guardadas en la base traen el offset y seguirian rotas, y ademas es un
cambio de comportamiento del modelo (area protegida).

La coercion **repara el tipo, no la semantica**: si el texto trae offset, el
resultado queda *aware*; si no, queda *naive*. Cada call site sigue aplicando su
misma regla de zona horaria de siempre.

## Call sites

### Se arreglan con un solo cambio en `utc_datetime_to_local()`
- `app/ui/audit_query_page.py` — la ventana **no abria**
- `app/ui/audit_history_dialog.py`
- `app/ui/financial_history_dialog.py`
- `app/ui/remittance_history_dialog.py`

### Aplican el helper
- `app/ui/customer_ledger.py` `_display_datetime` (columna Fecha sin `movement_date`)
- `app/services/payment_receipt_print_service.py` `_display_datetime` (2do duplicado)
- `app/services/account_statement_print_service.py` `_movement_date`
- `app/ui/aviso_center.py` fecha del aviso
- `app/ui/master_abm.py` historial de costo de producto

Habia **3 copias** de `_display_datetime` con la misma logica. No se unificaron (queda
pendiente); lo que se hizo es que las tres hagan la coercion.

## Archivos

### Modificados
- `app/utils/datetime_utils.py` — `as_datetime()` + coercion en `utc_datetime_to_local()`.
- `app/ui/customer_ledger.py` — `import` + coercion.
- `app/services/payment_receipt_print_service.py` — `import` + coercion.
- `app/services/account_statement_print_service.py` — `import` + coercion.
- `app/ui/aviso_center.py` — `import` + coercion.
- `app/ui/master_abm.py` — `import` + coercion.

### Agregados
- `tests/test_issue_615_persisted_datetime_as_text.py` — 13 tests.
- Este registro.

**Sin cambios** en el modelo, el esquema, los datos ni la logica contable.

## Efecto comprobable

`scripts/generate_issue_581_screenshot.py` **vuelven a correr**. Antes de este fix
moria con el mismo `AttributeError`; despues genera las dos capturas. Era el
comprobante de que el bug estaba donde dijeron los tests y no en otra parte.

Eso tambien desbloquea la evidencia visual del #613, que no se podia generar.

## El fix no es neutro: repara tests que estaban rotos

Medido en el **mismo worktree** con `git stash`, sobre tres archivos de UI:

| | Resultado |
|---|---|
| `main` limpio | 22 failed / 47 passed |
| con este fix | **69 passed / 0 failed** |

Los 22 que fallaban ahora pasan (47 + 22 = 69). Cero regresiones.

En la suite completa el efecto se ve igual: de **46 failed / 1031 passed** a
**6 failed / 1084 passed**. De las 53 pasadas de mas, 13 son los tests nuevos y el
resto es el fix reparando los tests que reventaban con el mismo `tzinfo`.

**Salvedad honesta:** la linea base de la suite completa (46 / 1031) se midio en el
worktree del #613, no en este. En este, la corrida de `main` limpio **se colgo**
(8 minutos con 3,5 s de CPU: un test de UI abre un modal y queda esperando). La
comparacion **aislada** si es del mismo worktree y es la que sostiene la afirmacion.

## Tests

- `tests/test_issue_615_persisted_datetime_as_text.py` — **13 passed**
  - `as_datetime` con `datetime`, `date`, texto con offset, texto sin offset, texto
    vacio y `None`.
  - Que la coercion **preserva** el caracter aware/naive.
  - `utc_datetime_to_local` con texto y con naive (no cambia la zona horaria).
  - Objetos **releidos de la base** (donde el valor llega como texto) en columna
    Fecha, ventana de auditoria, dialogo de historial, recibo anulado y extracto.

Se verifico que los objetos releidos de la base llegan efectivamente como `str`
(`assert isinstance(desde_base.created_at, str)`), asi que los tests ejercitan el
caso real y no un mock.

## Pendientes

- [ ] Abrir y revisar el PR.
- [ ] Unificar los 3 duplicados de `_display_datetime` (issue aparte).
- [ ] Revisar el impacto del `sql_mode` de MySQL con peewee 4 (#616).
- [ ] Arreglar por separado el bug de `ensure_runtime_schema()` que deja la base
      inutilizable (mencionado en #616).
- [ ] Corregir el fallo preexistente de `test_webapp_qr_orders.py` (falta `flask`).

---

## Bitacora

| Fecha | Que se hizo |
|---|---|
| 2026-10-02 | Bug detectado mientras se cerraba el #613, en los scripts de captura y tests de UI. |
| 2026-10-02 | Confirmado empiricamente que peewee 3.17.8 devuelve `str` con el offset UTC. |
| 2026-10-02 | Verificado que el proyecto pide `>=3.17`: no es deriva de version. |
| 2026-10-02 | Issue #615 creado, worktree aislado, TDD con 13 tests. |
| 2026-10-02 | Helper implementado y aplicado en los 6 archivos. |
| 2026-10-02 | Corregidos 4 errores propios de test (imports y firmas reales de los widgets). |
| 2026-10-02 | `scripts/generate_issue_581_screenshot.py` vuelve a correr: comprobante del fix. |
| 2026-10-02 | Issue #616 abierto para la migracion a peewee 4. |
