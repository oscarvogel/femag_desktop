import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt5.QtWidgets import QApplication
from peewee import SqliteDatabase

from app.config.database import bind_database
from app.config.schema import ensure_runtime_schema
from app.models.masters import Client, ClientAddress, Product
from app.services.remittance_service import RemittanceService
from app.ui.desktop_app import STYLES
from app.ui.remittances import RemittanceEntryDialog, RemittancesPage


OUTPUT = ROOT / "docs" / "screenshots" / "issue_10_independent_remittances"


def main() -> None:
    database = SqliteDatabase(":memory:", pragmas={"foreign_keys": 1})
    bind_database(database)
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)
    client = Client.create(name="Cliente Demo FEMAG", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12 km 8",
        is_primary=True,
    )
    product = Product.create(name="Fecula de mandioca", unit="kg")
    RemittanceService(current_user="demo").create_manual(
        client=client,
        delivery_address=address,
        products=[{"product": product, "quantity": 250}],
        observations="Entrega de demostracion",
    )

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(STYLES)
    OUTPUT.mkdir(parents=True, exist_ok=True)

    page = RemittancesPage(current_user="demo")
    page.resize(1280, 760)
    page.show()
    app.processEvents()
    page.grab().save(str(OUTPUT / "remittances_page.png"))

    dialog = RemittanceEntryDialog(RemittanceService(current_user="demo"))
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(OUTPUT / "manual_remittance_dialog.png"))
    dialog.close()
    page.close()
    database.close()
    print(OUTPUT)


if __name__ == "__main__":
    main()
