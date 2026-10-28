#!/bin/sh
# Arranque del contenedor FEMAG Web (#803).
#
# Las migraciones NO se aplican solas en produccion. Para la instancia demo se
# habilita FEMAG_WEB_AUTO_INIT_SCHEMA=1; en produccion se corre scripts/init_db.py
# como tarea controlada antes de desplegar.
set -eu

if [ "${FEMAG_WEB_AUTO_INIT_SCHEMA:-0}" = "1" ]; then
    echo "Preparando esquema de FEMAG Web..."
    python scripts/init_db.py
fi

if [ "${FEMAG_WEB_SEED_DEMO:-0}" = "1" ]; then
    echo "Cargando datos sinteticos de demo..."
    python scripts/seed_webapp_demo.py
fi

exec gunicorn --config deploy/coolify/gunicorn.conf.py webapp.wsgi:app
