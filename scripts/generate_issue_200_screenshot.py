import os
import sys
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import Product
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService
from app.ui.desktop_app import FemagDesktopWindow

OUTPUT = Path("docs/screenshots/issue_200_product_classification/products.png")


def generate() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    database = SqliteDatabase(":memory:")
    bind_database(database); database.connect(); database.create_tables(ALL_MODELS)
    PermissionService().seed_defaults()
    user = AuthService().create_user("captura_productos", "clave", "Administrador")
    for name, kind, weight, review in (
        ("PACK 10 UNIDADES X 1 KG", "producto", "10", False),
        ("FLETE", "servicio", "0", False),
        ("CHEQUE DEVUELTO", "financiero", "0", False),
        ("CONSUMO KG. BOBINAS", "interno", "0", False),
        ("YERBA MATE PUESTA EN PLANTA", "revisar", "0", True),
    ):
        Product.create(name=name, unit="kg", peso_unitario_kg=Decimal(weight), product_kind=kind, review_required=review)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    window.resize(1440, 900); window.show(); window._navigate_to_route("products"); app.processEvents()
    image = window.grab().toImage().convertToFormat(QImage.Format_RGB32)
    if not image.save(str(OUTPUT), "PNG"):
        raise RuntimeError(f"No se pudo guardar {OUTPUT}")
    window.close(); database.close(); app.quit()
    return OUTPUT


if __name__ == "__main__":
    print(generate())
