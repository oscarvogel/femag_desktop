# EXE gerencial: reporte + cotizaciones

El `FEMAG_Managerial_Summary.exe` ahora conserva el reporte gerencial y suma
los comandos operativos de cotizaciones. No requiere Python en el servidor.

> El agente `FEMAG Sync Agent` ya actualiza las cotizaciones una vez por día
> después de las 19:00 ART dentro de `--sync`. Estos comandos quedan para
> backfill histórico, importaciones manuales y diagnóstico; no hace falta una
> tarea diaria separada.

## Comandos

```powershell
# Reporte gerencial (sin cambios)
FEMAG_Managerial_Summary.exe --health-check
FEMAG_Managerial_Summary.exe --send-now
FEMAG_Managerial_Summary.exe --daily

# Actualizacion diaria de cotizaciones (ArgentinaDatos + BNA + faltantes)
FEMAG_Managerial_Summary.exe --update-rates
FEMAG_Managerial_Summary.exe --update-rates --json

# Importacion historica: primero siempre dry-run
FEMAG_Managerial_Summary.exe --import-rates --budgets --dry-run --types oficial
FEMAG_Managerial_Summary.exe --import-rates --budgets --types oficial --max-records 500
FEMAG_Managerial_Summary.exe --import-rates --from-date 2026-01-01 --to-date 2026-11-27 --types oficial
```

`--import-rates` acepta las mismas opciones del CLI `app.jobs.import_historical_exchange_rates`:
`--budgets`, `--from-date`, `--to-date`, `--currency`, `--types`, `--dry-run`,
`--refresh`, `--max-records`, `--max-requests`, `--holidays-file`,
`--coverage-any-source`, `--json`.

## Configuracion

El reporte gerencial usa el runtime y la configuracion segura de FEMAG Desktop.
Los comandos de cotizaciones tienen su propio circuito:

- Si el EXE corre con el mismo usuario de Windows que FEMAG, toman la conexion
  segura ya configurada.
- Si corre como tarea/SYSTEM, crear
  `C:\ProgramData\FEMAG\exchange_rates.env` con las credenciales MySQL y
  ejecutarlo con `FEMAG_EXCHANGE_RATE_ENV_FILE` apuntando a ese archivo.
- No reemplaza ni modifica el `.env` ni las credenciales de FEMAG.

## Programador de tareas

Se recomienda una tarea separada de la del reporte, para que un fallo de correo
o WhatsApp no bloquee la ingesta:

```bat
schtasks /Create /TN "FEMAG - Cotizaciones" /SC DAILY /ST 19:00 ^
  /RU "%USERNAME%" /RP * ^
  /TR "\"C:\ProgramData\FEMAG\tools\FEMAG_Managerial_Summary.exe\" --update-rates --json --log-file C:\ProgramData\FEMAG\logs\exchange_rates.log"
```

La importacion historica no debe programarse como tarea diaria: se ejecuta
manualmente por rango o por presupuestos, con `--dry-run` primero.

## Prueba segura

1. Copiar el EXE al servidor.
2. Ejecutar `--update-rates --json` y revisar el resumen.
3. Ejecutar `--import-rates --budgets --dry-run --types oficial --json` y
   revisar la conciliacion.
4. Recien despues ejecutar una importacion acotada con `--max-records`.

No hay pantalla de cotizaciones todavia (#972). El EXE solo ejecuta los jobs.

## Build

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_managerial_summary.ps1 -SkipInstallDependencies
```

Salida: `dist\FEMAG_Managerial_Summary.exe`.
