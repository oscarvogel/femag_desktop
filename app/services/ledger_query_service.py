from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from peewee import JOIN, fn

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
    """Return the current client portfolio in three grouped queries at most.

    The seller filter is applied in SQL before materializing rows. Payments are
    not allocated to documents in FEMAG, so overdue and next-7-day exposure use
    the same conservative rule as the managerial dashboard: positive documents
    consume the client's current positive balance from oldest buckets first.
    """

    reference_date = as_of or date.today()
    rounded_amount = fn.ROUND(ClientAccountMovement.total_amount, 2)
    rows_query = (
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

    result = [
        {
            "client": row,
            "balance": float(_money(row.balance)),
            "movements": int(row.movements or 0),
            "overdue": 0.0,
            "due_7": 0.0,
        }
        for row in rows_query
    ]
    if not result:
        return []

    overdue = _positive_due_totals(
        due_before=reference_date,
        salesperson_id=salesperson_id,
        unassigned=unassigned,
    )
    due_7 = _positive_due_totals(
        due_from=reference_date,
        due_to=reference_date + timedelta(days=7),
        salesperson_id=salesperson_id,
        unassigned=unassigned,
    )

    for entry in result:
        client_id = int(entry["client"].id)
        positive_balance = max(float(entry["balance"]), 0.0)
        overdue_exposure = min(
            positive_balance,
            max(float(overdue.get(client_id, 0.0)), 0.0),
        )
        remaining = max(positive_balance - overdue_exposure, 0.0)
        due_7_exposure = min(
            remaining,
            max(float(due_7.get(client_id, 0.0)), 0.0),
        )
        entry["overdue"] = round(overdue_exposure, 2)
        entry["due_7"] = round(due_7_exposure, 2)

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


def _positive_due_totals(
    *,
    due_before: date | None = None,
    due_from: date | None = None,
    due_to: date | None = None,
    salesperson_id: int | None = None,
    unassigned: bool = False,
) -> dict[int, float]:
    query = (
        ClientAccountMovement.select(
            ClientAccountMovement.client.alias("client_id"),
            fn.ROUND(
                fn.COALESCE(fn.SUM(ClientAccountMovement.total_amount), 0),
                2,
            ).alias("total"),
        )
        .join(Client)
        .where(
            ClientAccountMovement.total_amount > 0,
            ClientAccountMovement.due_date.is_null(False),
        )
    )
    if due_before is not None:
        query = query.where(ClientAccountMovement.due_date < due_before)
    if due_from is not None:
        query = query.where(ClientAccountMovement.due_date >= due_from)
    if due_to is not None:
        query = query.where(ClientAccountMovement.due_date <= due_to)
    query = _filter_clients_by_salesperson(
        query,
        salesperson_id=salesperson_id,
        unassigned=unassigned,
    )
    query = query.group_by(ClientAccountMovement.client).dicts()
    return {
        int(row["client_id"]): float(_money(row["total"]))
        for row in query
    }


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
