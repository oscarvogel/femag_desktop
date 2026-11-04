"""Vaciar todos los pallets desde el editor guiado (#876)."""

import os
from decimal import Decimal

from conftest import _master_data, _valid_order_payload

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_APP = None


def _app():
    global _APP
    from PyQt5.QtWidgets import QApplication

    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


def _destinations(db, *, quantity=100):
    from app.models.masters import Client, ClientAddress, Product

    client = Client.create(name="Cliente 876", cuit="30700876001", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Destino 876",
    )
    product = Product.create(
        name="Producto 876",
        unit="bolsa",
        peso_unitario_kg=Decimal("25.000"),
    )
    return [
        {
            "client_id": client.id,
            "address_id": address.id,
            "client_label": client.name,
            "address_label": address.address,
            "products": [
                {
                    "product_id": product.id,
                    "product_label": product.name,
                    "quantity": quantity,
                    "unit": product.unit,
                }
            ],
        }
    ]


def _widget(destinations):
    from app.ui.pallet_composition import PalletCompositionWidget

    _app()
    return PalletCompositionWidget(destinations=destinations)


def _fill_widget(widget, address_id, product_id, *, loose=True):
    widget.add_pallet()
    widget.add_pallet()
    widget.add_allocation(1, address_id, product_id, 40)
    widget.add_allocation(2, address_id, product_id, 20)
    widget._selected_sequence = 1
    widget.toggle_selected_pallet_lock()
    if loose:
        widget.add_loose_allocation(address_id, product_id, 10)


def _answer(monkeypatch, choice):
    from PyQt5.QtWidgets import QMessageBox

    value = QMessageBox.Yes if choice == "yes" else QMessageBox.No
    captured = {}

    def fake_question(parent, title, text, *args, **kwargs):
        captured["title"] = title
        captured["text"] = text
        return value

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    return captured


def test_guided_clear_button_is_visible_and_disabled_without_assignments(db):
    from PyQt5.QtWidgets import QPushButton

    destination = _destinations(db)[0]
    widget = _widget([destination])
    button = widget.findChild(QPushButton, "guidedClearAllPalletAllocationsButton")

    assert button is not None
    assert button.isEnabled() is False

    widget.add_pallet()
    widget.add_allocation(
        1,
        destination["address_id"],
        destination["products"][0]["product_id"],
        10,
    )

    assert button.isEnabled() is True


def test_cancel_keeps_assignments_locks_and_loose_goods(db, monkeypatch):
    destination = _destinations(db)[0]
    widget = _widget([destination])
    _fill_widget(
        widget,
        destination["address_id"],
        destination["products"][0]["product_id"],
    )
    captured = _answer(monkeypatch, "no")

    widget._guided_confirm_clear_allocations()

    drafts = widget.pallet_drafts()
    assert [len(pallet["allocations"]) for pallet in drafts] == [1, 1]
    assert drafts[0]["locked"] is True
    assert len(widget.loose_drafts()) == 1
    assert "suelta no se modifica" in captured["text"]
    assert "2 pallet" in captured["text"]


def test_confirm_clears_all_pallets_and_unlocks_but_keeps_loose_goods(db, monkeypatch):
    destination = _destinations(db)[0]
    widget = _widget([destination])
    _fill_widget(
        widget,
        destination["address_id"],
        destination["products"][0]["product_id"],
    )
    captured = _answer(monkeypatch, "yes")

    widget._guided_confirm_clear_allocations()

    drafts = widget.pallet_drafts()
    assert [pallet["sequence"] for pallet in drafts] == [1, 2]
    assert [pallet["allocations"] for pallet in drafts] == [[], []]
    assert [pallet["locked"] for pallet in drafts] == [False, False]
    assert len(widget.loose_drafts()) == 1
    assert "Cancelar no modifica nada" in captured["text"]

    pending = sum(row["pending"] for row in widget._current_rows())
    assert pending == Decimal("90.000")


def test_clear_then_save_keeps_empty_pallets_and_pending_quantity(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication

    from app.models.load_orders import LoadOrderLooseAllocation, LoadOrderPallet, LoadOrderPalletAllocation
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderPalletDialog

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    data["product"].peso_unitario_kg = Decimal("25.000")
    data["product"].save()
    service = LoadOrderService(current_user="issue876")
    order = service.create_order(**_valid_order_payload(data))
    destination = order.destinations.get()
    service.update_order(
        order,
        pallets=[
            {
                "sequence": 1,
                "pallet_type": None,
                "allocations": [
                    {
                        "client": destination.client,
                        "delivery_address": destination.delivery_address,
                        "product": data["product"],
                        "quantity": 40,
                    }
                ],
            },
            {
                "sequence": 2,
                "pallet_type": None,
                "allocations": [
                    {
                        "client": destination.client,
                        "delivery_address": destination.delivery_address,
                        "product": data["product"],
                        "quantity": 20,
                    }
                ],
            },
        ],
        loose_allocations=[
            {
                "client": destination.client,
                "delivery_address": destination.delivery_address,
                "product": data["product"],
                "quantity": 10,
            }
        ],
    )
    _answer(monkeypatch, "yes")
    dialog = LoadOrderPalletDialog(service, order)
    app.processEvents()

    dialog.pallet_widget._guided_confirm_clear_allocations()
    dialog._save()

    assert LoadOrderPallet.select().where(LoadOrderPallet.order == order).count() == 2
    assert (
        LoadOrderPalletAllocation.select()
        .join(LoadOrderPallet)
        .where(LoadOrderPallet.order == order)
        .count()
        == 0
    )
    assert (
        LoadOrderLooseAllocation.select()
        .where(LoadOrderLooseAllocation.order == order)
        .count()
        == 1
    )
    assert service.composition(order).pending_quantity == Decimal("90.000")
