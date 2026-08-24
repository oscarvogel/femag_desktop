from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client
from app.reports.managerial_dashboard import DEFAULT_CURRENCY, ManagerialDashboardService


@dataclass(frozen=True)
class AccountRiskFilters:
    as_of: date
    client_id: int | None = None
    debt_state: str = "all"
    due_window_days: int | None = None


@dataclass(frozen=True)
class AccountRiskTotals:
    balance: float
    overdue: float
    due_7: float
    due_15: float
    due_30: float
    clients_with_debt: int
    clients_overdue: int


@dataclass(frozen=True)
class AccountRiskReportResult:
    filters: AccountRiskFilters
    rows: tuple[dict, ...]
    totals: AccountRiskTotals
    currency: str


class ManagerialAccountRiskService:
    """Consolidated client-account exposure for managerial reporting.

    FEMAG does not yet allocate payments to individual documents. For that
    reason, positive due documents are consumed against the current positive
    client balance from oldest to newest. This keeps overdue/future buckets
    mutually exclusive and consistent with the dashboard's conservative cap.
    Reversed source documents are removed from the due-document pool while the
    signed reversal itself continues affecting the account balance exactly once.
    """

    VALID_STATES = {"all", "with_debt", "without_debt", "overdue"}

    def __init__(self, *, currency: str = DEFAULT_CURRENCY) -> None:
        self.currency = currency

    def report(self, filters: AccountRiskFilters) -> AccountRiskReportResult:
        if filters.debt_state not in self.VALID_STATES:
            raise ValueError(f"Estado de deuda desconocido: {filters.debt_state!r}")
        rows = [self._client_row(client, filters.as_of) for client in Client.select().order_by(Client.name)]
        rows = [row for row in rows if self._matches(row, filters)]
        rows.sort(key=lambda row: (row["overdue"], row["balance"], row["client_name"].casefold()), reverse=True)
        return AccountRiskReportResult(
            filters=filters,
            rows=tuple(rows),
            totals=self._totals(rows),
            currency=self.currency,
        )

    def _client_row(self, client: Client, as_of: date) -> dict:
        movements = list(
            ClientAccountMovement.select()
            .where(
                ClientAccountMovement.client == client,
                ClientAccountMovement.currency == self.currency,
                (ClientAccountMovement.movement_date.is_null(True))
                | (ClientAccountMovement.movement_date <= as_of),
            )
            .order_by(ClientAccountMovement.due_date, ClientAccountMovement.id)
        )
        raw_balance = round(sum(float(m.total_amount or 0) for m in movements), 2)
        balance = max(raw_balance, 0.0)

        reversed_ids = {
            int(m.reverses_id)
            for m in movements
            if m.is_reversal and m.reverses_id is not None
        }
        positive_docs = [
            m
            for m in movements
            if float(m.total_amount or 0) > 0
            and m.due_date is not None
            and m.id not in reversed_ids
        ]
        positive_docs.sort(key=lambda m: (m.due_date, m.id))

        remaining = balance
        overdue = due_7 = due_15 = due_30 = 0.0
        oldest_unpaid_due = None
        max_days_overdue = 0
        for movement in positive_docs:
            if remaining <= 0:
                break
            exposed = min(float(movement.total_amount or 0), remaining)
            remaining -= exposed
            due = movement.due_date
            delta = (due - as_of).days
            if delta < 0:
                overdue += exposed
                if oldest_unpaid_due is None or due < oldest_unpaid_due:
                    oldest_unpaid_due = due
                max_days_overdue = max(max_days_overdue, -delta)
            elif delta <= 7:
                due_7 += exposed
                due_15 += exposed
                due_30 += exposed
            elif delta <= 15:
                due_15 += exposed
                due_30 += exposed
            elif delta <= 30:
                due_30 += exposed

        due_7 = round(due_7, 2)
        due_15 = round(due_15, 2)
        due_30 = round(due_30, 2)
        overdue = round(overdue, 2)
        due_future = round(max(balance - overdue, 0.0), 2)

        credit_limit = getattr(client, "limite_credito", None)
        try:
            credit_limit = float(credit_limit) if credit_limit not in (None, "") else None
        except (TypeError, ValueError):
            credit_limit = None
        available_credit = None if credit_limit is None else round(max(credit_limit - balance, 0.0), 2)
        credit_usage_pct = None
        exceeded = False
        near_limit = False
        if credit_limit is not None and credit_limit > 0:
            credit_usage_pct = round((balance / credit_limit) * 100.0, 1)
            exceeded = balance > credit_limit
            near_limit = not exceeded and credit_usage_pct >= 80.0

        return {
            "client_id": client.id,
            "client_name": client.name,
            "balance": round(balance, 2),
            "overdue": overdue,
            "due_future": due_future,
            "due_7": due_7,
            "due_15": due_15,
            "due_30": due_30,
            "max_days_overdue": max_days_overdue,
            "oldest_unpaid_due": oldest_unpaid_due,
            "credit_limit": credit_limit,
            "available_credit": available_credit,
            "credit_usage_pct": credit_usage_pct,
            "credit_exceeded": exceeded,
            "credit_near_limit": near_limit,
        }

    @staticmethod
    def _matches(row: dict, filters: AccountRiskFilters) -> bool:
        if filters.client_id is not None and row["client_id"] != filters.client_id:
            return False
        if filters.debt_state == "with_debt" and row["balance"] <= 0:
            return False
        if filters.debt_state == "without_debt" and row["balance"] > 0:
            return False
        if filters.debt_state == "overdue" and row["overdue"] <= 0:
            return False
        if filters.due_window_days is not None:
            key = {7: "due_7", 15: "due_15", 30: "due_30"}.get(filters.due_window_days)
            if key is None:
                raise ValueError("La ventana de vencimiento debe ser 7, 15 o 30 días.")
            if row[key] <= 0:
                return False
        return True

    @staticmethod
    def _totals(rows: list[dict]) -> AccountRiskTotals:
        return AccountRiskTotals(
            balance=round(sum(row["balance"] for row in rows), 2),
            overdue=round(sum(row["overdue"] for row in rows), 2),
            due_7=round(sum(row["due_7"] for row in rows), 2),
            due_15=round(sum(row["due_15"] for row in rows), 2),
            due_30=round(sum(row["due_30"] for row in rows), 2),
            clients_with_debt=sum(1 for row in rows if row["balance"] > 0),
            clients_overdue=sum(1 for row in rows if row["overdue"] > 0),
        )

    def dashboard_totals(self, *, as_of: date) -> tuple[float, float]:
        dashboard = ManagerialDashboardService(currency=self.currency)
        return dashboard.total_receivables(), dashboard.overdue_receivables(as_of=as_of)
