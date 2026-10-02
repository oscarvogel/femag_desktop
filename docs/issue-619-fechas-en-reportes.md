# Issue #619 - Quedan call sites del bug de fechas en logica de negocio y reportes

- **GitHub:** https://github.com/oscarvogel/femag_desktop/issues/619
- **Estado:** IMPLEMENTADO (rama `fix/issue-619-fechas-en-reportes`, pendiente de PR)
- **Registrado:** 2026-10-02

## Contexto

El #615 corrigio el bug de "las fechas persistidas llegan como texto" en los **sitios de
presentacion**. Su auditoria busco por nombres de campo (`created_at`, `occurred_at`,
`updated_at`) y se dejo afuera los sitios de **logica de negocio y reportes**, que llaman
metodos de `datetime` igual de directo.

Aparecieron al pinear peewee a 3.x (#618): el CI paso de 1102 passed / 0 failed (peewee
4.5.2) a **6 failed / 1133 passed** (peewee 3.17.8).

## Call sites corregidos

| Archivo | Que rompia |
|---|---|
| `app/services/load_order_return_credit_service.py` | `closure.closed_at.date()` al generar la nota de credito por devolucion |
| `app/reports/returns_report.py` | `closure.closed_at.date()` en el informe de devoluciones |
| `app/reports/daily_collections.py` (x4) | `payment.annulled_at.date()` al filtrar y armar anulaciones |
| `app/importers/femagfab.py` | `received_at.isoformat()` sobre un valor tomado de una fila cruda |

Los 7 usan `as_datetime()` de `app/utils/datetime_utils.py`, que ya introdujo el #615.

## Por que importa mas de lo que parece

Con peewee 4.5.2 (lo que corre hoy el CI) todo esto **pasa desapercibido**. Con 3.17.8 (lo
que corre en los puestos y en produccion), una devolucion con credito puede reventar al
generar la nota, y los informes de cobranzas diarias y de devoluciones al filtrar
anulaciones. Eran bugs reales en produccion que el CI no podia ver.

## Tests

- `tests/test_issue_619_datetime_in_reports.py` - 3 tests, escritos antes del fix.
  - `test_cobranzas_diarias_usa_la_fecha_de_anulacion_que_llega_texto`: pasa
    `annulled_at` **como texto** y reproduce el bug exacto.
  - `test_cobranzas_diarias_no_toca_los_demas_casos`: los otros tres caminos de la
    misma funcion siguen dando lo mismo.
  - `test_as_datetime_repara_el_texto_de_pewee_3`: el contrato.

Ese era el hole real: **el informe de cobranzas diarias no tenia ninguna cobertura**,
por eso el bug paso inadvertido. El path de la nota de credito ya estaba cubierto por los
6 tests que fallaban.

## Validaciones ejecutadas

| Comando | Resultado |
|---|---|
| Suite completa en **peewee 3.17.8**, antes del fix | 6 failed / 1133 passed |
| Suite completa en **peewee 3.17.8**, despues del fix | **1142 passed / 0 failed** |
| `python -m compileall app` | exit 0 |
| `python -m pytest` (los tests afectados) | 16 passed |

## Documentacion agregada

`VALIDATION.md`: la suite **cuelga** si no se corre con `QT_QPA_PLATFORM=offscreen`
(`test_close_without_payment_requires_and_persists_reason` abre un dialogo modal y queda
esperando). El CI lo define en `env:`; localmente hay que exportarlo a mano. Costo real
medido: dos corridas de 20+ minutos colgadas antes de diagnostics.

## Una leccion del propio cambio

Una version intermedia de este fix rompio 3 tests con `'crÃ©dito'` en vez de `'crédito'`:
un `Get-Content` + `Set-Content -Encoding UTF8` de PowerShell 5.1 sobre archivos UTF-8
del repo. Se detecto porque los tests comparan strings con acentos. Se revirtio y se
rehicieron los cambios con edicion directa, que respeta el encoding.

**Regla para este repo: no usar `Get-Content | Set-Content` para editar codigo.** Usar la
herramienta de edicion de archivos o un script con encoding explicito.

## Pendientes

- [ ] Unificar los 3 duplicados de `_display_datetime` (heredado del #615).
- [ ] Migrar a peewee 4 (#616), que elimina el bug de raiz.
- [ ] Arreglar el bug de `ensure_runtime_schema()` que deja la base inutilizable.
- [ ] `test_webapp_qr_orders.py` no corre localmente por falta de `flask`.
