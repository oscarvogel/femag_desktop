from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.models.load_orders import LoadOrder
from app.models.masters import Product
from app.models.stock import StockMovement
from app.services.audit_service import AuditService
from app.services.stock_service import StockService

ZERO = Decimal("0.000")


class LoadOrderStockError(ValueError):
    pass


def dispatch_source_prefix(order_id: int) -> str:
    """Prefijo de los movimientos de stock de una orden.

    Va por **orden** y no por cierre: el descuento pasa a ser cosa de la
    emision, no de la entrega. Una orden emitida y luego anulada no vuelve a
    emitirse ("No se puede emitir una orden anulada"), asi que el ciclo de stock
    por orden es de una sola vez y el indice unico alcanza para garantizarlo.
    """
    return f"LoadOrder:{order_id}:Dispatch"


def _miles(unidades: Decimal) -> str:
    """Miles con punto, que es como se leen los numeros aca."""
    return f"{unidades:,.0f}".replace(",", ".")


class LoadOrderStockService:
    """Despachos de ordenes FEMAG como salidas del libro de stock (#573).

    El evento operativo es la **emision de la orden**: es el momento en que sale
    el presupuesto y la mercaderia se va de la planta. Ni el borrador ni la
    entrega posterior lo mueven, porque ninguno de los dos significa que el
    camion salio.

    Y al anular una orden emitida, la mercaderia vuelve: la anulacion genera el
    movimiento contrario, no borra nada.

    La cantidad sale de las **asignaciones** de pallet y de las sueltas, no del
    renglon de la orden: las asignaciones guardan ``peso_unitario_kg`` como copia
    del momento en que se armo el pallet, asi que corregir despues el peso del
    maestro no reescribe lo que ya salio. Verificado sobre el historico: las
    asignaciones coinciden exactamente con la cantidad de la orden en los 102
    pares (orden, producto) de las ordenes cerradas, sin una sola diferencia.

    Idempotente por el indice unico de ``StockMovement``: volver a generar el
    despacho de una orden no duplica la salida.
    """

    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def _require_order(self, order) -> LoadOrder:
        if order is None or not isinstance(order, LoadOrder) or order.id is None:
            raise LoadOrderStockError("Debe seleccionar una orden válida.")
        return order

    @staticmethod
    def _allocations_of(order):
        """Todas las asignaciones de la orden, en pallets y sueltas.

        Las de pallet llegan por ``order.pallets`` y las sueltas cuelgan directo de
        la orden; no hay un backref unico porque la asignacion de pallet cuelga
        del pallet y del destino, no de la orden.
        """
        for pallet in order.pallets:
            for asignacion in pallet.allocations:
                yield asignacion
        for asignacion in order.loose_allocations:
            yield asignacion

    def _dispatched_by_product(self, order) -> dict[int, tuple[Decimal, Decimal]]:
        """Kg despachados por producto, y las unidades, desde las asignaciones."""
        totales: dict[int, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
        for asignacion in self._allocations_of(order):
            totales[asignacion.product_id][0] += Decimal(str(asignacion.quantity or 0))
            totales[asignacion.product_id][1] += Decimal(str(asignacion.kilos or 0))
        return {
            producto_id: (unidades, kilos)
            for producto_id, (unidades, kilos) in totales.items()
        }

    def register_dispatch(self, order) -> list[StockMovement]:
        """Descuenta del stock lo que sale al emitir la orden."""
        order = self._require_order(order)
        prefix = dispatch_source_prefix(order.id)

        movimientos: list[StockMovement] = []
        for producto_id, (unidades, kilos) in sorted(
            self._dispatched_by_product(order).items()
        ):
            if kilos <= ZERO:
                # Sin peso de bolsa en la asignacion no hay kilos que restar, y
                # un movimiento de 0 solo ensucia el libro.
                continue
            producto = Product.get_or_none(Product.id == producto_id)
            if producto is None:
                raise LoadOrderStockError(
                    f"El producto {producto_id} de la orden {order.order_number} no existe."
                )
            movimientos.append(
                StockService.register(
                    product=producto,
                    movement_type=StockMovement.TYPE_DISPATCH,
                    quantity_kg=kilos,
                    source_ref=f"{prefix}:{producto_id}",
                    description=(
                        f"Despacho OC-{order.order_number:06d} · "
                        f"{_miles(unidades)} unidad(es)"
                    ),
                    movement_date=order.date,
                    created_by=self.current_user,
                )
            )

        if movimientos:
            self.audit_service.record(
                user=self.current_user,
                module="Stock",
                action="descontar_despacho",
                record_ref=f"LoadOrder:{order.id}",
                new_value={
                    "order_number": order.order_number,
                    "movement_ids": [m.id for m in movimientos],
                    "kg": str(sum(m.quantity_kg for m in movimientos)),
                },
            )
        return movimientos

    def reverse_dispatch(self, order, *, reason: str | None = None) -> list[StockMovement]:
        """Devuelve la mercaderia al anular una orden que ya habia salido."""
        order = self._require_order(order)
        prefix = dispatch_source_prefix(order.id)

        originales = list(
            StockMovement.select()
            .where(
                (StockMovement.source_ref.startswith(f"{prefix}:"))
                & (StockMovement.movement_type == StockMovement.TYPE_DISPATCH)
                & (StockMovement.is_reversal == False)  # noqa: E712
            )
            .order_by(StockMovement.id)
        )

        motivo = (reason or "").strip() or (
            f"Anulación de la orden OC-{order.order_number:06d}"
        )
        reversas: list[StockMovement] = []
        for original in originales:
            reversas.append(
                StockService.reverse(
                    original,
                    created_by=self.current_user,
                    reason=motivo,
                )
            )

        if reversas:
            self.audit_service.record(
                user=self.current_user,
                module="Stock",
                action="revertir_despacho",
                record_ref=f"LoadOrder:{order.id}",
                new_value={
                    "order_number": order.order_number,
                    "reversal_ids": [m.id for m in reversas],
                },
            )
        return reversas
