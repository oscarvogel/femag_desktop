from datetime import date, timedelta

from app.config.database import database_proxy
from app.models.budgets import Budget, BudgetItem
from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
from app.models.masters import Client, Product
from app.models.system import NumberSequence
from app.services.audit_service import AuditService


class BudgetService:
    CURRENCY = "ARS"

    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    def _next_budget_number(self) -> int:
        sequence, _ = NumberSequence.get_or_create(
            name="budget", defaults={"current_number": 0}
        )
        sequence.current_number += 1
        sequence.save()
        return sequence.current_number

    def ensure_for_load_order(self, order: LoadOrder) -> list[Budget]:
        order = LoadOrder.get_by_id(order.id)
        return [self.ensure_for_load_order_client(order, client) for client in self._clients_for_order(order)]

    def _observations_for_order_client(self, order: LoadOrder, client: Client) -> str | None:
        """Condiciones comerciales del cliente dentro de la orden.

        Une las observaciones de los destinos de ese cliente (y, como
        respaldo, las observaciones de sus renglones), sin duplicados,
        para que el PDF separado por cliente conserve la información
        comercial que antes mostraba el presupuesto combinado.
        """
        seen: list[str] = []

        def _remember(value: str | None) -> None:
            cleaned = (value or "").strip()
            if cleaned and cleaned not in seen:
                seen.append(cleaned)

        for destination in order.destinations.order_by(LoadOrderDestination.sequence):
            if destination.client_id == client.id:
                _remember(destination.observations)
        for row in self._load_order_rows_for_client(order, client):
            _remember(row.observations)
        if not seen:
            return None
        return " / ".join(seen)

    def ensure_for_load_order_client(self, order: LoadOrder, client: Client) -> Budget:
        order = LoadOrder.get_by_id(order.id)
        client = Client.get_by_id(client.id)
        existing = Budget.get_or_none(
            (Budget.load_order == order)
            & (Budget.client == client)
            & (Budget.origin == Budget.ORIGIN_LOAD_ORDER)
        )
        if existing is not None:
            backfill = self._observations_for_order_client(order, client)
            if backfill and not (existing.observations or "").strip():
                existing.observations = backfill
                existing.save(only=[Budget.observations])
            return existing

        rows = self._load_order_rows_for_client(order, client)
        if not rows:
            raise ValueError("El cliente no tiene mercadería en la orden de carga.")
        totals = self._totals_from_order_rows(rows)

        with database_proxy.atomic():
            budget = Budget.create(
                budget_number=self._next_budget_number(),
                client=client,
                load_order=order,
                origin=Budget.ORIGIN_LOAD_ORDER,
                issue_date=order.date,
                observations=self._observations_for_order_client(order, client),
                net_amount=totals["net_amount"],
                discount_amount=totals["discount_amount"],
                vat_amount=totals["vat_amount"],
                total_amount=totals["total_amount"],
                created_by=self.current_user,
            )
            for row in rows:
                BudgetItem.create(
                    budget=budget,
                    product=row.product,
                    source_order_product=row,
                    quantity=float(row.quantity),
                    unit=row.unit,
                    unit_price=float(row.precio_neto_unitario or 0),
                    discount_percentage=float(row.descuento_porcentaje or 0),
                    net_subtotal=float(row.neto_subtotal or 0),
                    discount_amount=float(row.descuento_importe or 0),
                    net_taxable=float(row.neto_gravado or 0),
                    vat_percentage=float(row.iva_porcentaje or 0),
                    vat_amount=float(row.iva_importe or 0),
                    total=float(row.total or 0),
                    observations=row.observations,
                )
            self._record("crear_desde_orden", budget)
        return budget

    def create_manual(
        self,
        *,
        client: Client,
        items: list[dict],
        issue_date: date | None = None,
        observations: str | None = None,
    ) -> Budget:
        from app.models.accounting import ClientAccountMovement

        client = Client.get_by_id(client.id)
        normalized_items = [self._normalize_manual_item(item) for item in items]
        if not normalized_items:
            raise ValueError("El presupuesto debe tener al menos un producto.")
        totals = self._totals_from_manual_items(normalized_items)
        movement_date = issue_date or date.today()
        due_date = movement_date + timedelta(days=max(int(client.dias_plazo_pago or 0), 0))

        with database_proxy.atomic():
            budget = Budget.create(
                budget_number=self._next_budget_number(),
                client=client,
                load_order=None,
                origin=Budget.ORIGIN_MANUAL,
                issue_date=movement_date,
                observations=observations,
                net_amount=totals["net_amount"],
                discount_amount=totals["discount_amount"],
                vat_amount=totals["vat_amount"],
                total_amount=totals["total_amount"],
                created_by=self.current_user,
            )
            for item in normalized_items:
                BudgetItem.create(budget=budget, **item)
            movement = ClientAccountMovement.create(
                client=client,
                load_order=None,
                budget=budget,
                payment=None,
                movement_type=ClientAccountMovement.TYPE_BUDGET_MANUAL,
                amount=0,
                net_amount=budget.net_amount,
                discount_amount=budget.discount_amount,
                vat_amount=budget.vat_amount,
                total_amount=budget.total_amount,
                currency=self.CURRENCY,
                movement_date=movement_date,
                due_date=due_date,
                description=f"Presupuesto {budget.display_number} - mercadería",
                observations=observations,
                source_ref=f"Budget:{budget.id}",
                reference=budget.display_number,
                is_reversal=False,
                created_by=self.current_user,
            )
            self._record("crear_manual", budget, movement=movement)
        return budget

    def annul_manual(self, budget: Budget, *, reason: str | None = None) -> Budget:
        from app.models.accounting import ClientAccountMovement

        budget = Budget.get_by_id(budget.id)
        reason = (reason or "").strip()
        if not reason:
            raise ValueError("Debe indicar el motivo de la anulación.")
        if budget.origin != Budget.ORIGIN_MANUAL:
            raise ValueError("Solo los presupuestos manuales se anulan con este flujo.")
        if budget.status == Budget.STATUS_ANNULLED:
            return budget
        original = ClientAccountMovement.get_or_none(
            (ClientAccountMovement.budget == budget)
            & (ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_BUDGET_MANUAL)
            & (ClientAccountMovement.is_reversal == False)  # noqa: E712
        )
        if original is None:
            raise ValueError("No se encontró el movimiento original del presupuesto.")

        with database_proxy.atomic():
            ClientAccountMovement.get_or_create(
                client=budget.client,
                budget=budget,
                movement_type=ClientAccountMovement.TYPE_BUDGET_MANUAL_REVERSAL,
                is_reversal=True,
                defaults={
                    "load_order": None,
                    "amount": -original.amount,
                    "net_amount": -original.net_amount,
                    "discount_amount": -original.discount_amount,
                    "vat_amount": -original.vat_amount,
                    "total_amount": -original.total_amount,
                    "currency": original.currency,
                    "movement_date": date.today(),
                    "due_date": original.due_date,
                    "description": f"Anulación {budget.display_number}",
                    "observations": budget.observations,
                    "source_ref": f"Budget:{budget.id}",
                    "reference": budget.display_number,
                    "reverses": original,
                    "created_by": self.current_user,
                },
            )
            budget.status = Budget.STATUS_ANNULLED
            budget.save(only=[Budget.status])
            self._record("anular_manual", budget, reason=reason)
        return budget

    def _load_order_rows_for_client(self, order: LoadOrder, client: Client) -> list[LoadOrderProduct]:
        rows = list(
            LoadOrderProduct.select(LoadOrderProduct)
            .join(LoadOrderDestination, on=LoadOrderProduct.destination)
            .where(
                (LoadOrderProduct.order == order)
                & (LoadOrderDestination.client == client)
            )
            .order_by(LoadOrderProduct.id)
        )
        if rows:
            return rows
        if order.client_id == client.id:
            return list(
                LoadOrderProduct.select()
                .where(
                    (LoadOrderProduct.order == order)
                    & (LoadOrderProduct.destination.is_null(True))
                )
                .order_by(LoadOrderProduct.id)
            )
        return []

    def _clients_for_order(self, order: LoadOrder) -> list[Client]:
        clients = []
        seen = set()
        for destination in order.destinations.order_by(LoadOrderDestination.sequence):
            if destination.client_id not in seen:
                clients.append(destination.client)
                seen.add(destination.client_id)
        if not clients and order.client_id is not None:
            clients.append(order.client)
        return clients

    @staticmethod
    def _totals_from_order_rows(rows: list[LoadOrderProduct]) -> dict[str, float]:
        return {
            "net_amount": round(sum(float(row.neto_subtotal or 0) for row in rows), 2),
            "discount_amount": round(sum(float(row.descuento_importe or 0) for row in rows), 2),
            "vat_amount": round(sum(float(row.iva_importe or 0) for row in rows), 2),
            "total_amount": round(sum(float(row.total or 0) for row in rows), 2),
        }

    def _normalize_manual_item(self, item: dict) -> dict:
        product = item.get("product")
        if not isinstance(product, Product):
            raise ValueError("Producto inválido en presupuesto manual.")
        quantity = float(item.get("quantity") or 0)
        if quantity <= 0:
            raise ValueError("La cantidad del presupuesto debe ser mayor a cero.")
        unit_price = float(item.get("unit_price", item.get("precio_neto_unitario", 0)) or 0)
        if unit_price < 0:
            raise ValueError("El precio unitario no puede ser negativo.")
        discount_percentage = float(item.get("discount_percentage", item.get("descuento_porcentaje", 0)) or 0)
        vat_percentage = float(item.get("vat_percentage", item.get("iva_porcentaje", 21)) or 0)
        net_subtotal = round(quantity * unit_price, 2)
        discount_amount = round(net_subtotal * discount_percentage / 100, 2)
        net_taxable = round(net_subtotal - discount_amount, 2)
        vat_amount = round(net_taxable * vat_percentage / 100, 2)
        total = round(net_taxable + vat_amount, 2)
        return {
            "product": product,
            "source_order_product": None,
            "quantity": quantity,
            "unit": str(item.get("unit") or "UN"),
            "unit_price": unit_price,
            "discount_percentage": discount_percentage,
            "net_subtotal": net_subtotal,
            "discount_amount": discount_amount,
            "net_taxable": net_taxable,
            "vat_percentage": vat_percentage,
            "vat_amount": vat_amount,
            "total": total,
            "observations": item.get("observations"),
        }

    @staticmethod
    def _totals_from_manual_items(items: list[dict]) -> dict[str, float]:
        return {
            "net_amount": round(sum(item["net_subtotal"] for item in items), 2),
            "discount_amount": round(sum(item["discount_amount"] for item in items), 2),
            "vat_amount": round(sum(item["vat_amount"] for item in items), 2),
            "total_amount": round(sum(item["total"] for item in items), 2),
        }

    def _record(
        self,
        action: str,
        budget: Budget,
        movement=None,
        reason: str | None = None,
    ) -> None:
        self.audit_service.record(
            user=self.current_user,
            module="Presupuestos",
            action=action,
            record_ref=f"Budget:{budget.id}",
            new_value={
                "budget_number": budget.budget_number,
                "client_id": budget.client_id,
                "load_order_id": budget.load_order_id,
                "origin": budget.origin,
                "status": budget.status,
                "total_amount": budget.total_amount,
                "movement_id": movement.id if movement is not None else None,
                "reason": reason,
            },
            observation=reason,
        )
