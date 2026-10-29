# Contratos FEMAG Web Sync v1

Contratos de sincronización entre **FEMAG Web** (Coolify) y **FEMAG Sync**
(fábrica). Son la base de los issues #804 y #805 y deben aprobarse antes de
implementar. La arquitectura general está en
[`docs/FEMAG_WEB_ARCHITECTURE.md`](../../FEMAG_WEB_ARCHITECTURE.md).

## Reglas de versionado

- La versión **v1 es inmutable** una vez aprobada.
- Todo mensaje lleva `schema_version: "1.0"`.
- Cambios compatibles (campos opcionales nuevos) suben el minor: `1.1`.
- Cambios incompatibles abren una carpeta `femag_web_sync_v2/`; no se reescribe
  v1.
- Un consumidor debe ignorar campos desconocidos y rechazar un `schema_version`
  mayor que el soportado.
- Los nombres de eventos y campos no se renombran dentro de v1.

## Transporte

- HTTPS obligatorio, JSON UTF-8, `Content-Type: application/json`.
- **Todas las conexiones las inicia la fábrica.** La nube no abre conexiones
  hacia Windows Server 2019.
- Timestamps en UTC ISO 8601: `YYYY-MM-DDTHH:MM:SSZ`.
- IDs globales UUIDv4; los IDs autoincrementales de MySQL no cruzan ambientes.

### Endpoints propuestos (a implementar en #804)

| Método | Ruta | Uso |
| --- | --- | --- |
| `POST` | `/api/sync/v1/snapshots/orders` | Publicar snapshot inicial o de reconciliación |
| `POST` | `/api/sync/v1/events` | Publicar eventos del outbox de fábrica |
| `GET` | `/api/sync/v1/events?cursor=<n>&limit=<n>` | Traer eventos originados en la nube |
| `POST` | `/api/sync/v1/events/{event_id}/ack` | Confirmar aplicación o conflicto |
| `GET` | `/api/sync/v1/status` | Estado observable de sync |
| `GET` | `/health` | Salud del servicio |

La primera implementación cubre snapshots de órdenes, pull de eventos, ACK y
status en `webapp/sync_api.py`. El agente que publica y aplica esos eventos se
implementa en la siguiente rebanada de #804.

### Autenticación

Cabeceras mínimas:

```text
Authorization: Bearer <machine-token>
X-FEMAG-Client: femag-sync
X-FEMAG-Timestamp: 2026-10-28T15:00:00Z
Idempotency-Key: <uuid>
```

- El token de máquina es rotativo, con permisos mínimos y nunca se loguea.
- Opcional para una etapa posterior: firma HMAC `X-FEMAG-Signature` sobre
  `timestamp + body` para defensa de replay.
- La nube valida timestamp dentro de una ventana corta y rechaza reutilización
  de `Idempotency-Key`.

## Envelope de evento

Todo evento usa este sobre:

| Campo | Tipo | Obligatorio | Descripción |
| --- | --- | --- | --- |
| `schema_version` | string | Sí | `"1.0"` |
| `event_id` | UUID | Sí | ID estable del evento; se repite en reintentos |
| `event_type` | string | Sí | Ver tipos abajo |
| `origin` | string | Sí | `factory` o `cloud` |
| `occurred_at` | string | Sí | UTC ISO 8601 |
| `aggregate_type` | string | Sí | `order`, `order_line`, `order_request` |
| `aggregate_id` | UUID | Sí | `order_uid`, `line_uid` o `request_uid` |
| `aggregate_version` | integer | Sí | Versión del agregado que el emisor conoce |
| `idempotency_key` | string | Sí | Clave única de la operación lógica |
| `cursor` | integer | Sí | Posición monotónica en el stream del emisor |
| `actor` | object | No | `{ "user_uid", "role", "display_name" }` |
| `payload` | object | Sí | Según `event_type` |

Tipos v1:

| `event_type` | Origen | Payload |
| --- | --- | --- |
| `order_lote_fecha_updated` | cloud | `order_uid`, `line_uid`, `lote`, `fecha_elaboracion`, `expected_version` |
| `order_lote_applied` | factory | `order_uid`, `line_uid`, `lote`, `fecha_elaboracion`, `applied_version`, `applied_at` |
| `order_cancelled` | factory | `order_uid`, `order_number`, `cancelled_at`, `reason` |
| `order_request_created` | cloud | `request_uid`, `client_uid`, `items`, `delivery_address_uid`, `observations` |
| `order_request_cancelled` | cloud | `request_uid`, `reason` |
| `order_request_decided` | factory | `request_uid`, `decision`, `reason`, `decided_at` |

## Snapshot de órdenes

El snapshot incluye `orders[]` con:

- `order_uid`, `order_number`, `qr_token`, `status`, `version`;
- `order_date`, `published_at`, `updated_at`, `cancelled_at`;
- `client`: `client_uid`, `name`;
- `destination`: `destination_uid`, `city`, `address`;
- `lines[]`: `line_uid`, `product_name`, `quantity`, `unit`, `lote`,
  `fecha_elaboracion`;
- `pallets[]`: `pallet_uid`, `sequence`, `type`, `weight_kg`.

No incluye precios, costos, saldos, stock, remitos ni contabilidad.

## Cursores e idempotencia

- Cada stream (`factory`, `cloud`) tiene un cursor monotónico.
- El consumidor guarda el último cursor aplicado por stream.
- Un evento con `cursor` menor o igual al último aplicado se descarta como
  duplicado.
- Un evento con cursor salteado se retiene hasta recibir el anterior o se
  resuelve como conflicto.
- `event_id` es la clave de deduplicación; `idempotency_key` es la clave de la
  operación de negocio.

## Conflictos

La respuesta de ACK puede ser:

```json
{
  "schema_version": "1.0",
  "event_id": "4e0f1f7a-5d4a-4b8e-9a3d-2b0f6d8c1a11",
  "result": "conflict",
  "error": {
    "code": "version_conflict",
    "message": "La orden cambió en fábrica después de la lectura.",
    "retryable": false,
    "details": {
      "expected_version": 4,
      "current_version": 5,
      "current_lote": "LOTE-2026-08"
    }
  }
}
```

Reglas:

- `result`: `applied`, `duplicate`, `conflict` o `rejected`.
- `conflict` y `rejected` no se reintentan automáticamente; van a revisión.
- Orden anulada => `rejected` con `order_cancelled`.
- Evento inválido => `rejected` con `validation_error`.
- Error transitorio => HTTP 5xx o `retryable: true`; el emisor reintenta con
  backoff.

## Códigos de error

| Código | Reintentable | Significado |
| --- | --- | --- |
| `validation_error` | No | Payload o campo inválido |
| `auth_failed` | No | Token/credencial inválida |
| `forbidden` | No | Rol o alcance insuficiente |
| `not_found` | No | Orden/renglón/cliente inexistente o fuera de alcance |
| `version_conflict` | No | `expected_version` no coincide |
| `order_cancelled` | No | La orden está anulada |
| `duplicate_event` | No | Evento ya aplicado (`result: duplicate`) |
| `rate_limited` | Sí | Límite de tasa |
| `temporary_unavailable` | Sí | Falla transitoria del servicio |
| `internal_error` | Sí | Error no clasificado |

## Ejemplo de evento cloud → fábrica

```json
{
  "schema_version": "1.0",
  "event_id": "0b6d1e2a-2f4c-4a5e-9f6a-1c2d3e4f5a6b",
  "event_type": "order_lote_fecha_updated",
  "origin": "cloud",
  "occurred_at": "2026-10-28T15:00:00Z",
  "aggregate_type": "order_line",
  "aggregate_id": "6f1e2d3c-4b5a-6978-8c9d-0e1f2a3b4c5d",
  "aggregate_version": 4,
  "idempotency_key": "lote:6f1e2d3c-4b5a-6978-8c9d-0e1f2a3b4c5d:v4",
  "cursor": 101,
  "actor": {
    "user_uid": "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
    "role": "operario",
    "display_name": "Operario Planta"
  },
  "payload": {
    "order_uid": "2c3d4e5f-6a7b-4c8d-9e0f-1a2b3c4d5e6f",
    "line_uid": "6f1e2d3c-4b5a-6978-8c9d-0e1f2a3b4c5d",
    "lote": "LOTE-2026-08",
    "fecha_elaboracion": "2026-08-27",
    "expected_version": 3
  }
}
```

## Archivos

- [`order-snapshot.schema.json`](order-snapshot.schema.json)
- [`sync-event.schema.json`](sync-event.schema.json)
- [`sync-error.schema.json`](sync-error.schema.json)

## Validación local

Los archivos deben ser JSON válido y mantener `schema_version` y `$id`:

```powershell
Get-ChildItem docs/contracts/femag_web_sync_v1/*.json |
  ForEach-Object { Get-Content $_.FullName -Raw | ConvertFrom-Json | Out-Null }
```

Cualquier cambio de contrato debe actualizar este README, el esquema y los
ejemplos en el mismo PR.
