"""Capturas de UX del issue #730: la produccion consume la materia prima.

Base en memoria con datos sinteticos: ningun dato real entra en la evidencia.
Misma receta que scripts/generate_issue_728_screenshot.py.
"""

import os
import sys
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
from app.ui.production_parts import ProductionPartPage
from scripts.generate_ux_screenshots import _capture

OUTPUT_DIR = Path("docs/screenshots/issue_730_consumo_materia_prima")

HOY = __import__("datetime").date(2026, 10, 20)


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])
    try:
        materia = Product.create(
            name="ALMIDON DE MAIZ BIG BAG", unit="kg",
            peso_unitario_kg=Decimal("1000.000"), product_kind="producto",
            stock_role="materia_prima", active=True,
        )
        bolsa = Product.create(
            name="BOLSAS ALMIDON DE MAIZ X 25 KG", unit="unidad",
            peso_unitario_kg=Decimal("25.000"), product_kind="producto",
            stock_role="terminado", active=True,
        )
        # Compra de 3 big bags: es lo que deja 3.000 kg en el deposito.
        StockService.register(
            product=materia,
            movement_type=StockMovement.TYPE_PURCHASE,
            quantity_kg=Decimal("3000.000"),
            source_ref="raw_material_intake:1",
            description="Compra de big bag",
            movement_date=HOY,
            created_by="operador1",
        )

        pagina = ProductionPartPage(current_username="operador1")
        pagina.resize(1500, 1080)
        pagina.show()
        app.processEvents()

        # El operador elige la materia prima y carga los kilos consumidos.
        pagina.raw_material_combo.setCurrentIndex(pagina.raw_material_combo.findData(materia.id))
        pagina.consumed_kg_input.setValue(2000.0)
        app.processEvents()
        pagina._add_consumption()

        # Y las bolsas embolsadas del turno.
        pagina.product_combo.setCurrentIndex(pagina.product_combo.findData(bolsa.id))
        pagina.bags_input.setValue(80)
        app.processEvents()
        pagina._add_line()

        app.processEvents()
        destino = OUTPUT_DIR / "parte_con_materia_prima_consumida.png"
        _capture(pagina, destino)
        pagina.close()

        return [destino]
    finally:
        database.close()


if __name__ == "__main__":
    for ruta in generate():
        print(ruta)
