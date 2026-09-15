# Despliegue repetible de la webapp QR en Windows Server

Este procedimiento instala y actualiza la webapp QR en un servidor Windows. Está pensado para `ALMANET-SERVER`, donde se verificó MySQL Community Server 5.7.15 sobre Windows x64, aunque funciona con otro Windows Server que tenga conectividad a la misma base.

La webapp corre detrás de Caddy; los celulares no se conectan nunca a MySQL.

```text
Celular/tablet -- HTTPS 443 --> Caddy --> Waitress 127.0.0.1:8000 --> MySQL
```

## Requisitos previos

- Ejecutar PowerShell como administrador en el servidor.
- Python 3.12 instalado.
- Caddy descargado en una ruta estable, por ejemplo `C:\Caddy\caddy.exe`.
- Una copia actualizada del checkout de FEMAG en el servidor; no usar el directorio de instalación como fuente de una actualización.
- Un usuario MySQL exclusivo para la webapp, con sólo los permisos mínimos necesarios para consultar órdenes y actualizar lote/fecha de elaboración. No utilizar una cuenta administrativa.
- Un nombre interno estable, por ejemplo `femag.local`, que resuelva a la IP del servidor para los celulares.

La aplicación actual es sólo para LAN interna. No la exponga a Internet: antes requiere autenticación/autorización, auditoría y una política de certificados pública adecuada.

## Primera instalación

1. Copiar o clonar el repo en una carpeta fuente, por ejemplo `C:\FEMAG\source\femag_desktop`.
2. Ejecutar una primera vez para crear el archivo de configuración protegido:

   ```powershell
   cd C:\FEMAG\source\femag_desktop
   .\scripts\deploy_webapp_server.ps1 -CaddyExePath C:\Caddy\caddy.exe -PublicHostName femag.local
   ```

3. Completar `C:\ProgramData\FEMAG\webapp.env`. Debe conservar `FEMAG_AUTO_MIGRATE_SCHEMA=0`; el servicio web no puede crear ni alterar tablas. Usar `DB_HOST=127.0.0.1` cuando MySQL corre en el mismo servidor.
4. Volver a ejecutar el mismo comando.
5. Verificar desde el servidor `http://127.0.0.1:8000/health` y desde un teléfono `https://femag.local/health`.
6. Instalar la CA interna de Caddy en los celulares/tablets autorizados. Sin una conexión HTTPS confiable, el navegador puede bloquear la cámara.

El script crea/actualiza la tarea `FEMAG Webapp QR`, que se ejecuta como `SYSTEM`, y el servicio `FEMAG Caddy`. También crea una regla de firewall de entrada TCP 443 sólo para perfiles de red Dominio/Privado.

## Re-despliegue

Después de actualizar el checkout fuente a un commit validado, ejecutar exactamente el mismo comando:

```powershell
.\scripts\deploy_webapp_server.ps1 -SourcePath C:\FEMAG\source\femag_desktop -CaddyExePath C:\Caddy\caddy.exe -PublicHostName femag.local
```

El script sincroniza el código hacia `C:\FEMAG\webapp`, actualiza dependencias, reemplaza la tarea de inicio, valida la configuración de Caddy, recarga Caddy sin tiempo de caída y comprueba `GET /health`. La configuración MySQL queda fuera del checkout, no se copia al redeplegar y sus permisos quedan restringidos a `SYSTEM` y administradores.

Para preparar solamente el backend, sin publicar HTTPS aún, usar `-SkipCaddy`. No usar esa opción como despliegue final para celulares: la cámara requiere HTTPS.

## Rollback

Conservar el checkout o tag del último commit validado. Para volver atrás, apuntar `-SourcePath` a ese checkout y ejecutar el mismo comando. No modificar la base ni ejecutar migraciones como parte del rollback.

## Evidencia mínima por despliegue

- Commit o tag desplegado.
- Resultado de `http://127.0.0.1:8000/health`.
- Resultado de `https://femag.local/health` desde un celular de la LAN.
- Escaneo de un QR de orden real y validación del flujo permitido.
- Confirmación de que MySQL no es accesible desde los celulares.
