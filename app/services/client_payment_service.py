from datetime import date

from peewee import IntegrityError

from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrderClosure
from app.models.masters import Client
from app.models.payments import ClientPayment, ClientPaymentDetail, PaymentMethod
from app.models.security import User
from app.models.base import utc_now
from app.models.system import NumberSequence
from app.services.audit_service import AuditService


RECEIPT_SEQUENCE_NAME = "client_payment_receipt"
DEFAULT_PAYMENT_METHODS = (
    (ClientPayment.METHOD_CASH, "Efectivo", 10),
    (ClientPayment.METHOD_TRANSFER, "Transferencia", 20),
    (ClientPayment.METHOD_CHECK, "Cheque", 30),
    (ClientPayment.METHOD_RETENTION, "Retenciones / Percepciones", 40),
    (ClientPayment.METHOD_HOLISTOR, "Holistor", 50),
    (ClientPayment.METHOD_OTHER, "Otros", 90),
)


class ClientPaymentError(ValueError):
    pass


class ClientPaymentService:
    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    @staticmethod
    def ensure_default_payment_methods() -> list[PaymentMethod]:
        """Crea los medios iniciales sin pisar personalizaciones existentes."""
        rows = []
        for code, name, sort_order in DEFAULT_PAYMENT_METHODS:
            row, created = PaymentMethod.get_or_create(
                code=code,
                defaults={"name": name, "active": True, "sort_order": sort_order},
            )
            if created:
                row.save()
            rows.append(row)
        return rows

    @classmethod
    def active_payment_methods(cls) -> list[PaymentMethod]:
        cls.ensure_default_payment_methods()
        return list(
            PaymentMethod.select()
            .where(PaymentMethod.active == True)  # noqa: E712
            .order_by(PaymentMethod.sort_order, PaymentMethod.name)
        )

    def register_payment(
        self,
        *,
        client: Client,
        amount: float,
        payment_date: date | None = None,
        method: str = ClientPayment.METHOD_CASH,
        reference: str | None = None,
        observations: str | None = None,
        closure: LoadOrderClosure | None = None,
    ) -> ClientPayment:
        """Compatibilidad: registra un recibo con un único medio."""
        return self.register_compound_payment(
            client=client,
            payment_date=payment_date,
            details=[
                {
                    "method": method,
                    "amount": amount,
                    "reference": reference,
                }
            ],
            observations=observations,
            closure=closure,
        )

    def register_compound_payment(
        self,
        *,
        client: Client,
        details: list[dict],
        payment_date: date | None = None,
        observations: str | None = None,
        closure: LoadOrderClosure | None = None,
    ) -> ClientPayment:
        if client is None or not isinstance(client, Client):
            raise ClientPaymentError("Debe seleccionar un cliente.")
        if not details:
            raise ClientPaymentError("Debe cargar al menos un medio de pago.")

        closure = self._validate_closure(client=client, closure=closure)
        methods = {row.code: row for row in self.active_payment_methods()}
        normalized = []
        for index, raw in enumerate(details, start=1):
            method_code = str(raw.get("method") or "").strip()
            method_row = methods.get(method_code)
            if method_row is None:
                raise ClientPaymentError(f"Medio de pago invalido: {method_code!r}.")
            try:
                amount = round(float(raw.get("amount") or 0), 2)
            except (TypeError, ValueError) as exc:
                raise ClientPaymentError(f"Importe inválido en la línea {index}.") from exc
            if amount <= 0:
                raise ClientPaymentError(
                    f"El importe de la línea {index} debe ser mayor a cero."
                )
            normalized.append(
                {
                    "method": method_row,
                    "amount": amount,
                    "reference": (str(raw.get("reference") or "").strip() or None),
                    "observations": (str(raw.get("observations") or "").strip() or None),
                    "sequence": index,
                }
            )

        total = round(sum(item["amount"] for item in normalized), 2)
        if total <= 0:
            raise ClientPaymentError("El monto total del pago debe ser mayor a cero.")

        receipt_number = self._next_receipt_number()
        first = normalized[0]
        database = ClientPayment._meta.database
        try:
            with database.atomic():
                payment = ClientPayment.create(
                    receipt_number=receipt_number,
                    client=client,
                    closure=closure,
                    payment_date=payment_date or date.today(),
                    amount=total,
                    method=(first["method"].code if len(normalized) == 1 else "multiple"),
                    reference=(first["reference"] if len(normalized) == 1 else None),
                    observations=observations,
                    created_by=self.current_user,
                )
                for item in normalized:
                    ClientPaymentDetail.create(
                        payment=payment,
                        payment_method=item["method"],
                        amount=item["amount"],
                        reference=item["reference"],
                        observations=item["observations"],
                        sequence=item["sequence"],
                    )
                self._register_ledger_movement(payment)
        except IntegrityError as exc:
            raise ClientPaymentError(f"No se pudo registrar el pago: {exc}") from exc

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
                "closure_id": payment.closure_id,
                "load_order_id": payment.closure.order_id if payment.closure_id else None,
                "details": [
                    {
                        "method": item["method"].code,
                        "amount": item["amount"],
                        "reference": item["reference"],
                    }
                    for item in normalized
                ],
            },
        )
        return payment

    def _validate_closure(
        self, *, client: Client, closure: LoadOrderClosure | None
    ) -> LoadOrderClosure | None:
        if closure is None:
            return None
        try:
            closure = LoadOrderClosure.get_by_id(closure.id)
        except (AttributeError, LoadOrderClosure.DoesNotExist) as exc:
            raise ClientPaymentError("El cierre de entrega no es valido.") from exc
        if not closure.is_active:
            raise ClientPaymentError("Solo se pueden imputar pagos a un cierre activo.")
        client_ids = {destination.client_id for destination in closure.order.destinations}
        if closure.order.client_id is not None:
            client_ids.add(closure.order.client_id)
        if client.id not in client_ids:
            raise ClientPaymentError("El cliente no pertenece a la orden de entrega.")
        return closure

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
                load_order=original_movement.load_order,
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
        load_order = payment.closure.order if payment.closure_id else None
        source_ref = (
            f"LoadOrderClosure:{payment.closure_id}:ClientPayment:{payment.id}"
            if payment.closure_id
            else f"ClientPayment:{payment.id}"
        )
        detail_count = ClientPaymentDetail.select().where(
            ClientPaymentDetail.payment == payment
        ).count()
        description = (
            f"Recibo {payment.receipt_number} - pago compuesto ({detail_count} medios) "
            f"${payment.amount:,.2f}"
            if detail_count > 1
            else f"Recibo {payment.receipt_number} - pago {payment.method} ${payment.amount:,.2f}"
        )
        return ClientAccountMovement.create(
            client=payment.client,
            load_order=load_order,
            payment=payment,
            movement_type=ClientAccountMovement.TYPE_PAYMENT,
            amount=-payment.amount,
            net_amount=-payment.amount,
            discount_amount=0.0,
            vat_amount=0.0,
            total_amount=-payment.amount,
            currency="ARS",
            description=description,
            source_ref=source_ref,
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
