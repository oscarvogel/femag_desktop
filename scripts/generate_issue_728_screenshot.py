"""Capturas de UX del issue #728: el campo "Rol en el stock" en el ABM de
productos que corre en la app.

Base en memoria con datos sinteticos: ningun dato real entra en la evidencia.
Misma receta que scripts/generate_issue_613_screenshot.py.

Deja dos capturas:
- el dialogo de Producto con el campo "Rol en el stock" elegido en
  "Materia prima" y su aclaracion del peso del big bag;
- el listado de Productos con la columna "Rol en el stock".
"""

import os
import sys
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtWidgets import QApplication, QComboBox

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import Product
from app.models.security import User, UserProfile
from app.services.permission_service import PermissionService
from app.ui.master_abm import build_master_abm_page, master_abm_configs
from scripts.generate_ux_screenshots import _capture


OUTPUT_DIR = Path("docs/screenshots/issue_728_rol_en_el_stock")

PRODUCTOS = [
    ("ALM-100", "ALMIDON MAIZ BIG BAG", "kg", Decimal("1000.000"), "materia_prima"),
    ("ALM-200", "ALMIDON MANDIOCA BIG BAG", "kg", Decimal("1000.000"), "materia_prima"),
    ("FEC-300", "BOLSAS DE FECULA NATIVA", "unidad", Decimal("25.000"), "terminado"),
]


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])
    try:
        for codigo, nombre, unidad, peso, rol in PRODUCTOS:
            Product.create(
                codigo=codigo,
                name=nombre,
                unit=unidad,
                peso_unitario_kg=peso,
                product_kind="producto",
                stock_role=rol,
                active=True,
            )

        config = master_abm_configs()["products"]
        salidas = []

        # 1. El dialogo con el campo nuevo, en materia prima.
        dialogo = config.dialog_class(current_user="issue728")
        combo = dialogo.findChild(QComboBox, "productStockRoleInput")
        combo.setCurrentIndex(combo.findData("materia_prima"))
        dialogo.resize(560, 620)
        dialogo.show()
        app.processEvents()
        destino = OUTPUT_DIR / "producto_rol_en_el_stock.png"
        _capture(dialogo, destino)
        salidas.append(destino)
        dialogo.close()

        # 2. El listado de Productos con la columna "Rol en el stock".
        PermissionService().seed_defaults()
        perfil = UserProfile.get(UserProfile.name == "Administrador")
        usuario = User.create(username="issue728_captura", password_hash="x", profile=perfil)

        pagina = build_master_abm_page(
            config=config, user=usuario, current_user=usuario.username
        )
        pagina.resize(1500, 640)
        pagina.show()
        app.processEvents()
        destino_listado = OUTPUT_DIR / "listado_productos_con_rol.png"
        _capture(pagina, destino_listado)
        salidas.append(destino_listado)
        pagina.close()

        return salidas
    finally:
        database.close()


if __name__ == "__main__":
    for ruta in generate():
        print(ruta)
