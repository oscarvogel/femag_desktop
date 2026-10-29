# FEMAG Sync — agente de fábrica (#804)

Primera rebanada del agente: publica un **snapshot completo** de órdenes desde
la MySQL de fábrica hacia FEMAG Web. Todavía no aplica eventos de lote/fecha ni
procesa incrementales.

## Requisitos

- Python y dependencias del proyecto en el servidor de fábrica.
- MySQL de fábrica accesible con la configuración habitual (`DB_*`).
- Tablas de sync creadas (`python scripts/init_db.py`).
- URL HTTPS de FEMAG Web y token de máquina.

## Variables

| Variable | Obligatoria | Uso |
| --- | --- | --- |
| `FEMAG_SYNC_BASE_URL` | Sí | `https://femag...` sin `/api` |
| `FEMAG_SYNC_API_TOKEN` | Sí | Token de máquina; debe coincidir con el de Coolify |
| `FEMAG_SYNC_CA_FILE` | No | CA propia si el servidor usa un certificado interno |
| `FEMAG_SYNC_LOG_FILE` | No | Archivo de log; si falta, sale por consola |
| `FEMAG_SYNC_ALLOW_HTTP` | No | `1` **solo** para pruebas locales; producción exige HTTPS |

El token no se pasa por parámetro de línea de comandos (queda visible en el
listado de procesos). Se lee del entorno.

## Ejecución

```bash
python -m app.jobs.sync_agent --snapshot
python -m app.jobs.sync_agent --status
```

`--snapshot`:

1. Selecciona órdenes en estado `Pendiente`, `Emitida` o `Anulada`.
2. Asigna UUID estables a orden, renglón, cliente, destino y pallet.
3. Arma el snapshot según `docs/contracts/femag_web_sync_v1/`.
4. Lo envía a `POST /api/sync/v1/snapshots/orders`.
5. Guarda el cursor local `factory_snapshot` y muestra un resumen JSON.

`--status` muestra el estado local de outbox, inbox, cursores y conflictos.

## Programación

Queda para la etapa de operación empaquetar el agente como EXE/servicio y
registrar una tarea programada. Mientras tanto se puede ejecutar con el
Programador de tareas de Windows usando el Python del proyecto.

## Seguridad

- Solo conexiones HTTPS salientes; no se abren puertos en fábrica.
- El token viaja en `Authorization: Bearer` y no se registra en logs.
- El snapshot no incluye precios, costos, saldos, stock, remitos ni contabilidad.
- No se modifican órdenes ni movimientos: el publicador solo lee.

## Pendiente

- Eventos incrementales por orden creada/modificada/anulada.
- Consumo de eventos cloud → fábrica para lote/fecha.
- Outbox en el envío del snapshot (hoy es un POST directo).
- Empaquetado, servicio, bloqueo de instancia única y métricas.
- Lectura de la proyección desde la pantalla cloud (#805).
