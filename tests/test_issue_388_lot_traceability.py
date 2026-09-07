from datetime import date

import pytest

from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck
from app.reports.lot_traceability import LotTraceabilityFilters, LotTraceabilityService


def _masters(tag: str):
    client = Client.create(name=f"Cliente LT {tag}", cuit=f"3070002{tag}", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address=f"Ruta LT {tag}",
    )
    carrier = Carrier.create(name=f"Transportista LT {tag}")
    truck = Truck.create(domain=f"LT{tag}AA", carrier=carrier)
    driver = Driver.create(name=f"Chofer LT {tag}", carrier=carrier)
    return client, address, carrier, truck, driver


def _product(tag: str):
    return Product.create(name=f"Producto LT {tag}", unit="bolsa", peso_unitario_kg=25)


def _order(*, number: int, tag: str, order_date: date, status=LoadOrder.STATUS_CLOSED):
    client, address, carrier, truck, driver = _masters(tag)
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
        order=order, client=client, delivery_address=address, sequence=1
    )
    return order, destination


def _line(order, destination, product, *, quantity: float, lote: str | None, elab: date | None):
    return LoadOrderProduct.create(
        order=order,
        destination=destination,
        product=product,
        quantity=quantity,
        unit="bolsa",
        precio_neto_unitario=100.0,
        neto_subtotal=quantity * 100.0,
        neto_gravado=quantity * 100.0,
        iva_porcentaje=21.0,
        iva_importe=quantity * 21.0,
        total=quantity * 121.0,
        lote=lote,
        fecha_elaboracion=elab,
    )


def _pallet(order, *, sequence: int = 1):
    pallet_type, _ = PalletType.get_or_create(
        type="LT pallet", defaults={"measure": "1x1", "weight": 18.0, "active": True}
    )
    return LoadOrderPallet.create(
        order=order, pallet_type=pallet_type, sequence=sequence, quantity=1
    )


def _alloc(pallet, destination, product, quantity: float):
    return LoadOrderPalletAllocation.create(
        pallet=pallet, destination=destination, product=product,
        quantity=quantity, peso_unitario_kg=25,
    )


def test_direct_lot_search_returns_every_client_and_order(db):
    order_a, dest_a = _order(number=3881, tag="0001", order_date=date(2026, 8, 10))
    _line(order_a, dest_a, _product("A1"), quantity=100, lote="L-58", elab=date(2026, 7, 16))
    order_b, dest_b = _order(number=3882, tag="0002", order_date=date(2026, 8, 12))
    _line(order_b, dest_b, _product("A2"), quantity=60, lote="L-58", elab=date(2026, 7, 16))

    result = LotTraceabilityService().report(LotTraceabilityFilters(lote="L-58"))

    assert {row["order_number"] for row in result.rows} == {3881, 3882}
    assert result.totals.clients == 2
    assert result.totals.orders == 2
    assert result.totals.dispatched_quantity == 160
    assert result.totals.first_dispatch == date(2026, 8, 10)
    assert result.totals.last_dispatch == date(2026, 8, 12)


def test_inverse_client_search_returns_received_lots(db):
    order, dest = _order(number=3883, tag="0003", order_date=date(2026, 8, 11))
    _line(order, dest, _product("B1"), quantity=40, lote="L-60", elab=date(2026, 7, 20))
    _line(order, dest, _product("B2"), quantity=30, lote="L-69", elab=date(2026, 7, 21))

    result = LotTraceabilityService().report(
        LotTraceabilityFilters(
            client_id=order.client_id,
            dispatch_from=date(2026, 8, 1),
            dispatch_to=date(2026, 8, 31),
        )
    )

    assert {row["lote"] for row in result.rows} == {"L-60", "L-69"}


def test_mixed_pallet_represents_each_product(db):
    order, dest = _order(number=3884, tag="0004", order_date=date(2026, 8, 11))
    product_a, product_b = _product("C1"), _product("C2")
    _line(order, dest, product_a, quantity=40, lote="L-58", elab=date(2026, 7, 16))
    _line(order, dest, product_b, quantity=20, lote="L-56", elab=date(2026, 7, 19))
    pallet = _pallet(order)
    _alloc(pallet, dest, product_a, 40)
    _alloc(pallet, dest, product_b, 20)

    result = LotTraceabilityService().report(LotTraceabilityFilters(order_number=3884))

    assert {(row["pallet"], row["lote"]) for row in result.rows} == {
        ("Pallet 1", "L-58"),
        ("Pallet 1", "L-56"),
    }
    assert result.totals.dispatched_quantity == 60


def test_same_lot_in_many_pallets_consolidates_with_detail(db):
    order, dest = _order(number=3885, tag="0005", order_date=date(2026, 8, 11))
    product = _product("D1")
    _line(order, dest, product, quantity=100, lote="L-58", elab=date(2026, 7, 16))
    pallet_1, pallet_2 = _pallet(order, sequence=1), _pallet(order, sequence=2)
    _alloc(pallet_1, dest, product, 60)
    _alloc(pallet_2, dest, product, 40)

    result = LotTraceabilityService().report(LotTraceabilityFilters(lote="L-58"))

    rows = [row for row in result.rows if row["order_number"] == 3885]
    assert {(row["pallet"], row["quantity"]) for row in rows} == {
        ("Pallet 1", 60),
        ("Pallet 2", 40),
    }
    assert sum(row["quantity"] for row in rows) == 100


def test_unassigned_remainder_is_reported_without_double_counting(db):
    order, dest = _order(number=3886, tag="0006", order_date=date(2026, 8, 11))
    product = _product("E1")
    _line(order, dest, product, quantity=100, lote="L-70", elab=date(2026, 7, 22))
    pallet = _pallet(order)
    _alloc(pallet, dest, product, 70)
    LoadOrderLooseAllocation.create(
        order=order, destination=dest, product=product, quantity=20, peso_unitario_kg=25
    )

    result = LotTraceabilityService().report(LotTraceabilityFilters(lote="L-70"))

    rows = [row for row in result.rows if row["order_number"] == 3886]
    assert {(row["pallet"], row["quantity"]) for row in rows} == {
        ("Pallet 1", 70),
        ("Suelto", 20),
        ("Sin asignar", 10),
    }
    assert result.totals.dispatched_quantity == 100


def test_annulled_orders_are_excluded_unless_requested(db):
    order, dest = _order(
        number=3887, tag="0007", order_date=date(2026, 8, 11), status=LoadOrder.STATUS_ANNULLED
    )
    _line(order, dest, _product("F1"), quantity=50, lote="L-71", elab=date(2026, 7, 22))

    assert LotTraceabilityService().report(LotTraceabilityFilters(lote="L-71")).rows == ()
    requested = LotTraceabilityService().report(
        LotTraceabilityFilters(lote="L-71", status=LoadOrder.STATUS_ANNULLED)
    )
    assert [row["order_number"] for row in requested.rows] == [3887]


def test_inverted_dates_raise(db):
    with pytest.raises(ValueError):
        LotTraceabilityService().report(
            LotTraceabilityFilters(dispatch_from=date(2026, 8, 12), dispatch_to=date(2026, 8, 10))
        )
