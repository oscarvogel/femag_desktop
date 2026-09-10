from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.models.accounting import ClientAccountMovement


STATUS_OVERDUE = "Vencido"
STATUS_TODAY = "Vence hoy"
STATUS_NEXT_7 = "Próximos 7 días"
STATUS_NEXT_30 = "Próximos 30 días"
STATUS_FUTURE = "Futuro"


@dataclass(frozen=True)
class CollectionDueFilters:
    client_id: int | None = None
    due_from: date | None = None
    due_to: date | None = None
    status: str | None = None


@dataclass(frozen=True)
class CollectionDueTotals:
    overdue: float
    due_today: float
    next_7_days: float
    next_30_days: float
    filtered_total: float


@dataclass(frozen=True)
class CollectionDueResult:
    filters: CollectionDueFilters
    rows: tuple[dict, ...]
    totals: CollectionDueTotals


class CollectionDueReportService:
    STATUSES = (
        STATUS_OVERDUE,
        STATUS_TODAY,
        STATUS_NEXT_7,
        STATUS_NEXT_30,
        STATUS_FUTURE,
    )

    def report(
        self,
        filters: CollectionDueFilters,
        *,
        today: date | None = None,
    ) -> CollectionDueResult:
        if filters.due_from and filters.due_to and filters.due_from > filters.due_to:
            raise ValueError("La fecha desde no puede ser posterior a la fecha hasta.")

        today = today or date.today()
        query = ClientAccountMovement.select().where(
            ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_LOAD_ORDER,
            ClientAccountMovement.is_reversal == False,  # noqa: E712
            ClientAccountMovement.due_date.is_null(False),
        )
        if filters.client_id:
            query = query.where(ClientAccountMovement.client == filters.client_id)
        if filters.due_from:
            query = query.where(ClientAccountMovement.due_date >= filters.due_from)
        if filters.due_to:
            query = query.where(ClientAccountMovement.due_date <= filters.due_to)

        rows = []
        for movement in query.order_by(
            ClientAccountMovement.due_date,
            ClientAccountMovement.movement_date,
            ClientAccountMovement.id,
        ):
            if self._has_reversal(movement):
                continue
            status = self.status_for(movement.due_date, today=today)
            if filters.status and status != filters.status:
                continue
            delta_days = (movement.due_date - today).days
            rows.append(
                {
                    "movement_id": movement.id,
                    "client_id": movement.client_id,
                    "client_name": movement.client.name,
                    "load_order_id": movement.load_order_id,
                    "order_number": movement.load_order.order_number if movement.load_order_id else None,
                    "movement_date": movement.movement_date,
                    "due_date": movement.due_date,
                    "total_amount": round(float(movement.total_amount or 0), 2),
                    "delta_days": delta_days,
                    "status": status,
                }
            )

        totals = CollectionDueTotals(
            overdue=round(sum(row["total_amount"] for row in rows if row["due_date"] < today), 2),
            due_today=round(sum(row["total_amount"] for row in rows if row["due_date"] == today), 2),
            next_7_days=round(
                sum(row["total_amount"] for row in rows if today < row["due_date"] <= today + timedelta(days=7)),
                2,
            ),
            next_30_days=round(
                sum(row["total_amount"] for row in rows if today < row["due_date"] <= today + timedelta(days=30)),
                2,
            ),
            filtered_total=round(sum(row["total_amount"] for row in rows), 2),
        )
        return CollectionDueResult(filters=filters, rows=tuple(rows), totals=totals)

    @classmethod
    def status_for(cls, due_date: date, *, today: date) -> str:
        if due_date < today:
            return STATUS_OVERDUE
        if due_date == today:
            return STATUS_TODAY
        if due_date <= today + timedelta(days=7):
            return STATUS_NEXT_7
        if due_date <= today + timedelta(days=30):
            return STATUS_NEXT_30
        return STATUS_FUTURE

    @staticmethod
    def _has_reversal(movement: ClientAccountMovement) -> bool:
        return ClientAccountMovement.select().where(
            ClientAccountMovement.reverses == movement,
            ClientAccountMovement.is_reversal == True,  # noqa: E712
        ).exists()
