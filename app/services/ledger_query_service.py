from __future__ import annotations

from typing import Iterable

from peewee import fn

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client


def client_balance(client: Client) -> float:
    total = (
        ClientAccountMovement.select(
            fn.COALESCE(fn.SUM(ClientAccountMovement.total_amount), 0)
        )
        .where(ClientAccountMovement.client == client)
        .scalar()
    )
    return round(float(total or 0), 2)


def movements_for_client(client: Client) -> list[ClientAccountMovement]:
    return list(
        ClientAccountMovement.select()
        .where(ClientAccountMovement.client == client)
        .order_by(ClientAccountMovement.created_at, ClientAccountMovement.id)
    )


def client_balances() -> list[dict]:
    rows = (
        ClientAccountMovement.select(
            ClientAccountMovement.client,
            fn.COALESCE(fn.SUM(ClientAccountMovement.total_amount), 0).alias("balance"),
            fn.COUNT(ClientAccountMovement.id).alias("movements"),
        )
        .group_by(ClientAccountMovement.client)
        .order_by(fn.SUM(ClientAccountMovement.total_amount).desc())
    )
    return [
        {
            "client": row.client,
            "balance": round(float(row.balance or 0), 2),
            "movements": int(row.movements or 0),
        }
        for row in rows
    ]


def running_balance(movements: Iterable[ClientAccountMovement]) -> list[float]:
    balances: list[float] = []
    running = 0.0
    for movement in movements:
        running += float(movement.total_amount or 0)
        balances.append(round(running, 2))
    return balances
