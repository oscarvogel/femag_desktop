from __future__ import annotations

from decimal import Decimal

from app.models.budgets import Budget
from app.models.masters import PRODUCT_KIND_PRODUCT
from app.models.stock import StockMovement
from app.services.audit_service import AuditService
from app.services.stock_service import StockService, bags_to_kg, is_countable_in_bags
from app.services.stock_shortfall import StockShortfall, stock_shortfall_of

ZERO = Decimal("0.000")


class BudgetStockError(ValueError):
    pass


class BudgetStockShortfallError(ValueError):
    """El presupuesto manual pide mas mercaderia de la que hay en stock (#734).

    Lleva el detalle del faltante para que la pantalla pueda mostrarlo y pedir el
    motivo con el que el operador decide emitir igual. Sin ese motivo el
    presupuesto no se crea.
    """

    def __init__(self, message: str, *, faltantes: list[StockShortfall]):
        super().__init__(message)
        self.faltantes = list(faltantes)


def dispatch_source_prefix(budget_id: int) -> str:
    """Prefijo de los movimientos de stock de un presupuesto manual.

    Va por **presupuesto** y no por linea: el documento es el hecho operativo
    que hace salir la mercaderia, y el indice unico de ``StockMovement`` sobre
    ``(producto, origen, tipo)`` garantiza que el mismo presupuesto no se
    descuente dos veces.
    """
    return f"Budget:{budget_id}:Dispatch"


def _miles(unidades: Decimal) -> str:
    """Miles con punto, que es como se leen los numeros aca."""
    return f"{unidades:,.0f}".replace(",", ".")


def descuenta_stock(product) -> bool:
    """Si este producto descuenta stock en un presupuesto manual.

    La regla vive aca y no en la pantalla para que no puedan divergir: la
    pantalla le dice al operador que renglones no descuentan stock, y el
    servicio decide lo mismo. Si las dos reglas se desalinean, el operador ve
    un aviso que miente.

    Son dos condiciones, y las dos hacen falta:

    - Es mercaderia: un servicio, un interno, un financiero o algo en revision
      no sale del deposito. Es el mismo filtro que usan el inventario inicial y
      el conteo fisico.
    - Tiene peso de bolsa: sin el no hay conversion a kilos, y un movimiento
      de 0 kg no dice nada.
    """
    if product is None:
        return False
    if product.product_kind != PRODUCT_KIND_PRODUCT:
        return False
    return is_countable_in_bags(product)


class BudgetStockService:
    """La mercaderia que sale por presupuesto manual descuenta el stock (#734).

    Es la segunda puerta de salida de mercaderia: la primera es el despacho de
    la orden de carga (#573). Sin esta, la mercaderia que un cliente se lleva
    con un presupuesto manual sale de la planta sin dejar rastro en el libro, y
    el aviso de faltante de #732 no la ve.

    El movimiento es el mismo tipo que el del despacho (``dispatch``): sale de la
    planta. Lo que cambia es el origen, que es el presupuesto y no la orden.
    """

    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def plan(self, items) -> list[tuple]:
        """Calcula la mercaderia que sale con el presupuesto, **sin escribir nada**.

        El plan es una lista de ``(producto, unidades, kilos)``.

        Solo entra la **mercaderia** con peso de bolsa cargado. Las dos
        condiciones son necesarias:

        - No es servicio, ni interno, ni financiero, ni esta en revision: eso no
          sale del deposito. Es el mismo filtro que usan el inventario inicial y
          el conteo fisico.
        - Tiene peso de bolsa: sin el no hay conversion a kilos, y un movimiento
          de 0 kg no dice nada.

        Los kilos se derivan aca con el peso de bolsa del maestro, y no en la
        pantalla: es la misma conversion que usa el conteo fisico y los partes
        de produccion, en un solo lugar.
        """
        plan: list[tuple] = []
        for item in items or []:
            producto = item.get("product") if isinstance(item, dict) else None
            if not descuenta_stock(producto):
                continue
            try:
                unidades = Decimal(str(item.get("quantity") or 0))
            except (TypeError, ValueError, ArithmeticError):
                continue
            if unidades <= ZERO:
                continue
            kilos = bags_to_kg(producto, unidades)
            if kilos <= ZERO:
                continue
            plan.append((producto, unidades, kilos))
        return plan

    def shortfall(self, plan) -> list[StockShortfall]:
        """Faltante del plan, con la misma regla que el despacho (#732)."""
        return stock_shortfall_of(plan)

    def register(
        self,
        budget: Budget,
        plan,
        *,
        override_reason: str = "",
    ) -> list[StockMovement]:
        """Descuenta del stock la mercaderia que sale con el presupuesto.

        ``override_reason`` es el motivo con el que el operador confirmo emitir
        igual sin stock suficiente (#734). Va en las observaciones del movimiento
        y en la auditoria: cuando despues se ve un saldo en negativo, el libro
        dice por que salio.
        """
        budget = Budget.get_by_id(budget.id)
        prefix = dispatch_source_prefix(budget.id)
        motivo = (override_reason or "").strip()
        observaciones = (
            f"Despacho con stock insuficiente. Motivo: {motivo}" if motivo else None
        )

        movimientos: list[StockMovement] = []
        for producto, unidades, kilos in plan:
            movimientos.append(
                StockService.register(
                    product=producto,
                    movement_type=StockMovement.TYPE_DISPATCH,
                    quantity_kg=kilos,
                    source_ref=f"{prefix}:{producto.id}",
                    description=(
                        f"Presupuesto {budget.display_number} - {producto.name} "
                        f"({_miles(unidades)} unidad(es))"
                    ),
                    movement_date=budget.issue_date,
                    observations=observaciones,
                    created_by=self.current_user,
                )
            )

        if movimientos:
            self.audit_service.record(
                user=self.current_user,
                module="Stock",
                action="descontar_despacho",
                record_ref=f"Budget:{budget.id}",
                new_value={
                    "budget_number": budget.budget_number,
                    "movement_ids": [m.id for m in movimientos],
                    "kg": str(sum(m.quantity_kg for m in movimientos)),
                    "stock_override_reason": motivo or None,
                },
            )
        return movimientos

    def reverse(self, budget: Budget, *, reason: str | None = None) -> list[StockMovement]:
        """Devuelve la mercaderia al anular un presupuesto manual.

        No borra nada: deja el movimiento de salida y su contrario, con el motivo
        de la anulacion. Es lo mismo que hace el despacho con la orden emitida.
        """
        budget = Budget.get_by_id(budget.id)
        prefix = dispatch_source_prefix(budget.id)

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
            f"Anulación del presupuesto {budget.display_number}"
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
                record_ref=f"Budget:{budget.id}",
                new_value={
                    "budget_number": budget.budget_number,
                    "reversal_ids": [m.id for m in reversas],
                },
            )
        return reversas
