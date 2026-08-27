# FEMAG Webapp móvil

La webapp vive en `webapp/` y comparte los modelos Peewee y la configuración de base de datos de FEMAG Desktop. No depende de PyQt para ejecutarse.

## Objetivo inicial

- abrir una orden por su `qr_token`;
- mostrar sus productos desde un celular;
- cargar o corregir `lote` y `fecha_elaboracion` por línea;
- persistir esos datos en la misma base utilizada por Desktop.

## Instalación

Desde la raíz del repositorio:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements-web.txt
```

Linux:

```bash
source .venv/bin/activate
pip install -r requirements-web.txt
```

La configuración de MySQL es la misma que utiliza FEMAG Desktop (`FEMAG_DB_HOST`, `FEMAG_DB_PORT`, `FEMAG_DB_NAME`, `FEMAG_DB_USER`, `FEMAG_DB_PASSWORD` o el archivo indicado por `FEMAG_ENV_FILE`).

## Ejecución

```bash
python -m webapp
```

Por defecto escucha en todas las interfaces, puerto 8000:

```text
http://IP_DEL_SERVIDOR:8000/
```

Puede modificarse sin cambiar código:

```text
FEMAG_WEB_HOST=0.0.0.0
FEMAG_WEB_PORT=8000
```

## Flujo con el QR actual

El QR impreso actualmente contiene:

```text
FEMAG:LOAD_ORDER:<token>
```

La portada de la webapp acepta ese texto completo o solamente `<token>`. Además, la orden puede abrirse directamente con:

```text
http://IP_DEL_SERVIDOR:8000/orden/<token>
```

Cuando se defina el hostname/IP estable del servidor, un cambio posterior podrá imprimir directamente esa URL en el QR sin modificar el modelo ni regenerar los tokens existentes.

## Despliegue futuro en otro servidor

La webapp puede copiarse/instalarse en otra máquina Windows o Linux. La condición es que esa máquina tenga conectividad TCP hacia el mismo MySQL utilizado por FEMAG Desktop. No necesita ejecutarse en la misma PC que el desktop.

## Seguridad

Esta primera etapa está pensada para LAN interna. Antes de publicarla hacia Internet se debe agregar autenticación/autorización, HTTPS, política de exposición de MySQL y auditoría de cambios.

## Healthcheck

```text
GET /health
```

Devuelve HTTP 200 cuando la webapp puede ejecutar una consulta contra la base configurada y HTTP 503 si no hay conexión.
