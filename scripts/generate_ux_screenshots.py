import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtCore import QPoint
from PyQt5.QtGui import QColor, QImage, QPainter
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.security import User, UserProfile
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService
from app.ui.desktop_app import FemagDesktopWindow, LoadOrderEntryDialog, LoadOrderPalletDialog


DEFAULT_OUTPUT = Path("docs") / "screenshots" / "issue_178_pallet_composition"


def _set_combo(combo, value) -> None:
    index = combo.findData(value)
    if index < 0:
        raise RuntimeError(f"No se encontro {value!r} en {combo.objectName()}")
    combo.setCurrentIndex(index)


def _masters():
    carrier = Carrier.create(name="Transporte Captura")
    driver = Driver.create(name="Chofer Captura", carrier=carrier)
    truck = Truck.create(domain="CAP178", carrier=carrier)
    client_a = Client.create(name="Ferreteria Avenida", cuit="30700001781", iva_condition="RI")
    address_a = ClientAddress.create(
        client=client_a,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Deposito Central",
    )
    client_b = Client.create(name="Construcciones Norte", cuit="30700001782", iva_condition="RI")
    address_b = ClientAddress.create(
        client=client_b,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Obra Ruta 14",
    )
    cement = Product.create(
        name="Cemento 25 kg",
        unit="bolsa",
        peso_unitario_kg=Decimal("25.000"),
    )
    lime = Product.create(
        name="Cal 20 kg",
        unit="bolsa",
        peso_unitario_kg=Decimal("20.000"),
    )
    adhesive = Product.create(
        name="Adhesivo 10 kg",
        unit="unidad",
        peso_unitario_kg=Decimal("10.000"),
    )
    return locals()


def _destination_drafts(data):
    return [
        {
            "client_id": data["client_a"].id,
            "address_id": data["address_a"].id,
            "client_label": data["client_a"].name,
            "address_label": data["address_a"].address,
            "products": [
                {
                    "product_id": data["cement"].id,
                    "product_label": data["cement"].name,
                    "quantity": 40,
                    "unit": data["cement"].unit,
                    "total": 0,
                },
                {
                    "product_id": data["lime"].id,
                    "product_label": data["lime"].name,
                    "quantity": 15,
                    "unit": data["lime"].unit,
                    "total": 0,
                },
            ],
        },
        {
            "client_id": data["client_b"].id,
            "address_id": data["address_b"].id,
            "client_label": data["client_b"].name,
            "address_label": data["address_b"].address,
            "products": [
                {
                    "product_id": data["adhesive"].id,
                    "product_label": data["adhesive"].name,
                    "quantity": 20,
                    "unit": data["adhesive"].unit,
                    "total": 0,
                }
            ],
        },
    ]


def _service_destinations(data):
    return [
        {
            "client": data["client_a"],
            "delivery_address": data["address_a"],
            "products": [
                {"product": data["cement"], "quantity": 40},
                {"product": data["lime"], "quantity": 15},
            ],
        },
        {
            "client": data["client_b"],
            "delivery_address": data["address_b"],
            "products": [{"product": data["adhesive"], "quantity": 20}],
        },
    ]


def _pallet_payload(data):
    return [
        {
            "sequence": 1,
            "pallet_type": None,
            "allocations": [
                {
                    "client": data["client_a"],
                    "delivery_address": data["address_a"],
                    "product": data["cement"],
                    "quantity": 25,
                },
                {
                    "client": data["client_b"],
                    "delivery_address": data["address_b"],
                    "product": data["adhesive"],
                    "quantity": 20,
                },
            ],
        },
        {
            "sequence": 2,
            "pallet_type": None,
            "allocations": [
                {
                    "client": data["client_a"],
                    "delivery_address": data["address_a"],
                    "product": data["cement"],
                    "quantity": 15,
                },
                {
                    "client": data["client_a"],
                    "delivery_address": data["address_a"],
                    "product": data["lime"],
                    "quantity": 15,
                },
            ],
        },
    ]


def _show_dialog(dialog, app, *, step: int | None = None) -> None:
    dialog.resize(1180, 700)
    dialog.show()
    if step is not None:
        dialog._go_to_step(step)
    app.processEvents()


def _capture(widget, target: Path) -> None:
    widget.repaint()
    QApplication.processEvents()
    opaque_image = QImage(widget.size(), QImage.Format_RGB32)
    opaque_image.fill(QColor("white"))
    painter = QPainter(opaque_image)
    widget.render(painter, QPoint())
    painter.end()
    if not opaque_image.save(str(target), "PNG"):
        raise RuntimeError(f"No se pudo guardar {target}")


def generate(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables(ALL_MODELS)
    data = _masters()
    service = LoadOrderService(current_user="captura178")
    app = QApplication.instance() or QApplication([])

    new_dialog = LoadOrderEntryDialog(service, "captura178")
    _set_combo(new_dialog.driver_combo, data["driver"].id)
    _set_combo(new_dialog.truck_combo, data["truck"].id)
    new_dialog.destinations = _destination_drafts(data)
    new_dialog._render_destinations()
    _show_dialog(new_dialog, app, step=3)
    targets = [output_dir / "01_nueva_orden_grilla_pallets.png"]
    _capture(new_dialog, targets[-1])

    order = service.create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=_service_destinations(data),
        pallets=[],
    )
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="captura178_admin", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    window.resize(1440, 900)
    window._navigate_to_route("load_orders")
    window.show()
    app.processEvents()
    targets.append(output_dir / "02_panel_lateral_pallet_mixto.png")
    _capture(window, targets[-1])
    window.close()

    order = service.update_order(order, pallets=_pallet_payload(data))
    pallet_dialog = LoadOrderPalletDialog(service, order)
    _show_dialog(pallet_dialog, app)
    pallet_dialog.pallet_widget._select_pallet(1)
    app.processEvents()
    targets.append(output_dir / "03_editar_orden_reconstruida.png")
    _capture(pallet_dialog, targets[-1])

    pallet_dialog.close()
    edit_dialog = LoadOrderPalletDialog(service, order)
    _show_dialog(edit_dialog, app)
    edit_dialog.pallet_widget.add_allocation(2, data["address_a"].id, data["cement"].id, 1)
    edit_dialog.pallet_widget._select_pallet(2)
    app.processEvents()
    targets.append(output_dir / "04_estado_rojo_excedente.png")
    _capture(edit_dialog, targets[-1])

    new_dialog.close()
    edit_dialog.close()
    database.close()
    return targets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Genera evidencia visual del issue #178")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    for path in generate(args.output_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
