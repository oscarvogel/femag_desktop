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
from app.services.client_manual_debit_service import ClientManualDebitService
from app.services.permission_service import PermissionService
from app.ui.client_manual_debit_dialog import ClientManualDebitDialog
from app.ui.customer_ledger import CustomerLedgerPage
from app.ui.desktop_app import FemagDesktopWindow
from scripts.generate_ux_screenshots import _capture


OUTPUT_DIR = Path("docs/screenshots/issue_217_manual_debits")


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])
    try:
        PermissionService().seed_defaults()
        admin = AuthService().create_user("captura217", "secreto", "Administrador")
        client = Client.create(
            name="Distribuidora Misiones",
            cuit="30700000217",
            iva_condition="RI",
        )
        service = ClientManualDebitService(current_user=admin.username)
        active = service.register_manual_debit(
            client=client,
            amount=5000,
            description="Interés por mora - agosto 2026",
            reference="ND-000217",
        )
        reversed_debit = service.register_manual_debit(
            client=client,
            amount=1250,
            description="Ajuste de prueba reversado",
            reference="AJ-001250",
        )
        service.reverse_manual_debit(reversed_debit)

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
        ledger_target = OUTPUT_DIR / "customer_ledger_manual_debits.png"
        _capture(window, ledger_target)

        dialog = ClientManualDebitDialog(
            current_user=admin.username,
            preset_client=client,
            parent=window,
        )
        dialog.date_input.setDate(QDate(2026, 8, 7))
        dialog.amount_input.setValue(5000)
        dialog.description_input.setText("Interés por mora")
        dialog.reference_input.setText("ND-000217")
        dialog.show()
        app.processEvents()
        dialog_target = OUTPUT_DIR / "manual_debit_dialog.png"
        _capture(dialog, dialog_target)
        dialog.close()
        window.close()
        return [ledger_target, dialog_target]
    finally:
        database.close()


if __name__ == "__main__":
    for path in generate():
        print(path)
