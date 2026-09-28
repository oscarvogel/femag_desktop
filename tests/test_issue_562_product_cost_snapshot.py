from decimal import Decimal

from app.models.load_orders import LoadOrder, LoadOrderProduct
from app.models.masters import Product
from app.services.load_order_service import LoadOrderService


def _existing_order(db):
    order = LoadOrder.select().order_by(LoadOrder.id).first()
    assert order is not None, "El fixture debe proveer una orden"
    return order


def test_cost_snapshot_is_frozen_on_first_issue(db):
    order = _existing_order(db)
    product = Product.select().order_by(Product.id).first()
    product.costo_unitario = Decimal("15000.0000")
    product.save()
    line = LoadOrderProduct.create(
        order=order, product=product, quantity=10, unit=product.unit,
        precio_neto_unitario=20000, total=200000,
    )
    service = LoadOrderService("snapshot-test")

    service._change_status(order, LoadOrder.STATUS_ISSUED)
    assert LoadOrderProduct.get_by_id(line.id).costo_unitario_aplicado == Decimal("15000.0000")

    product.costo_unitario = Decimal("15500.0000")
    product.save()
    service._snapshot_product_costs(order)
    assert LoadOrderProduct.get_by_id(line.id).costo_unitario_aplicado == Decimal("15000.0000")


def test_unknown_cost_stays_unknown_after_issue(db):
    order = _existing_order(db)
    product = Product.select().order_by(Product.id).first()
    product.costo_unitario = None
    product.save()
    line = LoadOrderProduct.create(
        order=order, product=product, quantity=1, unit=product.unit,
        precio_neto_unitario=100, total=100,
    )

    LoadOrderService("snapshot-null")._change_status(order, LoadOrder.STATUS_ISSUED)

    assert LoadOrderProduct.get_by_id(line.id).costo_unitario_aplicado is None


def test_second_dispatch_uses_new_product_cost(db):
    first = _existing_order(db)
    product = Product.select().order_by(Product.id).first()
    product.costo_unitario = Decimal("15000.0000")
    product.save()
    first_line = LoadOrderProduct.create(
        order=first, product=product, quantity=1, unit=product.unit,
        precio_neto_unitario=20000, total=20000,
    )
    service = LoadOrderService("snapshot-two")
    service._change_status(first, LoadOrder.STATUS_ISSUED)

    product.costo_unitario = Decimal("15500.0000")
    product.save()
    second = LoadOrder.create(
        order_number=999991, carrier=first.carrier, driver=first.driver,
        truck=first.truck, created_by="snapshot-two", updated_by="snapshot-two",
    )
    second_line = LoadOrderProduct.create(
        order=second, product=product, quantity=1, unit=product.unit,
        precio_neto_unitario=20000, total=20000,
    )
    service._change_status(second, LoadOrder.STATUS_ISSUED)

    assert LoadOrderProduct.get_by_id(first_line.id).costo_unitario_aplicado == Decimal("15000.0000")
    assert LoadOrderProduct.get_by_id(second_line.id).costo_unitario_aplicado == Decimal("15500.0000")
