# Importacion historica de cotizaciones (#970)

Complementa `docs/COTIZACIONES.md` (#969). El objetivo es disponer de las
cotizaciones historicas necesarias para analizar los presupuestos existentes,
sin tocar la tabla `budget` ni inventar fechas.

## 1. Auditoria de datos

El descubrimiento es dinamico: el servicio lee `budget.issue_date`, calcula
minimo, maximo y cantidad por fecha. No hay fechas hardcodeadas.

- En este entorno no se dispone de una base productiva autorizada. Los SQLite
  demo locales no tienen tabla `budget` (son anteriores al modelo), por lo que
  no se usaron para inferir un rango real.
- Si la tabla no existe, el importador lo informa; no inventa un rango.
- La consulta es de solo lectura y el importador nunca escribe en `budget`.

Comando para obtener el rango real en la base configurada:

```bash
python -m app.jobs.import_historical_exchange_rates --budgets --dry-run --types oficial
```

## 2. Cobertura real de los proveedores

Consultas HTTP reales del 27/11/2026. ArgentinaDatos publica la serie completa
por tipo en un unico endpoint; se usa esa serie y se filtra localmente, en vez
de una solicitud por cada fecha.

| Tipo | Endpoint | Registros | Desde | Hasta |
|---|---|---:|---|---|
| USD oficial | `/v1/cotizaciones/dolares/oficial` | 5808 | 2011-01-03 | 2026-11-27 |
| USD blue | `/v1/cotizaciones/dolares/blue` | 5808 | 2011-01-03 | 2026-11-27 |
| USD MEP (`bolsa`) | `/v1/cotizaciones/dolares/bolsa` | 2952 | 2018-10-29 | 2026-11-27 |
| USD CCL (`contadoconliqui`) | `/v1/cotizaciones/dolares/contadoconliqui` | 5078 | 2013-01-02 | 2026-11-27 |
| USD mayorista | `/v1/cotizaciones/dolares/mayorista` | 5808 | 2011-01-03 | 2026-11-27 |
| USD tarjeta | `/v1/cotizaciones/dolares/tarjeta` | 2532 | 2019-12-23 | 2026-11-27 |
| BRL oficial | `/v1/cotizaciones/brl` | 1125 | 2023-10-22 | 2026-11-27 |

La serie de ArgentinaDatos incluye filas los fines de semana y feriados cuando
el proveedor las publica. El importador **no sintetiza** filas: si el proveedor
no devuelve una fecha, no se crea; el fallback se resuelve al consultar con
`ExchangeRateService.get_latest_before`.

DolarAPI no ofrece historico propio. BNA no tiene serie completa: su endpoint
devuelve fechas cercanas por consulta, por lo que no se usa para backfill
masivo (sigue siendo fuente actual/faltantes en #969).

## 3. Servicio y CLI

Servicio: `app.services.exchange_rate_history_import_service`.
CLI: `app.jobs.import_historical_exchange_rates`.

### Importar el rango de presupuestos

```bash
python -m app.jobs.import_historical_exchange_rates --budgets --dry-run --json
python -m app.jobs.import_historical_exchange_rates --budgets --types oficial,blue,mep
python -m app.jobs.import_historical_exchange_rates --budgets --max-records 5000
```

`--budgets` toma `min(issue_date)..max(issue_date)` de los presupuestos. Si se
interrumpe o se alcanza `--max-records`, se vuelve a ejecutar el mismo comando:
lo ya importado se omite y la corrida continua.

### Importar un rango explicito

```bash
python -m app.jobs.import_historical_exchange_rates ^
  --from-date 2026-01-01 --to-date 2026-11-27 --types oficial --json
```

### BRL

```bash
python -m app.jobs.import_historical_exchange_rates ^
  --from-date 2024-01-01 --to-date 2026-11-27 --currency BRL --types oficial
```

### Opciones relevantes

- `--dry-run`: cuenta lo que haria, sin escribir.
- `--refresh`: revisa correcciones de la misma fuente; si cambio el valor crea
  una nueva version, conserva la anterior.
- `--max-records`: tope de registros nuevos por corrida; `0` = sin limite.
- `--max-requests`: tope de solicitudes HTTP; por defecto 20 (una por tipo).
- `--holidays-file`: JSON de feriados ISO para clasificar faltantes.
- `--coverage-any-source`: evalua presupuestos contra cualquier fuente, no solo
  la importada.
- `--json`: resumen completo para automatizacion.

## 4. Semantica de importacion

1. **Fuente independiente.** Cada registro conserva `source`, `rate_type` y
   `effective_date`; nunca se sobrescribe una fuente con otra.
2. **Solo faltantes.** Por defecto, si ya existe una cotizacion para
   moneda/tipo/fecha (de cualquier fuente), se omite. `--refresh` solo actualiza
   la **misma** fuente y crea version si el valor cambio.
3. **Sin registros artificiales.** No se rellenan fines de semana ni feriados;
   se importan exclusivamente filas devueltas por el proveedor.
4. **Idempotencia.** Repetir la corrida no duplica; el servicio #968 devuelve
   `created=False`.
5. **Reanudacion.** El estado es la propia tabla `exchangerate`; no hay cursor
   que se pueda perder.
6. **HTTP acotado.** Una solicitud por tipo para la serie completa, no una por
   fecha. `--max-requests` corta antes de exceder el limite.
7. **Sin transacciones durante HTTP.** Primero se descarga la serie; despues se
   registra cada fila en una transaccion corta.

## 5. Conciliacion con presupuestos

El resultado incluye:

- rango solicitado;
- registros existentes, importados, sin cambios, versiones nuevas y diferidos;
- duplicados/omitidos por fuente;
- fechas sin publicacion (fin de semana o feriado declarado);
- fechas sin cobertura (dia habil sin fila del proveedor ni de otra fuente);
- errores por proveedor;
- presupuestos con cotizacion exacta, anterior o sin cotizacion utilizable.

La cobertura se calcula por moneda, tipo y fuente. `--coverage-any-source`
permite evaluar si, aunque falte la fuente historica, existe otra fuente
utilizable para esa fecha.

Ejemplo de salida real de una importacion local de prueba (3 tipos, 4 fechas):

```json
{
  "status": "ok",
  "imported": 12,
  "provider_requests": 3,
  "budget_audit": {"total_budgets": 2, "distinct_dates": 2},
  "coverage": [
    {"rate_type": "oficial", "exact_budgets": 2, "prior_budgets": 0, "missing_budgets": 0},
    {"rate_type": "blue", "exact_budgets": 2, "prior_budgets": 0, "missing_budgets": 0},
    {"rate_type": "mep", "exact_budgets": 2, "prior_budgets": 0, "missing_budgets": 0}
  ]
}
```

La segunda ejecucion devolvio `imported=0`, `skipped_existing=12`, sin
duplicados.

## 6. Limites y riesgos

- No se ejecuto una importacion masiva contra produccion.
- No se modificaron presupuestos, remitos, F150 ni ordenes de carga.
- ArgentinaDatos no tiene SLA; una respuesta incompleta queda como error o
  fecha sin cobertura, nunca como cotizacion inventada.
- El calendario de feriados historico no esta disponible en la API publica
  consultada; el informe clasifica fines de semana y acepta un archivo de
  feriados. Un feriado no declarado puede aparecer como "sin cobertura".
- El rango de presupuestos puede comenzar antes de 2011 (inicio de la serie
  oficial/blue/mayorista) o antes de 2018/2019/2023 para otros tipos. Esos
  tramos quedan como faltantes reales y deben revisarse, no rellenarse.
- La importacion usa una transaccion corta por fila; para volumenes grandes se
  recomienda `--max-records` y varias corridas.
