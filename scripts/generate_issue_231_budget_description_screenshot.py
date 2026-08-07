import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService
from app.services.load_order_service import LoadOrderService
from app.ui.desktop_app import FemagDesktopWindow, LoadOrderEntryDialog
from scripts.generate_ux_screenshots import _capture


OUTPUT_DIR = Path("docs/screenshots/issue_231_budget_description")


def generate() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])
    try:
        PermissionService().seed_defaults()
        admin = AuthService().create_user("captura231", "secreto", "Administrador")
        window = FemagDesktopWindow(user=admin, demo_mode=True)
        window.resize(1280, 800)
        dialog = LoadOrderEntryDialog(
            LoadOrderService(current_user=admin.username),
            admin.username,
            parent=window,
        )
        dialog.destinations = [
            {
                "client_id": 1,
                "address_id": 1,
                "client_label": "Distribuidora Posadas",
                "address_label": "Av. Uruguay 2450 - Posadas",
                "observations": "Validez de la oferta: 15 dias. Entrega coordinada.",
                "products": [
                    {
                        "product_id": 1,
                        "product_label": "Fecula premium",
                        "quantity": 100,
                        "unit": "kg",
                        "precio_neto_unitario": 850,
                        "descuento_porcentaje": 0,
                        "total": 85000,
                    }
                ],
            },
            {
                "client_id": 2,
                "address_id": 2,
                "client_label": "Mayorista Obera",
                "address_label": "Ruta Nacional 14 Km 12 - Obera",
                "observations": "Pago a 30 dias. Mercaderia puesta en deposito.",
                "products": [
                    {
                        "product_id": 2,
                        "product_label": "Almidon industrial",
                        "quantity": 50,
                        "unit": "bolsa",
                        "precio_neto_unitario": 1200,
                        "descuento_porcentaje": 5,
                        "total": 57000,
                    }
                ],
            },
        ]
        dialog._render_destinations()
        dialog.destination_table.setCurrentCell(0, 0)
        dialog._go_to_step(1)
        dialog.resize(1100, 660)
        dialog.show()
        app.processEvents()
        target = OUTPUT_DIR / "load_order_destination_descriptions.png"
        _capture(dialog, target)
        dialog.close()
        window.close()
        return target
    finally:
        database.close()


if __name__ == "__main__":
    print(generate())
