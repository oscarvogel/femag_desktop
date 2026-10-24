# Servidor de la webapp en Windows Server 2019

Procedimiento de instalación y validación del servidor de la webapp móvil de
FEMAG en la fábrica. El código y los scripts están en el repositorio; lo que
todavía **no** se ejecutó contra el servidor real está marcado como
**PENDIENTE EN EL SERVIDOR**.

## Arquitectura

```text
 Celular / tablet
       │  HTTPS 443  (certificado de la CA interna de Caddy)
       ▼
    Caddy            servicio Windows "FEMAG Caddy"
       │  HTTP 127.0.0.1:8000
       ▼
    Waitress/Flask   tarea programada "FEMAG Webapp QR", cuenta SYSTEM
       │  MySQL por loopback
       ▼
    MySQL            en el mismo servidor
```

El celular nunca habla con MySQL ni con el puerto 8000. Sólo con el 443.

## Los dos modos

|  | Modo simple (sin HTTPS) | Modo con HTTPS |
| --- | --- | --- |
| Qué corre | Waitress en el puerto 8000, escuchando en la placa de red | Waitress en loopback + Caddy en el 443 |
| Qué se instala en el celular | **Nada** | La raíz de Caddy (1 paso en Android, 2 en iOS) |
| HTTPS | No | Sí, con la CA interna de Caddy |
| Cámara dentro de la página | No | Sí |
| Se puede instalar como PWA | No | Sí |
| Cifrado en la LAN | No | Sí |
| Comando | `-SkipCaddy` | el default |

**Para arrancar en la fábrica, el modo simple.** El flujo que pidió Oscar
(cargar partes de embolsado) **no usa la cámara**: el turno se elige de un
select nativo y el QR de turno se escanea con la **cámara nativa** del celular
(Google Lens o la app de Cámara), que no exige contexto seguro y abre el link
igual.

El modo con HTTPS queda para dos casos: cuando haya que usar el escáner de
órdenes QR **desde la página** (el de `/produccion` no lo necesita), o cuando
el cifrado en la LAN sea un requisito. La pantalla de órdenes ya tiene entrada
manual, así que el modo simple no deja nada sin hacer.

## Decisiones de fábrica

| Tema | Decisión |
| --- | --- |
| Sistema | Windows Server 2019 |
| MySQL | En el mismo servidor (`DB_HOST=127.0.0.1`) |
| Certificados | CA interna de Caddy (`tls internal`) |
| Nombre interno | `femag.lan` |
| Puerto público | 443 |
| Puerto backend | 8000, sólo loopback |

### Por qué el nombre no termina en `.local`

La RFC 6762 reserva el sufijo `.local` para mDNS. Los celulares (iOS y Android)
resuelven los nombres `.local` por multicast y **no consultan el DNS de la LAN**,
así que el QR de turnos abriría en el teléfono sin encontrar el servidor. La
misma RFC recomienda `.lan`, `.corp`, `.internal` o `.intranet` para redes
privadas. Si más adelante hay un dominio propio, mejor ese.

## La forma más simple: el instalador

Hay un camino de un solo paso: **`FEMAG_Webapp_Server_Setup.exe`**.

1. Copiar el `.exe` al servidor.
2. Correrlo **como administrador**.
3. Escribir el nombre del host, el puerto del servidor web y los datos de MySQL.
4. Terminar.

El instalador deja esto andando:

| Qué | Dónde |
| --- | --- |
| El servidor | `C:\FEMAG\webapp\FEMAG Webapp Server.exe` (no necesita Python) |
| La configuración | `C:\ProgramData\FEMAG\webapp.env` (sólo SYSTEM y administradores) |
| El lanzador | `C:\FEMAG\webapp\run_webapp.cmd` |
| El arranque automático | tarea programada `FEMAG Webapp QR` (SYSTEM, se reinicia 3 veces si se cae) |
| El firewall | regla `FEMAG Webapp Server` en el puerto elegido |
| El registro de la instalación | `C:\ProgramData\FEMAG\logs\instalar_servidor.log` |

El instalador **verifica** que el servidor responda en `/health` antes de
terminar. Si no levanta, muestra el error, deja la cola del log en pantalla y
termina con código de error: el administrador no se queda creyendo que quedó
andando.

Para una instalación desatendida se puede pasar todo por línea de comandos:

```powershell
FEMAG_Webapp_Server_Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART `
  /HOST=femag.lan /WEBPORT=8000 /DBHOST=127.0.0.1 /DBNAME=femag_desktop `
  /DBUSER=femag_webapp /DBPASSWORD=<clave>
```

**Los pasos 1 a 3 de más abajo son del camino manual** (instalar con el script
de despliegue). Sirven cuando hay que actualizar sin reinstalar, o para ver
exactamente qué se está tocando. Con el instalador no hacen falta: no hay que
instalar Python, ni copiar el checkout, ni compilar nada.

El instalador se genera desde el repositorio con:

```powershell
.\scripts\build_webapp_server_installer.ps1
```

y queda en `installer\output\FEMAG_Webapp_Server_Setup.exe`.

## Requisitos previos

En el servidor:

- [ ] Windows Server 2019 con la placa de red en perfil **Domain o Private** (ver [Paso 5](#paso-5--perfil-de-red-y-firewall)).
- [ ] MySQL 8.x (o MariaDB) corriendo en el mismo servidor.
- [ ] `femag.lan` resuelto por el DNS de la LAN.
- [ ] Caddy 2.x (`C:\Caddy\caddy.exe`), **sólo si se va el modo con HTTPS**.

Estos tres son **sólo del camino manual**:

- [ ] Python 3.12 instalado. El script acepta 3.10 o superior.
- [ ] Una copia del checkout del repositorio en el servidor.

Con el instalador no hacen falta: el servidor va congelado en un `.exe` y no
necesita Python ni el checkout.

**Git no hace falta en el servidor.** `requirements-web.txt` lista sólo lo que
usa la webapp (peewee, PyMySQL, python-dotenv, Pillow, reportlab, Flask,
waitress). No arrastra PyQt5 ni `pyqt5libs`, que venía desde git.

## Paso 0 — Preparar la base (bloqueante)

La webapp arranca, autentica y guarda partes. Lo que **no** puede es confirmar
un parte si a la base le faltan datos de fábrica.

### 0.1 Esquema

La columna `production_part.recorded_by` es nueva y `validate_runtime_schema`
hace fallar el arranque de FEMAG Desktop si la base no la tiene. Preparar el
esquema **antes** de actualizar los puestos:

- desde el asistente de conexión de FEMAG Desktop: *Crear o actualizar ahora las tablas de FEMAG*; o
- `python scripts\init_db.py`.

### 0.2 Datos de fábrica

Verificado en la base de producción (21/10/2026), falta:

| Dato | Estado | Sin esto |
| --- | --- | --- |
| Producto con `stock_role='materia_prima'` | 38 productos, **todos** `terminado` | No se puede registrar el consumo y **ningún parte se puede confirmar** |
| `peso_unitario_kg` de los productos | 24 de 38 en cero | No hay kilos, no hay bolsa |
| Inventario inicial | 53 movimientos, todos `dispatch`, **cero entradas** | El control de stock rechaza la confirmación por material insuficiente |
| Usuarios de planta | 4 usuarios, todos de oficina | Los operarios no pueden entrar al webapp |

Los usuarios de planta se crean en FEMAG Desktop (Administrador → Usuarios). El
webapp usa los mismos usuarios del escritorio.

### 0.3 Usuario MySQL de la webapp

El servicio web corre con `FEMAG_AUTO_MIGRATE_SCHEMA=0`: **no** crea ni altera
tablas, así que no necesita `CREATE`/`ALTER`/`DROP`.

```sql
CREATE USER 'femag_webapp'@'localhost'  IDENTIFIED BY '<clave de la webapp>';
CREATE USER 'femag_webapp'@'127.0.0.1' IDENTIFIED BY '<clave de la webapp>';
GRANT SELECT, INSERT, UPDATE, DELETE ON femag_desktop.* TO 'femag_webapp'@'localhost';
GRANT SELECT, INSERT, UPDATE, DELETE ON femag_desktop.* TO 'femag_webapp'@'127.0.0.1';
FLUSH PRIVILEGES;
```

## Paso 1 — Instalar Python y Caddy

**Python** (descargar de python.org, *Add python.exe to PATH*):

```powershell
py -3.12 --version
```

**Caddy**, sólo para el modo con HTTPS (descargar `caddy_2.x.x_windows_amd64.zip`
de la página de releases):

```powershell
C:\Caddy\caddy.exe version
```

> `encode zstd gzip` en el Caddyfile requiere **Caddy 2.4 o superior**. Con una
> versión anterior, `caddy validate` falla y el despliegue se frena.

En el **modo simple** no se instala Caddy: no hace falta para nada de lo que
hace el operario.

## Paso 2 — Copiar el código al servidor

> **El instalador de FEMAG Desktop NO sirve para el servidor.** `FEMAG Desktop.exe`
> es la aplicación de escritorio (PyQt5): es un bundle de PyInstaller cuyo
> punto de entrada es `app/production_entrypoint.py`, y **no incluye el paquete
> `webapp`**. Instalarlo en el servidor deja la GUI de oficina, no la webapp.
>
> El instalador que sí sirve es **`FEMAG_Webapp_Server_Setup.exe`**, que es
> otro bundle: el del servidor. Ver [la forma más simple](#la-forma-más-simple-el-instalador).

El camino manual (este paso) necesita **el código fuente**, no un ejecutable. Y no el repo
entero: el checkout local pesa **1,4 GB**, casi todo en venvs y builds que no
sirven para nada acá (`.venv`, `.venv_broken`, `venv_p4`, `dist`, `build`,
`installer/output`, `backups`, `outputs`). Lo que la webapp realmente carga al
arrancar son 26 módulos:

```text
app.config      app.models (todos)      app.services
audit_service   auth_service   production_part_service   stock_service
webapp
```

Ni uno solo de `app.ui`: **el servidor no carga PyQt**. Por eso el paquete
real son ~12 MB.

### Copiar sólo lo necesario

Desde la máquina de desarrollo, con el recurso compartido administrativo
habilitado en el servidor:

```powershell
robocopy "C:\Programacion\dante\femag_desktop" "\\SRV-FEMAG\admin\C$\FEMAG\source\femag_desktop" /MIR `
    /XD .git .venv .venv_broken venv venv_p4 build dist outputs output installer backups .codegraph tests docs `
    /XF .env *.credential *.pyc *.sqlite3
```

Y el runbook, para que quede a mano en el servidor:

```powershell
robocopy "C:\Programacion\dante\femag_desktop\docs" "\\SRV-FEMAG\admin\C$\FEMAG\source\femag_desktop\docs" WEBAPP_SERVER_WINDOWS.md WEBAPP.md
```

El despliegue vuelve a sincronizar con `/MIR` al directorio de instalación, así
que esta copia sólo tiene que estar reasonably al día. Para actualizar, se
vuelve a correr el `robocopy` y después el despliegue.

### Alternativa: un zip

Si no hay recurso compartido, se puede armar un zip con esas mismas carpetas
(`app`, `webapp`, `requirements-web.txt` y `scripts`) y pasarlo por el medio
que haya. **No** include el instalador de FEMAG Desktop.

## Paso 3 — Primer despliegue

Copiar el script al servidor y ejecutarlo **desde una consola de PowerShell
como administrador**.

### Modo simple (sin HTTPS) — el recomendado para arrancar

```powershell
cd C:\FEMAG\source\femag_desktop
.\scripts\deploy_webapp_server.ps1 `
    -SourcePath C:\FEMAG\source\femag_desktop `
    -SkipCaddy `
    -PublicHostName femag.lan
```

La webapp queda escuchando en el puerto 8000 de la placa de red y el firewall
abre ese puerto. El QR de turnos sale con `http://femag.lan:8000`.

### Modo con HTTPS

```powershell
cd C:\FEMAG\source\femag_desktop
.\scripts\deploy_webapp_server.ps1 `
    -SourcePath C:\FEMAG\source\femag_desktop `
    -CaddyExePath C:\Caddy\caddy.exe `
    -PublicHostName femag.lan
```

### Lo que pasa en las dos corridas

La primera vez el script crea `C:\ProgramData\FEMAG\webapp.env` a partir de la
plantilla y **se detiene** para que se completen `DB_USER` y `DB_PASSWORD`.
Después:

1. Editar `C:\ProgramData\FEMAG\webapp.env` con el usuario y la clave del punto 0.3.
2. Volver a ejecutar el mismo comando.

El script deja:

| Qué | Dónde |
| --- | --- |
| Código de la webapp | `C:\FEMAG\webapp` |
| Configuración protegida | `C:\ProgramData\FEMAG\webapp.env` |
| Secreto de sesión | `C:\ProgramData\FEMAG\webapp_secret.key` |
| Caddyfile (sólo modo HTTPS) | `C:\ProgramData\FEMAG\Caddyfile` |
| Tarea programada | `FEMAG Webapp QR` (arranca con el sistema, corre como SYSTEM) |
| Servicio | `FEMAG Caddy` (sólo modo HTTPS) |
| Regla de firewall | `FEMAG Webapp HTTPS` (443) o `FEMAG Webapp HTTP` (8000) |

### Si el servidor tiene la red en perfil Public

El script avisa por pantalla si el perfil de red activo no está cubierto por la
regla de firewall. Pasarlo explícitamente:

```powershell
.\scripts\deploy_webapp_server.ps1 -FirewallProfiles Domain,Private,Public ...
```

o corregir el perfil:

```powershell
Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
```

## Paso 4 — DNS interno

El servidor tiene que resolver `femag.lan` y los celulares también.

- **En el servidor**, para poder verificarse a sí mismo, alcanza con la entrada
  de hosts en `C:\Windows\System32\drivers\etc\hosts`:

  ```text
  192.168.0.50   femag.lan
  ```

- **En los celulares**, la entrada de hosts no es práctica. Hace falta DNS real:
  - el DNS del router, si permite agregar nombres;
  - o el rol DNS de Windows Server 2019 (`Add-WindowsFeature DNS`);
  - o un servidor DNS interno que ya exista.

Verificar desde el celular, con datos o con un navegador:

```text
nslookup femag.lan
```

> Si `nslookup` devuelve la IP del servidor pero el navegador no entra, el
> problema es el **firewall o el perfil de red**, no el DNS.

## Paso 5 — Perfil de red y firewall

La regla que abre el 443 la crea el despliegue. Lo que decide si aplica es el
perfil de red de la placa:

```powershell
Get-NetConnectionProfile
Get-NetFirewallRule -DisplayName "FEMAG Webapp HTTPS"
```

El 443 tiene que ser alcanzable **desde la LAN** y sólo desde la LAN: el 8000
escucha en `127.0.0.1` y no es accesible desde afuera.

## Paso 6 — Distribuir la CA raíz de Caddy

> **Sólo para el modo con HTTPS.** En el modo simple no hay CA que instalar y
> el celular no tiene que hacer nada.

Caddy firma los certificados con su propia CA. Sin instalar esa raíz en el
celular, el navegador avisa que el certificado no es confiable y **la cámara
no abre**.

### 6.1 Sacar la raíz del servidor

El servicio corre como SYSTEM, así que la CA está en su perfil:

```text
C:\Windows\System32\config\systemprofile\AppData\Roaming\Caddy\pki\authorities\local\root.crt
```

Copiar ese archivo a un lugar accesible y pasarlo a los celulares.

> Si se borra ese directorio, Caddy genera una CA nueva y **todos los celulares
> hay que volver a configurarlos**.

### 6.2 Android (Chrome o Edge)

1. Settings → Security → Encryption & credentials → **Install a certificate** → **CA certificate**.
2. Elegir el archivo `root.crt`.
3. Android exige un bloqueo de pantalla (PIN, patrón o contraseña) antes de
   aceptar una CA.
4. Some modelos (Samsung, Xiaomi) lo esconden en otros menús: buscar
   *Certificate* en los ajustes.

Chrome confía en las CA instaladas por el usuario. **Ojo**: las apps que
tienen su propia lista de raíces no la van a confiar; por eso hay que usar el
navegador, no la app nativa de cámara.

### 6.3 iPhone / iPad (Safari)

Son **dos** pasos, y con uno solo no funciona:

1. Mandar el `root.crt` al teléfono (correo, AirDrop, WhatsApp) y abrirlo.
   Aparece *Se ha descargado un perfil de configuración*.
2. Settings → General → **VPN & Device Management** → perfil de Caddy → **Instalar**.
3. Settings → General → About → **Certificate Trust Settings** → activar
   **confianza completa** para la raíz de Caddy.

Sin el paso 3 el perfil queda instalado pero no confiable, y Safari sigue
avisando.

### 6.4 Computadora de la planta (para pruebas)

```powershell
certutil -addstore -f "Root" C:\ruta\root.crt
```

## Paso 7 — Validar

### Desde el servidor

```powershell
Invoke-WebRequest http://127.0.0.1:8000/health -UseBasicParsing | Select-Object -ExpandProperty Content
```

El backend tiene que responder `{"ok": true, ...}`. Si MySQL no está o la
configuración está mal, el detalle viene en el cuerpo de la respuesta.

### Desde un celular de la LAN

1. `https://femag.lan/health` → tiene que abrir sin aviso de certificado.
   (En el modo simple: `http://femag.lan:8000/health`.)
2. `https://femag.lan/produccion` → redirige al login.
   (En el modo simple: `http://femag.lan:8000/produccion`.)
3. Entrar con un usuario de planta.
4. Cargar un parte de prueba, confirmarlo y comprobar que el stock refleja las
   bolsas que entraron y el material que salió.
5. Escanear con la cámara del celular el QR de un turno → abre la pantalla con
   el turno prellenado. En el modo simple, con la **cámara nativa** del
   celular; en el modo con HTTPS, también se puede desde la página.

### Evidencia que hay que dejar

- La URL de `/health` desde un celular.
- Una captura de la pantalla de partes con el parte cargado, con el usuario de
  planta visible.
- La consulta del saldo en la base después de confirmar.

## Re-despliegue

Con el checkout actualizado en `C:\FEMAG\source\femag_desktop`:

```powershell
cd C:\FEMAG\source\femag_desktop
.\scripts\deploy_webapp_server.ps1 `
    -SourcePath C:\FEMAG\source\femag_desktop `
    -SkipCaddy `
    -PublicHostName femag.lan
```

(modo con HTTPS: cambiar `-SkipCaddy` por `-CaddyExePath C:\Caddy\caddy.exe`)

El script sincroniza con `/MIR`, reinstala las dependencias, reescribe el
lanzador, reinicia la tarea y recarga Caddy. **No** toca
`C:\ProgramData\FEMAG\webapp.env` ni el secreto de sesión: la base y las
sesiones siguen como estaban.

## Rollback

1. Detener la tarea y el servicio:

   ```powershell
   Stop-ScheduledTask -TaskName "FEMAG Webapp QR"
   Stop-Service -Name "FEMAG Caddy"
   ```

2. Quitar el firewall:

   ```powershell
   Remove-NetFirewallRule -DisplayName "FEMAG Webapp HTTPS"
   ```

3. Sacar el código anterior y volver a desplegarlo. La base no se toca: los
   partes cargados siguen ahí.

## Problemas frecuentes

| Síntoma | Causa probable | Qué mirar |
| --- | --- | --- |
| En el modo simple el celular no entra a `http://femag.lan:8000` | El puerto 8000 quedó cerrado o el perfil de red es Public | `Get-NetFirewallRule -DisplayName "FEMAG Webapp HTTP"`, `Get-NetConnectionProfile` |
| El navegador avisa que la conexión no es segura | Es normal en el modo simple: no hay HTTPS | — |
| El celular no entra a `https://femag.lan` | Perfil de red en Public o DNS que no resuelve | `Get-NetConnectionProfile`, `nslookup femag.lan` desde el celular |
| El navegador avisa que el certificado no es confiable | Falta instalar la raíz de Caddy, o en iOS falta el paso de confianza completa | [Paso 6](#paso-6--distribuir-la-ca-raíz-de-caddy) |
| La cámara no abre dentro de la webapp | Contexto no seguro: se entró por `http://`. En el modo simple es lo esperado | La URL de la barra tiene que ser `https://`; para escanear el QR de turno alcanza con la cámara nativa del celular |
| El QR de turno abre en `http://` o con la IP interna | Falta `FEMAG_WEB_PUBLIC_URL` | El despliegue lo define con `-PublicHostName`; tiene que ser la URL que el celular puede abrir |
| El parte no se puede confirmar | Falta materia prima, falta peso unitario o no hay inventario inicial | [Paso 0.2](#02--datos-de-fábrica) |
| El script dice que no encuentra Python | Python no está en el PATH | `py -3.12 --version`; si no, `-PythonPath C:\ruta\python.exe` |
| `caddy validate` falla | Caddy anterior a 2.4 (no soporta `encode zstd`) | `caddy.exe version` |
| Los mensajes del script salen con caracteres raros | PowerShell 5.1 leyó el .ps1 como Windows-1252 | El archivo va con BOM UTF-8 a propósito; si se editó y se perdió, volver a guardarlo con BOM |

## Lo que este documento NO cubre

- La **migración de esquema** y los **datos de fábrica**: son [Paso 0](#paso-0--preparar-la-base-bloqueante) y no son código.
- El **perfil "Producción"** en la matriz de permisos: los usuarios del webapp
  heredan los perfiles del escritorio.
- Las **rutas de órdenes QR** (`/orden/<token>`), que todavía no autentican.
- El **modo offline**: la webapp es online-first.
