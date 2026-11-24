# Análisis: tarjeta "Presupuestos vencidos" del Dashboard operativo

**Fecha:** 24/11/2026
**Pedido:** "no puede ser tanto presupuesto vencidos" (captura del Dashboard operativo)
**Fuente de datos:** `C:\Users\Usuario\Downloads\femag_desktop.sql` (dump de 24/11/2026 07:22, MySQL 5.7.15 en Windows)
**Estado:** solo análisis. **No se modificó código de la app ni datos de producción.**

---

## 1. Veredicto

La tarjeta **no mide deuda vencida: suma el importe bruto de documentos emitidos y nunca descuenta los pagos.**

| | Lo que muestra el dashboard | Lo que dice ser |
|---|---|---|
| **Presupuestos vencidos** | **$ 4.561.758.719,00 / 429** | "dinero a cobrar" |
| Saldo deudor clientes (misma pantalla) | $ 2.133.801.435,03 / 124 clientes | "deuda total" |

La misma pantalla dice que los clientes deben **$ 2.133.801.435** y, dos tarjetas más abajo, que hay **$ 4.561.758.719 vencidos**. La deuda vencida no puede ser 2,14x la deuda total. O sea: **el tablero se contradice solo**, y el número "vencido" está inflado.

Con la regla que ya usa la pantalla de Cuenta Corriente (vencimiento recortado al saldo del cliente), el mismo dato da **$ 1.960.973.209,76**.

Además, **907 de los 912 clientes no tienen plazo de pago configurado** (`dias_plazo_pago = 0`), así que su documento vence el mismo día de la orden de carga: al día siguiente ya figura "vencido". De los 429 documentos contados, **394 ($ 3.378.473.199) son de clientes sin plazo** y solo **35 ($ 1.183.285.520) de los 5 clientes que sí tienen plazo (30/60 días)** están vencimientos en el sentido comercial.

---

## 2. Cómo se validó

Base real, no simulada:

- Dump importado en **MariaDB 11.8.6** (contenedor Docker aislado `femag-analysis` en WSL), sin tocar la base de trabajo.
- Volumen cargado: 912 clientes, 407 presupuestos, 149 órdenes de carga, 1.493 movimientos de cuenta corriente, 503 pagos, 124 cierres de orden.
- La lógica de la tarjeta (`app/reports/collection_due_report.py` + `app/ui/dashboard.py`) reproducida en SQL **contra la base real**: da **429 documentos / $ 4.561.758.719,00**, exactamente lo que muestra la captura.

Reproducción de las otras tarjetas de cobranza desde el mismo dump (confirma que la base es fiel):

| Tarjeta | Pantalla | Recalculado desde el dump |
|---|---|---|
| Vencidos | $ 4.561.758.719,00 / 429 | $ 4.561.758.719,00 / 429 ✅ |
| Vence hoy | $ 0,00 / 0 | $ 0,00 / 0 ✅ |
| Próximos 7 días | $ 321.943.996,00 / 11 | $ 321.943.996,00 / 11 ✅ |
| Próximos 30 días | $ 861.338.976,00 / 30 | $ 861.338.976,00 / 30 ✅ |
| Saldo deudor clientes | $ 2.133.801.435,03 / 124 | $ 2.132.901.435,03 / 124 |

La única diferencia es **$ 900.000** en el saldo deudor: es el pago `ClientPayment:503` del **23/11/2026** ($ 900.000, cliente 130), que ya está en el dump y no estaba en la captura. La base es, por lo tanto, fiel a la pantalla.

---

## 3. Causa raíz

### 3.1 La tarjeta suma bruto y no descuenta pagos (causa principal)

`app/ui/dashboard.py:114-124` arma la tarjeta con la suma de `total_amount` de cada movimiento vencido; `app/reports/collection_due_report.py:59-117` trae los movimientos **sin ningún netting contra pagos ni créditos**.

En la misma ventana de datos:

| Concepto | Importe |
|---|---|
| Facturado (469 documentos de OC, 148 órdenes, 225 clientes) | $ 5.621.374.675,00 |
| Pagos registrados (503 movimientos `payment`) | $ 7.772.741.315,40 |
| Créditos manuales (180) | $ 1.006.619.060,81 |
| Débitos manuales (293) | $ 2.441.068.663,17 |
| **Deuda real (saldo deudor del tablero)** | **$ 2.133.801.435,03** |

Se está cobrando (los pagos superan lo facturado), pero la tarjeta lo ignora: cuenta el documento como si estuviera 100% impago.

**El sistema ya tiene la regla correcta, pero en otra pantalla.** `app/services/ledger_query_service.py:109-191` (Cuenta Corriente) recorta el vencimiento al saldo positivo del cliente: `min(saldo, vencido)`. Con ese mismo dato: **$ 1.960.973.209,76** y **175 clientes** donde el bruto excede el saldo. Son dos pantallas del mismo sistema con el mismo underlying dando **$ 4.561.758.719 vs $ 1.960.973.209**.

### 3.2 "Vencido" desde el día siguiente, porque casi nadie tiene plazo de pago

`app/services/account_ledger_service.py:87-95`:

```python
plazo = max(int(client.dias_plazo_pago or 0), 0)
due_date = movement_date + timedelta(days=plazo)
```

| `dias_plazo_pago` | clientes | movs vencidos | importe |
|---|---|---|---|
| 0 (sin plazo) | 907 | 394 | $ 3.378.473.199,00 |
| 30 | 4 | 31 | $ 1.101.129.620,00 |
| 60 | 1 | 4 | $ 82.155.900,00 |

Además, cuando la orden está partida (contado + diferido), la parte al contado vence **el mismo día** de la orden (`account_ledger_service.py:92-93`), sin importar el plazo del cliente.

### 3.3 La antigüedad no aguanta la lectura de "$ 4.500 millones vencidos"

| Atraso | documentos | importe |
|---|---|---|
| 1 a 30 días | 155 | $ 1.890.089.547,00 |
| 31 a 60 días | 143 | $ 1.157.194.852,00 |
| 61 a 90 días | 131 | $ 1.514.474.320,00 |

**El 36% de la "deuda vencida" tiene menos de un mes.** No hay deuda de 4.500 millones vencida: hay facturación reciente sin imputar.

### 3.4 "429 presupuestos" no son 429 presupuestos

- 429 es el conteo de **movimientos de cuenta corriente** vencidos, no de documentos de presupuesto.
- Solo **327** de esos 429 tienen presupuesto asociado; **102** movimientos no lo tienen (`budget_id` NULL) — son de las órdenes más viejas (setiembre).
- En total existen **407 presupuestos** (405 activos): el número "429 presupuestos" no puede ser un conteo de presupuestos, hay más movimientos que documentos.
- **2 de los 429** son documentos con importe **$ 0** ("movimiento documental sin importe comercial", PRES-000382 y PRES-000396): inflan el conteo sin aportar un peso.
- 8 pares (OC, cliente) generan **dos** movimientos (contado + diferido), así que la misma orden aparece dos veces. **Verificado que el desdoble es correcto**, no es doble facturación: OC-082 / cliente 369 → total de la orden $ 41.447.700 = $ 20.723.850 contado + $ 20.723.850 diferido.

### 3.5 Lo que el reporte además deja afuera

- **28 presupuestos manuales** ($ 106.704.214,60; **25 ya vencidos, $ 83.608.414,60**) tienen `due_date`, pero `collection_due_report.py:61-66` filtra solo `load_order_documental` y `load_order_documental_deferred` → no aparecen en ninguna tarjeta.
- **Los pagos no se imputan a documentos**: se registran como créditos a nivel cliente (`payment_id`), sin vínculo al presupuesto. Con el modelo actual **es imposible** responder "¿cuánto de este presupuesto quedó impago?" — esa es la causa de fondo de que el reporte solo pueda dar brutos.

---

## 4. Números para decidir (base 24/11/2026)

| Escenario | Importe | Conteo |
|---|---|---|
| A) Como está hoy (bruto, documents sin plazo incluidos) | $ 4.561.758.719,00 | 429 |
| B) Neto por cliente (misma regla que Cuenta Corriente) | **$ 1.960.973.209,76** | 175 clientes con exceso |
| C) Solo documentos con plazo de pago > 0 (vencimiento real) | $ 1.183.285.520,00 | 35 |
| D) Saldo deudor total (tarjeta "Saldo deudor clientes") | $ 2.133.801.435,03 | 124 clientes |
| E) Manuales ya vencidos, hoy fuera del reporte | $ 83.608.414,60 | 25 documentos |

B y E no son sumables sin definir la imputación (E está dentro de D por cliente, pero no dentro de A porque A excluye los manuales).

---

## 5. Corrección propuesta

Ninguna de estas opciones toca datos ni áreas protegidas (no toca Importación DBF/MySQL, liquidaciones ni modelos).

### Opción 1 — Neteo por cliente en la tarjeta (recomendada, chico)
- **Dónde:** `app/ui/dashboard.py:114-124` y `app/reports/collection_due_report.py:104-116`.
- **Qué:** aplicar `min(saldo_positivo_cliente, vencido_cliente)` — la regla que ya existe en `ledger_query_service.py:173-178` — y **renombrar la tarjeta** para que no prometa "deuda vencida" si se mantiene el bruto.
- **Esfuerzo:** chico (1 issue, 1 rama, 1 PR, tests sobre `collection_snapshot`).
- **Riesgo:** el número de la tarjeta baja de $ 4.561M a ~$ 1.960M; hay que avisar a quien mira el tablero. El reporte de cobranzas en detalle (filas) puede seguir mostrando el bruto, aclarando la diferencia.

### Opción 2 — Separar "sin plazo" de "vencido" (complemento de la 1)
- **Dónde:** `app/reports/collection_due_report.py` (nuevo estado `Sin plazo definido`) y el set de tarjetas de `app/ui/dashboard.py:158-180`.
- **Qué:** si `cliente.dias_plazo_pago == 0`, el documento no está "vencido": está "sin plazo definido". Aparece en su propia tarjeta, no en la de vencidos.
- **Esfuerzo:** medio (issue propio). Necesita decidir antes qué significa comercialmente plazo 0 (ver abajo).

### Opción 3 — Imputación real de pagos a presupuestos (robusto, grande)
- **Qué:** vincular cada pago a los presupuestos que cancela (columna nueva o tabla de imputación) y mostrar el saldo por documento.
- **Esfuerzo:** grande: migración de modelo + migración de los 503 pagos históricos + cambio en el flujo de carga de pagos + reporte nuevo.
- **Es la única forma de que "cuánto impago de este presupuesto" sea una verdad contable.** Sin esto, cualquier tarjeta de vencimientos es una aproximación.

### Opción 4 — Datos de maestro (no es código)
- Cargar `dias_plazo_pago` de los 907 clientes con plazo 0. **Decisión comercial**, no técnica: si "plazo 0" significa "cobrar al contado", entonces la deuda vencida real es chica y el problema es la imputación (opción 3); si significa "sin definir", el problema es la tarjeta (opciones 1 y 2).

---

## 6. Hallazgo secundario: **este dump no se restaura**

Al importarlo crudo fallan **10 INSERT** y **8 tablas quedan vacías**:

```
auditlog: FALTAN ['user_id']
budget: FALTAN ['salesperson_id']
carrier: FALTAN ['fiscal_address']
client: FALTAN ['whatsapp_phone']
driver: FALTAN ['fiscal_address']
loadorderdestination: FALTAN ['salesperson_id']
managerialsummarydelivery: FALTAN ['provider_status']
salesperson: FALTAN ['whatsapp_phone']
```

El `CREATE TABLE` del dump está desactualizado respecto a sus propios `INSERT` (columnas que el schema agrega en runtime, p. ej. `ensure_runtime_schema`). **Restaurar este archivo en una base vacía deja sin 912 clientes, sin 407 presupuestos, sin transportistas, sin audit log, etc.** Para poder analizarlo hubo que correr 8 `ALTER TABLE ... ADD COLUMN` primero.

Verificado que **es específico de este archivo**: los otros 8 dumps de `Descargas` (`femag.sql`, `femag_fab.sql`, los de octubre, `staging-...`, `a0110632_mant.sql`) son consistentes. El generador de backup del proyecto (`app/services/mysql_dump.py:132-144`) usa `SHOW CREATE TABLE`, o sea que **no debería producir este problema**; el archivo de la captura salió de HeidiSQL (header "HeidiSQL VersiÃ³n: 12.21.0.7344"), probablemente con la estructura cacheada desactualizada.

**Acción sugerida:** regenerar el respaldo con el backup de la app (o con HeidiSQL haciendo *Refresh* del schema antes de exportar) y **probar la restauración** de un backup en limpio.

---

## 7. Cómo reproducirlo

Todo lo de este informe se corrió contra la base real, no contra SQLite:

```bash
# 1. Levantar MariaDB con el dump importado (puerto 3307)
wsl -e bash docs/analisis/sql/levantar-base-real.sh
wsl -e bash docs/analisis/sql/importar-dump.sh

# 2. Recalcular las tarjetas con el codigo de la app y contrastar con el SQL
PYTHONPATH=. python scripts/validate_issue_952_exposure.py

# 3. Captura del dashboard contra la base real
PYTHONPATH=. python scripts/generate_issue_952_screenshot.py
```

Las consultas forenses que sostienen cada numero de este informe estan en el **apendice A** (el repo ignora los `.sql`, asi que el SQL vive aca y en los scripts de `docs/analisis/sql/`). El chequeo de que un dump tenga el DDL coherente con sus INSERT esta en `docs/analisis/sql/check-dump-ddl-consistente.py`.

---

## 8. Bitácora

| Qué | Cómo |
|---|---|
| Reproducción de la tarjeta | SQL con la lógica de `collection_due_report.py` sobre la base importada → 429 / $ 4.561.758.719,00 |
| Verificación de fidelidad | Las 5 tarjetas de cobranza recalculadas desde el dump coinciden con la captura (salvo $ 900.000 del pago del 23/11) |
| Causa raíz | Lectura de `app/ui/dashboard.py`, `app/reports/collection_due_report.py`, `app/services/ledger_query_service.py`, `app/services/account_ledger_service.py` + consultas de desglose |
| Base de análisis | Contenedor Docker `femag-analysis` (MariaDB 11.8.6) en WSL, import del dump con 8 `ALTER` correctivos |
| Dump original | Intacto, no se modificó |
| Código de la app | Sin cambios **en este documento** (la corrección llegó después, en #952 / PR #953) |

---

## 9. Pendientes y decisiones

1. **Qué número va en la tarjeta** → **resuelto**: la opción 1 (neteo por cliente), implementada en #952 / PR #953. La tarjeta pasó de $ 4.561.758.719 a $ 1.939.999.974,08.
2. **Qué significa comercialmente `dias_plazo_pago = 0`**: "¿cobrar al contado" o "sin definir". **Abierto**: define si la deuda vencida real es la que dice el tablero.
3. **Imputación de pagos a presupuestos**: sigue abierta. Es la única forma de que "cuánto impago de este presupuesto" sea una verdad contable (#940 es el equivalente para proveedores).
4. **Presupuestos manuales fuera del reporte**: 25 vencidos por $ 83.608.414,60 que no aparecen en ninguna tarjeta.
5. **Regenerar y probar el backup** (sección 6) — independiente de lo anterior, pero con riesgo de pérdida de datos si no se hace.

---

## Apéndice A — SQL forense

Todas las consultas corren sobre `femag_desktop` en el contenedor de análisis.

**A.1 Reproducir la tarjeta** (misma lógica que `app/reports/collection_due_report.py`):

```sql
SELECT COUNT(*) AS n_vencidos, ROUND(SUM(m.total_amount),2) AS importe
FROM clientaccountmovement m
WHERE m.movement_type IN ('load_order_documental','load_order_documental_deferred')
  AND m.is_reversal = 0
  AND m.due_date IS NOT NULL
  AND m.due_date < CURDATE()
  AND NOT EXISTS (
    SELECT 1 FROM clientaccountmovement r
    WHERE r.reverses_id = m.id AND r.is_reversal = 1);
```

**A.2 Vencido vs saldo real del cliente** (el contraste que abre el caso):

```sql
SELECT ROUND(SUM(t.vencido),2) AS vencido_bruto,
       ROUND(SUM(GREATEST(t.saldo,0)),2) AS saldo_deudor,
       ROUND(SUM(LEAST(t.vencido, GREATEST(t.saldo,0))),2) AS vencido_neto,
       SUM(t.vencido > GREATEST(t.saldo,0)) AS clientes_con_exceso
FROM (
  SELECT m.client_id,
         SUM(CASE WHEN m.due_date < CURDATE() AND m.is_reversal = 0
                   AND m.movement_type IN ('load_order_documental','load_order_documental_deferred')
                  THEN m.total_amount ELSE 0 END) AS vencido,
         SUM(m.total_amount) AS saldo
  FROM clientaccountmovement m GROUP BY m.client_id) t;
```

**A.3 Plazo de crédito configurado por cliente** (907 de 912 en cero):

```sql
SELECT c.dias_plazo_pago AS plazo, COUNT(*) AS movs_vencidos,
       ROUND(SUM(m.total_amount),2) AS importe
FROM clientaccountmovement m JOIN client c ON c.id = m.client_id
WHERE m.movement_type IN ('load_order_documental','load_order_documental_deferred')
  AND m.is_reversal = 0 AND m.due_date IS NOT NULL AND m.due_date < CURDATE()
  AND NOT EXISTS (SELECT 1 FROM clientaccountmovement r WHERE r.reverses_id = m.id AND r.is_reversal = 1)
GROUP BY c.dias_plazo_pago;
```

**A.4 Deducir el plazo desde la orden** (`due_date - fecha de la OC`):

```sql
SELECT DATEDIFF(m.due_date, o.date) AS dias_plazo, COUNT(*) AS n, ROUND(SUM(m.total_amount),2) AS importe
FROM clientaccountmovement m JOIN loadorder o ON o.id = m.load_order_id
WHERE m.movement_type IN ('load_order_documental','load_order_documental_deferred') AND m.is_reversal = 0
GROUP BY dias_plazo ORDER BY dias_plazo;
```

**A.5 Antigüedad de la deuda vencida**:

```sql
SELECT CASE WHEN DATEDIFF(CURDATE(), m.due_date) <= 30 THEN '1-30 dias'
            WHEN DATEDIFF(CURDATE(), m.due_date) <= 60 THEN '31-60 dias'
            WHEN DATEDIFF(CURDATE(), m.due_date) <= 90 THEN '61-90 dias'
            ELSE 'mas de 90 dias' END AS antiguedad,
       COUNT(*) AS movs, ROUND(SUM(m.total_amount),2) AS importe
FROM clientaccountmovement m
WHERE m.movement_type IN ('load_order_documental','load_order_documental_deferred')
  AND m.is_reversal = 0 AND m.due_date IS NOT NULL AND m.due_date < CURDATE()
  AND NOT EXISTS (SELECT 1 FROM clientaccountmovement r WHERE r.reverses_id = m.id AND r.is_reversal = 1)
GROUP BY antiguedad;
```

**A.6 Conteo de "presupuestos" vs documentos reales**:

```sql
SELECT COUNT(*) AS movs_contados, COUNT(DISTINCT m.budget_id) AS presupuestos_distintos,
       SUM(m.budget_id IS NULL) AS movs_sin_presupuesto, SUM(m.total_amount = 0) AS movs_en_cero
FROM clientaccountmovement m
WHERE m.movement_type IN ('load_order_documental','load_order_documental_deferred')
  AND m.is_reversal = 0 AND m.due_date IS NOT NULL AND m.due_date < CURDATE()
  AND NOT EXISTS (SELECT 1 FROM clientaccountmovement r WHERE r.reverses_id = m.id AND r.is_reversal = 1);
```

**A.7 Presupuestos manuales que el reporte deja afuera**:

```sql
SELECT COUNT(*) AS movs, SUM(due_date < CURDATE()) AS ya_vencidos,
       ROUND(SUM(CASE WHEN due_date < CURDATE() THEN total_amount ELSE 0 END),2) AS importe_vencido
FROM clientaccountmovement
WHERE movement_type = 'budget_manual' AND is_reversal = 0;
```


