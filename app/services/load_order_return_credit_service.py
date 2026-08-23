from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrderClosure, LoadOrderReturnLine
from app.services.audit_service import AuditService


class LoadOrderReturnCreditError(ValueError):
    pass


class LoadOrderReturnCreditService:
    """Generate and reverse account credits produced by returned delivery lines."""

    CURRENCY = "ARS"

    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def generate_for_closure(self, closure: LoadOrderClosure) -> list[ClientAccountMovement]:
        closure = self._require_closure(closure)
        grouped: dict[int, list[LoadOrderReturnLine]] = defaultdict(list)
        for row in closure.return_lines:
            grouped[row.client_id].append(row)

        movements: list[ClientAccountMovement] = []
        for client_id, rows in grouped.items():
            amount = round(sum(float(row.credit_amount) for row in rows), 2)
            if amount <= 0:
                continue
            source_ref = self._source_ref(closure, client_id)
            existing = (
                ClientAccountMovement.select()
                .where(
                    (ClientAccountMovement.source_ref == source_ref)
                    & (ClientAccountMovement.client_id == client_id)
                    & (
                        ClientAccountMovement.movement_type
                        == ClientAccountMovement.TYPE_RETURN_CREDIT
                    )
                    & (ClientAccountMovement.is_reversal == False)  # noqa: E712
                )
                .first()
            )
            if existing is not None:
                movements.append(existing)
                continue

            details = "; ".join(
                f"{row.order_product.product.name}: {float(row.quantity):g} ({row.reason})"
                for row in rows
            )
            order = closure.order
            movement = ClientAccountMovement.create(
                client=client_id,
                load_order=order,
                payment=None,
                movement_type=ClientAccountMovement.TYPE_RETURN_CREDIT,
                amount=-amount,
                net_amount=-amount,
                discount_amount=0.0,
                vat_amount=0.0,
                total_amount=-amount,
                currency=self.CURRENCY,
                movement_date=(closure.closed_at.date() if closure.closed_at else date.today()),
                due_date=None,
                description=(
                    f"Nota de crédito por devolución OC-{order.order_number:06d}"
                ),
                observations=details or None,
                source_ref=source_ref,
                reference=f"OC-{order.order_number:06d}",
                is_reversal=False,
                reverses=None,
                created_by=self.current_user,
            )
            self.audit_service.record(
                user=self.current_user,
                module="Cuenta corriente",
                action="generar_credito_devolucion",
                record_ref=f"ClientAccountMovement:{movement.id}",
                new_value=self._audit_value(movement, closure_id=closure.id),
            )
            movements.append(movement)
        return movements

    def reverse_for_closure(self, closure: LoadOrderClosure) -> list[ClientAccountMovement]:
        closure = self._require_closure(closure)
        originals = list(
            ClientAccountMovement.select().where(
                (ClientAccountMovement.load_order == closure.order)
                & (
                    ClientAccountMovement.movement_type
                    == ClientAccountMovement.TYPE_RETURN_CREDIT
                )
                & (ClientAccountMovement.is_reversal == False)  # noqa: E712
                & (ClientAccountMovement.source_ref.startswith(f"LoadOrderClosure:{closure.id}:ReturnCredit:"))
            )
        )
        reversals: list[ClientAccountMovement] = []
        for original in originals:
            existing = (
                ClientAccountMovement.select()
                .where(
                    (ClientAccountMovement.reverses == original)
                    & (
                        ClientAccountMovement.movement_type
                        == ClientAccountMovement.TYPE_RETURN_CREDIT_REVERSAL
                    )
                )
                .first()
            )
            if existing is not None:
                reversals.append(existing)
                continue

            reversal = ClientAccountMovement.create(
                client=original.client,
                load_order=original.load_order,
                payment=None,
                movement_type=ClientAccountMovement.TYPE_RETURN_CREDIT_REVERSAL,
                amount=-original.amount,
                net_amount=-original.net_amount,
                discount_amount=-original.discount_amount,
                vat_amount=-original.vat_amount,
                total_amount=-original.total_amount,
                currency=original.currency,
                movement_date=date.today(),
                due_date=None,
                description=f"Reverso: {original.description}",
                observations=original.observations,
                source_ref=f"{original.source_ref}:reversal",
                reference=original.reference,
                is_reversal=True,
                reverses=original,
                created_by=self.current_user,
            )
            self.audit_service.record(
                user=self.current_user,
                module="Cuenta corriente",
                action="reversar_credito_devolucion",
                record_ref=f"ClientAccountMovement:{original.id}",
                old_value=self._audit_value(original, closure_id=closure.id),
                new_value={
                    **self._audit_value(reversal, closure_id=closure.id),
                    "reversal_movement_id": reversal.id,
                },
            )
            reversals.append(reversal)
        return reversals

    @staticmethod
    def _source_ref(closure: LoadOrderClosure, client_id: int) -> str:
        return f"LoadOrderClosure:{closure.id}:ReturnCredit:{client_id}"

    @staticmethod
    def _require_closure(closure: LoadOrderClosure) -> LoadOrderClosure:
        if closure is None or not isinstance(closure, LoadOrderClosure) or closure.id is None:
            raise LoadOrderReturnCreditError("Debe indicar un cierre de entrega válido.")
        try:
            return LoadOrderClosure.get_by_id(closure.id)
        except LoadOrderClosure.DoesNotExist as exc:
            raise LoadOrderReturnCreditError("El cierre de entrega no existe.") from exc

    @staticmethod
    def _audit_value(movement: ClientAccountMovement, *, closure_id: int) -> dict:
        return {
            "closure_id": closure_id,
            "client_id": movement.client_id,
            "load_order_id": movement.load_order_id,
            "movement_type": movement.movement_type,
            "amount": movement.amount,
            "description": movement.description,
            "reference": movement.reference,
            "source_ref": movement.source_ref,
        }
