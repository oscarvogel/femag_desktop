from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models.masters import Product
from app.services.stock_service import StockService

ZERO = Decimal("0.000")


@dataclass(frozen=True)
class StockShortfall:
    """Faltante de un producto para una salida de mercaderia (#732, #734).

    ``available_kg`` es el saldo del libro: ya descuenta lo que salio antes, asi
    que el faltante es real, no una estimacion. ``requested_kg`` es lo que la
    operacion se lleva.
    """

    product: Product
    available_kg: Decimal
    requested_kg: Decimal

    @property
    def missing_kg(self) -> Decimal:
        return max(self.requested_kg - self.available_kg, ZERO)

    def describe(self) -> str:
        return (
            f"{self.product.name}: hay {self.available_kg:,.3f} kg, "
            f"se piden {self.requested_kg:,.3f} kg, "
            f"faltan {self.missing_kg:,.3f} kg"
        )


def stock_shortfall_of(plan) -> list[StockShortfall]:
    """Faltante de un plan de salida de mercaderia.

    El plan es una lista de ``(producto, unidades, kilos)``: la misma forma que
    usa el descuento, para que lo que se avisa y lo que se descuenta no puedan
    divergir.

    No bloquea nada: la operacion decide que hacer con el faltante. El saldo sale
    del libro de movimientos, asi que ya descuenta lo que salio antes y el
    faltante es real.

    Solo se avisa de los productos **con stock conocido**, es decir, los que
    alguna vez entraron al libro (inventario inicial, compra, produccion, ajuste
    de conteo). De un producto que nunca se conto no se puede afirmar que
    falte: se esta avisando de que el inventario todavia no esta cargado, que es
    otra cosa. Sin esta distincion el aviso aparece en cada salida hasta que se
    carga el inventario inicial, y a la larga el operador lo deja de leer.

    Vive aca y no duplicado en cada operacion porque lo usan dos: el despacho de
    la orden de carga (#732) y el presupuesto manual (#734).
    """
    faltantes: list[StockShortfall] = []
    for producto, _unidades, kilos in plan:
        if not StockService.has_inbound_movements(producto):
            continue
        disponible = StockService.balance_for(producto).balance_kg
        if kilos > disponible:
            faltantes.append(
                StockShortfall(
                    product=producto,
                    available_kg=disponible,
                    requested_kg=kilos,
                )
            )
    return faltantes
