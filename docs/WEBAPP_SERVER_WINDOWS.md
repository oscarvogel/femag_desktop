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

## Requisitos previos

En el servidor:

- [ ] Windows Server 2019 con la placa de red en perfil **Domain o Private** (ver [Paso 5](#paso-5--perfil-de-red-y-firewall)).
- [ ] Python 3.12 instalado. El script acepta 3.10 o superior.
- [ ] Caddy 2.x: el binario `caddy.exe` en, por ejemplo, `C:\Caddy\caddy.exe`.
- [ ] MySQL 8.x (o MariaDB) corriendo en el mismo servidor.
- [ ] `femag.lan` resuelto por el DNS de la LAN.
- [ ] Una copia del checkout del repositorio en el servidor.

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

**Caddy** (descargar `caddy_2.x.x_windows_amd64.zip` de la página de releases):

```powershell
C:\Caddy\caddy.exe version
```

> `encode zstd gzip` en el Caddyfile requiere **Caddy 2.4 o superior**. Con una
> versión anterior, `caddy validate` falla y el despliegue se frena.

## Paso 2 — Copiar el código al servidor

Desde la máquina de desarrollo, con el recurso compartido administrativo
habilitado en el servidor:

```powershell
robocopy "C:\Programacion\dante\femag_desktop" "\\SRV-FEMAG\admin\C$\FEMAG\source\femag_desktop" /MIR /XD .git .venv __pycache__ .pytest_cache docs\prints /XF .env *.credential
```

El despliegue vuelve a sincronizar con `/MIR` al directorio de instalación, así
que esta copia sólo tiene que estar reasonably al día.

## Paso 3 — Primer despliegue

Copiar el script al servidor y ejecutarlo **desde una consola de PowerShell
como administrador**:

```powershell
cd C:\FEMAG\source\femag_desktop
.\scripts\deploy_webapp_server.ps1 `
    -SourcePath C:\FEMAG\source\femag_desktop `
    -CaddyExePath C:\Caddy\caddy.exe `
    -PublicHostName femag.lan
```

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
| Caddyfile | `C:\ProgramData\FEMAG\Caddyfile` |
| Tarea programada | `FEMAG Webapp QR` (arranca con el sistema, corre como SYSTEM) |
| Servicio | `FEMAG Caddy` (arranca automáticamente) |

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
2. `https://femag.lan/produccion` → redirige al login.
3. Entrar con un usuario de planta.
4. Cargar un parte de prueba, confirmarlo y comprobar que el stock refleja las
   bolsas que entraron y el material que salió.
5. Escanear con la cámara el QR de un turno → abre la pantalla con el turno
   prellenado.

### Evidencia que hay que dejar

- `https://femag.lan/health` desde un celular.
- Una captura de la pantalla de partes con el parte cargado, con el usuario de
  planta visible.
- La consulta del saldo en la base después de confirmar.

## Re-despliegue

Con el checkout actualizado en `C:\FEMAG\source\femag_desktop`:

```powershell
cd C:\FEMAG\source\femag_desktop
.\scripts\deploy_webapp_server.ps1 `
    -SourcePath C:\FEMAG\source\femag_desktop `
    -CaddyExePath C:\Caddy\caddy.exe `
    -PublicHostName femag.lan
```

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
| El celular no entra a `https://femag.lan` | Perfil de red en Public o DNS que no resuelve | `Get-NetConnectionProfile`, `nslookup femag.lan` desde el celular |
| El navegador avisa que el certificado no es confiable | Falta instalar la raíz de Caddy, o en iOS falta el paso de confianza completa | [Paso 6](#paso-6--distribuir-la-ca-raíz-de-caddy) |
| La cámara no abre dentro de la webapp | Contexto no seguro: se entró por `http://` | La URL de la barra tiene que ser `https://` |
| El QR de turno abre en `http://` o con la IP interna | Falta `FEMAG_WEB_PUBLIC_URL` | El despliegue lo define con `-PublicHostName`; tiene que empezar con `https://` |
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
