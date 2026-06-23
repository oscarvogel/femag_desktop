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

## Backups

Configurar `BACKUP_DIR` y, si corresponde, `BACKUP_EXTRA_DIR`.
Programar en Windows Task Scheduler:

```bash
python scripts/run_backup.py --user admin
```
