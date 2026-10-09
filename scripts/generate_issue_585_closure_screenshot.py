"""Evidencia visual del cierre de entrega con la columna de parte (#585)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import (
    Carrier,
    Client,
    ClientAddress,
    Driver,
    Product,
    Truck,
)
from app.services.load_order_service import LoadOrderService
from app.services.load_order_operation_service import LoadOrderOperationService
from app.ui.load_order_closure_dialog import LoadOrderClosureDialog
from scripts.generate_ux_screenshots import _capture

OUTPUT_DIR = Path("docs/screenshots/issue_585_devoluciones_por_parte")
PRECIO = 29453.0


def generate() -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])
    try:
        carrier = Carrier.create(name="Transporte Norte", cuit="30777777770")
        driver = Driver.create(name="Juan Perez", carrier=carrier, document="123")
        truck = Truck.create(domain="AB123CD", carrier=carrier)
        client = Client.create(
            name="10 DE OCTUBRE SRL",
            cuit="30718034384",
            iva_condition="RI",
            dias_plazo_pago=30,
        )
        address = ClientAddress.create(
            client=client,
            address_type="entrega",
            province="Misiones",
            city="Posadas",
            address="Ruta 12 km 1540",
            is_primary=True,
        )
        almidon = Product.create(
            name="BOLSAS ALMIDON DE MAIZ X 25 KG",
            unit="unidad",
            precio_neto_base=PRECIO,
            peso_unitario_kg=25.0,
        )
        fecula = Product.create(
            name="BOLSAS DE FECULA NATIVA",
            unit="unidad",
            precio_neto_base=10000.0,
            peso_unitario_kg=1.0,
        )

        order = LoadOrderService(current_user="mavis").create_order(
            carrier=carrier,
            driver=driver,
            truck=truck,
            destinations=[
                {
                    "client": client,
                    "delivery_address": address,
                    "products": [
                        {
                            "product": almidon,
                            "quantity": 1500.0,
                            "cantidad_facturar_ahora": 1000.0,
                            "precio_neto_unitario": PRECIO,
                        },
                        {
                            "product": fecula,
                            "quantity": 1000.0,
                            "cantidad_facturar_ahora": 600.0,
                            "precio_neto_unitario": 10000.0,
                        },
                    ],
                }
            ],
        )
        for product in (almidon, fecula):
            if product.peso_unitario_kg == 0:
                product.peso_unitario_kg = 1
                product.save()
        LoadOrderService(current_user="mavis").update_order(
            order,
            pallets=[
                {
                    "sequence": 1,
                    "pallet_type": None,
                    "allocations": [
                        {
                            "client": client,
                            "delivery_address": address,
                            "product": product,
                            "quantity": float(line.quantity),
                        }
                        for line, product in (
                            (order.products[0], almidon),
                            (order.products[1], fecula),
                        )
                    ],
                }
            ],
        )
        LoadOrderOperationService(current_user="mavis").issue(order)

        dialog = LoadOrderClosureDialog(order=order, current_user="mavis")
        dialog.show()
        app.processEvents()
        target = OUTPUT_DIR / "cierre_entrega_columna_parte.png"
        _capture(dialog, target)
        dialog.close()
        return target
    finally:
        database.close()


if __name__ == "__main__":
    print(generate())
