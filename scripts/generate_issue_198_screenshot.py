import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication, QTableWidget

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import Client, ClientAddress
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService
from app.ui.desktop_app import FemagDesktopWindow


OUTPUT = Path("docs") / "screenshots" / "issue_198_shared_address" / "client_addresses.png"


def generate() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    PermissionService().seed_defaults()
    user = AuthService().create_user("captura_domicilios", "clave", "Administrador")
    client = Client.create(name="Cliente con domicilios", cuit="30700000198", iva_condition="RI")
    for address_type, city, address in (
        ("fiscal", "Posadas", "Domicilio fiscal 100"),
        ("entrega", "Oberá", "Depósito de entrega 200"),
        ("fiscal_entrega", "Eldorado", "Domicilio compartido 300"),
    ):
        ClientAddress.create(
            client=client,
            address_type=address_type,
            province="Misiones",
            city=city,
            address=address,
            is_primary=address_type != "fiscal",
        )
    window = FemagDesktopWindow(user=user, demo_mode=True)
    window.resize(1440, 900)
    window.show()
    window._navigate_to_route("clients")
    table = window.findChild(QTableWidget, "clientTable")
    for row in range(table.rowCount()):
        if table.item(row, 0).text() == client.name:
            table.setCurrentCell(row, 0)
            break
    app.processEvents()
    image = window.grab().toImage().convertToFormat(QImage.Format_RGB32)
    if not image.save(str(OUTPUT), "PNG"):
        raise RuntimeError(f"No se pudo guardar {OUTPUT}")
    window.close()
    database.close()
    app.quit()
    return OUTPUT


if __name__ == "__main__":
    print(generate())
