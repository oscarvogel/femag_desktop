from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from peewee import fn

from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrder
from app.models.masters import Client
from app.models.payments import ClientPayment
from app.reports.lot_traceability import LotTraceabilityFilters, LotTraceabilityService
from app.reports.managerial_dashboard import DEFAULT_EFFECTIVE_ORDER_STATUSES
from app.reports.managerial_sales_dispatch import (
    ManagerialSalesDispatchService,
    SalesDispatchFilters,
)
from app.reports.returns_report import ReturnsFilters, ReturnsReportService


@dataclass(frozen=True)
class ManagerialClientsFilters:
    start: date
    end: date
    client_id: int | None = None
    active_only: bool = True
    has_overdue: bool = False
    activity: str | None = None  # "with" | "without" | None
    min_idle_days: int = 0
    has_balance: bool = False
    has_returns: bool = False
    has_lots: bool = False
    idle_threshold_days: int = 60
    sort_by: str = "total"
    descending: bool = True


@dataclass(frozen=True)
class ManagerialClientsTotals:
    clients: int
    with_activity: int
    without_activity: int
    new_clients: int
    recovered_clients: int
    total: float
    overdue: float


@dataclass(frozen=True)
class ManagerialClientsResult:
    filters: ManagerialClientsFilters
    totals: ManagerialClientsTotals
    rows: tuple[dict, ...]


class ManagerialClientsService:
    """Consolidated per-client report (issue #325).

    Commercial activity reuses the sales/dispatch breakdown, financial
    exposure reuses the dashboard conservative balance/overdue rule,
    returns reuse the returns report and lots reuse the traceability
    report. No formula is duplicated here.
    """

    SORT_KEYS = {
        "total": lambda row: row["period_total"],
        "tonnes": lambda row: row["period_tonnes"],
        "balance": lambda row: row["balance"],
        "overdue": lambda row: row["overdue"],
        "idle": lambda row: row["days_since_dispatch"] if row["days_since_dispatch"] is not None else -1,
        "name": lambda row: row["client_name"].casefold(),
    }

    def report(self, filters: ManagerialClientsFilters) -> ManagerialClientsResult:
        if filters.start > filters.end:
            raise ValueError("La fecha desde no puede ser posterior a la fecha hasta.")
        today = date.today()
        as_of = min(filters.end, today)

        dispatch = ManagerialSalesDispatchService().report(
            SalesDispatchFilters(start=filters.start, end=filters.end)
        )
        previous = self._previous_dispatch_clients(filters)
        lifetime = self._lifetime_dispatch()
        balances = self._balances()
        last_payments = self._last_payments()
        returns = self._returns_by_client()
        lots = self._lots_by_client()

        clients_query = Client.select()
        if filters.active_only:
            clients_query = clients_query.where(Client.active == True)  # noqa: E712
        if filters.client_id is not None:
            clients_query = clients_query.where(Client.id == filters.client_id)
        clients = {client.id: client for client in clients_query.order_by(Client.name)}

        period_by_client: dict[int, list[dict]] = defaultdict(list)
        for row in dispatch.rows:
            period_by_client[row["client_id"]].append(row)

        rows = []
        for client_id, client in clients.items():
            period_rows = period_by_client.get(client_id, [])
            period_total = round(sum(float(row["total"]) for row in period_rows), 2)
            period_kilos = round(sum(float(row["kilos"]) for row in period_rows), 3)
            period_orders = len({row["order_id"] for row in period_rows})
            first, last = lifetime.get(client_id, (None, None))
            days_idle = (as_of - last).days if last else None
            last_payment = last_payments.get(client_id)
            balance, overdue, days_overdue = balances.get(client_id, (0.0, 0.0, None))
            client_returns = returns.get(client_id, {"count": 0, "credit": 0.0})
            client_lots = lots.get(client_id, set())
            has_activity = period_total > 0 or period_orders > 0
            is_new = first is not None and filters.start <= first <= filters.end
            recovered = has_activity and client_id not in previous and not is_new and (
                first is not None and first < filters.start
            )
            row = {
                "client_id": client_id,
                "client_name": client.name,
                "active": bool(client.active),
                "period_total": period_total,
                "period_tonnes": round(period_kilos / 1000.0, 3),
                "period_orders": period_orders,
                "average_ticket": round(period_total / period_orders, 2) if period_orders else 0.0,
                "distinct_products": len({row["product_id"] for row in period_rows}),
                "distinct_lots": len(client_lots),
                "last_dispatch": last,
                "days_since_dispatch": days_idle,
                "last_payment": last_payment,
                "days_since_payment": (as_of - last_payment).days if last_payment else None,
                "balance": balance,
                "overdue": overdue,
                "days_overdue": days_overdue,
                "returns_count": client_returns["count"],
                "returns_credit": client_returns["credit"],
                "has_activity": has_activity,
                "is_new": is_new,
                "recovered": recovered,
                "idle": days_idle is not None and days_idle >= max(filters.idle_threshold_days, 0),
            }
            if self._matches(row, filters):
                rows.append(row)

        sort_key = self.SORT_KEYS.get(filters.sort_by, self.SORT_KEYS["total"])
        rows.sort(key=sort_key, reverse=filters.descending)
        return ManagerialClientsResult(
            filters=filters,
            totals=ManagerialClientsTotals(
                clients=len(rows),
                with_activity=sum(1 for row in rows if row["has_activity"]),
                without_activity=sum(1 for row in rows if not row["has_activity"]),
                new_clients=sum(1 for row in rows if row["is_new"]),
                recovered_clients=sum(1 for row in rows if row["recovered"]),
                total=round(sum(row["period_total"] for row in rows), 2),
                overdue=round(sum(row["overdue"] for row in rows), 2),
            ),
            rows=tuple(rows),
        )

    @staticmethod
    def _matches(row: dict, filters: ManagerialClientsFilters) -> bool:
        if filters.has_overdue and row["overdue"] <= 0:
            return False
        if filters.activity == "with" and not row["has_activity"]:
            return False
        if filters.activity == "without" and row["has_activity"]:
            return False
        if filters.min_idle_days > 0 and (
            row["days_since_dispatch"] is None or row["days_since_dispatch"] < filters.min_idle_days
        ):
            return False
        if filters.has_balance and row["balance"] <= 0:
            return False
        if filters.has_returns and row["returns_count"] <= 0:
            return False
        if filters.has_lots and row["distinct_lots"] <= 0:
            return False
        return True

    @staticmethod
    def _previous_dispatch_clients(filters: ManagerialClientsFilters) -> set[int]:
        days = (filters.end - filters.start).days + 1
        prev_end = filters.start - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days - 1)
        previous = ManagerialSalesDispatchService().report(
            SalesDispatchFilters(start=prev_start, end=prev_end)
        )
        return {row["client_id"] for row in previous.rows}

    @staticmethod
    def _lifetime_dispatch() -> dict[int, tuple[date | None, date | None]]:
        query = (
            LoadOrder.select(
                LoadOrder.client,
                fn.MIN(LoadOrder.date).alias("first"),
                fn.MAX(LoadOrder.date).alias("last"),
            )
            .where(
                LoadOrder.status.in_(DEFAULT_EFFECTIVE_ORDER_STATUSES),
                LoadOrder.client.is_null(False),
            )
            .group_by(LoadOrder.client)
            .dicts()
        )
        return {int(row["client"]): (row["first"], row["last"]) for row in query}

    @staticmethod
    def _balances() -> dict[int, tuple[float, float, int | None]]:
        today = date.today()
        balance_rows = (
            ClientAccountMovement.select(
                ClientAccountMovement.client.alias("client_id"),
                fn.COALESCE(fn.SUM(ClientAccountMovement.total_amount), 0).alias("balance"),
            )
            .group_by(ClientAccountMovement.client)
            .dicts()
        )
        overdue_rows = (
            ClientAccountMovement.select(
                ClientAccountMovement.client.alias("client_id"),
                fn.COALESCE(fn.SUM(ClientAccountMovement.total_amount), 0).alias("overdue"),
                fn.MIN(ClientAccountMovement.due_date).alias("oldest_due"),
            )
            .where(
                ClientAccountMovement.due_date.is_null(False),
                ClientAccountMovement.due_date < today,
                ClientAccountMovement.total_amount > 0,
            )
            .group_by(ClientAccountMovement.client)
            .dicts()
        )
        balances = {
            int(row["client_id"]): max(float(row["balance"] or 0), 0.0) for row in balance_rows
        }
        overdue = {
            int(row["client_id"]): (max(float(row["overdue"] or 0), 0.0), row["oldest_due"])
            for row in overdue_rows
        }
        result = {}
        for client_id, balance in balances.items():
            due, oldest = overdue.get(client_id, (0.0, None))
            capped = min(balance, due)
            days = (today - oldest).days if capped > 0 and oldest else None
            result[client_id] = (round(balance, 2), round(capped, 2), days)
        return result

    @staticmethod
    def _last_payments() -> dict[int, date]:
        query = (
            ClientPayment.select(
                ClientPayment.client.alias("client_id"),
                fn.MAX(ClientPayment.payment_date).alias("last"),
            )
            .where(ClientPayment.status == ClientPayment.STATUS_ACTIVE)
            .group_by(ClientPayment.client)
            .dicts()
        )
        return {int(row["client_id"]): row["last"] for row in query}

    @staticmethod
    def _returns_by_client() -> dict[int, dict]:
        result = ReturnsReportService().report(ReturnsFilters())
        aggregated: dict[int, dict] = defaultdict(lambda: {"count": 0, "credit": 0.0})
        for row in result.rows:
            if row["reversed"]:
                continue
            target = aggregated[int(row["client_id"])]
            target["count"] += 1
            target["credit"] += float(row["credit_amount"] or 0)
        return {
            client_id: {"count": item["count"], "credit": round(item["credit"], 2)}
            for client_id, item in aggregated.items()
        }

    @staticmethod
    def _lots_by_client() -> dict[int, set[str]]:
        result = LotTraceabilityService().report(LotTraceabilityFilters())
        grouped: dict[int, set[str]] = defaultdict(set)
        for row in result.rows:
            if row["client_id"] is not None and row["lote"]:
                grouped[int(row["client_id"])].add(row["lote"])
        return grouped
