from datetime import date

import pytest

from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.payments import ClientPayment
from app.reports.managerial_clients import ManagerialClientsFilters, ManagerialClientsService


def _client(tag: str, *, active: bool = True) -> Client:
    return Client.create(
        name=f"Cliente MC {tag}", cuit=f"3070004{tag}", iva_condition="RI", active=active
    )


def _masters(tag: str):
    carrier = Carrier.create(name=f"Transportista MC {tag}")
    truck = Truck.create(domain=f"MC{tag}AA", carrier=carrier)
    driver = Driver.create(name=f"Chofer MC {tag}", carrier=carrier)
    return carrier, truck, driver


def _order(client: Client, *, number: int, order_date: date, status=LoadOrder.STATUS_CLOSED, destinations: int = 1):
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones",
        city="Posadas", address=f"Ruta MC {number}",
    )
    carrier, truck, driver = _masters(f"{number:04d}")
    order = LoadOrder.create(
        order_number=number, date=order_date, client=client, delivery_address=address,
        carrier=carrier, driver=driver, truck=truck, status=status,
    )
    for sequence in range(1, destinations + 1):
        destination = LoadOrderDestination.create(
            order=order, client=client, delivery_address=address, sequence=sequence
        )
        product = Product.create(
            name=f"Producto MC {number}-{sequence}", unit="bolsa", peso_unitario_kg=25
        )
        LoadOrderProduct.create(
            order=order, destination=destination, product=product, quantity=100, unit="bolsa",
            precio_neto_unitario=100.0, neto_subtotal=10000.0, neto_gravado=10000.0,
            iva_porcentaje=21.0, iva_importe=2100.0, total=12100.0,
        )
    ClientAccountMovement.create(
        client=client, load_order=order,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        amount=10000.0 * destinations, net_amount=10000.0 * destinations,
        total_amount=12100.0 * destinations, currency="ARS",
        movement_date=order_date, due_date=order_date,
        description=f"Despacho {number}", source_ref=f"test-325-order:{number}",
        created_by="admin",
    )
    return order


def test_aggregation_matches_sales_and_ledger(db):
    client = _client("0001")
    _order(client, number=3251, order_date=date(2026, 9, 1))
    _order(client, number=3252, order_date=date(2026, 9, 2))
    ClientPayment.create(
        receipt_number="REC-325-01", client=client, payment_date=date(2026, 9, 3),
        amount=5000, method="efectivo", status=ClientPayment.STATUS_ACTIVE,
    )

    result = ManagerialClientsService().report(
        ManagerialClientsFilters(start=date(2026, 9, 1), end=date(2026, 9, 4))
    )
    row = next(row for row in result.rows if row["client_id"] == client.id)

    assert row["period_total"] == 24200.0
    assert row["period_tonnes"] == 5.0
    assert row["period_orders"] == 2
    assert row["average_ticket"] == 12100.0
    assert row["balance"] == 24200.0
    assert row["last_payment"] == date(2026, 9, 3)
    assert row["has_activity"] is True


def test_multiple_destinations_do_not_double_count_orders(db):
    client = _client("0002")
    _order(client, number=3253, order_date=date(2026, 9, 1), destinations=2)

    result = ManagerialClientsService().report(
        ManagerialClientsFilters(start=date(2026, 9, 1), end=date(2026, 9, 4))
    )
    row = next(row for row in result.rows if row["client_id"] == client.id)

    assert row["period_orders"] == 1
    assert row["period_total"] == 24200.0


def test_client_without_movements_and_idle_filter(db):
    active_client = _client("0003")
    _order(active_client, number=3254, order_date=date(2026, 6, 1))
    quiet = _client("0004")

    result = ManagerialClientsService().report(
        ManagerialClientsFilters(start=date(2026, 9, 1), end=date(2026, 9, 4))
    )
    by_id = {row["client_id"]: row for row in result.rows}

    assert by_id[quiet.id]["has_activity"] is False
    assert by_id[quiet.id]["period_total"] == 0
    assert by_id[quiet.id]["last_dispatch"] is None
    assert by_id[active_client.id]["has_activity"] is False

    idle = ManagerialClientsService().report(
        ManagerialClientsFilters(start=date(2026, 9, 1), end=date(2026, 9, 4), min_idle_days=30)
    )
    assert active_client.id in {row["client_id"] for row in idle.rows}
    assert quiet.id not in {row["client_id"] for row in idle.rows}


def test_new_and_recovered_flags_and_sorting(db):
    new_client = _client("0005")
    _order(new_client, number=3255, order_date=date(2026, 9, 2))
    old_client = _client("0006")
    _order(old_client, number=3256, order_date=date(2026, 7, 1))
    _order(old_client, number=3257, order_date=date(2026, 9, 2))

    result = ManagerialClientsService().report(
        ManagerialClientsFilters(start=date(2026, 9, 1), end=date(2026, 9, 4))
    )
    by_id = {row["client_id"]: row for row in result.rows}

    assert by_id[new_client.id]["is_new"] is True
    assert by_id[old_client.id]["recovered"] is True
    assert by_id[old_client.id]["is_new"] is False

    by_balance = ManagerialClientsService().report(
        ManagerialClientsFilters(
            start=date(2026, 9, 1), end=date(2026, 9, 4), sort_by="balance"
        )
    )
    balances = [row["balance"] for row in by_balance.rows]
    assert balances == sorted(balances, reverse=True)


def test_inverted_dates_raise(db):
    with pytest.raises(ValueError):
        ManagerialClientsService().report(
            ManagerialClientsFilters(start=date(2026, 9, 5), end=date(2026, 9, 4))
        )
