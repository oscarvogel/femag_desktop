"""Captura la evidencia visual del issue #795.

Muestra la cabecera del remito con el orden de transporte pedido (Chofer,
Transportista, Camion y Acoplado) y el autocompletado al elegir el chofer.
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
from app.ui.theme import Theme, stylesheet_for


OUTPUT_DIR = Path("docs/screenshots/issue-795-remito-orden-transporte")


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

    carrier = Carrier.create(name="Transportista Demo SRL", cuit="30700079501")
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
    client = Client.create(name="Cliente Demo SRL", cuit="30700079502", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12 km 8",
    )
    product = Product.create(name="Fecula de mandioca", unit="kg")

    dialog = RemittanceDialog(current_user="captura795")
    _set_combo(dialog.client_combo, client.id)
    _set_combo(dialog.address_combo, address.id)
    dialog.items.cellWidget(0, 0).setCurrentIndex(
        dialog.items.cellWidget(0, 0).findData(product.id)
    )
    dialog.resize(1080, 720)
    dialog.show()
    app.processEvents()

    targets = []
    empty = OUTPUT_DIR / "01_remito_orden_chofer_primero.png"
    _capture(dialog, empty)
    targets.append(empty)

    _set_combo(dialog.driver_combo, driver.id)
    app.processEvents()
    filled = OUTPUT_DIR / "02_remito_transporte_completado.png"
    _capture(dialog, filled)
    targets.append(filled)

    dialog.setStyleSheet(stylesheet_for(Theme.DARK))
    app.processEvents()
    dark = OUTPUT_DIR / "03_remito_transporte_tema_oscuro.png"
    _capture(dialog, dark)
    targets.append(dark)

    dialog.close()
    database.close()
    app.quit()
    return targets


if __name__ == "__main__":
    for path in generate():
        print(path)
