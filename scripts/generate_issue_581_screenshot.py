"""Capturas de UX del issue #581: resumen de cartera por vendedor.

Base en memoria con datos sinteticos: ninguna cifra ni cliente real entra en la
evidencia. Mismo receta que scripts/generate_issue_452_screenshot.py.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.accounting import ClientAccountMovement
from app.models.masters import Client, Salesperson
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService
from app.ui.customer_ledger import CustomerLedgerPage
from app.ui.desktop_app import FemagDesktopWindow
from scripts.generate_ux_screenshots import _capture


OUTPUT_DIR = Path("docs/screenshots/issue_581_resumen_cuenta_vendedor")

CLIENTES = [
    ("Alimentos Guarani", "30700000581", 79_009_859.57, 12_000_000.0, 3_000_000.0),
    ("Mayorista Ruta 12", "30700000582", 57_539_594.06, 0.0, 0.0),
    ("Supermercados Norte", "30700000583", -293_160_175.34, 0.0, 0.0),
    ("Distribuidora Parana", "30700000584", 0.0, 0.0, 0.0),
]


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])
    try:
        PermissionService().seed_defaults()
        admin = AuthService().create_user("captura581", "secreto", "Administrador")
        luis = Salesperson.create(
            name="Luis",
            phone="5493743667526",
            email="luis@example.com",
        )
        for name, cuit, total, overdue, due_7 in CLIENTES:
            client = Client.create(
                name=name, cuit=cuit, iva_condition="RI", salesperson=luis
            )
            if total:
                movement = ClientAccountMovement.create(
                    client=client,
                    movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
                    source_ref=f"OC-581-{cuit}",
                    description=f"Orden de carga {name}",
                    total_amount=total,
                )
                movement.save()

        window = FemagDesktopWindow(user=admin, demo_mode=True)
        window.resize(1440, 900)
        window._navigate_to_route("customer_ledger")
        window.show()
        app.processEvents()
        page = window.stack.currentWidget()
        if not isinstance(page, CustomerLedgerPage):
            raise RuntimeError("No se pudo abrir la cuenta corriente.")

        page.salesperson_filter.setCurrentIndex(
            page.salesperson_filter.findData(luis.id)
        )
        # Un click real en el combo emite "activated"; setCurrentIndex solo no lo hace.
        page.salesperson_filter.activated.emit(luis.id)
        app.processEvents()

        if not page.portfolio_print_action.isEnabled():
            raise RuntimeError("La accion de resumen deberia estar habilitada.")
        if not page.portfolio_whatsapp_action.isEnabled():
            raise RuntimeError("El envio por WhatsApp deberia estar habilitado.")

        ledger_target = OUTPUT_DIR / "customer_ledger_cartera_por_vendedor.png"
        _capture(window, ledger_target)

        menu = page.more_actions_menu
        menu.show()
        app.processEvents()
        menu_target = OUTPUT_DIR / "customer_ledger_acciones_resumen_vendedor.png"
        _capture(menu, menu_target)
        menu.close()
        window.close()
        return [ledger_target, menu_target]
    finally:
        database.close()


if __name__ == "__main__":
    for path in generate():
        print(path)
