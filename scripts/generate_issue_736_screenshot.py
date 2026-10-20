"""Capturas de UX del issue #736: el refresco no borra lo que el operador escribe.

Base en memoria con datos sinteticos: ningun dato real entra en la evidencia.
La plataforma es `windows` en vez de `offscreen` para que el texto se dibuje
(#652).
"""

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import Product
from app.models.stock import StockMovement
from app.services.stock_service import StockService
from app.ui.stock_initial_inventory import StockInitialInventoryPage
from scripts.generate_ux_screenshots import _capture

OUTPUT_DIR = Path("docs/screenshots/issue_736_conteo_no_se_borra")
PESO = Decimal("25.000")


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])
    try:
        for nombre, peso in (
            ("BOLSAS ALMIDON DE MAIZ X 25 KG", PESO),
            ("BOLSAS DE FECULA NATIVA", PESO),
            ("BOLSAS ALMID. PAPA 2ª CALIDAD", Decimal("0")),
        ):
            Product.create(
                name=nombre, unit="unidad", peso_unitario_kg=peso,
                product_kind="producto", stock_role="terminado", active=True,
            )
        producto = Product.get(Product.name == "BOLSAS ALMIDON DE MAIZ X 25 KG")
        StockService.register(
            product=producto, movement_type=StockMovement.TYPE_INITIAL_INVENTORY,
            quantity_kg=Decimal("3000.000"), source_ref="stock_count:2026-10-20",
            description="Inventario inicial", movement_date=date(2026, 10, 20),
            created_by="operador1",
        )

        pagina = StockInitialInventoryPage(current_username="operador1")
        pagina.resize(1180, 560)
        # El operador cuenta 120 bolsas de almidon.
        pagina.inputs[producto.id].setValue(120)
        pagina.show()
        app.processEvents()
        antes = OUTPUT_DIR / "conteo_escrito.png"
        _capture(pagina, antes)

        # Llega el refresco automatico de 10 segundos.
        pagina.refresh()
        app.processEvents()
        despues = OUTPUT_DIR / "conteo_tras_el_refresco.png"
        _capture(pagina, despues)

        valor = pagina.inputs[producto.id].value()
        pagina.close()
        if valor != 120:
            raise AssertionError(f"el refresco se llevo el conteo: quedo {valor}")
        return [antes, despues]
    finally:
        database.close()


if __name__ == "__main__":
    for ruta in generate():
        print(ruta)
