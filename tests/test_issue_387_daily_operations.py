from datetime import date

import pytest

from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.reports.daily_operations import DailyOperationsFilters, DailyOperationsService
from app.services.client_payment_service import ClientPaymentService


def _order(*, number: int, order_date: date, status=LoadOrder.STATUS_PENDING):
    client = Client.create(name=f"Cliente OP {number}", cuit=f"3070001{number:04d}", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address=f"Ruta OP {number}",
    )
    carrier = Carrier.create(name=f"Transportista OP {number}")
    truck = Truck.create(domain=f"OP{number:03d}AA", carrier=carrier)
    driver = Driver.create(name=f"Chofer OP {number}", carrier=carrier)
    product = Product.create(
        name=f"Producto OP {number}",
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
        precio_neto_unitario=100.0,
        neto_subtotal=10000.0,
        neto_gravado=10000.0,
        iva_porcentaje=21.0,
        iva_importe=2100.0,
        total=12100.0,
    )
    return order


def test_period_status_counts_and_pending_section(db):
    _order(number=3871, order_date=date(2026, 9, 4))
    _order(number=3872, order_date=date(2026, 9, 4), status=LoadOrder.STATUS_ISSUED)
    _order(number=3873, order_date=date(2026, 9, 4), status=LoadOrder.STATUS_CLOSED)
    _order(number=3874, order_date=date(2026, 9, 4), status=LoadOrder.STATUS_ANNULLED)

    result = DailyOperationsService().report(
        DailyOperationsFilters(date(2026, 9, 4), date(2026, 9, 4))
    )

    assert result.totals.created == 4
    assert result.totals.closed == 1
    assert result.totals.annulled == 1
    assert result.totals.open_orders == 2
    assert {row["order_number"] for row in result.pending_rows} == {3871, 3872}
    # La anulada no contamina el despachado efectivo.
    assert result.totals.dispatched_orders == 1
    assert result.totals.dispatched_total == 12100.0


def test_dispatch_rows_carry_navigation_data_and_clients_served(db):
    _order(number=3875, order_date=date(2026, 9, 4), status=LoadOrder.STATUS_CLOSED)
    _order(number=3876, order_date=date(2026, 9, 4), status=LoadOrder.STATUS_CLOSED)

    result = DailyOperationsService().report(
        DailyOperationsFilters(date(2026, 9, 4), date(2026, 9, 4))
    )

    assert result.totals.clients_served == 2
    assert result.totals.dispatched_tonnes == 5.0
    numbers = {row["order_number"] for row in result.dispatch_rows}
    assert numbers == {3875, 3876}


def test_collections_and_manual_movements_are_summarized(db):
    order = _order(number=3877, order_date=date(2026, 9, 4), status=LoadOrder.STATUS_CLOSED)
    ClientPaymentService(current_user="admin").register_payment(
        client=order.client,
        amount=5000,
        payment_date=date(2026, 9, 4),
        method="efectivo",
    )
    ClientAccountMovement.create(
        client=order.client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        amount=1500.0,
        net_amount=1500.0,
        total_amount=1500.0,
        currency="ARS",
        movement_date=date(2026, 9, 4),
        description="Débito manual operativo",
        source_ref="test-387-debit",
        created_by="admin",
    )
    ClientAccountMovement.create(
        client=order.client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_CREDIT,
        amount=-400.0,
        net_amount=-400.0,
        total_amount=-400.0,
        currency="ARS",
        movement_date=date(2026, 9, 4),
        description="Crédito manual operativo",
        source_ref="test-387-credit",
        created_by="admin",
    )

    result = DailyOperationsService().report(
        DailyOperationsFilters(date(2026, 9, 4), date(2026, 9, 4))
    )

    assert result.totals.collected == 5000
    assert result.totals.collection_payments == 1
    assert result.totals.manual_debit == 1500.0
    assert result.totals.manual_credit == 400.0
    assert result.totals.manual_movements == 2


def test_status_filter_narrows_dispatch_rows(db):
    _order(number=3878, order_date=date(2026, 9, 4), status=LoadOrder.STATUS_CLOSED)
    _order(number=3879, order_date=date(2026, 9, 4), status=LoadOrder.STATUS_PENDING)

    result = DailyOperationsService().report(
        DailyOperationsFilters(
            date(2026, 9, 4), date(2026, 9, 4), status=LoadOrder.STATUS_CLOSED
        )
    )

    assert [row["order_number"] for row in result.dispatch_rows] == [3878]


def test_inverted_dates_raise(db):
    with pytest.raises(ValueError):
        DailyOperationsService().report(
            DailyOperationsFilters(date(2026, 9, 5), date(2026, 9, 4))
        )
