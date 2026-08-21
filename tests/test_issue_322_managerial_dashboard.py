from datetime import date
from decimal import Decimal

import pytest

from app.models.accounting import ClientAccountMovement
from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.reports.managerial_dashboard import ManagerialDashboardService, ReportPeriod


def _transport():
    carrier = Carrier.create(name="Transporte Gerencial")
    driver = Driver.create(name="Chofer Gerencial", carrier=carrier)
    truck = Truck.create(domain="GER322", carrier=carrier)
    return carrier, driver, truck


def _client(name: str, cuit: str) -> Client:
    client = Client.create(name=name, cuit=cuit, iva_condition="RI")
    ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address=f"Calle {name}",
    )
    return client


def _closed_order(*, number: int, order_date: date, client: Client, product: Product, quantity: float, total: float):
    carrier, driver, truck = _transport_for_number(number)
    order = LoadOrder.create(
        order_number=number,
        date=order_date,
        client=client,
        delivery_address=client.addresses.get(),
        carrier=carrier,
        driver=driver,
        truck=truck,
        status=LoadOrder.STATUS_CLOSED,
    )
    destination = LoadOrderDestination.create(
        order=order,
        client=client,
        delivery_address=client.addresses.get(),
        sequence=1,
    )
    LoadOrderProduct.create(
        order=order,
        destination=destination,
        product=product,
        quantity=quantity,
        unit=product.unit,
        precio_neto_unitario=total / quantity if quantity else 0,
        neto_subtotal=total,
        descuento_importe=0,
        neto_gravado=total,
        iva_porcentaje=0,
        iva_importe=0,
        total=total,
    )
    return order


def _transport_for_number(number: int):
    carrier = Carrier.create(name=f"Transporte {number}")
    driver = Driver.create(name=f"Chofer {number}", carrier=carrier)
    truck = Truck.create(domain=f"G{number:05d}"[-6:], carrier=carrier)
    return carrier, driver, truck


def test_report_period_presets_and_previous_equivalent():
    today = date(2026, 8, 21)
    period = ReportPeriod.preset("este mes", today=today)

    assert period.start == date(2026, 8, 1)
    assert period.end == today
    previous = period.previous_equivalent()
    assert previous.start == date(2026, 7, 11)
    assert previous.end == date(2026, 7, 31)

    previous_month = ReportPeriod.preset("mes anterior", today=today)
    assert previous_month.start == date(2026, 7, 1)
    assert previous_month.end == date(2026, 7, 31)


def test_report_period_rejects_inverted_dates():
    with pytest.raises(ValueError):
        ReportPeriod(date(2026, 8, 22), date(2026, 8, 21))


def test_dashboard_counts_only_closed_orders_by_default(db):
    client = _client("Cliente Dashboard", "30700000322")
    product = Product.create(
        name="Fécula Dashboard",
        unit="bolsa",
        peso_unitario_kg=25,
        precio_neto_base=100,
    )
    closed = _closed_order(
        number=32201,
        order_date=date(2026, 8, 10),
        client=client,
        product=product,
        quantity=40,
        total=100000,
    )
    carrier, driver, truck = _transport_for_number(32202)
    annulled = LoadOrder.create(
        order_number=32202,
        date=date(2026, 8, 11),
        client=client,
        delivery_address=client.addresses.get(),
        carrier=carrier,
        driver=driver,
        truck=truck,
        status=LoadOrder.STATUS_ANNULLED,
    )
    destination = LoadOrderDestination.create(
        order=annulled,
        client=client,
        delivery_address=client.addresses.get(),
        sequence=1,
    )
    LoadOrderProduct.create(
        order=annulled,
        destination=destination,
        product=product,
        quantity=400,
        unit="bolsa",
        neto_subtotal=900000,
        total=900000,
    )

    service = ManagerialDashboardService()
    metrics = service._period_metrics(ReportPeriod(date(2026, 8, 1), date(2026, 8, 31)))

    assert closed.status == LoadOrder.STATUS_CLOSED
    assert metrics["orders"] == 1
    assert metrics["valued_dispatches"] == 100000
    assert metrics["tonnes"] == 1.0
    assert metrics["average_ticket"] == 100000


def test_dashboard_tonnes_prioritize_physical_allocations_and_fallback_only_remainder(db):
    client = _client("Cliente Fisico", "30700000328")
    product = Product.create(name="Producto Fisico", unit="bolsa", peso_unitario_kg=25)
    order = _closed_order(
        number=32228,
        order_date=date(2026, 8, 18),
        client=client,
        product=product,
        quantity=100,
        total=250000,
    )
    destination = order.destinations.get()
    pallet = LoadOrderPallet.create(order=order, sequence=1)
    LoadOrderPalletAllocation.create(
        pallet=pallet,
        destination=destination,
        product=product,
        quantity=Decimal("40"),
        peso_unitario_kg=Decimal("24"),
    )
    LoadOrderLooseAllocation.create(
        order=order,
        destination=destination,
        product=product,
        quantity=Decimal("10"),
        peso_unitario_kg=Decimal("26"),
    )

    period = ReportPeriod(date(2026, 8, 1), date(2026, 8, 31))
    metrics = ManagerialDashboardService()._period_metrics(period)

    # 40*24 + 10*26 physical + remaining 50*25 fallback = 2,470 kg.
    assert metrics["tonnes"] == 2.47


def test_dashboard_effective_status_policy_is_injectable(db):
    client = _client("Cliente Emitida", "30700000323")
    product = Product.create(name="Producto Emitido", unit="bolsa", peso_unitario_kg=50)
    carrier, driver, truck = _transport_for_number(32203)
    order = LoadOrder.create(
        order_number=32203,
        date=date(2026, 8, 15),
        client=client,
        delivery_address=client.addresses.get(),
        carrier=carrier,
        driver=driver,
        truck=truck,
        status=LoadOrder.STATUS_ISSUED,
    )
    destination = LoadOrderDestination.create(order=order, client=client, delivery_address=client.addresses.get())
    LoadOrderProduct.create(
        order=order,
        destination=destination,
        product=product,
        quantity=20,
        unit="bolsa",
        neto_subtotal=50000,
        total=50000,
    )
    period = ReportPeriod(date(2026, 8, 1), date(2026, 8, 31))

    assert ManagerialDashboardService()._period_metrics(period)["orders"] == 0
    custom = ManagerialDashboardService(effective_statuses=(LoadOrder.STATUS_ISSUED, LoadOrder.STATUS_CLOSED))
    assert custom._period_metrics(period)["orders"] == 1
    assert custom._period_metrics(period)["tonnes"] == 1.0


def test_receivables_and_overdue_are_capped_by_real_balance(db):
    client = _client("Cliente Deuda", "30700000324")
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        amount=1000,
        net_amount=1000,
        total_amount=1000,
        currency="ARS",
        movement_date=date(2026, 7, 1),
        due_date=date(2026, 7, 15),
        description="Débito vencido",
        source_ref="test:debit:322",
    )
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
        amount=-600,
        net_amount=-600,
        total_amount=-600,
        currency="ARS",
        movement_date=date(2026, 8, 1),
        description="Pago parcial",
        source_ref="test:payment:322",
    )

    service = ManagerialDashboardService()

    assert service.total_receivables() == 400
    assert service.overdue_receivables(as_of=date(2026, 8, 21)) == 400


def test_top_clients_and_products_share_dashboard_rules(db):
    client_a = _client("Cliente A", "30700000325")
    client_b = _client("Cliente B", "30700000326")
    product_a = Product.create(name="Producto A", unit="bolsa", peso_unitario_kg=25)
    product_b = Product.create(name="Producto B", unit="bolsa", peso_unitario_kg=50)
    _closed_order(number=32210, order_date=date(2026, 8, 4), client=client_a, product=product_a, quantity=100, total=200000)
    _closed_order(number=32211, order_date=date(2026, 8, 5), client=client_b, product=product_b, quantity=20, total=50000)

    service = ManagerialDashboardService()
    period = ReportPeriod(date(2026, 8, 1), date(2026, 8, 31))
    clients = service.top_clients(period)
    products = service.top_products(period)

    assert clients[0]["name"] == "Cliente A"
    assert clients[0]["total"] == 200000
    assert products[0]["name"] == "Producto A"
    assert products[0]["tonnes"] == 2.5


def test_snapshot_contains_comparison_evolution_and_statuses(db):
    client = _client("Cliente Snapshot", "30700000327")
    product = Product.create(name="Producto Snapshot", unit="bolsa", peso_unitario_kg=25)
    _closed_order(number=32220, order_date=date(2026, 8, 20), client=client, product=product, quantity=40, total=100000)
    _closed_order(number=32221, order_date=date(2026, 7, 30), client=client, product=product, quantity=20, total=40000)

    snapshot = ManagerialDashboardService().snapshot(ReportPeriod(date(2026, 8, 1), date(2026, 8, 21)))

    assert snapshot.valued_dispatches.current == 100000
    assert snapshot.valued_dispatches.previous == 40000
    assert snapshot.valued_dispatches.variation_percent == 150.0
    assert len(snapshot.monthly_evolution) == 12
    assert any(row["status"] == LoadOrder.STATUS_CLOSED for row in snapshot.order_statuses)
