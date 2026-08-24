from datetime import date
from decimal import Decimal

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
from app.reports.managerial_sales_dispatch import (
    ManagerialSalesDispatchService,
    SalesDispatchFilters,
)


def _client(name: str, cuit: str, city: str) -> Client:
    client = Client.create(name=name, cuit=cuit, iva_condition="RI")
    ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city=city,
        address=f"Ruta acceso {city}",
    )
    return client


def _transport(number: int):
    carrier = Carrier.create(name=f"Transportista 323 {number}")
    driver = Driver.create(name=f"Chofer 323 {number}", carrier=carrier)
    truck = Truck.create(domain=f"T{number:05d}"[-6:], carrier=carrier)
    return carrier, driver, truck


def _order(
    *,
    number: int,
    order_date: date,
    client: Client,
    product: Product,
    quantity: float,
    net: float,
    vat: float,
    total: float,
    status: str = LoadOrder.STATUS_CLOSED,
):
    carrier, driver, truck = _transport(number)
    address = client.addresses.get()
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
    line = LoadOrderProduct.create(
        order=order,
        destination=destination,
        product=product,
        quantity=quantity,
        unit=product.unit,
        precio_neto_unitario=net / quantity if quantity else 0,
        neto_subtotal=net,
        neto_gravado=net,
        iva_porcentaje=21,
        iva_importe=vat,
        total=total,
    )
    return order, destination, line, carrier


def test_default_report_matches_dashboard_closed_totals(db):
    client = _client("Cliente 323", "30700010323", "Posadas")
    product = Product.create(name="Producto 323", unit="bolsa", peso_unitario_kg=25)
    _order(
        number=32301,
        order_date=date(2026, 8, 10),
        client=client,
        product=product,
        quantity=100,
        net=100000,
        vat=21000,
        total=121000,
    )

    filters = SalesDispatchFilters(date(2026, 8, 1), date(2026, 8, 31))
    report = ManagerialSalesDispatchService().report(filters)
    dashboard = ManagerialDashboardService()._period_metrics(
        ReportPeriod(date(2026, 8, 1), date(2026, 8, 31))
    )

    assert len(report.rows) == 1
    assert report.rows[0]["client_name"] == "Cliente 323"
    assert report.rows[0]["destination"].startswith("Posadas")
    assert report.totals.total == dashboard["valued_dispatches"] == 121000
    assert report.totals.tonnes == dashboard["tonnes"] == 2.5
    assert report.totals.orders == 1


def test_report_reuses_physical_kilos_rule(db):
    client = _client("Cliente Peso 323", "30700020323", "Oberá")
    product = Product.create(name="Producto Peso 323", unit="bolsa", peso_unitario_kg=25)
    order, destination, _line, _carrier = _order(
        number=32302,
        order_date=date(2026, 8, 11),
        client=client,
        product=product,
        quantity=100,
        net=200000,
        vat=42000,
        total=242000,
    )
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

    report = ManagerialSalesDispatchService().report(
        SalesDispatchFilters(date(2026, 8, 1), date(2026, 8, 31))
    )

    assert report.rows[0]["kilos"] == 2470
    assert report.rows[0]["tonnes"] == 2.47
    assert report.totals.tonnes == 2.47


def test_combined_filters_client_product_carrier_destination(db):
    client_a = _client("Cliente A 323", "30700030323", "Eldorado")
    client_b = _client("Cliente B 323", "30700040323", "Apóstoles")
    product_a = Product.create(name="Almidón 323 A", unit="bolsa", peso_unitario_kg=25)
    product_b = Product.create(name="Almidón 323 B", unit="bolsa", peso_unitario_kg=20)
    _order(
        number=32303,
        order_date=date(2026, 8, 12),
        client=client_a,
        product=product_a,
        quantity=10,
        net=10000,
        vat=2100,
        total=12100,
    )
    _order(
        number=32304,
        order_date=date(2026, 8, 13),
        client=client_b,
        product=product_b,
        quantity=20,
        net=20000,
        vat=4200,
        total=24200,
    )
    carrier = LoadOrder.get(LoadOrder.order_number == 32304).carrier

    result = ManagerialSalesDispatchService().report(
        SalesDispatchFilters(
            date(2026, 8, 1),
            date(2026, 8, 31),
            client_id=client_b.id,
            product_id=product_b.id,
            carrier_id=carrier.id,
            destination="apóstoles",
        )
    )

    assert [row["order_number"] for row in result.rows] == [32304]
    assert result.totals.total == 24200


def test_annulled_rows_can_be_shown_but_do_not_enter_valid_totals(db):
    client = _client("Cliente Anulada 323", "30700050323", "Garuhapé")
    product = Product.create(name="Producto Anulado 323", unit="bolsa", peso_unitario_kg=25)
    _order(
        number=32305,
        order_date=date(2026, 8, 14),
        client=client,
        product=product,
        quantity=50,
        net=50000,
        vat=10500,
        total=60500,
        status=LoadOrder.STATUS_ANNULLED,
    )

    result = ManagerialSalesDispatchService().report(
        SalesDispatchFilters(
            date(2026, 8, 1),
            date(2026, 8, 31),
            statuses=(LoadOrder.STATUS_ANNULLED,),
        )
    )

    assert len(result.rows) == 1
    assert result.rows[0]["status"] == LoadOrder.STATUS_ANNULLED
    assert result.totals.total == 0
    assert result.totals.tonnes == 0
    assert result.totals.orders == 0
