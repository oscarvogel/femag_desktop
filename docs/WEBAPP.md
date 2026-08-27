# FEMAG Webapp móvil

La webapp vive en `webapp/` y comparte los modelos Peewee y la configuración de base de datos de FEMAG Desktop. No depende de PyQt para ejecutarse.

## Objetivo inicial

- abrir una orden por su `qr_token`;
- escanear el QR desde la cámara del celular;
- mostrar sus productos desde un celular;
- cargar o corregir `lote` y `fecha_elaboracion` por línea;
- persistir esos datos en la misma base utilizada por Desktop.

## Arquitectura

La webapp está pensada para ejecutarse inicialmente dentro de la red de FEMAG y poder trasladarse más adelante a otro servidor sin modificar FEMAG Desktop.

```text
PCs FEMAG Desktop (PyQt) ─┐
                          ├──> MySQL FEMAG
Servidor Webapp ──────────┘
       ▲
       │ HTTP local :8000
       │
     Caddy
       ▲
       │ HTTPS
       │
Celulares / tablets
```

Desktop y Webapp utilizan la misma base MySQL. La webapp reutiliza `app.config.database` y `app.models`, por lo que no mantiene un modelo de datos paralelo.

El servidor de la webapp puede ser Windows o Linux. No necesita ser la misma máquina donde corre MySQL; solamente debe tener conectividad TCP hacia la base FEMAG.

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

En un despliegue definitivo se recomienda que Waitress/Webapp escuche solo en la interfaz local y que Caddy sea el único punto publicado a la LAN.

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

Cuando se defina el hostname/IP estable del servidor, un cambio posterior podrá imprimir directamente una URL como:

```text
https://femag.local/orden/<token>
```

No será necesario modificar el modelo ni regenerar los tokens existentes.

## Cámara y HTTPS

El acceso a cámara desde JavaScript requiere un contexto seguro en los navegadores modernos. En la misma PC `http://localhost:8000` normalmente funciona, pero desde un celular accediendo a `http://192.168.x.x:8000` el navegador puede bloquear la cámara por no usar HTTPS.

Por ese motivo, el despliegue interno definitivo debe publicar la webapp con HTTPS y un hostname estable. El ingreso manual del QR sigue disponible aunque la cámara esté bloqueada.

El lector usa la API nativa `BarcodeDetector` cuando está disponible; Chrome/Edge actuales son el objetivo inicial. Si el navegador no la soporta, la pantalla informa el motivo y mantiene el ingreso manual.

## Caddy

Caddy es un servidor web/reverse proxy. En FEMAG se utilizará delante de la aplicación Python para resolver HTTPS, certificados y el acceso desde la red sin incorporar esa complejidad dentro de Flask/Waitress.

El flujo recomendado es:

```text
https://femag.local
        │
        ▼
      Caddy
        │ reverse_proxy
        ▼
http://127.0.0.1:8000
        │
        ▼
  FEMAG Webapp
        │
        ▼
     MySQL
```

Caddy funciona tanto en Windows como en Linux, por lo que esta arquitectura no condiciona qué sistema operativo tenga actualmente el servidor de la fábrica.

### Caddyfile de referencia

Una configuración inicial puede ser:

```caddyfile
femag.local {
    tls internal
    reverse_proxy 127.0.0.1:8000
}
```

`tls internal` hace que Caddy genere certificados mediante su CA interna. Los dispositivos que vayan a utilizar la cámara deben confiar en esa CA para que el navegador considere segura la conexión.

No copiar esta configuración a producción sin adaptar hostname, puertos, firewall y confianza de certificados a la red real de FEMAG.

## Certificado interno y celulares

Para que `https://femag.local` no muestre advertencias y habilite correctamente las APIs seguras del navegador, los celulares/tablets deben confiar en la autoridad certificadora interna que firma el certificado.

Alternativas para una etapa futura:

1. **CA interna de Caddy**: adecuada para una LAN cerrada; requiere instalar/confiar el certificado raíz en los dispositivos autorizados.
2. **Dominio real con certificado público**: evita distribuir una CA interna, pero requiere resolver correctamente DNS y validación del dominio.

Para la primera instalación dentro de FEMAG se evaluará cuál conviene según el servidor, la red y la cantidad/tipo de celulares utilizados.

## Windows

La arquitectura es válida en Windows:

- Python/Waitress ejecuta `python -m webapp`;
- Caddy puede instalarse como servicio de Windows;
- el firewall debe permitir HTTPS desde la LAN hacia Caddy;
- MySQL debe ser accesible desde la máquina de la webapp.

El servicio web debe configurarse para iniciar automáticamente con Windows una vez validado el entorno productivo.

## Linux

La misma arquitectura es válida en Linux:

- Python/Waitress ejecuta `python -m webapp`;
- Caddy puede ejecutarse como servicio `systemd`;
- el firewall permite HTTPS desde la LAN;
- MySQL debe ser accesible desde el servidor de la webapp.

La aplicación Python y Caddy deben configurarse para iniciar automáticamente con el servidor.

## DNS / nombre interno

Es preferible un nombre estable como:

```text
femag.local
```

antes que imprimir una IP directamente en los QR. De esa forma, si la webapp cambia de servidor/IP, se modifica la resolución de nombre y no es necesario cambiar la lógica de FEMAG.

La forma concreta de resolver `femag.local` dependerá de la infraestructura existente: DNS del router/servidor, DNS interno o configuración equivalente.

## Despliegue futuro en otro servidor

La webapp puede trasladarse a otra máquina Windows o Linux manteniendo la misma base MySQL.

Para hacerlo deberían cambiar solamente aspectos de infraestructura:

- host/IP del servidor web;
- variables de entorno de conexión MySQL si corresponde;
- DNS de `femag.local`;
- Caddy/certificados.

FEMAG Desktop no necesita trasladarse junto con la webapp.

## Seguridad

Esta primera etapa está pensada para LAN interna. Antes de publicarla hacia Internet se debe agregar autenticación/autorización, HTTPS con una estrategia de certificados adecuada, política de exposición de MySQL, auditoría de cambios y endurecimiento del servidor.

MySQL nunca debe exponerse directamente a los celulares ni incluir credenciales de base en JavaScript. Los celulares hablan solamente con la webapp; la webapp es quien accede a MySQL.

## Healthcheck

```text
GET /health
```

Devuelve HTTP 200 cuando la webapp puede ejecutar una consulta contra la base configurada y HTTP 503 si no hay conexión.

## Pendiente para instalación en FEMAG

Antes del despliegue definitivo hay que relevar el servidor existente y confirmar:

- si utiliza Windows o Linux;
- IP y nombre de red;
- dónde corre actualmente MySQL;
- puerto y reglas de firewall;
- Wi-Fi/red que utilizarán los celulares;
- mecanismo disponible para DNS interno;
- dispositivos/navegadores que utilizarán el lector QR.

Con esos datos se define el Caddyfile y el mecanismo de certificados definitivo sin acoplar el código a una máquina concreta.
