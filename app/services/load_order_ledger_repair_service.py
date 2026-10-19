"""Reparación de órdenes de carga emitidas sin cuenta corriente ni salida de stock.

Una emisión de orden de carga deja tres efectos: el estado "Emitida", el
movimiento en la cuenta corriente del cliente y el descuento de stock. Desde
#726 esos tres efectos van en una sola transacción, así que **no puede volver a
pasar** que una orden quede emitida sin registrar.

Este servicio existe para las órdenes que ya quedaron a medias antes del
arranque de la garantía (OC-000078 y OC-000081 en producción): la mercadería
salió de la planta, pero no quedó registrada ni en la cuenta corriente ni en el
stock. Repararlas **no rehace la operación física**: se reponen los dos libros
con los mismos servicios que usa la emisión, que son idempotentes.

No cambia importes: los movimientos salen del presupuesto ya emitido, que es la
fuente de verdad del sistema.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config.database import database_proxy
from app.models.budgets import Budget
from app.models.load_orders import LoadOrder
from app.models.stock import StockMovement
from app.services.account_ledger_service import AccountLedgerService
from app.services.audit_service import AuditService
from app.services.load_order_stock_service import (
    LoadOrderStockService,
    dispatch_source_prefix,
)

#: Estados de orden que pueden tener movimientos de cuenta corriente vivos.
#: Las anuladas no se tocan: sus movimientos fueron revertidos.
REPAIRABLE_STATUSES = (LoadOrder.STATUS_ISSUED, LoadOrder.STATUS_CLOSED)

ACTION_REPAIR = "reparar_cuenta_corriente"


@dataclass(frozen=True)
class LedgerGap:
    """Un presupuesto de la orden al que le falta su movimiento."""

    budget_id: int
    budget_number: str
    client_id: int
    client_name: str
    timing: str
    total_amount: float


@dataclass(frozen=True)
class OrderLedgerGap:
    """Todo lo que falta registrar de una orden."""

    order_id: int
    order_number: int
    status: str
    date: str
    ledger_gaps: tuple[LedgerGap, ...] = ()
    missing_stock: bool = False
    stock_units: int = 0
    stock_kg: float = 0.0

    @property
    def is_repairable(self) -> bool:
        """Hay algo que reparar en esta orden."""
        return bool(self.ledger_gaps) or self.missing_stock

    @property
    def order_reference(self) -> str:
        return f"OC-{self.order_number:06d}"

    @property
    def total_amount(self) -> float:
        return sum(gap.total_amount for gap in self.ledger_gaps)

    def summary(self) -> str:
        """Resumen de una línea para tablas y listados."""
        partes = []
        if self.ledger_gaps:
            partes.append(f"{len(self.ledger_gaps)} documento(s) sin registrar")
        if self.missing_stock:
            partes.append(f"stock sin descontar ({self.stock_units} un / {self.stock_kg:,.0f} kg)")
        return " · ".join(partes) or "Sin faltantes"


@dataclass(frozen=True)
class RepairResult:
    """Qué se reparó de una orden."""

    order_id: int
    order_number: int
    movement_ids: tuple[int, ...] = ()
    stock_movement_ids: tuple[int, ...] = ()
    created_movement_ids: tuple[int, ...] = field(default_factory=tuple)

    @property
    def order_reference(self) -> str:
        return f"OC-{self.order_number:06d}"


class LoadOrderLedgerRepairService:
    """Detecta y repara órdenes emitidas a medias.

    Es idempotente: una orden ya reparada no se toca, no genera un segundo
    movimiento y no duplica el ``AuditLog``.
    """

    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()
        self.ledger = AccountLedgerService(
            current_user=current_user, audit_service=self.audit_service
        )
        self.stock = LoadOrderStockService(
            current_user=current_user, audit_service=self.audit_service
        )

    # -- Detección ---------------------------------------------------------
    def ledger_gaps_by_order(self) -> dict[int, list[LedgerGap]]:
        """Documentos sin movimiento, agrupados por orden.

        Consulta barata (tres queries) para poder usarla en la barra de avisos
        y en el botón de la pantalla sin abrir el diálogo.
        """
        from app.models.accounting import ClientAccountMovement

        orders = {
            o.id: o
            for o in LoadOrder.select().where(LoadOrder.status.in_(REPAIRABLE_STATUSES))
        }
        if not orders:
            return {}
        order_ids = list(orders)
        budgets = list(
            Budget.select().where(
                (Budget.load_order << order_ids)
                & (Budget.origin == Budget.ORIGIN_LOAD_ORDER)
            )
        )
        if not budgets:
            return {}

        budget_ids = [b.id for b in budgets]
        vinculados = {
            m.source_ref
            for m in ClientAccountMovement.select().where(
                ClientAccountMovement.source_ref
                << [f"Budget:{budget_id}" for budget_id in budget_ids]
            )
        }
        legacy = {
            (m.load_order_id, m.client_id, m.movement_type)
            for m in ClientAccountMovement.select().where(
                (ClientAccountMovement.load_order << order_ids)
                & (ClientAccountMovement.is_reversal == False)  # noqa: E712
            )
        }

        agrupado: dict[int, list[LedgerGap]] = {}
        for budget in budgets:
            if f"Budget:{budget.id}" in vinculados:
                continue
            tipo = (
                ClientAccountMovement.TYPE_LOAD_ORDER_IMMEDIATE
                if budget.timing == Budget.TIMING_IMMEDIATE
                else ClientAccountMovement.TYPE_LOAD_ORDER_DEFERRED
            )
            if (budget.load_order_id, budget.client_id, tipo) in legacy:
                continue
            cliente = budget.client
            agrupado.setdefault(budget.load_order_id, []).append(
                LedgerGap(
                    budget_id=budget.id,
                    budget_number=budget.display_number,
                    client_id=cliente.id,
                    client_name=cliente.name,
                    timing=budget.timing,
                    total_amount=float(budget.total_amount or 0),
                )
            )
        return agrupado

    def count_broken_orders(self) -> int:
        """Cuántas órdenes emitidas o cerradas están sin cuenta corriente.

        Cuenta **órdenes**, no documentos: es la unidad que el administrador
        tiene que resolver.
        """
        return len(self.ledger_gaps_by_order())

    def find_orders_missing_ledger(self) -> list[OrderLedgerGap]:
        """Órdenes emitidas sin movimiento en la cuenta corriente.

        No incluye el análisis de stock: es la lista para la alarma y para el
        botón, donde alcanza con saber qué documento falta.
        """
        from app.models.load_orders import LoadOrder as _LoadOrder

        agrupado = self.ledger_gaps_by_order()
        out: list[OrderLedgerGap] = []
        for order_id, gaps in agrupado.items():
            order = _LoadOrder.get_by_id(order_id)
            out.append(
                OrderLedgerGap(
                    order_id=order.id,
                    order_number=int(order.order_number),
                    status=order.status,
                    date=str(order.date),
                    ledger_gaps=tuple(gaps),
                    missing_stock=False,
                    stock_units=0,
                    stock_kg=0.0,
                )
            )
        return sorted(out, key=lambda f: f.order_number)

    def find_broken_orders(self) -> list[OrderLedgerGap]:
        """Todas las órdenes emitidas o cerradas con faltantes. No escribe nada."""
        findings = []
        for order in (
            LoadOrder.select()
            .where(LoadOrder.status.in_(REPAIRABLE_STATUSES))
            .order_by(LoadOrder.order_number)
        ):
            finding = self.find_gap(order)
            if finding.is_repairable:
                findings.append(finding)
        return findings

    def find_gap(self, order: LoadOrder) -> OrderLedgerGap:
        """Qué le falta registrar a una orden. No escribe nada."""
        order = LoadOrder.get_by_id(order.id)
        gaps: list[LedgerGap] = []
        for budget in self._budgets_of(order):
            if (
                self._movement_of_budget(budget.id) is not None
                or self._legacy_movement_of(order, budget) is not None
            ):
                continue
            cliente = budget.client
            gaps.append(
                LedgerGap(
                    budget_id=budget.id,
                    budget_number=budget.display_number,
                    client_id=cliente.id,
                    client_name=cliente.name,
                    timing=budget.timing,
                    total_amount=float(budget.total_amount or 0),
                )
            )

        plan = self.stock.plan_dispatch(order)
        despachos = self._dispatch_movements(order.id)
        unidades = int(sum(float(unidades) for _producto, unidades, _kilos in plan))
        kilos = float(sum(float(kilos) for _producto, _unidades, kilos in plan))

        # El faltante de stock sólo se marca si la orden ALSO perdió la cuenta
        # corriente: las órdenes anteriores al cambio que descuenta la
        # mercadería al emitir (y no al cerrar) no tienen movimientos de stock
        # por orden, y no es lo que esta herramienta repara. Marcarlas sería un
        # falso positivo que, al reparar, descontaría dos veces la mercadería.
        falta_stock = bool(plan) and not despachos and bool(gaps)

        return OrderLedgerGap(
            order_id=order.id,
            order_number=int(order.order_number),
            status=order.status,
            date=str(order.date),
            ledger_gaps=tuple(gaps),
            missing_stock=falta_stock,
            stock_units=unidades if falta_stock else 0,
            stock_kg=kilos if falta_stock else 0.0,
        )

    def can_repair(self, order: LoadOrder) -> bool:
        """Si a esta orden se le puede reparar algo."""
        return LoadOrder.get_by_id(order.id).status in REPAIRABLE_STATUSES

    # -- Reparación --------------------------------------------------------
    def repair(self, order: LoadOrder) -> RepairResult:
        """Repara UNA orden en una sola transacción.

        Usa los mismos servicios que la emisión, que son idempotentes: si el
        movimiento o el descuento ya estaban, no se duplican. Cualquier
        excepción revierte todo, incluida la auditoría.
        """
        order = LoadOrder.get_by_id(order.id)
        if order.status not in REPAIRABLE_STATUSES:
            raise ValueError(
                f"La {order.load_order_reference or 'orden'} esta en estado {order.status}: "
                f"solo se reparan ordenes {' y '.join(REPAIRABLE_STATUSES)}."
            )

        with database_proxy.atomic():
            gap = self.find_gap(order)
            movimientos = []
            despachos = []
            if gap.ledger_gaps:
                movimientos = self.ledger.generate_for_load_order(order)
            if gap.missing_stock:
                despachos = self.stock.register_dispatch(order)
            self.audit_service.record(
                user=self.current_user,
                module="Ordenes de carga",
                action=ACTION_REPAIR,
                record_ref=f"LoadOrder:{order.id}",
                new_value={
                    "order_number": int(order.order_number),
                    "movement_ids": [m.id for m in movimientos],
                    "stock_movement_ids": [m.id for m in despachos],
                },
                observation="Reparacion de emision parcial de cuenta corriente y stock (#726)",
            )

        return RepairResult(
            order_id=order.id,
            order_number=int(order.order_number),
            movement_ids=tuple(m.id for m in movimientos),
            stock_movement_ids=tuple(m.id for m in despachos),
        )

    # -- Internos ----------------------------------------------------------
    @staticmethod
    def _budgets_of(order: LoadOrder) -> list[Budget]:
        return list(
            Budget.select()
            .where(
                (Budget.load_order == order)
                & (Budget.origin == Budget.ORIGIN_LOAD_ORDER)
            )
            .order_by(Budget.id)
        )

    @staticmethod
    def _movement_of_budget(budget_id: int):
        from app.models.accounting import ClientAccountMovement

        return (
            ClientAccountMovement.select()
            .where(
                (ClientAccountMovement.source_ref == f"Budget:{budget_id}")
                & (ClientAccountMovement.is_reversal == False)  # noqa: E712
            )
            .order_by(ClientAccountMovement.id)
            .first()
        )

    @staticmethod
    def _legacy_movement_of(order: LoadOrder, budget: Budget):
        """Movimiento de la era previa al vínculo con el presupuesto.

        Las órdenes anteriores a #6xx registraron el movimiento con
        ``source_ref = 'LoadOrder:<id>'`` y sin vínculo al presupuesto. Si no se
        los reconociera, toda orden vieja aparecería como si no tuviera cuenta
        corriente.
        """
        from app.models.accounting import ClientAccountMovement

        tipo = (
            ClientAccountMovement.TYPE_LOAD_ORDER_IMMEDIATE
            if budget.timing == Budget.TIMING_IMMEDIATE
            else ClientAccountMovement.TYPE_LOAD_ORDER_DEFERRED
        )
        return (
            ClientAccountMovement.select()
            .where(
                (ClientAccountMovement.load_order == order)
                & (ClientAccountMovement.client == budget.client)
                & (ClientAccountMovement.movement_type == tipo)
                & (ClientAccountMovement.is_reversal == False)  # noqa: E712
            )
            .order_by(ClientAccountMovement.id)
            .first()
        )

    @staticmethod
    def _dispatch_movements(order_id: int) -> list[StockMovement]:
        return list(
            StockMovement.select().where(
                StockMovement.source_ref.startswith(f"{dispatch_source_prefix(order_id)}:")
            )
        )
