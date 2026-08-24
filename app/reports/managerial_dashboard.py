from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from peewee import fn

from app.config.database import database_proxy
from app.models.accounting import ClientAccountMovement
from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.models.masters import Client, Product


DEFAULT_EFFECTIVE_ORDER_STATUSES = (LoadOrder.STATUS_CLOSED,)
DEFAULT_CURRENCY = "ARS"


@dataclass(frozen=True)
class ReportPeriod:
    start: date
    end: date
    label: str = "Personalizado"

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("La fecha hasta no puede ser anterior a la fecha desde.")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def previous_equivalent(self) -> "ReportPeriod":
        previous_end = self.start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=self.days - 1)
        return ReportPeriod(previous_start, previous_end, "Período anterior")

    @classmethod
    def preset(cls, key: str, *, today: date | None = None) -> "ReportPeriod":
        current = today or date.today()
        normalized = key.strip().lower().replace("_", " ")
        if normalized in {"hoy", "today"}:
            return cls(current, current, "Hoy")
        if normalized in {"este mes", "mes actual", "current month"}:
            return cls(current.replace(day=1), current, "Este mes")
        if normalized in {"mes anterior", "previous month"}:
            first_this_month = current.replace(day=1)
            end = first_this_month - timedelta(days=1)
            return cls(end.replace(day=1), end, "Mes anterior")
        if normalized in {"este año", "ano actual", "año actual", "current year"}:
            return cls(date(current.year, 1, 1), current, "Este año")
        raise ValueError(f"Período predefinido desconocido: {key!r}.")


@dataclass(frozen=True)
class MetricComparison:
    current: float
    previous: float

    @property
    def variation_percent(self) -> float | None:
        if self.previous == 0:
            return None if self.current != 0 else 0.0
        return round(((self.current - self.previous) / abs(self.previous)) * 100, 1)


@dataclass(frozen=True)
class ManagerialSnapshot:
    period: ReportPeriod
    previous_period: ReportPeriod
    valued_dispatches: MetricComparison
    tonnes: MetricComparison
    orders: MetricComparison
    average_ticket: MetricComparison
    total_receivables: float
    overdue_receivables: float
    monthly_evolution: tuple[dict, ...]
    top_clients: tuple[dict, ...]
    top_products: tuple[dict, ...]
    order_statuses: tuple[dict, ...]
    effective_statuses: tuple[str, ...]
    currency: str


class ManagerialDashboardService:
    """Central source of truth for the first managerial dashboard.

    V1 considers only closed load orders as effective dispatches by default.
    Physical pallet/loose allocations are the primary source for dispatched
    kilos. Any quantity not physically allocated falls back to the product's
    configured unit weight, so partial preparation is not double counted.
    """

    def __init__(
        self,
        *,
        effective_statuses: Iterable[str] = DEFAULT_EFFECTIVE_ORDER_STATUSES,
        currency: str = DEFAULT_CURRENCY,
    ) -> None:
        self.effective_statuses = tuple(effective_statuses)
        if not self.effective_statuses:
            raise ValueError("Debe existir al menos un estado efectivo para el dashboard.")
        self.currency = currency

    def snapshot(self, period: ReportPeriod) -> ManagerialSnapshot:
        previous = period.previous_equivalent()
        current = self._period_metrics(period)
        before = self._period_metrics(previous)
        return ManagerialSnapshot(
            period=period,
            previous_period=previous,
            valued_dispatches=MetricComparison(current["valued_dispatches"], before["valued_dispatches"]),
            tonnes=MetricComparison(current["tonnes"], before["tonnes"]),
            orders=MetricComparison(current["orders"], before["orders"]),
            average_ticket=MetricComparison(current["average_ticket"], before["average_ticket"]),
            total_receivables=self.total_receivables(),
            overdue_receivables=self.overdue_receivables(as_of=period.end),
            monthly_evolution=tuple(self.monthly_evolution(period.end, months=12)),
            top_clients=tuple(self.top_clients(period)),
            top_products=tuple(self.top_products(period)),
            order_statuses=tuple(self.order_status_distribution(period)),
            effective_statuses=self.effective_statuses,
            currency=self.currency,
        )

    def _period_metrics(self, period: ReportPeriod) -> dict[str, float]:
        if database_proxy.obj is None:
            return {"valued_dispatches": 0.0, "tonnes": 0.0, "orders": 0.0, "average_ticket": 0.0}

        order_filter = self._effective_order_filter(period)
        order_count = LoadOrder.select().where(order_filter).count()
        total = (
            LoadOrderProduct.select(fn.COALESCE(fn.SUM(LoadOrderProduct.total), 0))
            .join(LoadOrder)
            .where(order_filter)
            .scalar()
        )
        valued_dispatches = round(float(total or 0), 2)
        tonnes = round(self._dispatch_kilos(period) / 1000.0, 3)
        average_ticket = round(valued_dispatches / order_count, 2) if order_count else 0.0
        return {
            "valued_dispatches": valued_dispatches,
            "tonnes": tonnes,
            "orders": float(order_count),
            "average_ticket": average_ticket,
        }

    def _dispatch_line_rows(self, period: ReportPeriod) -> list[dict]:
        if database_proxy.obj is None:
            return []
        return list(
            LoadOrderProduct.select(
                LoadOrderProduct.order.alias("order_id"),
                LoadOrderProduct.destination.alias("destination_id"),
                LoadOrderProduct.product.alias("product_id"),
                LoadOrderProduct.quantity.alias("quantity"),
                LoadOrderProduct.total.alias("total"),
                Product.name.alias("product_name"),
                Product.peso_unitario_kg.alias("fallback_weight"),
                Client.id.alias("client_id"),
                Client.name.alias("client_name"),
            )
            .join(LoadOrder)
            .switch(LoadOrderProduct)
            .join(Product)
            .switch(LoadOrderProduct)
            .join(LoadOrderDestination, on=(LoadOrderProduct.destination == LoadOrderDestination.id))
            .join(Client, on=(LoadOrderDestination.client == Client.id))
            .where(self._effective_order_filter(period))
            .dicts()
        )

    def _physical_allocations(self, period: ReportPeriod) -> dict[tuple[int, int, int], dict[str, float]]:
        physical: dict[tuple[int, int, int], dict[str, float]] = defaultdict(
            lambda: {"quantity": 0.0, "kilos": 0.0}
        )
        order_filter = self._effective_order_filter(period)

        pallet_rows = (
            LoadOrderPalletAllocation.select(
                LoadOrderPallet.order.alias("order_id"),
                LoadOrderPalletAllocation.destination.alias("destination_id"),
                LoadOrderPalletAllocation.product.alias("product_id"),
                LoadOrderPalletAllocation.quantity.alias("quantity"),
                LoadOrderPalletAllocation.peso_unitario_kg.alias("weight"),
            )
            .join(LoadOrderPallet)
            .join(LoadOrder)
            .where(order_filter)
            .dicts()
        )
        for row in pallet_rows:
            key = (int(row["order_id"]), int(row["destination_id"]), int(row["product_id"]))
            quantity = float(row["quantity"] or 0)
            weight = float(row["weight"] or 0)
            physical[key]["quantity"] += quantity
            physical[key]["kilos"] += quantity * weight

        loose_rows = (
            LoadOrderLooseAllocation.select(
                LoadOrderLooseAllocation.order.alias("order_id"),
                LoadOrderLooseAllocation.destination.alias("destination_id"),
                LoadOrderLooseAllocation.product.alias("product_id"),
                LoadOrderLooseAllocation.quantity.alias("quantity"),
                LoadOrderLooseAllocation.peso_unitario_kg.alias("weight"),
            )
            .join(LoadOrder)
            .where(order_filter)
            .dicts()
        )
        for row in loose_rows:
            key = (int(row["order_id"]), int(row["destination_id"]), int(row["product_id"]))
            quantity = float(row["quantity"] or 0)
            weight = float(row["weight"] or 0)
            physical[key]["quantity"] += quantity
            physical[key]["kilos"] += quantity * weight
        return physical

    def _dispatch_breakdown(self, period: ReportPeriod) -> list[dict]:
        physical = self._physical_allocations(period)
        rows: list[dict] = []
        for line in self._dispatch_line_rows(period):
            key = (int(line["order_id"]), int(line["destination_id"]), int(line["product_id"]))
            actual = physical.get(key, {"quantity": 0.0, "kilos": 0.0})
            line_quantity = max(float(line["quantity"] or 0), 0.0)
            physical_quantity = min(max(float(actual["quantity"]), 0.0), line_quantity)
            # If bad historical data allocates more than the ordered quantity,
            # keep the physical kilos but do not add a negative fallback.
            physical_kilos = max(float(actual["kilos"]), 0.0)
            remaining_quantity = max(line_quantity - physical_quantity, 0.0)
            fallback_weight = max(float(line["fallback_weight"] or 0), 0.0)
            rows.append(
                {
                    **line,
                    "kilos": physical_kilos + (remaining_quantity * fallback_weight),
                }
            )
        return rows

    def _dispatch_kilos(self, period: ReportPeriod) -> float:
        return round(sum(float(row["kilos"]) for row in self._dispatch_breakdown(period)), 3)

    def total_receivables(self) -> float:
        if database_proxy.obj is None:
            return 0.0
        total = (
            ClientAccountMovement.select(fn.COALESCE(fn.SUM(ClientAccountMovement.total_amount), 0))
            .where(ClientAccountMovement.currency == self.currency)
            .scalar()
        )
        return round(max(float(total or 0), 0.0), 2)

    def overdue_receivables(self, *, as_of: date | None = None) -> float:
        """Estimate overdue exposure with two grouped ledger queries.

        Payments are not allocated to individual documents yet. For each client,
        overdue positive documents are therefore capped by the client's current
        positive balance, preserving the existing conservative V1 rule without
        issuing N+1 queries.
        """
        if database_proxy.obj is None:
            return 0.0
        reference_date = as_of or date.today()
        balance_rows = (
            ClientAccountMovement.select(
                ClientAccountMovement.client.alias("client_id"),
                fn.COALESCE(fn.SUM(ClientAccountMovement.total_amount), 0).alias("balance"),
            )
            .where(ClientAccountMovement.currency == self.currency)
            .group_by(ClientAccountMovement.client)
            .dicts()
        )
        overdue_rows = (
            ClientAccountMovement.select(
                ClientAccountMovement.client.alias("client_id"),
                fn.COALESCE(fn.SUM(ClientAccountMovement.total_amount), 0).alias("overdue"),
            )
            .where(
                ClientAccountMovement.currency == self.currency,
                ClientAccountMovement.due_date.is_null(False),
                ClientAccountMovement.due_date < reference_date,
                ClientAccountMovement.total_amount > 0,
            )
            .group_by(ClientAccountMovement.client)
            .dicts()
        )
        balances = {int(row["client_id"]): max(float(row["balance"] or 0), 0.0) for row in balance_rows}
        overdue = {int(row["client_id"]): max(float(row["overdue"] or 0), 0.0) for row in overdue_rows}
        total = sum(min(balance, overdue.get(client_id, 0.0)) for client_id, balance in balances.items())
        return round(total, 2)

    def top_clients(self, period: ReportPeriod, *, limit: int = 10) -> list[dict]:
        aggregated: dict[int, dict] = {}
        for row in self._dispatch_breakdown(period):
            client_id = int(row["client_id"])
            target = aggregated.setdefault(
                client_id,
                {"client_id": client_id, "name": row["client_name"], "total": 0.0, "kilos": 0.0},
            )
            target["total"] += float(row["total"] or 0)
            target["kilos"] += float(row["kilos"] or 0)
        ordered = sorted(aggregated.values(), key=lambda row: row["total"], reverse=True)[:limit]
        return [
            {
                "client_id": row["client_id"],
                "name": row["name"],
                "total": round(row["total"], 2),
                "tonnes": round(row["kilos"] / 1000.0, 3),
            }
            for row in ordered
        ]

    def top_products(self, period: ReportPeriod, *, limit: int = 10) -> list[dict]:
        aggregated: dict[int, dict] = {}
        for row in self._dispatch_breakdown(period):
            product_id = int(row["product_id"])
            target = aggregated.setdefault(
                product_id,
                {"product_id": product_id, "name": row["product_name"], "total": 0.0, "kilos": 0.0},
            )
            target["total"] += float(row["total"] or 0)
            target["kilos"] += float(row["kilos"] or 0)
        ordered = sorted(aggregated.values(), key=lambda row: row["kilos"], reverse=True)[:limit]
        return [
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "total": round(row["total"], 2),
                "tonnes": round(row["kilos"] / 1000.0, 3),
            }
            for row in ordered
        ]

    def order_status_distribution(self, period: ReportPeriod) -> list[dict]:
        if database_proxy.obj is None:
            return []
        rows = (
            LoadOrder.select(LoadOrder.status, fn.COUNT(LoadOrder.id).alias("count"))
            .where(LoadOrder.date.between(period.start, period.end))
            .group_by(LoadOrder.status)
            .order_by(LoadOrder.status)
            .dicts()
        )
        return [{"status": row["status"], "count": int(row["count"] or 0)} for row in rows]

    def monthly_evolution(self, end: date, *, months: int = 12) -> list[dict]:
        if months <= 0:
            return []
        points: list[dict] = []
        year, month = end.year, end.month
        starts: list[date] = []
        for _ in range(months):
            starts.append(date(year, month, 1))
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        for start in reversed(starts):
            if start.month == 12:
                next_month = date(start.year + 1, 1, 1)
            else:
                next_month = date(start.year, start.month + 1, 1)
            month_end = min(next_month - timedelta(days=1), end)
            metrics = self._period_metrics(ReportPeriod(start, month_end, start.strftime("%m/%Y")))
            points.append(
                {
                    "period": start.strftime("%Y-%m"),
                    "label": start.strftime("%m/%Y"),
                    "total": metrics["valued_dispatches"],
                    "tonnes": metrics["tonnes"],
                    "orders": int(metrics["orders"]),
                }
            )
        return points

    def _effective_order_filter(self, period: ReportPeriod):
        return (
            LoadOrder.status.in_(self.effective_statuses)
            & LoadOrder.date.between(period.start, period.end)
        )
