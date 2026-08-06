import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
from app.models.payments import ClientPayment
from app.ui.desktop_app import STYLES
from app.ui.load_order_closure_dialog import LoadOrderClosureDialog


OUTPUT = Path("docs/screenshots/issue_220_closure_payments/closure_dialog.png")


def generate() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)

    iva = TipoIVA.iva_default()
    client = Client.create(name="Distribuidora del Litoral", cuit="30111111220", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Nacional 12 km 8",
    )
    carrier = Carrier.create(name="Transporte Norte")
    driver = Driver.create(name="Juan Pérez", carrier=carrier)
    truck = Truck.create(domain="AA220BB", carrier=carrier)
    product_a = Product.create(name="Fécula premium", unit="kg", tipo_iva=iva)
    product_b = Product.create(name="Almidón bolsa 25 kg", unit="bolsa", tipo_iva=iva)
    order = LoadOrder.create(
        order_number=220,
        client=client,
        delivery_address=address,
        carrier=carrier,
        driver=driver,
        truck=truck,
        status=LoadOrder.STATUS_ISSUED,
        created_by="captura220",
    )
    destination = LoadOrderDestination.create(
        order=order,
        client=client,
        delivery_address=address,
        sequence=1,
    )
    LoadOrderProduct.create(
        order=order,
        destination=destination,
        product=product_a,
        quantity=10,
        unit="kg",
        precio_neto_unitario=1000,
        total=12100,
    )
    LoadOrderProduct.create(
        order=order,
        destination=destination,
        product=product_b,
        quantity=5,
        unit="bolsa",
        precio_neto_unitario=2000,
        total=12100,
    )

    dialog = LoadOrderClosureDialog(order=order, current_user="captura220")
    dialog.setStyleSheet(STYLES)
    dialog.amount_input.setValue(12000)
    dialog.method_combo.setCurrentIndex(
        dialog.method_combo.findData(ClientPayment.METHOD_TRANSFER)
    )
    dialog.reference_input.setText("TRF-000220")
    dialog.add_payment_button.click()
    dialog.resize(900, 740)
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
