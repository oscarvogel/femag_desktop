from datetime import date
from decimal import Decimal

from app.models.load_orders import LoadOrder, LoadOrderProduct
from app.models.masters import Carrier, Client, Driver, Product, Truck
from app.reports.product_profitability import ProductProfitabilityService


def _data(suffix):
    client = Client.create(name=f"Cliente rentabilidad {suffix}", cuit=f"3070000{suffix:04d}", iva_condition="RI")
    carrier = Carrier.create(name=f"Transporte rentabilidad {suffix}", cuit=f"3060000{suffix:04d}")
    driver = Driver.create(name=f"Chofer rentabilidad {suffix}", carrier=carrier, document=f"563{suffix}")
    truck = Truck.create(domain=f"R{suffix:05d}", carrier=carrier)
    product = Product.create(name=f"Producto rentabilidad {suffix}", unit="kg")
    return client, carrier, driver, truck, product


def _order(number, *, client, carrier, driver, truck):
    return LoadOrder.create(
        order_number=number, date=date.today(), client=client, carrier=carrier,
        driver=driver, truck=truck, status=LoadOrder.STATUS_ISSUED,
        created_by="profit-test", updated_by="profit-test",
    )


def test_profitability_preserves_two_historical_costs(db):
    client, carrier, driver, truck, product = _data(1)
    first = _order(563001, client=client, carrier=carrier, driver=driver, truck=truck)
    second = _order(563002, client=client, carrier=carrier, driver=driver, truck=truck)
    LoadOrderProduct.create(order=first, product=product, quantity=10, unit="kg", precio_neto_unitario=20000, neto_subtotal=200000, neto_gravado=200000, iva_importe=42000, total=242000, costo_unitario_aplicado=Decimal("15000"))
    LoadOrderProduct.create(order=second, product=product, quantity=10, unit="kg", precio_neto_unitario=21000, neto_subtotal=210000, neto_gravado=210000, iva_importe=44100, total=254100, costo_unitario_aplicado=Decimal("15500"))

    snap = ProductProfitabilityService().snapshot(date.today(), date.today())
    assert {row.applied_unit_cost for row in snap.lines} == {15000.0, 15500.0}
    assert snap.sales == 410000.0
    assert snap.cost == 305000.0
    assert snap.gross_profit == 105000.0
    assert snap.cost_coverage_percent == 100.0


def test_unknown_cost_is_not_zero(db):
    client, carrier, driver, truck, product = _data(2)
    known = _order(563003, client=client, carrier=carrier, driver=driver, truck=truck)
    unknown = _order(563004, client=client, carrier=carrier, driver=driver, truck=truck)
    LoadOrderProduct.create(order=known, product=product, quantity=1, unit="kg", precio_neto_unitario=100, neto_subtotal=100, neto_gravado=100, iva_importe=21, total=121, costo_unitario_aplicado=Decimal("60"))
    LoadOrderProduct.create(order=unknown, product=product, quantity=1, unit="kg", precio_neto_unitario=100, neto_subtotal=100, neto_gravado=100, iva_importe=21, total=121, costo_unitario_aplicado=None)

    snap = ProductProfitabilityService().snapshot(date.today(), date.today())
    unknown_row = next(row for row in snap.lines if row.order_number == 563004)
    assert unknown_row.cost_amount is None
    assert unknown_row.gross_profit is None
    assert snap.sales == 200.0
    assert snap.known_cost_sales == 100.0
    assert snap.cost == 60.0
    assert snap.gross_profit == 40.0
    assert snap.cost_coverage_percent == 50.0


def test_profitability_excludes_vat_from_sale_and_margin(db):
    client, carrier, driver, truck, product = _data(3)
    order = _order(563005, client=client, carrier=carrier, driver=driver, truck=truck)
    LoadOrderProduct.create(
        order=order, product=product, quantity=1500, unit="kg",
        precio_neto_unitario=18000, neto_subtotal=27000000,
        descuento_porcentaje=0, descuento_importe=0, neto_gravado=27000000,
        iva_porcentaje=21, iva_importe=5670000, total=32670000,
        costo_unitario_aplicado=Decimal("15300"),
    )
    snap = ProductProfitabilityService().snapshot(date.today(), date.today())
    row = next(row for row in snap.lines if row.order_number == 563005)
    assert row.sale_amount == 27000000.0
    assert row.cost_amount == 22950000.0
    assert row.gross_profit == 4050000.0
    assert row.margin_percent == 15.0
