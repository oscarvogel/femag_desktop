from datetime import date

from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderLooseAllocation,
    LoadOrderProduct,
)
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.remittances import Remittance
from app.reports.pending_orders_aging import PendingOrdersAgingService, PendingOrdersFilters


def _order(*, number: int, order_date: date, status=LoadOrder.STATUS_PENDING, with_allocation=False, with_traceability=True, with_remittance=False):
    client = Client.create(name=f"Cliente {number}", cuit=f"3070000{number:04d}", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address=f"Ruta {number}",
    )
    carrier = Carrier.create(name=f"Transportista {number}")
    truck = Truck.create(domain=f"AA{number:03d}AA", carrier=carrier)
    driver = Driver.create(name=f"Chofer {number}", carrier=carrier)
    product = Product.create(
        name=f"Producto {number}",
        unit="bolsa",
        peso_unitario_kg=25,
    )
    order = LoadOrder.create(
        order_number=number,
        date=order_date,
        client=client,
        delivery_address=address,
        carrier=carrier,
        driver=driver,
        truck=truck,
        status=status,
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
        product=product,
        quantity=100,
        unit="bolsa",
        lote="L-389" if with_traceability else None,
        fecha_elaboracion=date(2026, 9, 1) if with_traceability else None,
    )
    if with_allocation:
        LoadOrderLooseAllocation.create(
            order=order,
            destination=destination,
            product=product,
            quantity=100,
            peso_unitario_kg=25,
        )
    if with_remittance:
        Remittance.create(
            remittance_number=f"R-{number}",
            date=order_date,
            status=Remittance.STATUS_ISSUED,
            client=client,
            delivery_address=address,
            source_order=order,
            carrier=carrier,
            truck=truck,
            driver=driver,
            client_name=client.name,
            delivery_address_text=address.address,
        )
    return order


def test_pending_report_excludes_final_orders_and_calculates_age(db):
    open_order = _order(number=3891, order_date=date(2026, 9, 1))
    _order(number=3892, order_date=date(2026, 8, 20), status=LoadOrder.STATUS_CLOSED)

    result = PendingOrdersAgingService().report(
        PendingOrdersFilters(),
        today=date(2026, 9, 4),
    )

    assert [row["order_number"] for row in result.rows] == [open_order.order_number]
    assert result.rows[0]["age_days"] == 3
    assert result.totals.open_orders == 1
    assert result.totals.over_1_day == 1


def test_incomplete_order_explains_missing_assignment(db):
    _order(
        number=3893,
        order_date=date(2026, 9, 2),
        with_allocation=False,
        with_traceability=True,
    )

    row = PendingOrdersAgingService().report(
        PendingOrdersFilters(),
        today=date(2026, 9, 4),
    ).rows[0]

    assert row["pending_quantity"] == 100
    assert row["pending_stage"] == PendingOrdersAgingService.STAGE_PREPARATION
    assert "preparación" in row["pending_reason"].lower()


def test_complete_preparation_reports_traceability_gap_before_documental_gap(db):
    _order(
        number=3894,
        order_date=date(2026, 9, 3),
        with_allocation=True,
        with_traceability=False,
    )

    row = PendingOrdersAgingService().report(
        PendingOrdersFilters(),
        today=date(2026, 9, 4),
    ).rows[0]

    assert row["pending_quantity"] == 0
    assert row["traceability_pending"] is True
    assert row["pending_stage"] == PendingOrdersAgingService.STAGE_TRACEABILITY


def test_complete_order_without_remittance_is_documental_pending(db):
    _order(
        number=3895,
        order_date=date(2026, 9, 3),
        with_allocation=True,
        with_traceability=True,
        with_remittance=False,
    )

    row = PendingOrdersAgingService().report(
        PendingOrdersFilters(),
        today=date(2026, 9, 4),
    ).rows[0]

    assert row["pending_stage"] == PendingOrdersAgingService.STAGE_DOCUMENTAL
    assert row["remittance_pending"] is True


def test_issued_order_is_pending_closure_and_filters_by_age(db):
    _order(
        number=3896,
        order_date=date(2026, 8, 25),
        status=LoadOrder.STATUS_ISSUED,
        with_allocation=True,
        with_traceability=True,
        with_remittance=True,
    )
    _order(
        number=3897,
        order_date=date(2026, 9, 4),
        with_allocation=True,
        with_traceability=True,
        with_remittance=True,
    )

    result = PendingOrdersAgingService().report(
        PendingOrdersFilters(min_age_days=7),
        today=date(2026, 9, 4),
    )

    assert [row["order_number"] for row in result.rows] == [3896]
    assert result.rows[0]["pending_stage"] == PendingOrdersAgingService.STAGE_CLOSURE
    assert result.totals.pending_closure == 1
