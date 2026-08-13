from __future__ import annotations

from datetime import date

from peewee import IntegrityError

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client
from app.services.audit_service import AuditService


class ClientOpeningBalanceError(ValueError):
    pass


class ClientOpeningBalanceService:
    TYPE_DEBIT = "debit"
    TYPE_CREDIT = "credit"

    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    @staticmethod
    def normalize_currency(currency: str) -> str:
        normalized = (currency or "").strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ClientOpeningBalanceError("La moneda debe tener un codigo de tres letras.")
        return normalized

    @classmethod
    def normalize_balance_type(cls, balance_type: str) -> str:
        normalized = (balance_type or "").strip().lower()
        if normalized not in (cls.TYPE_DEBIT, cls.TYPE_CREDIT):
            raise ClientOpeningBalanceError("Seleccione si el saldo es debito o credito.")
        return normalized

    @classmethod
    def has_opening_balance(cls, client: Client, currency: str | None = None) -> bool:
        query = ClientAccountMovement.select().where(
            (ClientAccountMovement.client == client)
            & (ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_OPENING_BALANCE)
            & (ClientAccountMovement.is_reversal == False)  # noqa: E712
        )
        if currency is not None:
            query = query.where(
                ClientAccountMovement.currency == cls.normalize_currency(currency)
            )
        return query.exists()

    def register(
        self,
        *,
        client: Client,
        amount: float,
        balance_type: str = TYPE_DEBIT,
        currency: str = "ARS",
        movement_date: date | None = None,
    ) -> ClientAccountMovement:
        if client is None or not isinstance(client, Client):
            raise ClientOpeningBalanceError("Debe seleccionar un cliente.")
        entered_amount = round(float(amount or 0), 2)
        if entered_amount <= 0:
            raise ClientOpeningBalanceError("El importe del saldo inicial debe ser mayor a cero.")
        normalized_type = self.normalize_balance_type(balance_type)
        signed_amount = entered_amount if normalized_type == self.TYPE_DEBIT else -entered_amount
        type_label = "Débito" if normalized_type == self.TYPE_DEBIT else "Crédito"
        reference_type = "DEBITO" if normalized_type == self.TYPE_DEBIT else "CREDITO"
        normalized_currency = self.normalize_currency(currency)
        source_ref = f"OpeningBalance:{normalized_currency}"
        database = ClientAccountMovement._meta.database

        try:
            with database.atomic():
                if self.has_opening_balance(client, normalized_currency):
                    raise ClientOpeningBalanceError(
                        f"El cliente ya tiene saldo inicial en {normalized_currency}."
                    )
                movement = ClientAccountMovement.create(
                    client=client,
                    load_order=None,
                    payment=None,
                    movement_type=ClientAccountMovement.TYPE_OPENING_BALANCE,
                    amount=signed_amount,
                    net_amount=signed_amount,
                    discount_amount=0.0,
                    vat_amount=0.0,
                    total_amount=signed_amount,
                    currency=normalized_currency,
                    movement_date=movement_date or date.today(),
                    description=f"Saldo inicial de apertura - {type_label} ({normalized_currency})",
                    source_ref=source_ref,
                    reference=f"APERTURA-{reference_type}-{normalized_currency}",
                    is_reversal=False,
                    reverses=None,
                    created_by=self.current_user,
                )
                self.audit_service.record(
                    user=self.current_user,
                    module="Cuenta corriente",
                    action="registrar_saldo_inicial",
                    record_ref=f"ClientAccountMovement:{movement.id}",
                    new_value={
                        "client_id": client.id,
                        "amount": signed_amount,
                        "entered_amount": entered_amount,
                        "balance_type": normalized_type,
                        "currency": normalized_currency,
                        "movement_date": movement.movement_date.isoformat(),
                        "source_ref": source_ref,
                    },
                )
                return movement
        except IntegrityError as exc:
            raise ClientOpeningBalanceError(
                f"El cliente ya tiene saldo inicial en {normalized_currency}."
            ) from exc
