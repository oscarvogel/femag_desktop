"""Preservacion y lectura de lote/fechas por contenido (#864, PR 1)."""

from datetime import date
from decimal import Decimal

from conftest import _master_data, _valid_order_payload

from app.models.load_orders import (
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.reports.pending_orders_aging import (
    PendingOrdersAgingService,
    PendingOrdersFilters,
)
from app.services.load_order_service import LoadOrderService


def _add_traceability(data):
    data["product"].peso_unitario_kg = Decimal("25.000")
    data["product"].save()
    service = LoadOrderService(current_user="issue864")
    order = service.create_order(**_valid_order_payload(data))
    destination = order.destinations.get()
    line = LoadOrderProduct.get(LoadOrderProduct.order == order)
    line.lote = "LOTE-LINEA"
    line.fecha_elaboracion = date(2026, 10, 19)
    line.fecha_envasado = date(2026, 10, 18)
    line.save()

    pallet = LoadOrderPallet.create(order=order, sequence=1)
    allocation = LoadOrderPalletAllocation.create(
        pallet=pallet,
        destination=destination,
        product=data["product"],
        quantity=40,
        peso_unitario_kg=Decimal("25.000"),
        lote="LOTE-PALLET",
        fecha_elaboracion=date(2026, 10, 20),
        fecha_envasado=date(2026, 10, 21),
    )
    loose = LoadOrderLooseAllocation.create(
        order=order,
        destination=destination,
        product=data["product"],
        quantity=10,
        peso_unitario_kg=Decimal("25.000"),
        lote="LOTE-SUELTO",
        fecha_elaboracion=date(2026, 10, 22),
        fecha_envasado=date(2026, 10, 23),
    )
    return service, order, destination, allocation, loose


def _pallet_payload(data, destination):
    return [
        {
            "sequence": 1,
            "pallet_type": None,
            "allocations": [
                {
                    "client": destination.client,
                    "delivery_address": destination.delivery_address,
                    "product": data["product"],
                    "quantity": 40,
                    "peso_unitario_kg": Decimal("25.000"),
                    "lote": "LOTE-PALLET",
                    "fecha_elaboracion": date(2026, 10, 20),
                    "fecha_envasado": date(2026, 10, 21),
                }
            ],
        }
    ]


def _loose_payload(data, destination):
    return [
        {
            "client": destination.client,
            "delivery_address": destination.delivery_address,
            "product": data["product"],
            "quantity": 10,
            "peso_unitario_kg": Decimal("25.000"),
            "lote": "LOTE-SUELTO",
            "fecha_elaboracion": date(2026, 10, 22),
            "fecha_envasado": date(2026, 10, 23),
        }
    ]


def test_update_pallets_and_loose_persists_traceability(db):
    data = _master_data()
    service, order, destination, _allocation, _loose = _add_traceability(data)

    service.update_order(
        order,
        pallets=_pallet_payload(data, destination),
        loose_allocations=_loose_payload(data, destination),
    )

    allocation = LoadOrderPalletAllocation.get()
    loose = LoadOrderLooseAllocation.get()
    assert (
        allocation.lote,
        allocation.fecha_elaboracion,
        allocation.fecha_envasado,
    ) == ("LOTE-PALLET", date(2026, 10, 20), date(2026, 10, 21))
    assert (
        loose.lote,
        loose.fecha_elaboracion,
        loose.fecha_envasado,
    ) == ("LOTE-SUELTO", date(2026, 10, 22), date(2026, 10, 23))


def test_update_destinations_preserves_line_and_content_traceability(db):
    data = _master_data()
    service, order, destination, _allocation, _loose = _add_traceability(data)

    service.update_order(
        order,
        destinations=[
            {
                "client": destination.client,
                "delivery_address": destination.delivery_address,
                "products": [{"product": data["product"], "quantity": 100}],
            }
        ],
    )

    line = LoadOrderProduct.get(LoadOrderProduct.order == order)
    allocation = LoadOrderPalletAllocation.get()
    loose = LoadOrderLooseAllocation.get()
    assert (
        line.lote,
        line.fecha_elaboracion,
        line.fecha_envasado,
    ) == ("LOTE-LINEA", date(2026, 10, 19), date(2026, 10, 18))
    assert (
        allocation.lote,
        allocation.fecha_elaboracion,
        allocation.fecha_envasado,
    ) == ("LOTE-PALLET", date(2026, 10, 20), date(2026, 10, 21))
    assert (
        loose.lote,
        loose.fecha_elaboracion,
        loose.fecha_envasado,
    ) == ("LOTE-SUELTO", date(2026, 10, 22), date(2026, 10, 23))


def test_pallet_dialog_keeps_traceability_of_untouched_contents(db):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt5.QtWidgets import QApplication

    from app.ui.desktop_app import LoadOrderPalletDialog

    data = _master_data()
    service, order, _destination, _allocation, _loose = _add_traceability(data)

    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderPalletDialog(service, order)
    app.processEvents()

    pallet_drafts = dialog._pallet_drafts()
    loose_drafts = dialog._loose_drafts()
    assert pallet_drafts[0]["allocations"][0]["lote"] == "LOTE-PALLET"
    assert pallet_drafts[0]["allocations"][0]["fecha_envasado"] == date(2026, 10, 21)
    assert loose_drafts[0]["lote"] == "LOTE-SUELTO"
    assert loose_drafts[0]["fecha_envasado"] == date(2026, 10, 23)

    dialog._save()

    allocation = LoadOrderPalletAllocation.get()
    loose = LoadOrderLooseAllocation.get()
    assert allocation.lote == "LOTE-PALLET"
    assert allocation.fecha_elaboracion == date(2026, 10, 20)
    assert allocation.fecha_envasado == date(2026, 10, 21)
    assert loose.lote == "LOTE-SUELTO"
    assert loose.fecha_elaboracion == date(2026, 10, 22)
    assert loose.fecha_envasado == date(2026, 10, 23)


def test_pending_control_uses_content_traceability_as_fallback(db):
    data = _master_data()
    _service, order, _destination, allocation, loose = _add_traceability(data)
    line = LoadOrderProduct.get(LoadOrderProduct.order == order)
    line.lote = None
    line.fecha_elaboracion = None
    line.fecha_envasado = None
    line.save()

    row = PendingOrdersAgingService().report(PendingOrdersFilters()).rows[0]

    assert row["order_id"] == order.id
    assert row["traceability_pending"] is False

    allocation.lote = None
    allocation.fecha_elaboracion = None
    allocation.save()
    loose.lote = None
    loose.fecha_elaboracion = None
    loose.save()

    row = PendingOrdersAgingService().report(PendingOrdersFilters()).rows[0]

    assert row["traceability_pending"] is True
