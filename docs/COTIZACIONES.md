# Cotizaciones historicas: proveedores y actualizacion diaria (#969)

Este documento registra la evaluacion de proveedores, la seleccion y el
procedimiento operativo del job que alimenta la tabla `exchangerate` de #968.

## Convencion

- `base_currency`: moneda cotizada (1 unidad).
- `quote_currency`: moneda del precio.
- `USD/ARS`: pesos argentinos por un dolar. `BRL/ARS`: pesos por un real.
- Compra/venta se guardan en `DECIMAL(18,6)`; nunca se convierten por `float`.
- La fecha efectiva se conserva tal como la publica el proveedor. No se usa una
  cotizacion posterior a la fecha consultada.
- Cada registro conserva `source` y `rate_type`. Para una serie homogenea hay
  que consultar con `source`; el servicio #968 no elige una fuente cuando hay
  mas de una para la misma fecha y tipo.

## Evaluacion de proveedores (consulta HTTP real 2026-11-27)

| Proveedor | Endpoint verificado | Auth/costo | Tipos | Compra/venta | Fecha efectiva | Historico | BRL/ARS | Uso |
|---|---|---|---|---|---|---|---|---|
| DolarAPI | `https://dolarapi.com/v1/dolares` | Sin auth, gratis | oficial, blue, bolsa (MEP), contadoconliqui (CCL), mayorista, tarjeta, cripto | Si | `fechaActualizacion` (UTC) | No propio; deriva a ArgentinaDatos | `https://dolarapi.com/v1/cotizaciones/brl` | **Seleccionado** (actual) |
| ArgentinaDatos | `https://api.argentinadatos.com/v1/cotizaciones/dolares/{casa}/{yyyy}/{mm}/{dd}` | Sin auth, gratis | los 6 tipos USD + BRL | Si | Campo `fecha` explicito | Si, diario desde 2011 (BRL desde 2023) | `https://api.argentinadatos.com/v1/cotizaciones/brl/{yyyy}/{mm}/{dd}` | **Seleccionado** (faltantes) |
| Banco Nacion (BNA) | `https://www.bna.com.ar/Cotizador/HistoricoPrincipales?id=billetes&fecha=dd/mm/yyyy&idMoneda=22&idMoneda=23` | Sin auth, gratis, HTML publico | Dolar U.S.A y Real (billetes) | Si | Columna `Fecha` de la tabla | Si, por fecha (devuelve fechas cercanas) | Si, cotizacion cada 100 unidades | **Seleccionado** (BNA) |
| BCRA | `https://api.bcra.gob.ar/estadisticascambiarias/v1.0/Cotizaciones` | Sin auth, gratis; requiere UA de navegador | Oficial por moneda | **No: un solo `tipoCotizacion`** | Campo `fecha` | Diario | Si (BRL 278,497522 al 26/11) | **No integrado**: el modelo #968 exige compra y venta |
| Bluelytics | `https://api.bluelytics.com.ar/v2/latest` | Sin auth, gratis | oficial, blue | Si | No informa fecha efectiva; `last_update` es el momento de consulta | No en `latest` | No | No seleccionado |
| Criptoya | `https://criptoya.com/api/dolar` | Sin auth, gratis | oficial, blue, MEP, CCL, cripto, etc. | Si (segun tipo) | Timestamp Unix de cotizacion | No documentado | No | No seleccionado |
| MonedAPI | `https://monedapi.ar/api/v2/quotes`, `/api/v2/date/{fecha}` | Sin auth, gratis | 9 USD + BNA + BRL | Si | `updatedAt` / `quotedAt` | Si, por fecha | Si (`/api/v2/brl/bna`) | Alternativa/backup; terminos no localizados (404 al consultar) |

### Muestra real obtenida (ultimo cierre 26/11/2026)

DolarAPI:

| Tipo | Compra | Venta |
|---|---:|---:|
| Oficial | 1575 | 1625 |
| Blue | 1690 | 1710 |
| MEP (`bolsa`) | 1657,2 | 1666,4 |
| CCL (`contadoconliqui`) | 1765,6 | 1767,9 |
| Mayorista | 1592,5 | 1601,5 |
| Tarjeta | 2047,5 | 2112,5 |
| BRL oficial | 281,318 | 281,4646 |

BNA (billetes, 26/11/2026):

| Moneda | Compra | Venta |
|---|---:|---:|
| Dolar U.S.A | 1575,0000 | 1625,0000 |
| Real (por 100) | 26100,0000 | 29100,0000 |
| Real (por 1) | 261,0000 | 291,0000 |

ArgentinaDatos (26/11/2026):

| Tipo | Compra | Venta |
|---|---:|---:|
| Oficial | 1580 | 1630 |
| Blue | 1690 | 1710 |
| MEP | 1664 | 1688,7 |
| CCL | 1765,6 | 1767,9 |
| Mayorista | 1595 | 1604 |
| Tarjeta | 2054 | 2119 |
| BRL oficial | 275,6705 | 275,8111 |

BCRA (26/11/2026): USD `tipoCotizacion=1601,5`; BRL `278,497522`. Un solo
valor por moneda, sin compra/venta. No se duplica el valor en ambas puntas
porque seria inventar una punta.

## Proveedores seleccionados y justificacion

1. **DolarAPI** cubre la cotizacion vigente de los seis tipos de dolar del
   alcance, con compra/venta y timestamp de actualizacion, sin autenticacion ni
   costo. Es la fuente principal del job diario.
2. **ArgentinaDatos** cubre el historico diario con `fecha` explicita y los
   mismos tipos, mas BRL. Se usa solo para recuperar fechas faltantes recientes
   (por defecto 7 dias); no es la importacion historica masiva de #970.
3. **BNA** es la unica fuente consultada para el tipo `bna`, porque DolarAPI
   `oficial` declara como fuente a Ambito Financiero. No se asume que `oficial`
   y `bna` sean la misma serie: se guardan con `rate_type` y `source` distintos.

No se integran BCRA, Bluelytics, Criptoya ni MonedAPI en esta etapa. BCRA no
puede representarse sin cambiar el modelo; los otros no aportan una fecha
efectiva confiable o son redundantes.

## Uso de datos y limites

- DolarAPI y ArgentinaDatos son proyectos abiertos (codigo MIT); el uso de las
  series permite conservar copia local citando el servicio. No hay maximo
  numerico, pero recomiendan no repetir la misma consulta en bucle y una
  consulta cada 3 horas por serie. Este job hace una corrida diaria.
- BNA no ofrece una API publica ni terminos de uso automatico. Se consulta la
  misma pagina publica del cotizador con timeout y reintentos acotados: una
  consulta por dia y, al recuperar faltantes, una por fecha. Es el punto mas
  fragil: un cambio de HTML produce un error controlado sin inventar datos.
- MonedAPI se verifico como alternativa, pero sus terminos no estaban
  disponibles en la URL consultada y su antiguedad es menor; no se usa como
  fuente principal.

## Infraestructura existente auditada

- `app/jobs/send_managerial_summary.py`: patron de job independiente que abre la
  base, asegura el esquema, ejecuta y cierra; se reutiliza ese esquema de
  arranque y de codigos de salida.
- `app/managerial_summary_entrypoint.py`: entrypoint de produccion con runtime y
  archivo de entorno dedicado. Este job usa `resolve_effective_connection_settings`
  y permite `FEMAG_EXCHANGE_RATE_ENV_FILE` en lugar de duplicar esa capa.
- `scripts/build_managerial_summary.ps1`: empaquetado PyInstaller del job
  gerencial. No se construye un EXE en esta etapa (fuera de alcance: instalador
  y despliegue).
- Tareas programadas existentes: se documenta el alta con `schtasks`; no se
  modifican tareas ni instaladores existentes.

## Job

Comando manual:

```bash
python -m app.jobs.update_exchange_rates
python -m app.jobs.update_exchange_rates --json
python -m app.jobs.update_exchange_rates --status
```

Opciones:

- `--lookback-days N`: dias hacia atras para faltantes (0..31, default 7).
- `--providers dolarapi,bna,argentinadatos`: subconjunto de proveedores.
- `--dry-run`: consulta y valida sin escribir.
- `--no-gap`: no recupera faltantes.
- `--no-lock`: solo diagnostico.
- `--status`: muestra ultima corrida, ultimo exito y ultimo error.

Codigos de salida: `0` OK / lock tomado, `2` parcial, `1` error.

Estado persistido en `AppParameter`:

- `exchange_rate.last_attempt_at`
- `exchange_rate.last_attempt_status`
- `exchange_rate.last_success_at`
- `exchange_rate.last_success_summary`
- `exchange_rate.last_error`

## Horario recomendado

**Todos los dias a las 19:00 de Argentina (UTC-3).** BNA actualiza su pizarra
alrededor de las 17:00 y DolarAPI publica el cierre entre las 17:00 y las 18:00.
Las 19:00 dejan margen para ambos. En fines de semana y feriados no hay
publicacion nueva; el job es idempotente y no borra nada. Si una corrida falla,
la siguiente recupera los dias faltantes dentro de la ventana de 7 dias.

## Configuracion en el Programador de tareas de Windows

1. Probar manualmente, desde la raiz del repositorio y con el Python del
   servidor:

   ```bat
   cd /d D:\FEMAG\femag_desktop
   .venv\Scripts\python.exe -m app.jobs.update_exchange_rates --json
   .venv\Scripts\python.exe -m app.jobs.update_exchange_rates --status
   ```

2. Crear la tarea (ejecutar como el mismo usuario que configuro FEMAG, para que
   use la configuracion segura; o como SYSTEM con un archivo de entorno):

   ```bat
   schtasks /Create /TN "FEMAG - Cotizaciones" /SC DAILY /ST 19:00 ^
     /RU "%USERNAME%" /RP * ^
     /TR "cmd /c cd /d D:\FEMAG\femag_desktop && .venv\Scripts\python.exe -m app.jobs.update_exchange_rates --json --log-file C:\ProgramData\FEMAG\logs\exchange_rates.log"
   ```

   Si la tarea corre como SYSTEM, crear
   `C:\ProgramData\FEMAG\exchange_rates.env` con las credenciales MySQL
   (`FEMAG_DB_ENGINE=mysql`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`,
   `DB_PASSWORD`) y ejecutar la tarea con:

   ```bat
   /TR "cmd /c set FEMAG_EXCHANGE_RATE_ENV_FILE=C:\ProgramData\FEMAG\exchange_rates.env && cd /d D:\FEMAG\femag_desktop && .venv\Scripts\python.exe -m app.jobs.update_exchange_rates --json"
   ```

3. Verificar:

   ```bat
   schtasks /Run /TN "FEMAG - Cotizaciones"
   schtasks /Query /TN "FEMAG - Cotizaciones" /V /FO LIST
   ```

   Revisar `C:\ProgramData\FEMAG\logs\exchange_rates.log` y el comando
   `--status`.

No se genera instalador ni se despliega en produccion en esta etapa.

## Lock, reintentos e interrupciones

- Lock de archivo atomico entre procesos (por defecto
  `%LOCALAPPDATA%\FEMAG Desktop\exchange_rate_update.lock` o
  `FEMAG_EXCHANGE_RATE_LOCK`). Si el proceso murio o el lock supera 2 horas, se
  recupera.
- Sin transacciones ni locks de escritura abiertos durante las consultas HTTP.
- Timeout HTTP por defecto 15 s y 2 reintentos solo para timeout, red, 429 y
  5xx.
- Si no hay Internet, no se borra ni modifica ninguna cotizacion existente; se
  registra el error y se sale con codigo 1.
- Si una fuente responde parcialmente, se guardan las cotizaciones validas y el
  estado queda `partial`.

## Riesgos residuales

- BNA depende de HTML publico y puede cambiar sin aviso.
- DolarAPI y ArgentinaDatos son APIs de terceros sin SLA; pueden cambiar
  nombres de campos o limites.
- Las series `oficial` de DolarAPI/ArgentinaDatos y `bna` pueden diferir; se
  conservan separadas por fuente/tipo.
- La recuperacion cubre 7 dias por defecto; la importacion historica masiva es
  #970. Ver `docs/COTIZACIONES_HISTORICAS.md`.
- No hay cotizaciones intradiarias: la fecha efectiva es diaria.
