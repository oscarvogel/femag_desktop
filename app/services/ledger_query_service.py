from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client


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
    detail grid. This is the single source of truth for account balances.
    """
    return float(_balance_from_movements(movements_for_client(client)))


def movements_for_client(client: Client) -> list[ClientAccountMovement]:
    return list(
        ClientAccountMovement.select()
        .where(ClientAccountMovement.client == client)
        .order_by(
            ClientAccountMovement.movement_date,
            ClientAccountMovement.created_at,
            ClientAccountMovement.id,
        )
    )


def client_balances() -> list[dict]:
    """
    Build the left-side client grid from the same movements and the same money
    accumulator used by client_balance() and running_balance().

    Do not use SQL SUM() over FloatField here: MySQL can accumulate binary
    floating-point error for large monetary values and make the grid/header
    disagree with the movement detail.
    """
    movements = list(
        ClientAccountMovement.select(ClientAccountMovement, Client)
        .join(Client)
        .order_by(
            ClientAccountMovement.client,
            ClientAccountMovement.movement_date,
            ClientAccountMovement.created_at,
            ClientAccountMovement.id,
        )
    )

    grouped: dict[int, dict] = {}
    for movement in movements:
        client = movement.client
        entry = grouped.setdefault(
            client.id,
            {
                "client": client,
                "balance_decimal": Decimal("0.00"),
                "movements": 0,
            },
        )
        entry["balance_decimal"] += _movement_amount(movement)
        entry["movements"] += 1

    result = [
        {
            "client": entry["client"],
            "balance": float(
                entry["balance_decimal"].quantize(
                    _MONEY_QUANTUM,
                    rounding=ROUND_HALF_UP,
                )
            ),
            "movements": entry["movements"],
        }
        for entry in grouped.values()
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
