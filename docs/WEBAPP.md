# FEMAG Webapp móvil

La webapp vive en `webapp/` y comparte los modelos Peewee y la configuración de base de datos de FEMAG Desktop. No depende de PyQt para ejecutarse.

## Objetivo inicial

- abrir una orden por su `qr_token`;
- escanear el QR desde la cámara del celular;
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

La portada incluye **Escanear QR**. En un navegador compatible abre la cámara trasera, detecta el QR, copia automáticamente el valor leído y abre la orden. También se mantiene el ingreso manual como fallback.

La orden puede abrirse directamente con:

```text
http://IP_DEL_SERVIDOR:8000/orden/<token>
```

Cuando se defina el hostname/IP estable del servidor, un cambio posterior podrá imprimir directamente esa URL en el QR sin modificar el modelo ni regenerar los tokens existentes.

## Cámara y HTTPS

El acceso a cámara desde JavaScript requiere un contexto seguro en los navegadores modernos. En la misma PC `http://localhost:8000` normalmente funciona, pero desde un celular accediendo a `http://192.168.x.x:8000` el navegador puede bloquear la cámara por no usar HTTPS.

Por ese motivo, para el despliegue interno definitivo se recomienda publicar la webapp con HTTPS en un hostname estable (por ejemplo `https://femag.local/`) mediante un proxy/servidor web interno. El ingreso manual del QR sigue disponible aunque la cámara esté bloqueada.

El lector usa la API nativa `BarcodeDetector` cuando está disponible; Chrome/Edge actuales son el objetivo inicial. Si el navegador no la soporta, la pantalla informa el motivo y mantiene el ingreso manual.

## Despliegue futuro en otro servidor

La webapp puede copiarse/instalarse en otra máquina Windows o Linux. La condición es que esa máquina tenga conectividad TCP hacia el mismo MySQL utilizado por FEMAG Desktop. No necesita ejecutarse en la misma PC que el desktop.

## Seguridad

Esta primera etapa está pensada para LAN interna. Antes de publicarla hacia Internet se debe agregar autenticación/autorización, HTTPS, política de exposición de MySQL y auditoría de cambios.

## Healthcheck

```text
GET /health
```

Devuelve HTTP 200 cuando la webapp puede ejecutar una consulta contra la base configurada y HTTP 503 si no hay conexión.
