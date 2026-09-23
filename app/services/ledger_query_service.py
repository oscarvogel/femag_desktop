from __future__ import annotations

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
