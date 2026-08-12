from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from peewee import fn

from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrder
from app.models.masters import Client


@dataclass(frozen=True)
class ClientCreditStatus:
    client_id: int
    pending_dispatches: int
    limit_dispatches: int | None
    pending_balance: float
    overdue_balance: float
    next_due_date: date | None
    state: str
    can_issue: bool

    @property
    def limit_label(self) -> str:
        return "Sin límite" if self.limit_dispatches is None else str(self.limit_dispatches)


class ClientCreditService:
    STATE_AVAILABLE = "Disponible"
    STATE_AT_LIMIT = "Al límite"
    STATE_BLOCKED = "Bloqueado"
    EPSILON = 0.01

    @classmethod
    def status_for_client(cls, client: Client, *, as_of: date | None = None) -> ClientCreditStatus:
        client = Client.get_by_id(client.id)
        as_of = as_of or date.today()
        rows = cls._dispatch_balances(client)
        pending = [row for row in rows if row["balance"] > cls.EPSILON]
        pending_count = len(pending)
        limit = client.max_despachos_pendientes
        if limit is not None:
            limit = max(int(limit), 0)

        overdue_balance = round(
            sum(row["balance"] for row in pending if row["due_date"] is not None and row["due_date"] < as_of),
            2,
        )
        future_due_dates = [
            row["due_date"]
            for row in pending
            if row["due_date"] is not None and row["due_date"] >= as_of
        ]
        next_due_date = min(future_due_dates) if future_due_dates else None
        pending_balance = round(sum(row["balance"] for row in pending), 2)

        if limit is None:
            state = cls.STATE_AVAILABLE
            can_issue = True
        elif pending_count > limit:
            state = cls.STATE_BLOCKED
            can_issue = False
        elif pending_count == limit:
            state = cls.STATE_AT_LIMIT
            can_issue = False
        else:
            state = cls.STATE_AVAILABLE
            can_issue = True

        return ClientCreditStatus(
            client_id=client.id,
            pending_dispatches=pending_count,
            limit_dispatches=limit,
            pending_balance=pending_balance,
            overdue_balance=overdue_balance,
            next_due_date=next_due_date,
            state=state,
            can_issue=can_issue,
        )

    @classmethod
    def assert_can_issue(cls, order: LoadOrder) -> list[ClientCreditStatus]:
        order = LoadOrder.get_by_id(order.id)
        statuses = []
        for client in cls._clients_for_order(order):
            status = cls.status_for_client(client, as_of=order.date)
            statuses.append(status)
            if status.can_issue:
                continue
            overdue = (
                f" Deuda vencida: ${status.overdue_balance:,.2f}."
                if status.overdue_balance > cls.EPSILON
                else ""
            )
            raise ValueError(
                "Cliente con crédito bloqueado. "
                f"{client.name} posee {status.pending_dispatches} despachos pendientes "
                f"y su límite es {status.limit_dispatches}."
                f"{overdue} Regularice la cuenta corriente antes de generar un nuevo despacho."
            )
        return statuses

    @classmethod
    def _dispatch_balances(cls, client: Client) -> list[dict]:
        rows = (
            ClientAccountMovement.select(
                ClientAccountMovement.load_order,
                fn.SUM(ClientAccountMovement.total_amount).alias("balance"),
            )
            .where(
                (ClientAccountMovement.client == client)
                & ClientAccountMovement.load_order.is_null(False)
            )
            .group_by(ClientAccountMovement.load_order)
        )
        result = []
        for row in rows:
            order = row.load_order
            if order.status == LoadOrder.STATUS_ANNULLED:
                continue
            original = (
                ClientAccountMovement.select()
                .where(
                    (ClientAccountMovement.client == client)
                    & (ClientAccountMovement.load_order == order)
                    & (ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_LOAD_ORDER)
                    & (ClientAccountMovement.is_reversal == False)  # noqa: E712
                )
                .order_by(ClientAccountMovement.id)
                .first()
            )
            if original is None:
                continue
            result.append(
                {
                    "order": order,
                    "balance": round(float(row.balance or 0), 2),
                    "due_date": original.due_date,
                }
            )
        return result

    @staticmethod
    def _clients_for_order(order: LoadOrder) -> list[Client]:
        clients: list[Client] = []
        seen: set[int] = set()
        for destination in order.destinations.order_by():
            if destination.client_id not in seen:
                clients.append(destination.client)
                seen.add(destination.client_id)
        if not clients and order.client_id is not None:
            clients.append(order.client)
        return clients
