import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication, QDialog

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.services.load_order_service import LoadOrderService
from app.ui.desktop_app import LoadOrderEntryDialog, LoadOrderProductDialog


OUTPUT = Path("docs/screenshots/issue_230_unique_load_order_lines/duplicate_product_blocked.png")


def _set_combo(combo, value) -> None:
    index = combo.findData(value)
    if index < 0:
        raise RuntimeError(f"No se encontro {value} en {combo.objectName()}")
    combo.setCurrentIndex(index)


def generate() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)

    carrier = Carrier.create(name="Transportista Demo SRL")
    driver = Driver.create(name="Chofer Demo", carrier=carrier)
    truck = Truck.create(domain="ABC123", carrier=carrier)
    client = Client.create(name="Demo 2", cuit="30700023002", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Garuhape",
        address="Entrega Garuhape",
    )
    product = Product.create(name="Fecula de maiz", unit="kg")

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="captura230"), "captura230")
    _set_combo(dialog.driver_combo, driver.id)
    _set_combo(dialog.truck_combo, truck.id)
    _set_combo(dialog.client_combo, client.id)
    _set_combo(dialog.address_combo, address.id)
    dialog._add_destination()

    original_exec = LoadOrderProductDialog.exec_

    def accept_product(product_dialog):
        product_dialog.product = {
            "product_id": product.id,
            "product_label": product.name,
            "quantity": 250,
            "unit": product.unit,
            "precio_neto_unitario": 0,
            "descuento_porcentaje": 0,
            "iva_porcentaje": 21,
            "total": 0,
        }
        return QDialog.Accepted

    try:
        LoadOrderProductDialog.exec_ = accept_product
        dialog._open_product_dialog()
        dialog._open_product_dialog()
    finally:
        LoadOrderProductDialog.exec_ = original_exec

    dialog.show()
    app.processEvents()
    image = dialog.grab().toImage().convertToFormat(QImage.Format_RGB32)
    if not image.save(str(OUTPUT), "PNG"):
        raise RuntimeError(f"No se pudo guardar {OUTPUT}")

    dialog.close()
    database.close()
    app.quit()
    return OUTPUT


if __name__ == "__main__":
    print(generate())
