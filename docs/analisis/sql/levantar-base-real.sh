#!/bin/bash
# Levanta un MariaDB 11.8 aislado con el dump de produccion importado.
#
# No toca la base de trabajo: corre en un contenedor propio, con el puerto
# 3307 publicado para que la app de Windows se pueda conectar.
set -e
CONTAINER=${CONTAINER:-femag-analysis}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

docker rm -f "$CONTAINER" 2>/dev/null || true
docker run -d --name "$CONTAINER" \
  -p 3307:3306 \
  -e MARIADB_ROOT_PASSWORD=root \
  -e MARIADB_DATABASE=femag_desktop \
  mariadb:11 >/dev/null
echo "contenedor arriba"

bash "$SCRIPT_DIR/importar-dump.sh"
