"""
Validacion del issue #952 contra la base real.

Corre el codigo de la app (DashboardService) contra un MariaDB con el dump de
produccion `femag_desktop.sql` importado, y contrasta el resultado con el SQL
de control de la regla de exposicion.

Uso (desde la raiz del repo, con la base real levantada en 127.0.0.1:3307):

    python scripts/validate_issue_952_exposure.py
"""

import os
import sys
from pathlib import Path

os.environ["FEMAG_SECURE_CONFIG"] = "0"
os.environ["FEMAG_DB_ENGINE"] = "mysql"
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3307")
os.environ.setdefault("DB_NAME", "femag_desktop")
os.environ.setdefault("DB_USER", "root")
os.environ.setdefault("DB_PASSWORD", "root")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import build_mysql_database, database_proxy  # noqa: E402
from app.ui.dashboard import DashboardService  # noqa: E402


CONTROL_SQL = """
WITH docs AS (
    SELECT m.client_id,
           SUM(m.total_amount) AS vencido
    FROM clientaccountmovement m
    WHERE m.movement_type IN ('load_order_documental', 'load_order_documental_deferred')
      AND m.is_reversal = 0
      AND m.due_date IS NOT NULL
      AND m.due_date < CURDATE()
      AND NOT EXISTS (
          SELECT 1 FROM clientaccountmovement r
          WHERE r.reverses_id = m.id AND r.is_reversal = 1
      )
    GROUP BY m.client_id
),
saldos AS (
    SELECT client_id, ROUND(SUM(ROUND(total_amount, 2)), 2) AS saldo
    FROM clientaccountmovement
    GROUP BY client_id
),
exposicion AS (
    SELECT d.client_id, LEAST(d.vencido, GREATEST(s.saldo, 0)) AS importe
    FROM docs d
    JOIN saldos s ON s.client_id = d.client_id
)
SELECT COUNT(*) AS clientes,
       ROUND(SUM(importe), 2) AS exposicion
FROM exposicion
WHERE importe > 0
"""

BRUTO_SQL = """
SELECT COUNT(*) AS documentos, ROUND(SUM(m.total_amount), 2) AS bruto
FROM clientaccountmovement m
WHERE m.movement_type IN ('load_order_documental', 'load_order_documental_deferred')
  AND m.is_reversal = 0
  AND m.due_date IS NOT NULL
  AND m.due_date < CURDATE()
  AND NOT EXISTS (
      SELECT 1 FROM clientaccountmovement r
      WHERE r.reverses_id = m.id AND r.is_reversal = 1
  )
"""


def main() -> int:
    db = build_mysql_database()
    database_proxy.initialize(db)
    db.connect(reuse_if_open=True)

    snapshot = DashboardService().collection_snapshot()
    control = db.execute_sql(CONTROL_SQL).fetchone()
    bruto = db.execute_sql(BRUTO_SQL).fetchone()

    print("=== Tarjetas del dashboard (codigo de la app, base real) ===")
    print(f"Deuda vencida        : {snapshot['overdue_amount']:>18,.2f}  ({snapshot['overdue_clients']} clientes)")
    print(f"Vence hoy            : {snapshot['due_today_amount']:>18,.2f}  ({snapshot['due_today_clients']} clientes)")
    print(f"Proximos 7 dias      : {snapshot['next_7_amount']:>18,.2f}  ({snapshot['next_7_clients']} clientes)")
    print(f"Proximos 30 dias     : {snapshot['next_30_amount']:>18,.2f}  ({snapshot['next_30_clients']} clientes)")
    print(f"Saldo deudor clientes: {snapshot['debtor_balance']:>18,.2f}  ({snapshot['debtor_clients']} clientes)")
    print()
    print("=== Control SQL (misma regla, escrita en SQL) ===")
    print(f"Clientes con exposicion: {control[0]}")
    print(f"Exposicion vencida      : {control[1]:,.2f}")
    print()
    print("=== Antes (bruto de documentos, el numero que veia el usuario) ===")
    print(f"Documentos vencidos     : {bruto[0]}")
    print(f"Bruto                   : {bruto[1]:,.2f}")

    ok = abs(float(control[1]) - snapshot["overdue_amount"]) < 0.01
    ok = ok and int(control[0]) == snapshot["overdue_clients"]
    print()
    print("RESULTADO:", "OK el codigo y el SQL coinciden" if ok else "DIFIEREN")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
