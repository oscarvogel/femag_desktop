from datetime import date

from peewee import IntegrityError

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client
from app.models.payments import ClientPayment
from app.models.security import User
from app.models.base import utc_now
from app.models.system import NumberSequence
from app.services.audit_service import AuditService


RECEIPT_SEQUENCE_NAME = "client_payment_receipt"


class ClientPaymentError(ValueError):
    pass


class ClientPaymentService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def register_payment(
        self,
        *,
        client: Client,
        amount: float,
        payment_date: date | None = None,
        method: str = ClientPayment.METHOD_CASH,
        reference: str | None = None,
        observations: str | None = None,
    ) -> ClientPayment:
        if client is None or not isinstance(client, Client):
            raise ClientPaymentError("Debe seleccionar un cliente.")
        if amount is None or amount <= 0:
            raise ClientPaymentError("El monto del pago debe ser mayor a cero.")
        if method not in ClientPayment.METHODS:
            raise ClientPaymentError(f"Medio de pago invalido: {method!r}.")

        receipt_number = self._next_receipt_number()
        try:
            payment = ClientPayment.create(
                receipt_number=receipt_number,
                client=client,
                payment_date=payment_date or date.today(),
                amount=round(float(amount), 2),
                method=method,
                reference=reference,
                observations=observations,
                created_by=self.current_user,
            )
        except IntegrityError as exc:
            raise ClientPaymentError(f"No se pudo registrar el pago: {exc}") from exc

        self._register_ledger_movement(payment)
        self.audit_service.record(
            user=self.current_user,
            module="Cuenta corriente",
            action="registrar_pago",
            record_ref=f"ClientPayment:{payment.id}",
            new_value={
                "client_id": client.id,
                "receipt_number": payment.receipt_number,
                "amount": payment.amount,
                "method": payment.method,
                "payment_date": payment.payment_date.isoformat(),
                "reference": payment.reference,
            },
        )
        return payment

    def annul_payment(
        self,
        payment: ClientPayment,
        *,
        authorized_by: User,
        reason: str | None = None,
    ) -> ClientPayment:
        if payment is None or not isinstance(payment, ClientPayment):
            raise ClientPaymentError("Debe seleccionar un pago.")
        if (
            authorized_by is None
            or not isinstance(authorized_by, User)
            or not authorized_by.active
            or authorized_by.profile.name.strip().lower() != "administrador"
        ):
            raise PermissionError("La anulación requiere autorización de un administrador.")

        database = ClientPayment._meta.database
        with database.atomic():
            payment = ClientPayment.get_by_id(payment.id)
            if payment.status == ClientPayment.STATUS_ANNULLED:
                raise ClientPaymentError("El pago ya está anulado.")
            original_movement = (
                ClientAccountMovement.select()
                .where(
                    ClientAccountMovement.payment == payment,
                    ClientAccountMovement.movement_type
                    == ClientAccountMovement.TYPE_PAYMENT,
                    ClientAccountMovement.is_reversal == False,  # noqa: E712
                )
                .order_by(ClientAccountMovement.id)
                .first()
            )
            if original_movement is None:
                raise ClientPaymentError(
                    "No se encontró el movimiento contable original del pago."
                )
            existing_reversal = (
                ClientAccountMovement.select()
                .where(
                    ClientAccountMovement.reverses == original_movement,
                    ClientAccountMovement.movement_type
                    == ClientAccountMovement.TYPE_PAYMENT_REVERSAL,
                )
                .first()
            )
            if existing_reversal is not None:
                raise ClientPaymentError("El pago ya tiene una reversión contable.")

            annulled_at = utc_now()
            reversal = ClientAccountMovement.create(
                client=payment.client,
                load_order=None,
                payment=payment,
                movement_type=ClientAccountMovement.TYPE_PAYMENT_REVERSAL,
                amount=payment.amount,
                net_amount=payment.amount,
                discount_amount=0.0,
                vat_amount=0.0,
                total_amount=payment.amount,
                currency=original_movement.currency,
                description=f"Anulación recibo {payment.receipt_number}",
                source_ref=f"ClientPayment:{payment.id}:annulment",
                is_reversal=True,
                reverses=original_movement,
                created_by=self.current_user,
            )
            payment.status = ClientPayment.STATUS_ANNULLED
            payment.annulled_at = annulled_at
            payment.annulled_by = authorized_by.username
            payment.annulment_reason = (reason or "").strip() or None
            payment.save()
            self.audit_service.record(
                user=self.current_user,
                module="Cuenta corriente",
                action="anular_pago",
                record_ref=f"ClientPayment:{payment.id}",
                old_value={
                    "status": ClientPayment.STATUS_ACTIVE,
                    "amount": payment.amount,
                },
                new_value={
                    "status": payment.status,
                    "annulled_at": annulled_at.isoformat(timespec="seconds"),
                    "annulled_by": authorized_by.username,
                    "annulment_reason": payment.annulment_reason,
                    "reversal_movement_id": reversal.id,
                },
            )
        return payment

    def _register_ledger_movement(self, payment: ClientPayment) -> ClientAccountMovement:
        return ClientAccountMovement.create(
            client=payment.client,
            load_order=None,
            payment=payment,
            movement_type=ClientAccountMovement.TYPE_PAYMENT,
            amount=-payment.amount,
            net_amount=-payment.amount,
            discount_amount=0.0,
            vat_amount=0.0,
            total_amount=-payment.amount,
            currency="ARS",
            description=(
                f"Recibo {payment.receipt_number} - pago {payment.method} "
                f"${payment.amount:,.2f}"
            ),
            source_ref=f"ClientPayment:{payment.id}",
            is_reversal=False,
            reverses=None,
            created_by=self.current_user,
        )

    def _next_receipt_number(self) -> str:
        sequence, _ = NumberSequence.get_or_create(
            name=RECEIPT_SEQUENCE_NAME, defaults={"current_number": 0}
        )
        for _ in range(5):
            updated = (
                NumberSequence.update(current_number=NumberSequence.current_number + 1)
                .where(
                    NumberSequence.id == sequence.id,
                    NumberSequence.current_number == sequence.current_number,
                )
                .execute()
            )
            if updated:
                sequence.current_number += 1
                sequence.save()
                return f"REC-{sequence.current_number:08d}"
            sequence = NumberSequence.get_by_id(sequence.id)
        raise ClientPaymentError("No se pudo obtener el siguiente numero de recibo.")
