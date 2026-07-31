# Guia de instalacion local FEMAG Desktop

## Requisitos

- Python 3.11 o superior.
- Servidor MySQL accesible desde los puestos internos.
- Usuario MySQL con permisos sobre la base `femag`.

## Preparacion

1. Crear un entorno virtual.
2. Instalar dependencias con `pip install -r requirements.txt`.
3. Copiar `.env.example` a `.env`.
4. Completar `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` y `DB_PASSWORD`.
5. Ejecutar `python scripts/init_db.py`.
6. Crear el primer usuario con `python scripts/create_admin_user.py admin <clave>`.

## Preparacion administrativa y arranque de puestos

La preparacion del esquema y el arranque diario usan credenciales distintas:

- El usuario administrativo de MySQL se usa solamente con `scripts/init_db.py` y puede crear o modificar el esquema.
- El usuario operativo de cada puesto necesita `SELECT`, `INSERT`, `UPDATE` y `DELETE`, pero no `CREATE`, `ALTER` ni `DROP`.
- Las contrasenas se guardan en archivos locales ignorados por Git. Nunca se incluyen en el instalador, el repositorio, comandos compartidos ni capturas.

Antes del primer despliegue, apuntar `FEMAG_ENV_FILE` a la configuracion administrativa y preparar la base una sola vez:

```powershell
$env:FEMAG_ENV_FILE = "C:\ruta-segura\femag-admin.env"
python scripts\init_db.py
```

El resultado esperado es `Base FEMAG preparada correctamente`. Si el comando falla, no se debe abrir ningun puesto hasta resolver la causa.

Para el uso diario, apuntar la aplicacion a la configuracion operativa del puesto:

```powershell
$env:FEMAG_ENV_FILE = "C:\ProgramData\FEMAG Desktop\config.env"
python -m app.main --ui
```

El arranque productivo solo conecta y valida tablas y columnas requeridas. No crea tablas, no agrega columnas, no crea indices y no ejecuta normalizaciones de datos. Si la base esta vacia o su esquema es incompatible, la aplicacion bloquea el inicio y muestra que un administrador debe ejecutar `scripts/init_db.py`.

El modo DEMO conserva su inicializacion automatica de SQLite y permanece aislado del flujo productivo.

Las primeras pruebas MySQL deben realizarse sobre una base descartable y vacia. Nunca usar la base productiva para validar cambios de esquema.

## Validacion

Ejecutar:

```bash
python -m pytest
python -m compileall app
python -m app.main --smoke
```

Para validar visualmente la aplicacion en un puesto de escritorio, abrir la UI real con:

```bash
py -3.12 -m app.main --ui
```

Si se necesita una revision visual sin depender de MySQL ni crear datos productivos, abrir la pantalla demo aprobada con:

```bash
py -3.12 -m app.main --demo-ui
```

La ventana debe mostrarse con el titulo `FEMAG Desktop`, que permite identificarla desde herramientas de revision visual como Computer Use. Estos comandos requieren una sesion grafica de Windows y PyQt5 instalado.

## Backups

Configurar `BACKUP_DIR` y, si corresponde, `BACKUP_EXTRA_DIR`.
Programar en Windows Task Scheduler:

```bash
python scripts/run_backup.py --user admin
```
