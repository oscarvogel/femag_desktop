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
python -m app.jobs.sync_agent --init-schema
```

`--snapshot`:

1. Selecciona órdenes en estado `Pendiente`, `Emitida` o `Anulada`.
2. Asigna UUID estables a orden, renglón, cliente, destino y pallet.
3. Arma el snapshot según `docs/contracts/femag_web_sync_v1/`.
4. Lo envía a `POST /api/sync/v1/snapshots/orders`.
5. Guarda el cursor local `factory_snapshot` y muestra un resumen JSON.

`--status` muestra el estado local de outbox, inbox, cursores y conflictos.

## Instalación en fábrica (EXE + tarea programada)

El servidor de fábrica **no necesita Python**.

1. Generar/copiar `FEMAG_Sync_Agent_Setup.exe` y el archivo `femag_sync.env`
   (URL + token) a la máquina.
2. Copiar `femag_sync.env` a `C:\ProgramData\FEMAG\sync.env` o ejecutar el
   instalador con `/SYNCENV=C:\ruta\femag_sync.env`.
3. Ejecutar `FEMAG_Sync_Agent_Setup.exe` como administrador.
4. El instalador:
   - copia el EXE a `C:\FEMAG\sync`;
   - lee `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` y `DB_PASSWORD` desde
     `C:\ProgramData\FEMAG\webapp.env`;
   - escribe y protege `C:\ProgramData\FEMAG\sync.env`;
   - crea las tablas de sync con `FEMAG Sync Agent.exe --init-schema`
     (el usuario MySQL necesita permiso para crear tablas);
   - registra la tarea **FEMAG Sync Agent** cada 5 minutos como SYSTEM.
5. Revisar `C:\ProgramData\FEMAG\logs\sync_agent.log`.

Si el usuario MySQL de la webapp no puede crear tablas, el instalador falla
con un mensaje claro. En ese caso, ejecutar una vez el SQL incluido con un
usuario administrador de MySQL:

```bash
mysql -u root -p femag_desktop < C:\FEMAG\sync\sync_schema.sql
```

Después volver a ejecutar el instalador o la tarea.

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
- No se modifican órdenes ni movimientos: el publicador solo lee.

## Pendiente

- Eventos incrementales por orden creada/modificada/anulada.
- Consumo de eventos cloud → fábrica para lote/fecha.
- Outbox en el envío del snapshot (hoy es un POST directo).
- Empaquetado, servicio, bloqueo de instancia única y métricas.
- Lectura de la proyección desde la pantalla cloud (#805).
