from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrder
from app.models.masters import Client
from app.services.audit_service import AuditService


class AccountLedgerService:
    DOCUMENTAL_AMOUNT = 0
    CURRENCY = "ARS"

    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def generate_for_load_order(self, order: LoadOrder) -> list[ClientAccountMovement]:
        order = LoadOrder.get_by_id(order.id)
        movements = []
        for client in self._clients_for_order(order):
            movement, created = ClientAccountMovement.get_or_create(
                load_order=order,
                client=client,
                movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
                is_reversal=False,
                defaults={
                    "amount": self.DOCUMENTAL_AMOUNT,
                    "currency": self.CURRENCY,
                    "description": self._description(order),
                    "source_ref": self._source_ref(order),
                    "created_by": self.current_user,
                },
            )
            movements.append(movement)
            if created:
                self._record("generar", movement)
        return movements

    def reverse_for_load_order(self, order: LoadOrder) -> list[ClientAccountMovement]:
        order = LoadOrder.get_by_id(order.id)
        reversals = []
        originals = ClientAccountMovement.select().where(
            ClientAccountMovement.load_order == order,
            ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_LOAD_ORDER,
            ClientAccountMovement.is_reversal == False,  # noqa: E712
        )
        for original in originals:
            reversal, created = ClientAccountMovement.get_or_create(
                load_order=order,
                client=original.client,
                movement_type=ClientAccountMovement.TYPE_LOAD_ORDER_REVERSAL,
                is_reversal=True,
                reverses=original,
                defaults={
                    "amount": -original.amount,
                    "currency": original.currency,
                    "description": f"Reverso {original.description}",
                    "source_ref": self._source_ref(order),
                    "created_by": self.current_user,
                },
            )
            reversals.append(reversal)
            if created:
                self._record("revertir", reversal)
        return reversals

    def _clients_for_order(self, order: LoadOrder) -> list[Client]:
        clients: list[Client] = []
        for destination in order.destinations.order_by():
            if destination.client not in clients:
                clients.append(destination.client)
        if not clients and order.client is not None:
            clients.append(order.client)
        return clients

    def _description(self, order: LoadOrder) -> str:
        return f"Orden de carga OC-{order.order_number:06d} - movimiento documental sin importe comercial"

    def _source_ref(self, order: LoadOrder) -> str:
        return f"LoadOrder:{order.id}"

    def _record(self, action: str, movement: ClientAccountMovement) -> None:
        self.audit_service.record(
            user=self.current_user,
            module="Cuenta corriente",
            action=action,
            record_ref=f"ClientAccountMovement:{movement.id}",
            new_value={
                "client_id": movement.client.id,
                "load_order_id": movement.load_order.id,
                "movement_type": movement.movement_type,
                "amount": movement.amount,
                "source_ref": movement.source_ref,
            },
        )
