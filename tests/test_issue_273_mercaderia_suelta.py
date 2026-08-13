from decimal import Decimal

import pytest


def _data():
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck

    client = Client.create(name="Cliente suelto 273", cuit="30700273001", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Deposito suelto 273",
    )
    carrier = Carrier.create(name="Transporte suelto 273")
    driver = Driver.create(name="Chofer suelto 273", carrier=carrier)
    truck = Truck.create(domain="SUE273", carrier=carrier)
    product = Product.create(name="Fecula suelta 273", unit="bolsa", peso_unitario_kg=Decimal("25.000"))
    return {
        "client": client,
        "address": address,
        "carrier": carrier,
        "driver": driver,
        "truck": truck,
        "product": product,
    }


def _destinations(data, quantity=5):
    return [
        {
            "client": data["client"],
            "delivery_address": data["address"],
            "products": [{"product": data["product"], "quantity": quantity}],
        }
    ]


def _loose(data, quantity):
    return [
        {
            "client": data["client"],
            "delivery_address": data["address"],
            "product": data["product"],
            "quantity": Decimal(str(quantity)),
        }
    ]


def _pallet(data, quantity):
    return [
        {
            "sequence": 1,
            "allocations": [
                {
                    "client": data["client"],
                    "delivery_address": data["address"],
                    "product": data["product"],
                    "quantity": Decimal(str(quantity)),
                }
            ],
        }
    ]


def _create(service, data, *, destinations=None, pallets=None, loose=None):
    return service.create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=destinations if destinations is not None else _destinations(data),
        pallets=pallets or [],
        loose_allocations=loose or [],
    )


def test_issue_273_fully_loose_order_can_be_issued(db):
    from app.services.load_order_service import LoadOrderService

    data = _data()
    service = LoadOrderService(current_user="admin")
    order = _create(service, data, loose=_loose(data, 5))

    composition = service.composition(order)
    assert composition.is_complete is True
    assert composition.can_issue is True
    assert not composition.issues
    assert composition.total_kg == Decimal("125.000")


def test_issue_273_mixed_palletized_and_loose_assignments(db):
    from app.services.load_order_service import LoadOrderService

    data = _data()
    service = LoadOrderService(current_user="admin")
    order = _create(
        service,
        data,
        destinations=_destinations(data, quantity=10),
        pallets=_pallet(data, 6),
        loose=_loose(data, 4),
    )

    composition = service.composition(order)
    assert composition.can_issue is True
    assert not composition.issues
    assert composition.total_kg == Decimal("250.000")


def test_issue_273_pending_loose_blocks_issue(db):
    from app.services.load_order_service import LoadOrderService

    data = _data()
    service = LoadOrderService(current_user="admin")
    order = _create(service, data, loose=_loose(data, 4))

    composition = service.composition(order)
    assert composition.can_issue is False
    assert not composition.is_complete
    assert any(issue.code == "pending" for issue in composition.issues)


def test_issue_273_excess_loose_assignment_is_rejected(db):
    from app.services.load_order_service import LoadOrderService

    data = _data()
    service = LoadOrderService(current_user="admin")
    with pytest.raises(ValueError, match="excede lo solicitado"):
        _create(service, data, loose=_loose(data, 6))


def test_issue_273_loose_does_not_add_pallets(db):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    data = _data()
    service = LoadOrderService(current_user="admin")
    order = _create(
        service,
        data,
        destinations=_destinations(data, quantity=5),
        pallets=_pallet(data, 2),
        loose=_loose(data, 3),
    )

    assert LoadOrder.get_by_id(order.id).pallets.count() == 1
    assert len(service.composition(order).pallets) == 1
    assert LoadOrderPrintService(current_user="admin")._used_pallet_total(order) == 1


def test_issue_273_loose_persists_on_reload(db):
    from app.models.load_orders import LoadOrder, LoadOrderLooseAllocation
    from app.services.load_order_service import LoadOrderService

    data = _data()
    service = LoadOrderService(current_user="admin")
    order = _create(service, data, loose=_loose(data, 5))
    assert LoadOrderLooseAllocation.select().count() == 1

    reloaded = LoadOrder.get_by_id(order.id)
    composition = LoadOrderService(current_user="admin").composition(reloaded)
    assert composition.can_issue is True
    assert composition.total_kg == Decimal("125.000")


def test_issue_273_re_editing_loose_does_not_duplicate_rows(db):
    from app.models.load_orders import LoadOrderLooseAllocation
    from app.services.load_order_service import LoadOrderService

    data = _data()
    service = LoadOrderService(current_user="admin")
    order = _create(service, data, loose=_loose(data, 5))

    service.update_order(order, loose_allocations=_loose(data, 5))
    service.update_order(order, loose_allocations=_loose(data, 5))

    assert LoadOrderLooseAllocation.select().count() == 1
    allocation = LoadOrderLooseAllocation.get()
    assert allocation.quantity == Decimal("5.000")


def test_issue_273_print_splits_loose_rows_and_counts_total_kg(db, tmp_path):
    from load_order_printing_cases import _pdf_text

    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    data = _data()
    service = LoadOrderService(current_user="admin")
    order = _create(service, data, loose=_loose(data, 5))
    prints = LoadOrderPrintService(current_user="admin")

    rows = prints._detail_rows(order)
    assert len(rows) == 1
    assert rows[0]["pallet"] == "SUELTO"
    assert rows[0]["articles"]["Fecula suelta 273"] == 5.0
    assert prints._used_pallet_total(order) == 0

    text = _pdf_text(prints.export_pdf(order, tmp_path))
    assert "SUELTO" in text.replace("\n", "")
    assert "TOTAL MERCADERIA:" in text
    assert "125 kg" in text


def test_issue_273_ui_mark_loose_and_remaining_quantity(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.pallet_composition import PalletCompositionWidget

    app = QApplication.instance() or QApplication([])
    data = _data()
    destinations = [
        {
            "client_id": data["client"].id,
            "address_id": data["address"].id,
            "client_label": data["client"].name,
            "address_label": f"{data['client'].name} - {data['address'].address}",
            "products": [
                {
                    "product_id": data["product"].id,
                    "product_label": data["product"].name,
                    "quantity": 5,
                    "unit": "bolsa",
                }
            ],
        }
    ]
    widget = PalletCompositionWidget(destinations=destinations)

    widget.add_loose_allocation(data["address"].id, data["product"].id, 3)
    assert len(widget.loose_drafts()) == 1
    assert widget._remaining_quantity(data["address"].id, data["product"].id) == Decimal("2")

    widget.add_loose_allocation(data["address"].id, data["product"].id, 2)
    assert len(widget.loose_drafts()) == 1
    assert widget.loose_drafts()[0]["quantity"] == 5.0
    assert widget._remaining_quantity(data["address"].id, data["product"].id) == Decimal("0")

    widget.add_pallet()
    assert widget._remaining_quantity(data["address"].id, data["product"].id) == Decimal("0")

    widget.remove_loose_allocation(0)
    assert len(widget.loose_drafts()) == 0
    assert widget._remaining_quantity(data["address"].id, data["product"].id) == Decimal("5")


def test_issue_273_exact_case_five_bags_fully_loose_can_be_issued(db):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _data()
    service = LoadOrderService(current_user="admin")
    order = _create(service, data, loose=_loose(data, 5))

    issued = LoadOrderOperationService(current_user="admin").issue(order)
    assert issued.status == LoadOrder.STATUS_ISSUED
