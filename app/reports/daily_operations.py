from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from peewee import fn

from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrder
from app.reports.daily_collections import (
    DailyCollectionsFilters,
    DailyCollectionsReportService,
)
from app.reports.managerial_sales_dispatch import (
    ManagerialSalesDispatchService,
    SalesDispatchFilters,
)
from app.reports.pending_orders_aging import (
    PendingOrdersAgingService,
    PendingOrdersFilters,
)


@dataclass(frozen=True)
class DailyOperationsFilters:
    start: date
    end: date
    status: str | None = None
    client_id: int | None = None
    carrier_id: int | None = None

    @classmethod
    def today(cls) -> "DailyOperationsFilters":
        current = date.today()
        return cls(current, current)

    @classmethod
    def yesterday(cls) -> "DailyOperationsFilters":
        current = date.today() - timedelta(days=1)
        return cls(current, current)

    @classmethod
    def last_7_days(cls) -> "DailyOperationsFilters":
        current = date.today()
        return cls(current - timedelta(days=6), current)

    @classmethod
    def month_to_date(cls) -> "DailyOperationsFilters":
        current = date.today()
        return cls(current.replace(day=1), current)


@dataclass(frozen=True)
class DailyOperationsTotals:
    created: int
    pending: int
    issued: int
    closed: int
    annulled: int
    open_orders: int
    over_7_days: int
    incomplete_merchandise: int
    traceability_pending: int
    pending_closure: int
    dispatched_orders: int
    dispatched_total: float
    dispatched_tonnes: float
    clients_served: int
    collected: float
    collection_payments: int
    manual_debit: float
    manual_credit: float
    manual_movements: int


@dataclass(frozen=True)
class DailyOperationsResult:
    filters: DailyOperationsFilters
    totals: DailyOperationsTotals
    status_breakdown: tuple[dict, ...]
    dispatch_rows: tuple[dict, ...]
    pending_rows: tuple[dict, ...]


class DailyOperationsService:
    """Operational daily view for Administración/Secretaría.

    It composes the existing auditable services instead of duplicating
    formulas: pending/aging, sales/dispatch detail and collections.
    Only the period status counts and the manual debit/credit summary
    are computed here.
    """

    MANUAL_TYPES = (
        ClientAccountMovement.TYPE_MANUAL_DEBIT,
        ClientAccountMovement.TYPE_MANUAL_CREDIT,
    )

    def report(self, filters: DailyOperationsFilters) -> DailyOperationsResult:
        if filters.start > filters.end:
            raise ValueError("La fecha desde no puede ser posterior a la fecha hasta.")

        status_breakdown = self._status_breakdown(filters)
        counts = {row["status"]: row["count"] for row in status_breakdown}

        pending = PendingOrdersAgingService().report(
            PendingOrdersFilters(
                status=filters.status,
                client_id=filters.client_id,
                carrier_id=filters.carrier_id,
            ),
            today=filters.end,
        )
        dispatch = ManagerialSalesDispatchService().report(
            SalesDispatchFilters(
                start=filters.start,
                end=filters.end,
                client_id=filters.client_id,
                carrier_id=filters.carrier_id,
            )
        )
        collections = DailyCollectionsReportService().report(
            DailyCollectionsFilters(
                start=filters.start,
                end=filters.end,
                client_id=filters.client_id,
            )
        )
        manuals = self._manual_summary(filters)

        dispatch_rows = tuple(dispatch.rows)
        if filters.status is not None:
            dispatch_rows = tuple(
                row for row in dispatch_rows if row["status"] == filters.status
            )

        return DailyOperationsResult(
            filters=filters,
            totals=DailyOperationsTotals(
                created=sum(counts.values()),
                pending=counts.get(LoadOrder.STATUS_PENDING, 0)
                + counts.get(LoadOrder.STATUS_LEGACY_DRAFT, 0),
                issued=counts.get(LoadOrder.STATUS_ISSUED, 0),
                closed=counts.get(LoadOrder.STATUS_CLOSED, 0),
                annulled=counts.get(LoadOrder.STATUS_ANNULLED, 0),
                open_orders=pending.totals.open_orders,
                over_7_days=pending.totals.over_7_days,
                incomplete_merchandise=pending.totals.incomplete_pallets,
                traceability_pending=pending.totals.incomplete_traceability,
                pending_closure=pending.totals.pending_closure,
                dispatched_orders=dispatch.totals.orders,
                dispatched_total=dispatch.totals.total,
                dispatched_tonnes=dispatch.totals.tonnes,
                clients_served=len({row["client_id"] for row in dispatch.rows}),
                collected=collections.totals.collected,
                collection_payments=collections.totals.active_payments,
                manual_debit=manuals["debit"],
                manual_credit=manuals["credit"],
                manual_movements=manuals["movements"],
            ),
            status_breakdown=tuple(status_breakdown),
            dispatch_rows=dispatch_rows,
            pending_rows=pending.rows,
        )

    def _status_breakdown(self, filters: DailyOperationsFilters) -> list[dict]:
        query = LoadOrder.select(
            LoadOrder.status, fn.COUNT(LoadOrder.id).alias("count")
        ).where(LoadOrder.date.between(filters.start, filters.end))
        if filters.client_id is not None:
            query = query.where(LoadOrder.client == filters.client_id)
        if filters.carrier_id is not None:
            query = query.where(LoadOrder.carrier == filters.carrier_id)
        query = query.group_by(LoadOrder.status).order_by(LoadOrder.status)
        return [{"status": row["status"], "count": int(row["count"] or 0)} for row in query.dicts()]

    def _manual_summary(self, filters: DailyOperationsFilters) -> dict[str, float]:
        query = ClientAccountMovement.select().where(
            ClientAccountMovement.movement_type.in_(self.MANUAL_TYPES),
            ClientAccountMovement.movement_date.between(filters.start, filters.end),
        )
        if filters.client_id is not None:
            query = query.where(ClientAccountMovement.client == filters.client_id)
        debit = 0.0
        credit = 0.0
        movements = 0
        for movement in query:
            total = round(float(movement.total_amount or 0), 2)
            debit += max(total, 0.0)
            credit += max(-total, 0.0)
            movements += 1
        return {"debit": round(debit, 2), "credit": round(credit, 2), "movements": movements}
