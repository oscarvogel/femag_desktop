"""Utilidades compartidas por las pruebas de F150.

El precio fiscal de un renglón es el que congeló la operación, no el vigente del
maestro, así que las pruebas necesitan una orden de carga con precio por renglón.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
from app.models.remittances import Remittance


def attach_frozen_prices(remittance: Remittance, prices: dict[int, Decimal]) -> LoadOrder:
    """Crea la orden que originó al remito, con el precio congelado de cada producto.

    ``prices`` se indexa por ``RemittanceItem.product_id``. Un producto ausente
    queda sin precio congelado, que es el caso que debe bloquear la generación.
    """
    order = LoadOrder.create(
        order_number=_next_order_number(),
        date=remittance.date,
        carrier=remittance.carrier,
        driver=remittance.driver,
        truck=remittance.truck,
    )
    destination = LoadOrderDestination.create(
        order=order,
        client=remittance.client,
        delivery_address=remittance.delivery_address,
    )
    for row in remittance.items:
        LoadOrderProduct.create(
            order=order,
            destination=destination,
            product=row.product,
            quantity=float(row.quantity),
            unit=row.unit,
            precio_neto_unitario=float(prices.get(row.product_id, 0)),
        )
    remittance.source_order = order
    remittance.save(only=[Remittance.source_order])
    return order


def _next_order_number() -> int:
    existing = LoadOrder.select(LoadOrder.order_number).order_by(
        LoadOrder.order_number.desc()
    )
    return (existing[0].order_number + 1) if existing else 1
