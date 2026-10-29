# FEMAG Sync — agente de fábrica (#804)

El agente publica un **snapshot completo** de órdenes desde la MySQL de fábrica
hacia FEMAG Web y aplica los eventos de lote/fecha que la nube deja pendientes.
Los incrementales por orden quedan para una etapa posterior.

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
python -m app.jobs.sync_agent --sync
python -m app.jobs.sync_agent --snapshot
python -m app.jobs.sync_agent --status
python -m app.jobs.sync_agent --init-schema
```

`--sync` (lo que ejecuta la tarea programada):

1. Trae los eventos pendientes de la nube.
2. Aplica solo `lote` y `fecha_elaboracion`, validando orden, renglón, estado y
   versión.
3. Deja rastro en `SyncInbox` y auditoría.
4. Confirma el ACK a la nube.
5. Publica el snapshot actualizado de fábrica.

`--snapshot` publica solo el snapshot. `--status` muestra outbox, inbox,
cursores y conflictos. `--init-schema` crea las tablas de sync.

## Instalación en fábrica (EXE + tarea programada)

El servidor de fábrica **no necesita Python**.

1. Copiar `FEMAG_Sync_Agent_Setup.exe` y `femag_sync.env` **a la misma
   carpeta** del servidor.
2. Ejecutar `FEMAG_Sync_Agent_Setup.exe` como administrador.
3. En la página **MySQL administrador**, ingresar una vez un usuario con
   permiso para crear tablas (por ejemplo `root`). No se guarda.
4. El instalador:
   - copia el EXE a `C:\FEMAG\sync`;
   - copia `femag_sync.env` a `C:\ProgramData\FEMAG\sync.env`;
   - lee `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` y `DB_PASSWORD` desde
     `C:\ProgramData\FEMAG\webapp.env`;
   - crea las tablas de sync en la base correcta usando el usuario
     administrador;
   - ejecuta la primera sincronización;
   - registra la tarea **FEMAG Sync Agent** cada 5 minutos como SYSTEM.
5. Revisar `C:\ProgramData\FEMAG\logs\sync_agent.log`.

Si se prefiere instalación desatendida, se puede pasar
`/SYNCENV=C:\ruta\femag_sync.env`. El SQL de respaldo queda en
`C:\FEMAG\sync\sync_schema.sql` y es idempotente.

Para regenerar el instalador:

```powershell
.\scripts\build_sync_agent_installer.ps1
```

Salida: `installer\output\FEMAG_Sync_Agent_Setup.exe`.

El agente busca `C:\ProgramData\FEMAG\sync.env` por defecto; también se puede
indicar otro archivo con `FEMAG_SYNC_ENV_FILE`.

## Seguridad

- Solo conexiones HTTPS salientes; no se abren puertos en fábrica.
- El token viaja en `Authorization: Bearer` y no se registra en logs.
- El snapshot no incluye precios, costos, saldos, stock, remitos ni contabilidad.
- El consumidor solo puede escribir `lote` y `fecha_elaboracion`; no toca
  cantidades, stock, remitos ni contabilidad.
- Si la orden está anulada o la versión no coincide, el evento va a conflicto
  y no se aplica.

## Pendiente

- Eventos incrementales por orden creada/modificada/anulada.
- Outbox en el envío del snapshot (hoy es un POST directo).
- Bloqueo de instancia única, métricas y resolución de conflictos desde UI.
- Actualización masiva de versiones de orden para conflictos más finos.
