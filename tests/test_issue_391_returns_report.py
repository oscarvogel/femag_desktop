from datetime import date, datetime

import pytest

from app.models.load_orders import (
    LoadOrder,
    LoadOrderClosure,
    LoadOrderDestination,
    LoadOrderProduct,
    LoadOrderReturnLine,
)
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.reports.returns_report import ReturnsFilters, ReturnsReportService
from app.services.load_order_return_credit_service import LoadOrderReturnCreditService


def _order(*, number: int, tag: str, order_date: date, status=LoadOrder.STATUS_CLOSED):
    client = Client.create(name=f"Cliente DV {tag}", cuit=f"3070003{tag}", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address=f"Ruta DV {tag}",
    )
    carrier = Carrier.create(name=f"Transportista DV {tag}")
    truck = Truck.create(domain=f"DV{tag}AA", carrier=carrier)
    driver = Driver.create(name=f"Chofer DV {tag}", carrier=carrier)
    product = Product.create(name=f"Producto DV {tag}", unit="bolsa", peso_unitario_kg=25)
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
    line = LoadOrderProduct.create(
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
        lote="L-91",
        fecha_elaboracion=date(2026, 8, 1),
    )
    return order, line


def _close_with_return(order, line, *, quantity: float, reason: str, closed_day: date):
    closure = LoadOrderClosure.create(
        order=order,
        status=LoadOrderClosure.STATUS_ACTIVE,
        active_marker=True,
        closed_at=datetime(closed_day.year, closed_day.month, closed_day.day, 10, 0, 0),
        closed_by="demo",
    )
    unit_price = round(float(line.total) / float(line.quantity), 6)
    LoadOrderReturnLine.create(
        closure=closure,
        order_product=line,
        client=order.client,
        quantity=quantity,
        reason=reason,
        unit_price=unit_price,
        credit_amount=round(unit_price * quantity, 2),
        created_by="demo",
    )
    LoadOrderReturnCreditService(current_user="demo").generate_for_closure(closure)
    return closure


def test_partial_and_total_returns_with_gross_and_net(db):
    order_a, line_a = _order(number=3911, tag="0001", order_date=date(2026, 9, 1))
    _close_with_return(order_a, line_a, quantity=10, reason="Rotura", closed_day=date(2026, 9, 4))
    order_b, line_b = _order(number=3912, tag="0002", order_date=date(2026, 9, 2))
    _close_with_return(order_b, line_b, quantity=100, reason="Reclamo calidad", closed_day=date(2026, 9, 4))

    result = ReturnsReportService().report(
        ReturnsFilters(start=date(2026, 9, 1), end=date(2026, 9, 4))
    )

    assert result.totals.returns == 2
    assert result.totals.returned_quantity == 110
    assert result.totals.returned_kilos == 2750.0
    assert result.totals.credited_amount == round(121.0 * 110, 2)
    # Bruto conserva el movimiento original sin descontar.
    assert result.totals.dispatched_gross == 24200.0
    assert result.totals.net_amount == round(24200.0 - 121.0 * 110, 2)
    assert result.totals.return_rate_percent == round(121.0 * 110 / 24200.0 * 100, 2)
    assert {row["resolution"] for row in result.rows} == {"Con crédito"}
    assert result.top_clients[0]["count"] >= 1
    assert {row["lote"] for row in result.rows} == {"L-91"}


def test_reversed_credit_is_visible_but_not_effective(db):
    order, line = _order(number=3913, tag="0003", order_date=date(2026, 9, 1))
    closure = _close_with_return(
        order, line, quantity=20, reason="Faltante", closed_day=date(2026, 9, 4)
    )
    LoadOrderReturnCreditService(current_user="demo").reverse_for_closure(closure)

    result = ReturnsReportService().report(
        ReturnsFilters(start=date(2026, 9, 1), end=date(2026, 9, 4))
    )

    assert [row["resolution"] for row in result.rows] == ["Revertida"]
    assert result.totals.returns == 0
    assert result.totals.credited_amount == 0


def test_line_without_generated_credit_reports_resolution(db):
    order, line = _order(number=3914, tag="0004", order_date=date(2026, 9, 1))
    closure = LoadOrderClosure.create(
        order=order,
        status=LoadOrderClosure.STATUS_ACTIVE,
        active_marker=True,
        closed_at=datetime(2026, 9, 4, 10, 0, 0),
        closed_by="demo",
    )
    LoadOrderReturnLine.create(
        closure=closure,
        order_product=line,
        client=order.client,
        quantity=5,
        reason="Muestra",
        unit_price=121.0,
        credit_amount=0,
        created_by="demo",
    )

    result = ReturnsReportService().report(
        ReturnsFilters(start=date(2026, 9, 1), end=date(2026, 9, 4))
    )

    assert [row["resolution"] for row in result.rows] == ["Sin crédito generado"]


def test_filters_by_lote_reason_and_order(db):
    order, line = _order(number=3915, tag="0005", order_date=date(2026, 9, 1))
    _close_with_return(order, line, quantity=7, reason="Rotura en pallet", closed_day=date(2026, 9, 4))

    base = dict(start=date(2026, 9, 1), end=date(2026, 9, 4))
    assert len(ReturnsReportService().report(ReturnsFilters(**base, lote="L-91")).rows) == 1
    assert len(ReturnsReportService().report(ReturnsFilters(**base, lote="L-00")).rows) == 0
    assert len(ReturnsReportService().report(ReturnsFilters(**base, reason="pallet")).rows) == 1
    assert (
        len(ReturnsReportService().report(ReturnsFilters(**base, order_number=3915)).rows) == 1
    )
    assert (
        len(ReturnsReportService().report(ReturnsFilters(**base, order_number=9999)).rows) == 0
    )


def test_inverted_dates_raise(db):
    with pytest.raises(ValueError):
        ReturnsReportService().report(
            ReturnsFilters(start=date(2026, 9, 5), end=date(2026, 9, 4))
        )
