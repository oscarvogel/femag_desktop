"""Captura la evidencia visual del issue #756.

Muestra el dialogo de remito antes y despues de elegir el chofer: el
transportista, el camion y el acoplado se completan solos.
"""

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
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.ui.remittances import RemittanceDialog


OUTPUT_DIR = Path("docs/screenshots/issue-756-remito-transporte-chofer")


def _set_combo(combo, value) -> None:
    index = combo.findData(value)
    if index < 0:
        raise RuntimeError(f"No se encontro {value} en {combo.objectName()}")
    combo.setCurrentIndex(index)


def _capture(widget, target: Path) -> None:
    widget.repaint()
    QApplication.processEvents()
    image = widget.grab().toImage().convertToFormat(QImage.Format_RGB32)
    if not image.save(str(target), "PNG"):
        raise RuntimeError(f"No se pudo guardar {target}")


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)

    carrier = Carrier.create(name="Transportista Demo SRL", cuit="30700075601")
    truck = Truck.create(
        domain="ABC123",
        trailer_domain="XYZ987",
        carrier=carrier,
    )
    driver = Driver.create(
        name="Juan Perez",
        carrier=carrier,
        usual_truck=truck,
        document="30123456",
    )
    client = Client.create(name="Cliente Demo SRL", cuit="30700075602", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12 km 8",
    )
    product = Product.create(name="Fecula de mandioca", unit="kg")

    dialog = RemittanceDialog(current_user="captura756")
    _set_combo(dialog.client_combo, client.id)
    _set_combo(dialog.address_combo, address.id)
    dialog.items.cellWidget(0, 0).setCurrentIndex(
        dialog.items.cellWidget(0, 0).findData(product.id)
    )
    dialog.resize(1080, 720)
    dialog.show()
    app.processEvents()

    targets = []
    before = OUTPUT_DIR / "01_remito_sin_chofer.png"
    _capture(dialog, before)
    targets.append(before)

    # Al elegir el chofer, el transporte se completa solo.
    _set_combo(dialog.driver_combo, driver.id)
    app.processEvents()
    after = OUTPUT_DIR / "02_remito_chofer_completa_transporte.png"
    _capture(dialog, after)
    targets.append(after)

    dialog.close()
    database.close()
    app.quit()
    return targets


if __name__ == "__main__":
    for path in generate():
        print(path)
