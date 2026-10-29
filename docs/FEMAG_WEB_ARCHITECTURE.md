# FEMAG Web y Sync — arquitectura, contratos y plan de migración

Documento de diseño del issue **#802**. Define la arquitectura viable para
publicar una parte de FEMAG en la nube sin mover el sistema de registro de la
fábrica. **No describe un despliegue ya hecho**: el VPS, el dominio y el
sincronizador todavía no están implementados ni verificados.

Issues relacionados:

- #801 QR de orden con URL configurable (implementado en `main`).
- #803 despliegue aislado en Coolify.
- #804 agente de sincronización en Windows Server 2019.
- #805 carga pública de lote/fecha con confirmación de sincronización.
- #806 portal gerencial read-only.
- #807 portal B2B de pedidos.
- #808 EPIC y orden de los cortes.

## 1. Decisiones resumidas

| Tema | Decisión |
| --- | --- |
| Sistema de registro | MySQL de fábrica. La nube es una proyección y un canal de captura, no la fuente de verdad. |
| Dirección de las conexiones | La fábrica inicia **todas** las conexiones salientes HTTPS. No se abren puertos entrantes en Windows Server 2019 ni se cambia el router/Starlink. |
| Base de datos en la nube | MySQL propio de FEMAG Web, privado en la red de Coolify. Nunca se publica el puerto 3306 ni se replica la base completa. |
| Sincronización | Snapshots + eventos incrementales idempotentes con outbox/inbox durable. No replicación MySQL. |
| Latencia | La sincronización es eventual. Toda pantalla muestra `last_synced_at` y estados; no se presenta como tiempo real. |
| Identidad | IDs globales estables (`*_uid` UUID) para orden, renglón, cliente, destino y pallet. Los IDs autoincrementales de MySQL son locales. |
| Escritura desde la nube | Solo campos permitidos: lote y fecha de elaboración, y a futuro solicitudes de pedido. Cantidades, stock, precios, remitos, F150 y contabilidad son de fábrica. |
| HTTPS | Obligatorio para datos reales fuera de la LAN. HTTP queda solo para el piloto LAN controlado. |
| Dominio | `femag.186.5.245.12.sslip.io` es una URL **propuesta**, no desplegada. El dominio definitivo recomendado es `portal.femag.com.ar`. |
| Autenticación web | Usuarios y roles con RBAC. El QR identifica una orden; no autoriza a escribirla. |

## 2. Diagrama de componentes

```text
┌────────────────────────── FÁBRICA (LAN) ──────────────────────────┐
│                                                                   │
│  PCs FEMAG Desktop (PyQt5) ───────┐                               │
│                                    ├──> MySQL fábrica (registro)  │
│  Webapp LAN (Waitress/Flask) ──────┘         ▲                    │
│   http://192.168.0.111:8000                   │                   │
│                                               │                   │
│  FEMAG Sync (servicio/tarea Windows) ─────────┘                   │
│   - outbox/inbox durable                                          │
│   - solo conexiones HTTPS salientes                               │
└───────────────────────────────┬───────────────────────────────────┘
                                │  HTTPS 443 saliente
                                ▼
┌────────────────────────── VPS / COOLIFY ──────────────────────────┐
│  Proxy HTTPS (Nginx/Caddy de Coolify)                             │
│        │                                                          │
│        ▼                                                          │
│  FEMAG Web (Flask, contenedor aislado)                            │
│   - QR/lotes   - gerencia read-only   - portal B2B                │
│        │                                                          │
│        ▼                                                          │
│  MySQL FEMAG Web (privada, red interna de Coolify)                │
│   - proyección de datos                                           │
│   - eventos pendientes de ACK                                     │
└───────────────────────────────────────────────────────────────────┘
```

Reglas del diagrama:

- Ningún celular habla con MySQL.
- Ningún componente de la nube inicia conexiones hacia la fábrica.
- La web LAN existente sigue operando aunque la nube esté caída.
- El agente de sync no bloquea la UI de Desktop: corre como servicio o tarea
  programada independiente.

## 3. Responsabilidades y límites

### 3.1 Fábrica (Windows Server 2019 + MySQL)

Es dueña de:

- maestros de clientes, transportistas, choferes, camiones, productos y precios;
- stock y movimientos;
- cuentas corrientes y contabilidad;
- órdenes de carga, cantidades, pallets, remitos y F150;
- usuarios, perfiles y permisos de Desktop;
- estado final de lote y fecha de elaboración una vez aplicados.

Expone:

- un outbox de eventos hacia la nube;
- un endpoint HTTPS saliente para publicar snapshots y eventos;
- un pull de eventos originados en la nube;
- un ACK de aplicación o conflicto.

No expone MySQL, no abre puertos y no acepta conexiones entrantes desde
Internet.

### 3.2 FEMAG Web (Coolify)

Es dueña de:

- la captura de lote/fecha **mientras está pendiente de aplicación**;
- la identidad y sesión de sus propios usuarios web;
- las solicitudes B2B y su estado de recepción;
- la proyección de lectura para gerencia;
- su propia auditoría de accesos y cambios.

No puede:

- crear órdenes definitivas, remitos, F150 ni movimientos contables;
- descontar stock;
- cambiar cantidades, precios o pallets;
- sobrescribir un lote aplicado localmente sin política explícita.

### 3.3 FEMAG Sync (fábrica → nube)

Responsable de:

- publicar snapshot inicial y cambios incrementales;
- traer eventos de la nube;
- validar versión, estado de la orden y campos permitidos;
- aplicar cambios en MySQL de fábrica con idempotencia;
- registrar ACK, conflicto, error y reintento;
- exponer estado observable: última sync, lag, pendientes y fallidos;
- sobrevivir reinicios sin duplicar ni perder eventos.

Runbook de la primera rebanada del agente:
[`FEMAG_SYNC_AGENT.md`](FEMAG_SYNC_AGENT.md).

## 4. Infraestructura

### 4.1 Fábrica

| Componente | Rol | Requisito |
| --- | --- | --- |
| Windows Server 2019 | Host de Desktop, MySQL, webapp LAN y agente | Sin puertos entrantes nuevos |
| MySQL fábrica | Sistema de registro | Backup diario verificado |
| Webapp LAN | Piloto QR/lotes en la Wi-Fi de fábrica | `http://192.168.0.111:8000`, solo LAN |
| Agente Sync | Publicar/recibir eventos | Servicio o tarea programada, logs rotativos |
| Firewall | Salida HTTPS 443 | Sin reglas de entrada desde Internet |

El agente se instala como servicio o tarea programada, con configuración
protegida, credenciales fuera de git y actualizaciones versionadas. Debe poder
detenerse sin afectar Desktop ni la webapp LAN.

### 4.2 VPS / Coolify

| Componente | Rol | Requisito |
| --- | --- | --- |
| Proxy HTTPS | TLS, redirección HTTP→HTTPS | Certificado válido y renovación automática |
| FEMAG Web | Flask/Peewee sin PyQt | Contenedor aislado del resto del VPS |
| MySQL Web | Proyección y eventos | Privado, sin puerto público, backup/restore |
| Secretos | DB, `secret_key`, API sync | En Coolify, nunca en el repositorio |
| Healthcheck | `/health` | Monitoreo y rollback |

El despliegue inicial usa datos sintéticos o demo. No se clona la base completa
de fábrica ni se cargan credenciales productivas en la primera fase.

Runbook de despliegue y rollback:
[`FEMAG_WEB_COOLIFY_DEPLOY.md`](FEMAG_WEB_COOLIFY_DEPLOY.md).

### 4.3 Ambientes

| Ambiente | Datos | HTTPS | Uso |
| --- | --- | --- | --- |
| LAN piloto | Reales de fábrica | No (HTTP controlado) | Prueba operativa dentro de la planta |
| Cloud demo | Sintéticos/demo | Sí | Validar despliegue y contratos |
| Cloud producción | Reales mínimos | Sí | Operación con datos reales |

## 5. Modelo de datos y proyección

La nube no replica todas las tablas. Proyecta solo lo necesario:

### 5.1 Órdenes publicables

Snapshot de orden:

- `order_uid` (UUID estable), `order_number` (solo lectura/visual);
- fecha, estado, `version` de la orden;
- cliente y destino mínimos: `client_uid`, nombre, `destination_uid`, ciudad y
  dirección de entrega;
- renglones: `line_uid`, producto, cantidad, unidad, lote y fecha de
  elaboración;
- pallets relevantes: `pallet_uid`, secuencia, tipo y peso si aplica;
- `published_at`, `order_updated_at`, `cancelled_at` cuando corresponda.

No se publican costos, márgenes, datos bancarios, CUIT completo si no es
necesario, ni información de otras órdenes del mismo cliente.

### 5.2 Eventos nube → fábrica

- `lote_fecha_updated`: cambios de lote y fecha propuestos desde la web.
- `order_request_created`: solicitud B2B futura (Corte D).
- `order_request_cancelled`: baja de una solicitud todavía no aprobada.

### 5.3 Eventos fábrica → nube

- `order_snapshot` (carga inicial o reconciliación).
- `order_published`, `order_updated`, `order_cancelled`.
- `order_lote_applied`: confirma que la fábrica aplicó el cambio y cuál quedó.
- `order_request_decided`: aprobación o rechazo de una solicitud B2B.

### 5.4 Campos que nunca se sincronizan en V1

- contabilidad y asientos;
- stock completo y movimientos;
- precios internos y costos;
- remitos y F150;
- credenciales o hashes de contraseñas;
- tablas completas de clientes.

## 6. Identidad, versionado y cursores

- **IDs globales:** UUIDv4 generados una vez y mapeados en la fábrica. No se
  usan autoincrementales entre ambientes.
- **`version` por agregado:** entero que sube con cada cambio relevante. El
  escritor debe enviar la versión que conoce; si no coincide, hay conflicto.
- **`event_id`:** UUIDv4 del evento, estable ante reintentos.
- **`idempotency_key`:** clave única por operación lógica. La fábrica y la nube
  deben ignorar un evento ya aplicado.
- **`cursor`:** entero o string monotónico por stream (`factory`, `cloud`). El
  consumidor guarda el último cursor aplicado.
- **Timestamps:** UTC en ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`). La conversión a
  hora local es solo de presentación.
- **Orden de eventos:** se procesa por cursor; un evento con cursor anterior al
  último aplicado se descarta como duplicado. Un evento fuera de orden se
  retiene hasta que llegue el anterior o se resuelve como conflicto.

Los contratos concretos están en
[`docs/contracts/femag_web_sync_v1/`](contracts/femag_web_sync_v1/README.md).

## 7. Dueño de cada campo

| Campo / entidad | Dueño | Nube puede escribir | Fábrica puede escribir |
| --- | --- | --- | --- |
| Cliente maestro | Fábrica | No | Sí |
| Domicilios | Fábrica | No | Sí |
| Producto, precio, descuento | Fábrica | No | Sí |
| Orden de carga y número | Fábrica | No | Sí |
| Cantidad y unidad | Fábrica | No | Sí |
| Pallets y asignaciones | Fábrica | No | Sí |
| Estado de orden / anulación | Fábrica | No | Sí |
| Lote y fecha de elaboración | Nube propone, fábrica aplica | Solo como propuesta | Sí, valor final |
| Remitos y F150 | Fábrica | No | Sí |
| Stock y contabilidad | Fábrica | No | Sí |
| Usuario/rol web | Nube (identidad propia) | Sí | Solo referencia `user_uid` |
| Solicitud B2B | Cliente en nube | Sí, como solicitud | Aprueba/rechaza |
| Auditoría | Cada lado | Escribe la propia | Escribe la propia |

Regla de oro: si un campo no está en esta tabla, **no se sincroniza** hasta que
se agregue explícitamente al contrato y a la matriz de permisos.

## 8. Roles y permisos

| Rol | Alcance | Puede ver | Puede escribir |
| --- | --- | --- | --- |
| Gerencia | Datos de fábrica read-only | Clientes, ventas, saldos, stock, órdenes, última sync | Nada |
| Operario QR | Órdenes publicadas y sus renglones | Datos operativos mínimos de la orden | Lote y fecha de elaboración |
| Cliente B2B | Solo su `client_uid` | Catálogo, precios y pedidos propios | Solicitudes propias |
| Administrador web | Configuración y usuarios web | Según su rol | Usuarios, configuración, sync |
| Servicio Sync | API máquina-a-máquina | Eventos permitidos | ACK/conflicto |

Reglas:

- Aislamiento por `client_id`/`client_uid` en todas las consultas.
- Prevención de IDOR: nunca se confía en un ID de la URL sin verificar
  pertenencia.
- El token del QR no concede rol ni escritura.
- Un operario no ve datos de gerencia; un cliente no ve otra empresa.
- El usuario de sync es una identidad de máquina, no una persona.

## 9. Seguridad

### 9.1 Transporte

- HTTPS obligatorio con datos reales.
- Validación del certificado del servidor en el agente; no desactivar TLS.
- HTTP solo en LAN controlada y con advertencia operativa.
- Redirección HTTP→HTTPS en el dominio público.

### 9.2 Autenticación

- Sesiones web con secreto fuera del repositorio y expiración por turno.
- CSRF en formularios que modifican datos.
- API de sync con credencial de máquina rotativa y permisos mínimos.
- Rate limit por IP/usuario en login, QR y API.
- Bloqueo de órdenes anuladas y de tokens inválidos.

### 9.3 Exposición de datos

- La consulta por token muestra solo datos operativos de esa orden.
- La proyección gerencial muestra agregados y detalle autorizado, no la base
  completa.
- Los logs no incluyen secretos, tokens de sesión, API keys ni datos personales
  innecesarios.
- Las respuestas de error no revelan si un cliente/orden existe fuera del
  alcance del usuario.

### 9.4 Auditoría y retención (propuesta a aprobar)

| Dato | Retención propuesta |
| --- | --- |
| Eventos de sync aplicados | 24 meses |
| Auditoría de accesos y cambios | 5 años |
| Snapshots de proyección | 90 días |
| Backups de MySQL Web | 30 días |
| Logs de aplicación | 30–90 días |

La retención final debe acordarse con el dueño antes de producir con datos
reales.

## 10. Conflictos y sincronización

### 10.1 Reglas

- Optimistic lock por `version`.
- Eventos idempotentes por `event_id` e `idempotency_key`.
- Orden anulada: bloquea nuevas escrituras de lote/fecha.
- Cambio local y remoto simultáneo: no se sobrescribe en silencio. Se genera
  conflicto y cola de revisión.
- Un evento rechazado no se reintenta indefinidamente sin intervención.

### 10.2 Flujo de lote/fecha

1. Operario guarda lote/fecha en la nube con `version` conocida.
2. La nube responde **Pendiente de sincronización** y encola el evento.
3. El agente lo levanta por HTTPS saliente.
4. La fábrica valida orden, renglón, versión y estado.
5. Si aplica, actualiza MySQL y devuelve ACK con el valor final.
6. La nube marca **Sincronizado en fábrica**.
7. Si hay conflicto o error, muestra **Error/conflicto** con causa y permite
   reintentar o pedir revisión.

La nube no debe decir “guardado en fábrica” antes del ACK.

### 10.3 Offline, reintentos y dead-letter

- Outbox e inbox persistentes en disco/DB.
- Reintentos con backoff exponencial y jitter.
- Deduplicación al reenviar.
- Tras N intentos, el evento pasa a dead-letter con causa visible.
- Reconciliación manual desde una pantalla/log de operador.
- Reinicio del agente: retoma desde el último cursor confirmado.
- Internet caído una hora: los eventos se acumulan y se aplican al volver.

### 10.4 Reconciliación

Job periódico que compara:

- cantidad de órdenes publicadas vs. proyectadas;
- checksum por orden (`order_uid`, `version`, estado);
- eventos aplicados vs. ACK;
- lote/fecha canónico vs. último valor web.

Diferencias => cola de revisión, nunca corrección silenciosa.

## 11. Migración de dominio

Situación de partida:

- URL propuesta y **no verificada**: `https://femag.186.5.245.12.sslip.io`.
- QR de órdenes ya imprimen una URL configurable (#801).
- Los tokens son estables y no dependen del dominio.

Plan:

1. Verificar DNS, TLS y `/health` del dominio provisorio con datos demo.
2. Antes de imprimir masivamente, definir el dominio definitivo
   `portal.femag.com.ar`.
3. Emitir certificado para el dominio nuevo y mantener el anterior como alias.
4. Redirigir 301 el dominio viejo al nuevo **preservando ruta y query**:
   `/orden/<token>` debe seguir funcionando.
5. Actualizar la URL base desde FEMAG Desktop; las órdenes nuevas salen con el
   dominio nuevo.
6. Mantener el dominio viejo mientras existan QR impresos que lo usen.
7. Comunicar que un QR viejo no cambia solo: si el dominio viejo se retira, hay
   que reimprimir.

No se garantiza que `sslip.io` exista indefinidamente. Por eso no se debe usar
como dominio de impresión masiva.

## 12. Observabilidad y operación

La web y el agente deben exponer:

- `last_synced_at` por stream;
- lag en segundos/minutos;
- cantidad de eventos pendientes, fallidos y en dead-letter;
- último error y causa;
- versión desplegada y `source_sha`;
- estado de `/health` y de MySQL.

Alertas mínimas:

- sync sin avanzar más de X minutos;
- dead-letter > 0;
- errores 5xx sostenidos;
- certificado próximo a vencer;
- backup fallido.

## 13. Rollback

| Falla | Acción | Impacto |
| --- | --- | --- |
| Deploy web roto | Rollback a la imagen anterior en Coolify | Fábrica sigue operando |
| MySQL Web corrupta | Restore del último backup verificado | Se pierden eventos posteriores al backup; se reconcilia |
| Agente roto | Detener servicio y volver a la versión anterior | La nube queda pendiente; no se pierde el outbox |
| Dominio/TLS mal configurado | Volver al dominio anterior | QR viejos siguen funcionando |
| Sync con conflicto masivo | Pausar agente y activar reconciliación manual | Operación de fábrica intacta |
| Web caída | Operar con Desktop o webapp LAN | Sin pérdida de datos locales |

Criterio: la nube nunca debe ser un punto único de falla para la fábrica.

## 14. Fases y criterios go/no-go

### Corte A — Especificación e infraestructura (#802, #803)

Go:

- este documento y contratos aprobados;
- despliegue demo aislado con HTTPS válido y MySQL privado;
- `/health` sano, backup/restore probado;
- sin datos reales.

No-go:

- TLS no válido, MySQL público o deployment no reproducible.

### Corte B — V1 QR/lotes (#804, #801, #805)

Go:

- QR público abre la orden desde fuera de la LAN;
- login + CSRF + RBAC funcionando;
- lote/fecha aplicados en fábrica con ACK visible;
- anulación, offline, duplicados y conflictos probados;
- rollback probado.

No-go:

- se afirma “sincronizado” sin ACK;
- pérdida o doble aplicación de datos;
- QR viejo deja de funcionar sin plan de reimpresión.

### Corte C — Gerencia (#806)

Go:

- cifras reconciliadas contra Desktop en el mismo corte;
- permisos por rol y aislamiento probados;
- `última actualización` visible.

### Corte D — Portal B2B (#807)

Go:

- aislamiento multi-cliente probado;
- pedido web no crea orden/remito/stock/contabilidad;
- aprobación local con auditoría;
- falla de sync deja el pedido como recibido/pendiente.

## 15. Estrategia de pruebas

| Tipo | Qué cubre |
| --- | --- |
| Contrato | Esquemas JSON, ejemplos, compatibilidad v1 y versionado |
| Unitarias | Validación de campos, versiones, cursores, idempotencia |
| Integración | Outbox/inbox, ACK, reintentos, dead-letter |
| Seguridad | RBAC, IDOR, CSRF, rate limit, replay, TLS, secretos |
| Aislamiento | Cliente A no accede a B; operario no accede a gerencia |
| E2E LAN | QR → orden → lote → persistencia en MySQL fábrica |
| E2E público | Celular fuera de LAN → HTTPS → login → lote → ACK |
| Recuperación | Internet caído, reinicio, 500, respuesta duplicada, fuera de orden |
| Conciliación | Conteos/checksums y resolución de diferencias |
| Performance | Latencia de sync, volumen de órdenes y rate limits |

Casos obligatorios de #804/#805:

- orden creada, modificada y anulada;
- dos renglones con lote y fecha;
- internet caído una hora y retorno;
- duplicados y respuesta 500;
- reinicio del agente;
- evento fuera de orden;
- token inválido;
- conflicto entre edición local y remota;
- misma entidad mapeada de forma consistente;
- última sync y errores visibles.

## 16. Riesgos y decisiones abiertas

| Riesgo / decisión | Estado |
| --- | --- |
| Dominio `sslip.io` no desplegado ni con TLS verificado | Abierto; no usar para QR masivos |
| Identidad web de operarios/gerencia en MySQL separada | Definir provisión y vinculación con `user_uid` |
| Credenciales de clientes B2B | Diseñar en Corte D; no reutilizar usuarios de Desktop |
| Retención de datos y auditoría | Propuesta en este documento; requiere aprobación |
| Latencia y volumen de sync | Medir en Corte B antes de gerencia |
| Costo y capacidad del VPS | Validar con carga demo |
| Soporte operativo de conflictos | Requiere pantalla/log y responsable |
| Impresión masiva antes del dominio definitivo | Evitar; reimprimir es costoso |

## 17. Requisitos operativos antes de datos reales

- [ ] Contratos v1 aprobados.
- [ ] Dominio definitivo decidido y TLS válido.
- [ ] MySQL Web privado y backup/restore probado.
- [ ] Secretos fuera de git y rotación definida.
- [ ] RBAC y aislamiento probados.
- [ ] Sync con idempotencia, dead-letter y reconciliación probados.
- [ ] Rollback documentado y ejecutado al menos una vez.
- [ ] `/health` y alertas monitoreadas.
- [ ] Plan de reimpresión de QR comunicado.
- [ ] Validación manual E2E con evidencia.
