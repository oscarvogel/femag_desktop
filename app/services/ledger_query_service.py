from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from peewee import JOIN, Case, fn

from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrder
from app.models.masters import Client
from app.models.payments import ClientPayment


_MONEY_QUANTUM = Decimal("0.01")


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _movement_amount(movement: ClientAccountMovement) -> Decimal:
    return _money(movement.total_amount)


def _balance_from_movements(movements: Iterable[ClientAccountMovement]) -> Decimal:
    total = Decimal("0.00")
    for movement in movements:
        total += _movement_amount(movement)
    return total.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def client_balance(client: Client) -> float:
    """
    Return the client balance using the exact same movement stream used by the
    detail grid. This remains the reference implementation for callers that
    need a single client balance.
    """
    return float(_balance_from_movements(movements_for_client(client)))


def movements_for_client(client: Client) -> list[ClientAccountMovement]:
    """
    Load the chronological ledger once, including the relations needed by the
    detail grid so rendering does not trigger one query per movement.
    """
    return list(
        ClientAccountMovement.select(
            ClientAccountMovement,
            LoadOrder,
            ClientPayment,
        )
        .join(
            LoadOrder,
            JOIN.LEFT_OUTER,
            on=(ClientAccountMovement.load_order == LoadOrder.id),
        )
        .switch(ClientAccountMovement)
        .join(
            ClientPayment,
            JOIN.LEFT_OUTER,
            on=(ClientAccountMovement.payment == ClientPayment.id),
        )
        .where(ClientAccountMovement.client == client)
        .order_by(
            ClientAccountMovement.movement_date,
            ClientAccountMovement.created_at,
            ClientAccountMovement.id,
        )
    )


def client_portfolio_rows(
    *,
    salesperson_id: int | None = None,
    unassigned: bool = False,
    as_of: date | None = None,
) -> list[dict]:
    """Return the current client portfolio with one grouped movement query.

    Balance, overdue exposure and next-7-day exposure are aggregated together.
    This keeps the currency semantics used by the existing ledger while avoiding
    multiple full scans of ClientAccountMovement for the same snapshot.
    """

    reference_date = as_of or date.today()
    due_7_limit = reference_date + timedelta(days=7)
    rounded_amount = fn.ROUND(ClientAccountMovement.total_amount, 2)

    overdue_amount = Case(
        None,
        (
            (
                (ClientAccountMovement.total_amount > 0)
                & ClientAccountMovement.due_date.is_null(False)
                & (ClientAccountMovement.due_date < reference_date),
                ClientAccountMovement.total_amount,
            ),
        ),
        0,
    )
    due_7_amount = Case(
        None,
        (
            (
                (ClientAccountMovement.total_amount > 0)
                & ClientAccountMovement.due_date.is_null(False)
                & (ClientAccountMovement.due_date >= reference_date)
                & (ClientAccountMovement.due_date <= due_7_limit),
                ClientAccountMovement.total_amount,
            ),
        ),
        0,
    )

    rows_query = (
        Client.select(
            Client,
            fn.ROUND(
                fn.COALESCE(fn.SUM(rounded_amount), 0),
                2,
            ).alias("balance"),
            fn.COUNT(ClientAccountMovement.id).alias("movements"),
            fn.ROUND(
                fn.COALESCE(fn.SUM(overdue_amount), 0),
                2,
            ).alias("overdue_total"),
            fn.ROUND(
                fn.COALESCE(fn.SUM(due_7_amount), 0),
                2,
            ).alias("due_7_total"),
        )
        .join(
            ClientAccountMovement,
            JOIN.LEFT_OUTER,
            on=(ClientAccountMovement.client == Client.id),
        )
        .where(
            (Client.active == True)  # noqa: E712
            | ClientAccountMovement.id.is_null(False)
        )
        .group_by(Client)
    )
    rows_query = _filter_clients_by_salesperson(
        rows_query,
        salesperson_id=salesperson_id,
        unassigned=unassigned,
    )

    result: list[dict] = []
    for row in rows_query:
        balance = float(_money(row.balance))
        positive_balance = max(balance, 0.0)
        overdue_exposure = min(
            positive_balance,
            max(float(_money(row.overdue_total)), 0.0),
        )
        remaining = max(positive_balance - overdue_exposure, 0.0)
        due_7_exposure = min(
            remaining,
            max(float(_money(row.due_7_total)), 0.0),
        )
        result.append(
            {
                "client": row,
                "salesperson_id": row.salesperson_id,
                "balance": balance,
                "movements": int(row.movements or 0),
                "overdue": round(overdue_exposure, 2),
                "due_7": round(due_7_exposure, 2),
            }
        )

    result.sort(key=lambda entry: entry["balance"], reverse=True)
    return result


def _filter_clients_by_salesperson(
    query,
    *,
    salesperson_id: int | None,
    unassigned: bool,
):
    if unassigned:
        return query.where(Client.salesperson.is_null(True))
    if salesperson_id is not None:
        return query.where(Client.salesperson == salesperson_id)
    return query


def client_balances() -> list[dict]:
    """
    Build the left-side grid with one grouped SQL query.

    Monetary totals are rounded per movement to cents before SUM(), matching
    the Decimal/ROUND_HALF_UP accumulator used by the detail for values already
    persisted at currency precision. This avoids materializing the complete
    movement table in Python while keeping grid/header/detail aligned.
    """
    rounded_amount = fn.ROUND(ClientAccountMovement.total_amount, 2)
    rows = (
        Client.select(
            Client,
            fn.ROUND(
                fn.COALESCE(fn.SUM(rounded_amount), 0),
                2,
            ).alias("balance"),
            fn.COUNT(ClientAccountMovement.id).alias("movements"),
        )
        .join(
            ClientAccountMovement,
            on=(ClientAccountMovement.client == Client.id),
        )
        .group_by(Client)
    )

    result = [
        {
            "client": row,
            "balance": float(_money(row.balance)),
            "movements": int(row.movements or 0),
        }
        for row in rows
    ]
    result.sort(key=lambda entry: entry["balance"], reverse=True)
    return result


def running_balance(movements: Iterable[ClientAccountMovement]) -> list[float]:
    balances: list[float] = []
    running = Decimal("0.00")
    for movement in movements:
        running += _movement_amount(movement)
        running = running.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
        balances.append(float(running))
    return balances