"""Captura la evidencia visual de los issues #797 y #798.

- Combos sin preselección arbitraria y búsqueda F2 en Remitos y Órdenes.
- TOTAL GENERAL visible y actualizado en la pantalla de remitos.
"""

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.services.load_order_service import LoadOrderService
from app.services.remittance_service import RemittanceService
from app.ui.combo_autocomplete import ComboSearchDialog
from app.ui.desktop_app import LoadOrderEntryDialog
from app.ui.remittances import RemittanceDialog
from app.ui.theme import Theme, stylesheet_for


OUTPUT_DIR = Path("docs/screenshots/issue-797-798-remito-ux")


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


def _fill_remittance(dialog, *, client, address, driver, first, second) -> None:
    _set_combo(dialog.client_combo, client.id)
    _set_combo(dialog.address_combo, address.id)
    _set_combo(dialog.driver_combo, driver.id)
    dialog.items.cellWidget(0, 0).setCurrentIndex(
        dialog.items.cellWidget(0, 0).findData(first.id)
    )
    dialog.items.cellWidget(0, 1).setText("2")
    dialog.items.cellWidget(0, 2).setText("1500.00")
    dialog._add_item_row()
    dialog.items.cellWidget(1, 0).setCurrentIndex(
        dialog.items.cellWidget(1, 0).findData(second.id)
    )
    dialog.items.cellWidget(1, 1).setText("3")
    dialog.items.cellWidget(1, 2).setText("2000.00")


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)

    carrier = Carrier.create(name="Transportista Demo SRL", cuit="30700079701")
    truck = Truck.create(domain="ABC123", trailer_domain="XYZ987", carrier=carrier)
    driver = Driver.create(
        name="Juan Perez",
        carrier=carrier,
        usual_truck=truck,
        document="30123456",
    )
    client = Client.create(name="Cliente Demo SRL", cuit="30700079702", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12 km 8",
        is_primary=True,
    )
    first = Product.create(codigo="100", name="Fecula de mandioca", unit="kg")
    second = Product.create(codigo="200", name="Almidon de mandioca", unit="kg")

    targets = []

    new_dialog = RemittanceDialog(current_user="captura797")
    new_dialog.resize(1080, 720)
    new_dialog.show()
    app.processEvents()
    target = OUTPUT_DIR / "01_remito_nuevo_sin_preseleccion.png"
    _capture(new_dialog, target)
    targets.append(target)
    new_dialog.close()

    dialog = RemittanceDialog(current_user="captura797")
    _fill_remittance(
        dialog,
        client=client,
        address=address,
        driver=driver,
        first=first,
        second=second,
    )
    dialog.resize(1080, 720)
    dialog.show()
    app.processEvents()
    target = OUTPUT_DIR / "02_remito_total_en_vivo.png"
    _capture(dialog, target)
    targets.append(target)

    search = ComboSearchDialog(dialog.driver_combo, dialog)
    search.search_input.setText("juan")
    search.show()
    app.processEvents()
    target = OUTPUT_DIR / "03_busqueda_f2_chofer.png"
    _capture(search, target)
    targets.append(target)
    search.close()

    dialog.setStyleSheet(stylesheet_for(Theme.DARK))
    app.processEvents()
    target = OUTPUT_DIR / "04_remito_total_tema_oscuro.png"
    _capture(dialog, target)
    targets.append(target)
    dialog.close()

    draft = RemittanceService("captura798").create_manual(
        client=client,
        delivery_address=address,
        carrier=carrier,
        truck=truck,
        trailer_domain="XYZ987",
        driver=driver,
        physical_point_of_sale="0001",
        physical_number="7980",
        remittance_date=date(2026, 10, 27),
        items=[
            {"product": first, "quantity": Decimal("2"), "unit_price": Decimal("1500")},
            {"product": second, "quantity": Decimal("3"), "unit_price": Decimal("2000")},
        ],
    )
    draft_dialog = RemittanceDialog(current_user="captura798", remittance=draft)
    draft_dialog.resize(1080, 720)
    draft_dialog.show()
    app.processEvents()
    target = OUTPUT_DIR / "05_remito_borrador_total.png"
    _capture(draft_dialog, target)
    targets.append(target)
    draft_dialog.close()

    order_dialog = LoadOrderEntryDialog(
        LoadOrderService(current_user="captura797"), "captura797"
    )
    order_dialog.resize(1100, 760)
    order_dialog.show()
    app.processEvents()
    target = OUTPUT_DIR / "06_orden_nueva_sin_preseleccion.png"
    _capture(order_dialog, target)
    targets.append(target)

    order_search = ComboSearchDialog(order_dialog.driver_combo, order_dialog)
    order_search.search_input.setText("juan")
    order_search.show()
    app.processEvents()
    target = OUTPUT_DIR / "07_orden_busqueda_f2_chofer.png"
    _capture(order_search, target)
    targets.append(target)
    order_search.close()
    order_dialog.close()

    database.close()
    app.quit()
    return targets


if __name__ == "__main__":
    for path in generate():
        print(path)
