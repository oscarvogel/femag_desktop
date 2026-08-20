from __future__ import annotations

from datetime import date
from math import isfinite

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client
from app.services.audit_service import AuditService


class ClientManualCreditError(ValueError):
    pass


class ClientManualCreditService:
    CURRENCY = "ARS"

    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def register_manual_credit(
        self,
        *,
        client: Client,
        amount: float,
        description: str,
        credit_date: date | None = None,
        reference: str | None = None,
        observations: str | None = None,
    ) -> ClientAccountMovement:
        if client is None or not isinstance(client, Client):
            raise ClientManualCreditError("Debe seleccionar un cliente.")
        try:
            normalized_amount = round(float(amount), 2)
        except (TypeError, ValueError):
            normalized_amount = 0.0
        if not isfinite(normalized_amount) or normalized_amount <= 0:
            raise ClientManualCreditError("El monto del crédito debe ser mayor a cero.")
        normalized_description = (description or "").strip()
        if not normalized_description:
            raise ClientManualCreditError("El concepto del crédito es obligatorio.")
        normalized_reference = (reference or "").strip() or None
        normalized_observations = (observations or "").strip() or None
        database = ClientAccountMovement._meta.database

        with database.atomic():
            movement = ClientAccountMovement.create(
                client=client,
                load_order=None,
                payment=None,
                movement_type=ClientAccountMovement.TYPE_MANUAL_CREDIT,
                amount=-normalized_amount,
                net_amount=-normalized_amount,
                discount_amount=0.0,
                vat_amount=0.0,
                total_amount=-normalized_amount,
                currency=self.CURRENCY,
                movement_date=credit_date or date.today(),
                description=normalized_description,
                observations=normalized_observations,
                source_ref="ManualCredit:pending",
                reference=normalized_reference,
                is_reversal=False,
                reverses=None,
                created_by=self.current_user,
            )
            movement.source_ref = f"ManualCredit:{movement.id}"
            movement.save()
            self.audit_service.record(
                user=self.current_user,
                module="Cuenta corriente",
                action="registrar_credito_manual",
                record_ref=f"ClientAccountMovement:{movement.id}",
                new_value=self._audit_value(movement),
            )
        return movement

    def reverse_manual_credit(
        self,
        movement: ClientAccountMovement,
        *,
        reversal_date: date | None = None,
    ) -> ClientAccountMovement:
        if movement is None or not isinstance(movement, ClientAccountMovement):
            raise ClientManualCreditError("Debe seleccionar un crédito manual.")
        database = ClientAccountMovement._meta.database

        with database.atomic():
            original = ClientAccountMovement.get_by_id(movement.id)
            if (
                original.movement_type != ClientAccountMovement.TYPE_MANUAL_CREDIT
                or original.is_reversal
            ):
                raise ClientManualCreditError(
                    "El movimiento seleccionado no es un crédito manual."
                )
            existing = (
                ClientAccountMovement.select()
                .where(
                    ClientAccountMovement.reverses == original,
                    ClientAccountMovement.movement_type
                    == ClientAccountMovement.TYPE_MANUAL_CREDIT_REVERSAL,
                )
                .first()
            )
            if existing is not None:
                raise ClientManualCreditError("El crédito manual ya fue reversado.")

            reversal = ClientAccountMovement.create(
                client=original.client,
                load_order=None,
                payment=None,
                movement_type=ClientAccountMovement.TYPE_MANUAL_CREDIT_REVERSAL,
                amount=-original.amount,
                net_amount=-original.net_amount,
                discount_amount=-original.discount_amount,
                vat_amount=-original.vat_amount,
                total_amount=-original.total_amount,
                currency=original.currency,
                movement_date=reversal_date or date.today(),
                description=f"Reverso: {original.description}",
                observations=original.observations,
                source_ref=f"ManualCredit:{original.id}:reversal",
                reference=original.reference,
                is_reversal=True,
                reverses=original,
                created_by=self.current_user,
            )
            self.audit_service.record(
                user=self.current_user,
                module="Cuenta corriente",
                action="reversar_credito_manual",
                record_ref=f"ClientAccountMovement:{original.id}",
                old_value=self._audit_value(original),
                new_value={
                    **self._audit_value(reversal),
                    "reversal_movement_id": reversal.id,
                },
            )
        return reversal

    @staticmethod
    def _audit_value(movement: ClientAccountMovement) -> dict:
        return {
            "client_id": movement.client.id,
            "movement_type": movement.movement_type,
            "amount": movement.amount,
            "movement_date": (
                movement.movement_date.isoformat() if movement.movement_date else None
            ),
            "description": movement.description,
            "reference": movement.reference,
            "observations": movement.observations,
            "source_ref": movement.source_ref,
        }
