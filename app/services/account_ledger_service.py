from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrder, LoadOrderBudgetStatus, LoadOrderDestination, LoadOrderProduct
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
            totals = self._load_order_totals_for_client(order, client)
            movement, created = ClientAccountMovement.get_or_create(
                load_order=order,
                client=client,
                movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
                is_reversal=False,
                defaults={
                    "amount": self.DOCUMENTAL_AMOUNT,
                    "net_amount": totals["neto_subtotal"],
                    "discount_amount": totals["descuento_importe"],
                    "vat_amount": totals["iva_importe"],
                    "total_amount": totals["total"],
                    "currency": self.CURRENCY,
                    "description": self._description(order, totals),
                    "source_ref": self._source_ref(order),
                    "created_by": self.current_user,
                },
            )
            movements.append(movement)
            if created:
                self._update_budget_status(order, client)
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
                    "net_amount": -original.net_amount,
                    "discount_amount": -original.discount_amount,
                    "vat_amount": -original.vat_amount,
                    "total_amount": -original.total_amount,
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

    def _load_order_totals_for_client(self, order: LoadOrder, client: Client) -> dict:
        from peewee import fn

        totals = (
            LoadOrderProduct.select(
                fn.COALESCE(fn.SUM(LoadOrderProduct.neto_subtotal), 0).alias("neto_subtotal"),
                fn.COALESCE(fn.SUM(LoadOrderProduct.descuento_importe), 0).alias("descuento_importe"),
                fn.COALESCE(fn.SUM(LoadOrderProduct.iva_importe), 0).alias("iva_importe"),
                fn.COALESCE(fn.SUM(LoadOrderProduct.total), 0).alias("total"),
            )
            .join(LoadOrderDestination, on=LoadOrderProduct.destination)
            .where(
                (LoadOrderProduct.order == order)
                & (LoadOrderDestination.client == client)
            )
            .dicts()
            .first()
        )
        return {
            "neto_subtotal": round(totals["neto_subtotal"], 2),
            "descuento_importe": round(totals["descuento_importe"], 2),
            "iva_importe": round(totals["iva_importe"], 2),
            "total": round(totals["total"], 2),
        }

    def _update_budget_status(self, order: LoadOrder, client: Client) -> None:
        LoadOrderBudgetStatus.get_or_create(
            order=order,
            client=client,
            defaults={"status": LoadOrderBudgetStatus.STATUS_APPLIED},
        )
        updated = LoadOrderBudgetStatus.update(
            status=LoadOrderBudgetStatus.STATUS_APPLIED
        ).where(
            (LoadOrderBudgetStatus.order == order)
            & (LoadOrderBudgetStatus.client == client)
        )
        updated.execute()
        self.audit_service.record(
            user=self.current_user,
            module="Cuenta corriente",
            action="aplicar_presupuesto",
            record_ref=f"LoadOrderBudgetStatus:{order.id}:{client.id}",
            new_value={
                "order_id": order.id,
                "client_id": client.id,
                "status": LoadOrderBudgetStatus.STATUS_APPLIED,
            },
        )

    def _clients_for_order(self, order: LoadOrder) -> list[Client]:
        clients: list[Client] = []
        client_ids = set()
        for destination in order.destinations.order_by():
            if destination.client.id not in client_ids:
                clients.append(destination.client)
                client_ids.add(destination.client.id)
        if not clients and order.client is not None:
            clients.append(order.client)
        return clients

    def _description(self, order: LoadOrder, totals: dict | None = None) -> str:
        if totals and totals["total"]:
            return (
                f"Orden de carga OC-{order.order_number:06d} - "
                f"Neto ${totals['total']:,.2f} (neto ${totals['neto_subtotal']:,.2f}, "
                f"desc. ${totals['descuento_importe']:,.2f}, IVA ${totals['iva_importe']:,.2f})"
            )
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
                "net_amount": movement.net_amount,
                "discount_amount": movement.discount_amount,
                "vat_amount": movement.vat_amount,
                "total_amount": movement.total_amount,
                "source_ref": movement.source_ref,
            },
        )
