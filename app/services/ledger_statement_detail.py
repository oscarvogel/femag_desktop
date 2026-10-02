"""Detalle de cuenta corriente por cliente, en `Decimal`.

Fuente unica para cualquier presentacion que necesite la composicion del saldo
de un cliente (hoy, el PDF detallado del resumen por vendedor del #609).

Este modulo NO calcula saldos: consume `movements_for_client()` y
`running_balance_decimals()`, las mismas funciones que alimentan la grilla de
Cuenta Corriente. Si esas reglas cambian, el detalle cambia con ellas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client
from app.services.ledger_query_service import (
    money_decimal,
    movement_debit_credit,
    movements_for_client,
    running_balance_decimals,
)

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class StatementMovement:
    """Un movimiento de cuenta corriente con su saldo acumulado."""

    movement: ClientAccountMovement
    movement_type: str
    movement_date: date | None
    due_date: date | None
    debit: Decimal
    credit: Decimal
    balance: Decimal


@dataclass(frozen=True)
class ClientStatementDetail:
    """Los movimientos de un cliente y el saldo que explican su pantalla."""

    client: Client
    movements: list[StatementMovement]
    balance: Decimal

    @property
    def movements_count(self) -> int:
        return len(self.movements)


def client_statement_detail(client: Client) -> ClientStatementDetail:
    """Arma el detalle de `client` a partir del mismo flujo que muestra la pantalla."""
    movements = movements_for_client(client)
    balances = running_balance_decimals(movements)

    rows: list[StatementMovement] = []
    for movement, balance in zip(movements, balances):
        debit, credit = movement_debit_credit(movement)
        rows.append(
            StatementMovement(
                movement=movement,
                movement_type=movement.movement_type,
                movement_date=movement.movement_date,
                due_date=movement.due_date,
                debit=debit,
                credit=credit,
                balance=balance,
            )
        )
    # El saldo del cliente es el ultimo acumulado; nunca se recalcula aparte.
    balance = balances[-1] if balances else ZERO
    return ClientStatementDetail(client=client, movements=rows, balance=balance)


def detail_total(details: list[ClientStatementDetail]) -> Decimal:
    """Suma de saldos finales de varios clientes, en `Decimal`."""
    return money_decimal(sum((detail.balance for detail in details), ZERO))
