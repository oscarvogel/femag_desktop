"""Capturas de UX del issue #732: el aviso de stock insuficiente al emitir.

Base en memoria con datos sinteticos: ningun dato real entra en la evidencia.
La plataforma es `windows` en vez de `offscreen` para que el texto se dibuje
(#652).
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
from app.services.load_order_stock_service import StockShortfall
from app.services.stock_service import StockService
from app.ui.load_order_stock_shortfall_dialog import LoadOrderStockShortfallDialog
from scripts.generate_ux_screenshots import _capture

OUTPUT_DIR = Path("docs/screenshots/issue_732_stock_insuficiente")


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])
    try:
        bolsa = Product.create(
            name="BOLSAS ALMIDON DE MAIZ X 25 KG", unit="unidad",
            peso_unitario_kg=Decimal("25.000"), product_kind="producto",
            stock_role="terminado", active=True,
        )
        otra = Product.create(
            name="BOLSAS DE FECULA NATIVA", unit="unidad",
            peso_unitario_kg=Decimal("25.000"), product_kind="producto",
            stock_role="terminado", active=True,
        )
        # Stock real: 3.000 kg de la bolsa y 400 kg de la otra.
        StockService.register(
            product=bolsa, movement_type=StockMovement.TYPE_INITIAL_INVENTORY,
            quantity_kg=Decimal("3000.000"), source_ref="stock_count:1",
            description="Inventario inicial", created_by="operador1",
        )
        StockService.register(
            product=otra, movement_type=StockMovement.TYPE_INITIAL_INVENTORY,
            quantity_kg=Decimal("400.000"), source_ref="stock_count:2",
            description="Inventario inicial", created_by="operador1",
        )

        faltantes = [
            StockShortfall(
                product=bolsa, available_kg=Decimal("3000.000"),
                requested_kg=Decimal("12500.000"),
            ),
            StockShortfall(
                product=otra, available_kg=Decimal("400.000"),
                requested_kg=Decimal("1250.000"),
            ),
        ]

        # El dialogo relee la orden de la base, asi que hace falta una real.
        from app.models.load_orders import LoadOrder
        from app.models.masters import Carrier, Driver, Truck

        transportista = Carrier.create(name="TRANSPORTE DEMO", cuit="30730000001")
        chofer = Driver.create(
            name="CHOFER DEMO", carrier=transportista, document="D73000001"
        )
        camion = Truck.create(domain="I730ABC", carrier=transportista)
        orden = LoadOrder.create(
            order_number=73, carrier=transportista, driver=chofer, truck=camion
        )

        dialogo = LoadOrderStockShortfallDialog(orden, faltantes)
        dialogo.resize(760, 480)
        dialogo.show()
        app.processEvents()

        destino = OUTPUT_DIR / "aviso_stock_insuficiente.png"
        _capture(dialogo, destino)
        dialogo.close()

        return [destino]
    finally:
        database.close()


if __name__ == "__main__":
    for ruta in generate():
        print(ruta)
