"""Precio unitario de un producto para un cliente.

Cada cliente tiene asignada una de las cuatro listas de precios y cada producto
tiene un precio por lista. El precio de una operacion es, entonces, el de la
lista del cliente, no un precio unico del maestro: en el historico del sistema
anterior el mismo producto sale a distintos precios el mismo dia.

Este modulo es el unico lugar donde se resuelve esa regla. Las ordenes de carga
y los remitos lo usan para no divergir entre si.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


PRICE_QUANTUM = Decimal("0.0001")


def price_for_client_list(product, client) -> Decimal:
    """Precio unitario de ``product`` segun la lista de precios de ``client``.

    Cae a ``precio_neto_base`` cuando la lista del cliente no tiene precio
    cargado, que es el valor que el legacy mantiene siempre informado.
    """
    price_list = getattr(client, "lista_precios", None) or 1
    if price_list not in (1, 2, 3, 4):
        raise ValueError("La lista de precios del cliente debe ser 1, 2, 3 o 4.")
    value = getattr(product, f"precio_lista_{price_list}", None) or 0.0
    if not value:
        value = getattr(product, "precio_neto_base", None) or 0.0
    return as_money(Decimal(str(value)))


def as_money(value: Decimal) -> Decimal:
    """Redondeo monetario de cuatro decimales, con el criterio del proyecto."""
    return Decimal(value).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)