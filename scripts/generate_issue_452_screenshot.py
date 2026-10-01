import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.accounting import ClientAccountMovement
from app.models.masters import Client, Product
from app.services.auth_service import AuthService
from app.services.budget_service import BudgetService
from app.services.permission_service import PermissionService
from app.ui.customer_ledger import CustomerLedgerPage
from app.ui.desktop_app import FemagDesktopWindow
from scripts.generate_ux_screenshots import _capture


OUTPUT_DIR = Path("docs/screenshots/issue_452_reimprimir_presupuesto")


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])
    try:
        PermissionService().seed_defaults()
        admin = AuthService().create_user("captura452", "secreto", "Administrador")
        client = Client.create(
            name="Alimentos Guarani",
            cuit="30700000452",
            iva_condition="RI",
        )
        product = Product.create(name="Fecula de mandioca", unit="bolsa")
        budget = BudgetService(current_user=admin.username).create_manual(
            client=client,
            items=[
                {
                    "product": product,
                    "quantity": 120,
                    "unit": "bolsa",
                    "unit_price": 143000,
                    "vat_percentage": 21,
                }
            ],
        )
        movement = ClientAccountMovement.get(ClientAccountMovement.budget == budget)

        window = FemagDesktopWindow(user=admin, demo_mode=True)
        window.resize(1440, 900)
        window._navigate_to_route("customer_ledger")
        window.show()
        app.processEvents()
        page = window.stack.currentWidget()
        if not isinstance(page, CustomerLedgerPage):
            raise RuntimeError("No se pudo abrir la cuenta corriente.")
        row = next(
            index
            for index in range(page.movements_table.rowCount())
            if page.movements_table.item(index, 0).data(Qt.UserRole + 1) == movement.id
        )
        page.movements_table.setCurrentCell(row, 0)
        app.processEvents()
        if not page.print_budget_action.isEnabled():
            raise RuntimeError("La acción de reimpresión debería estar habilitada.")
        ledger_target = OUTPUT_DIR / "customer_ledger_presupuesto_seleccionado.png"
        _capture(window, ledger_target)

        # El menú es una ventana emergente propia: se captura por separado.
        menu = page.more_actions_menu
        menu.show()
        app.processEvents()
        menu_target = OUTPUT_DIR / "customer_ledger_acciones_reimprimir_presupuesto.png"
        _capture(menu, menu_target)
        menu.close()
        window.close()
        return [ledger_target, menu_target]
    finally:
        database.close()


if __name__ == "__main__":
    for path in generate():
        print(path)
