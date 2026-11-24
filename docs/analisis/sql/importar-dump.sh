#!/bin/bash
# Importa el dump de produccion en el contenedor MariaDB de analisis.
#
# El dump de Descargas (femag_desktop.sql, 24/11/2026) tiene el DDL desfasado
# respecto a sus propios INSERT: sin los ALTER de abajo, 8 tablas quedan vacias
# (clientes, presupuestos, transportistas, audit log, ...). Son dos pasadas:
# la primera crea las tablas, la segunda carga los datos con el esquema ya
# corregido.
set -e
DUMP=${DUMP:-/mnt/c/Users/Usuario/Downloads/femag_desktop.sql}
CONTAINER=${CONTAINER:-femag-analysis}

for i in $(seq 1 30); do
  if docker exec "$CONTAINER" mariadb -uroot -proot -e "SELECT 1" >/dev/null 2>&1; then
    echo "root listo"
    break
  fi
  sleep 3
done

echo "--- pasada 1: crea tablas (los INSERT de 8 tablas fallan) ---"
docker exec -i "$CONTAINER" mariadb -uroot -proot --default-character-set=utf8mb4 --force < "$DUMP" > /tmp/import_p1.log 2>&1
echo "errores SQL en la pasada 1: $(grep -c '^ERROR' /tmp/import_p1.log)"

echo "--- ALTER de las columnas que el DDL del dump no tiene ---"
docker exec -i "$CONTAINER" mariadb -uroot -proot <<'SQL'
USE femag_desktop;
ALTER TABLE auditlog ADD COLUMN user_id int NULL;
ALTER TABLE budget ADD COLUMN salesperson_id int NULL;
ALTER TABLE carrier ADD COLUMN fiscal_address varchar(255) NULL;
ALTER TABLE client ADD COLUMN whatsapp_phone varchar(255) NULL;
ALTER TABLE driver ADD COLUMN fiscal_address varchar(255) NULL;
ALTER TABLE loadorderdestination ADD COLUMN salesperson_id int NULL;
ALTER TABLE managerialsummarydelivery ADD COLUMN provider_status varchar(255) NULL;
ALTER TABLE salesperson ADD COLUMN whatsapp_phone varchar(255) NULL;
SQL

echo "--- pasada 2: import completo ---"
docker exec -i "$CONTAINER" mariadb -uroot -proot --default-character-set=utf8mb4 --force < "$DUMP" > /tmp/import_p2.log 2>&1
echo "errores SQL en la pasada 2: $(grep -c '^ERROR' /tmp/import_p2.log)"
docker exec "$CONTAINER" mariadb -uroot -proot -t -e "
USE femag_desktop;
SELECT (SELECT COUNT(*) FROM client) clientes,
       (SELECT COUNT(*) FROM budget) presupuestos,
       (SELECT COUNT(*) FROM clientaccountmovement) movimientos,
       (SELECT COUNT(*) FROM clientpayment) pagos;"
