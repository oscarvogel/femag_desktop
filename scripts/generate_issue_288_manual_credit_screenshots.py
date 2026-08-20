import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import Client
from app.services.auth_service import AuthService
from app.services.client_manual_credit_service import ClientManualCreditService
from app.services.client_manual_debit_service import ClientManualDebitService
from app.services.permission_service import PermissionService
from app.ui.client_manual_credit_dialog import ClientManualCreditDialog
from app.ui.customer_ledger import CustomerLedgerPage
from app.ui.desktop_app import FemagDesktopWindow
from scripts.generate_ux_screenshots import _capture


OUTPUT_DIR = Path("docs/screenshots/issue_288_manual_credits")


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])
    try:
        PermissionService().seed_defaults()
        admin = AuthService().create_user("captura288", "secreto", "Administrador")
        client = Client.create(
            name="Distribuidora Misiones",
            cuit="30700000288",
            iva_condition="RI",
        )
        ClientManualDebitService(current_user=admin.username).register_manual_debit(
            client=client,
            amount=5000,
            description="Ajuste pendiente",
            reference="ND-000288",
        )
        service = ClientManualCreditService(current_user=admin.username)
        active = service.register_manual_credit(
            client=client,
            amount=1800,
            description="Bonificación comercial",
            reference="NC-000288",
            observations="Cliente frecuente",
        )
        reversed_credit = service.register_manual_credit(
            client=client,
            amount=400,
            description="Crédito de prueba reversado",
            reference="NC-000289",
        )
        service.reverse_manual_credit(reversed_credit)

        window = FemagDesktopWindow(user=admin, demo_mode=True)
        window.resize(1440, 900)
        window._navigate_to_route("customer_ledger")
        window.show()
        app.processEvents()
        page = window.stack.currentWidget()
        if not isinstance(page, CustomerLedgerPage):
            raise RuntimeError("No se pudo abrir la cuenta corriente.")
        active_row = next(
            row
            for row in range(page.movements_table.rowCount())
            if page.movements_table.item(row, 0).data(Qt.UserRole + 1) == active.id
        )
        page.movements_table.setCurrentCell(active_row, 0)
        app.processEvents()
        ledger_target = OUTPUT_DIR / "customer_ledger_manual_credits.png"
        _capture(window, ledger_target)

        dialog = ClientManualCreditDialog(
            current_user=admin.username,
            preset_client=client,
            parent=window,
        )
        dialog.date_input.setDate(QDate(2026, 8, 13))
        dialog.amount_input.setValue(1800)
        dialog.description_input.setText("Bonificación comercial")
        dialog.reference_input.setText("NC-000288")
        dialog.observations_input.setText("Cliente frecuente")
        dialog.show()
        app.processEvents()
        dialog_target = OUTPUT_DIR / "manual_credit_dialog.png"
        _capture(dialog, dialog_target)
        dialog.close()
        window.close()
        return [ledger_target, dialog_target]
    finally:
        database.close()


if __name__ == "__main__":
    for path in generate():
        print(path)
