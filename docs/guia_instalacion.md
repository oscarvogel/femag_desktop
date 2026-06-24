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
