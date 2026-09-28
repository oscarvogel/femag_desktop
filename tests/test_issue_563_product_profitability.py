from datetime import date
from decimal import Decimal

from app.models.load_orders import LoadOrder, LoadOrderProduct
from app.models.masters import Product
from app.reports.product_profitability import ProductProfitabilityService


def test_profitability_preserves_two_historical_costs(db):
    order = LoadOrder.select().first()
    product = Product.select().first()
    order.date = date.today(); order.status = LoadOrder.STATUS_ISSUED; order.save()
    LoadOrderProduct.create(order=order, product=product, quantity=10, unit=product.unit, precio_neto_unitario=20000, total=200000, costo_unitario_aplicado=Decimal("15000"))
    second = LoadOrder.create(order_number=999992, date=date.today(), carrier=order.carrier, driver=order.driver, truck=order.truck, status=LoadOrder.STATUS_ISSUED)
    LoadOrderProduct.create(order=second, product=product, quantity=10, unit=product.unit, precio_neto_unitario=21000, total=210000, costo_unitario_aplicado=Decimal("15500"))
    snap = ProductProfitabilityService().snapshot(date.today(), date.today())
    rows = [r for r in snap.lines if r.order_number in (order.order_number, second.order_number)]
    assert {r.applied_unit_cost for r in rows} == {15000.0, 15500.0}


def test_unknown_cost_is_not_zero(db):
    order=LoadOrder.select().first(); product=Product.select().first()
    order.date=date.today(); order.status=LoadOrder.STATUS_ISSUED; order.save()
    LoadOrderProduct.create(order=order, product=product, quantity=1, unit=product.unit, precio_neto_unitario=100, total=100, costo_unitario_aplicado=None)
    snap=ProductProfitabilityService().snapshot(date.today(),date.today())
    row=next(r for r in snap.lines if r.order_number==order.order_number and r.sale_amount==100)
    assert row.cost_amount is None and row.gross_profit is None
    assert snap.cost_coverage_percent < 100
