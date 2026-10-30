# FEMAG Webapp móvil

La webapp vive en `webapp/` y comparte los modelos Peewee y la configuración de base de datos de FEMAG Desktop. No depende de PyQt para ejecutarse.

## Objetivo inicial

- abrir una orden por su `qr_token`;
- escanear el QR desde la cámara del celular;
- mostrar sus productos desde un celular;
- cargar o corregir `lote` y `fecha_elaboracion` por línea;
- persistir esos datos en la misma base utilizada por Desktop;
- registrar los partes de embolsado de la planta desde el celular, con el
  operador identificado (ver "Registro de producción" más abajo).

## Arquitectura

La webapp está pensada para ejecutarse inicialmente dentro de la red de FEMAG y poder trasladarse más adelante a otro servidor sin modificar FEMAG Desktop. Para el despliegue en contenedor/Coolify ver [`FEMAG_WEB_COOLIFY_DEPLOY.md`](FEMAG_WEB_COOLIFY_DEPLOY.md).

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

La configuración de MySQL es la misma que utiliza FEMAG Desktop: las variables se llaman `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` y `DB_PASSWORD` (sin el prefijo `FEMAG_`), y se leen del archivo indicado por `FEMAG_ENV_FILE`, que por defecto es `.env`. El motor de base se elige con `FEMAG_DB_ENGINE=mysql`.

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

Variables de la sesión y de los QR de turno:

| Variable | Para qué sirve |
|---|---|
| `FEMAG_WEB_SECRET_KEY` | Secreto con el que se firman las cookies de sesión. Si no está, la webapp genera uno aleatorio y lo guarda en el directorio de configuración del puesto. **El valor fijo que tenía antes el código se quitó**: con una clave conocida cualquiera podía firmar una cookie inventada y entrar como otro usuario. |
| `FEMAG_WEB_PUBLIC_URL` | URL pública del servidor (por ejemplo `https://femag.lan`). Es la que se imprime en los QR de turno. Sin ella se usa la URL que ve el propio servidor, que detrás de un proxy es la interna y no sirve desde el celular. |
| `FEMAG_WEB_SECRET_FILE` | Ruta donde se guarda el secreto de sesión generado. Por defecto, `%LOCALAPPDATA%\FEMAG Desktop\webapp_secret.key` (o `~/.config/FEMAG Desktop/` en Linux). En el despliegue del servidor se fija en `C:\ProgramData\FEMAG\webapp_secret.key`, fuera del perfil de la cuenta de servicio, y se protege con los mismos permisos que la configuración. |

En un despliegue definitivo se recomienda que Waitress/Webapp escuche solo en la interfaz local y que Caddy sea el único punto publicado a la LAN.

## Flujo con el QR de órdenes (#801)

El QR de las órdenes se imprime con una **URL navegable**, no con el texto
legado:

```text
http://192.168.0.111:8000/orden/<token>
```

La URL base se configura desde FEMAG Desktop en **Sistema > Servidor web** y
se guarda en la base central, así que la comparten todos los puestos. Se acepta
`http://` o `https://`, con puerto opcional y sin ruta; el slash final se
normaliza. El valor de ejemplo para el piloto en la LAN de fábrica es
`http://192.168.0.111:8000`.

- Cada QR nuevo se arma con la URL configurada y el `qr_token` existente. No se
  regeneran tokens ni se toca el modelo de órdenes.
- Si no hay URL configurada, la orden se imprime **sin QR** y con un aviso para
  configurar el servidor. No se imprime el formato legado para no mostrar un
  acceso que un lector genérico no puede abrir.
- Debajo del QR se imprime la dirección del servidor y el número de orden para
  poder abrir la orden a mano.
- Cambiar la URL afecta solo a las impresiones nuevas. Un QR ya impreso no
  cambia: para acceder con navegador hay que reimprimir la orden.

La portada incluye **Escanear QR**. En un navegador compatible abre la cámara
trasera, detecta el QR, copia automáticamente el valor leído y abre la orden.
El escáner acepta tanto la URL nueva como el formato legado
`FEMAG:LOAD_ORDER:<token>` y el token suelto.

### Escritura protegida

El token del QR identifica la orden pero **no autoriza a escribirla**. Para
guardar lote y fecha de elaboración:

- la webapp exige una sesión iniciada con un usuario de FEMAG Desktop;
- el formulario lleva un token CSRF atado a la sesión;
- cada guardado deja una fila de auditoría en el módulo `Despachos`, con el
  usuario, la IP del celular y los renglones modificados.

La consulta de la orden por token sigue siendo pública y muestra solo los datos
operativos necesarios para cargar el lote.

En la instancia cloud, `/orden/<token>` busca primero la orden local y, si no
existe, la **proyección de sync**. Lote y fecha se pueden editar; el cambio
queda en la proyección y se encola como evento cloud → fábrica. La pantalla
muestra **Pendiente de sincronización** hasta que el agente lo aplica y
confirma el ACK. Un snapshot posterior no pisa ese valor pendiente.

En órdenes con pallets, la carga es por **contenido de pallet**: cada artículo
del pallet tiene su propio lote y fecha, y se pueden cargar varios lotes en la
misma orden. Sigue habiendo **un QR por orden**.

Después de guardar, la webapp muestra una **pantalla de confirmación** con la
orden, los lotes y las fechas registradas, y los botones para volver a la orden
o buscar otra. Así el operario sabe que el guardado terminó y no repite el
envío. El botón se deshabilita mientras se envía el formulario y un guardado
sin cambios no genera otra fila de auditoría.

## Registro de producción desde el celular

En la planta embolsan varias personas y el dueño pidió que quedara registrado
diariamente qué embolsó cada uno (#754). La captura vive en `/produccion`.

### Qué hace

- Exige iniciar sesión con un usuario de FEMAG: son los mismos usuarios del
  escritorio, validados por `AuthService`. La sesión dura 12 horas.
- El parte guarda **quién lo cargó** (`ProductionPart.recorded_by`) además de
  quién lo confirmó. En un turno puede haber varias personas embolsando y cada
  una carga su propio parte: el modelo admite varios partes por (fecha, turno),
  así que la atribución queda por parte.
- El circuito de stock es **el mismo** del escritorio: `ProductionPartService`
  escribe las bolsas que entran y el material que sale en la misma transacción,
  no duplica saldos y bloquea la confirmación si no hay materia prima
  suficiente.
- Un parte confirmado no se edita más: se anula con motivo, y la anulación
  genera los movimientos contrarios.

### QR por turno

Un administrador puede imprimir la hoja de QR por turno en
`/produccion/turnos.pdf`. Cada QR abre `/produccion` con el turno ya puesto:
el operario escanea y carga, sin elegir turno ni escribir la dirección.

Para que el QR sea alcanzable desde el celular hay que definir
`FEMAG_WEB_PUBLIC_URL` con la URL pública del servidor.

### Qué hay que preparar en la base

La columna `production_part.recorded_by` es nueva. `validate_runtime_schema`
corta el arranque del Desktop si a la base le falta, así que hay que preparar
el esquema antes de que abran los puestos actualizados:

- **Crear o actualizar ahora las tablas de FEMAG**, en el asistente de conexión; o
- `python scripts/init_db.py`.

La webapp no prepara el esquema por su cuenta: es el camino de siempre.

### Lo que falta del lado de los datos

La pantalla no inventa datos. Para registrar bolsas hacen falta

- productos con **peso de bolsa** cargado en el maestro, y
- al menos un producto con rol de stock **Materia prima**, para el consumo.

Si no hay ninguno, el parte se puede guardar pero **no se puede confirmar**: el
servicio lo bloquea a propósito, porque sin salida de materia prima las bolsas
entrarían al stock y el mismo kilo quedaría en los dos stocks.

## Cámara y HTTPS

El acceso a cámara desde JavaScript requiere un contexto seguro en los navegadores modernos. En la misma PC `http://localhost:8000` normalmente funciona, pero desde un celular accediendo a `http://192.168.x.x:8000` el navegador puede bloquear la cámara por no usar HTTPS.

Por ese motivo, el despliegue interno definitivo debe publicar la webapp con HTTPS y un hostname estable. El ingreso manual del QR sigue disponible aunque la cámara esté bloqueada.

El lector usa la API nativa `BarcodeDetector` cuando está disponible; Chrome/Edge actuales son el objetivo inicial. Si el navegador no la soporta, la pantalla informa el motivo y mantiene el ingreso manual.

## Caddy

Caddy es un servidor web/reverse proxy. En FEMAG se utilizará delante de la aplicación Python para resolver HTTPS, certificados y el acceso desde la red sin incorporar esa complejidad dentro de Flask/Waitress.

El flujo recomendado es:

```text
https://femag.lan
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
femag.lan {
    tls internal
    reverse_proxy 127.0.0.1:8000
}
```

`tls internal` hace que Caddy genere certificados mediante su CA interna. Los dispositivos que vayan a utilizar la cámara deben confiar en esa CA para que el navegador considere segura la conexión.

No copiar esta configuración a producción sin adaptar hostname, puertos, firewall y confianza de certificados a la red real de FEMAG.

## Certificado interno y celulares

Para que `https://femag.lan` no muestre advertencias y habilite correctamente las APIs seguras del navegador, los celulares/tablets deben confiar en la autoridad certificadora interna que firma el certificado.

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
femag.lan
```

antes que imprimir una IP directamente en los QR. De esa forma, si la webapp cambia de servidor/IP, se modifica la resolución de nombre y no es necesario cambiar la lógica de FEMAG.

El nombre **no debe terminar en `.local`**. La RFC 6762 reserva ese sufijo para mDNS: los celulares (iOS y Android) resuelven los nombres `.local` por multicast y no consultan el DNS de la LAN, así que el QR abriría en el teléfono sin encontrar el servidor. La misma RFC recomienda `.lan`, `.corp`, `.internal` o `.intranet` para redes privadas.

La forma concreta de resolver `femag.lan` dependerá de la infraestructura existente: DNS del router/servidor, DNS interno o configuración equivalente.

## Despliegue futuro en otro servidor

La webapp puede trasladarse a otra máquina Windows o Linux manteniendo la misma base MySQL.

Para hacerlo deberían cambiar solamente aspectos de infraestructura:

- host/IP del servidor web;
- variables de entorno de conexión MySQL si corresponde;
- DNS de `femag.lan`;
- Caddy/certificados.

FEMAG Desktop no necesita trasladarse junto con la webapp.

## Seguridad

Esta primera etapa está pensada para LAN interna. Antes de publicarla hacia Internet se debe agregar autenticación/autorización, HTTPS con una estrategia de certificados adecuada, política de exposición de MySQL, auditoría de cambios y endurecimiento del servidor.

MySQL nunca debe exponerse directamente a los celulares ni incluir credenciales de base en JavaScript. Los celulares hablan solamente con la webapp; la webapp es quien accede a MySQL.

Estado de la autenticación:

- `/produccion` **exige iniciar sesión** con un usuario de FEMAG (#754). Es lo que
  permite saber quién cargó cada parte.
- `/orden/<token>` permite **consultar** la orden con el token del QR, pero
  **modificar lote y fecha exige sesión iniciada y token CSRF** (#801). Cada
  cambio queda auditado en el módulo `Despachos` con el usuario y la IP del
  celular. El QR identifica la orden; no autoriza a escribirla.
- El secreto con el que se firman las cookies de sesión no puede ser un valor
  fijo del repositorio: se resuelve por `FEMAG_WEB_SECRET_KEY` o por un archivo
  aleatorio del directorio de configuración del puesto.
- Con `FEMAG_WEB_PUBLIC_URL` en `https://`, las cookies se marcan `Secure`,
  `HttpOnly` y `SameSite=Lax`, la sesión dura 12 horas y se envían cabeceras
  HSTS, `X-Frame-Options`, `nosniff` y `Referrer-Policy`.
- El login se bloquea temporalmente tras 5 intentos fallidos por usuario o
  equipo en 15 minutos.

## Healthcheck

```text
GET /health
```

Devuelve HTTP 200 cuando la webapp puede ejecutar una consulta contra la base configurada y HTTP 503 si no hay conexión.

## Instalación en el servidor de la fábrica

El despliegue en la LAN está resuelto con una arquitectura que no acopla el código a una máquina concreta:

```text
Celular/tablet -- HTTPS 443 --> Caddy --> Waitress 127.0.0.1:8000 --> MySQL
```

Decisiones tomadas para la fábrica:

- **Windows Server 2019** como servidor de la webapp.
- **MySQL en el mismo servidor**: la webapp se conecta por loopback y los celulares nunca hablan con la base.
- **Certificado de la CA interna de Caddy** (`tls internal`): los celulares confían en la raíz que distribuye el administrador.

El procedimiento completo, con la distribución de la CA en Android e iOS, el DNS interno, el perfil de red del firewall y la evidencia que hay que dejar, está en [WEBAPP_SERVER_WINDOWS.md](WEBAPP_SERVER_WINDOWS.md).
