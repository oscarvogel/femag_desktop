from datetime import date, timedelta

from app.config.database import database_proxy
from app.models.budgets import Budget, BudgetItem
from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
from app.models.masters import Client, Product
from app.models.system import NumberSequence
from app.services.audit_service import AuditService
from app.services.client_service import ClientService
from app.services.money import (
    BudgetTotals,
    LineAmounts,
    assert_totals_match_items,
    compute_line_amounts,
    compute_totals,
    money_to_float,
    quantize_money,
    totals_from_persisted_items,
    to_decimal,
)


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

        # Los importes de cada renglón se recalculan con la rutina monetaria
        # única y se persisten a partir de ese mismo resultado. Los totales de
        # cabecera se derivan de esos renglones, nunca de otra suma: por
        # construcción, SUM(renglones) == total general.
        lines = [self._line_amounts_from_order_row(row) for row in rows]
        totals = compute_totals(lines)

        with database_proxy.atomic():
            budget = Budget.create(
                budget_number=self._next_budget_number(),
                client=client,
                load_order=order,
                origin=Budget.ORIGIN_LOAD_ORDER,
                issue_date=order.date,
                observations=self._observations_for_order_client(order, client),
                net_amount=money_to_float(totals.net_amount),
                discount_amount=money_to_float(totals.discount_amount),
                vat_amount=money_to_float(totals.vat_amount),
                total_amount=money_to_float(totals.total_amount),
                created_by=self.current_user,
            )
            for row, amounts in zip(rows, lines):
                BudgetItem.create(
                    budget=budget,
                    product=row.product,
                    source_order_product=row,
                    quantity=money_to_float(amounts.quantity),
                    unit=str(row.unit or ""),
                    unit_price=money_to_float(amounts.unit_price),
                    discount_percentage=money_to_float(amounts.discount_percentage),
                    net_subtotal=money_to_float(amounts.net_subtotal),
                    discount_amount=money_to_float(amounts.discount_amount),
                    net_taxable=money_to_float(amounts.net_taxable),
                    vat_percentage=money_to_float(amounts.vat_percentage),
                    vat_amount=money_to_float(amounts.vat_amount),
                    total=money_to_float(amounts.total),
                    observations=row.observations,
                )
            self._record("crear_desde_orden", budget)
        self.assert_monetary_integrity(budget)
        return budget

    def create_manual(
        self,
        *,
        client: Client,
        items: list[dict],
        issue_date: date | None = None,
        observations: str | None = None,
    ) -> Budget:
        client = Client.get_by_id(client.id)
        ClientService.ensure_active(client)
        from app.models.accounting import ClientAccountMovement

        client = Client.get_by_id(client.id)
        normalized_items = [self._normalize_manual_item(item) for item in items]
        if not normalized_items:
            raise ValueError("El presupuesto debe tener al menos un producto.")
        totals = self._totals_from_normalized_items(normalized_items)
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
                net_amount=money_to_float(totals.net_amount),
                discount_amount=money_to_float(totals.discount_amount),
                vat_amount=money_to_float(totals.vat_amount),
                total_amount=money_to_float(totals.total_amount),
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
        self.assert_monetary_integrity(budget)
        return budget

    def annul_manual(self, budget: Budget, *, reason: str | None = None) -> Budget:
        from app.models.accounting import ClientAccountMovement

        budget = Budget.get_by_id(budget.id)
        if budget.origin != Budget.ORIGIN_MANUAL:
            raise ValueError("Solo los presupuestos manuales se anulan con este flujo.")
        if budget.status == Budget.STATUS_ANNULLED:
            return budget
        reason = (reason or "").strip()
        if not reason:
            raise ValueError("Debe indicar el motivo de la anulación.")
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

    def _line_amounts_from_order_row(self, row: LoadOrderProduct) -> LineAmounts:
        """Recalcula los importes de un renglón de orden con la rutina única.

        Se usan cantidad, precio, descuento e IVA del renglón y se recalcula el
        resto, de modo que el presupuesto no herede totales calculados con
        otra aritmética.
        """
        return compute_line_amounts(
            quantity=row.quantity,
            unit_price=row.precio_neto_unitario,
            discount_percentage=row.descuento_porcentaje,
            vat_percentage=row.iva_porcentaje,
        )

    def totals_for_order_rows(self, order: LoadOrder, client: Client) -> BudgetTotals:
        """Totales derivados de los renglones de la orden, sin persistir.

        Usa la misma rutina de cálculo que la emisión del presupuesto para que
        ningún consumidor pueda obtener un importe por otra vía.
        """
        rows = self._load_order_rows_for_client(order, client)
        return compute_totals(self._line_amounts_from_order_row(row) for row in rows)

    def assert_monetary_integrity(self, budget: Budget) -> None:
        """Verifica que el detalle de un presupuesto sume su total general.

        Se invoca antes de emitir o imprimir. Si no coincide al centavo, lanza
        ``MonetaryIntegrityError`` con presupuesto, orden, cliente y ambos
        importes para que no se genere un documento con importes contradictorios.
        """
        items = list(budget.items)
        if not items:
            return
        assert_totals_match_items(
            items_totals=totals_from_persisted_items(items),
            header_totals=BudgetTotals(
                net_amount=quantize_money(budget.net_amount),
                discount_amount=quantize_money(budget.discount_amount),
                vat_amount=quantize_money(budget.vat_amount),
                total_amount=quantize_money(budget.total_amount),
            ),
            document_reference=f"{budget.budget_number:06d}",
            order_reference=budget.load_order_reference,
            client_name=budget.client.name if budget.client_id else None,
        )

    def _normalize_manual_item(self, item: dict) -> dict:
        product = item.get("product")
        if not isinstance(product, Product):
            raise ValueError("Producto inválido en presupuesto manual.")
        quantity = to_decimal(item.get("quantity"))
        if quantity <= 0:
            raise ValueError("La cantidad del presupuesto debe ser mayor a cero.")
        unit_price = to_decimal(
            item.get("unit_price", item.get("precio_neto_unitario"))
        )
        if unit_price < 0:
            raise ValueError("El precio unitario no puede ser negativo.")
        discount_percentage = to_decimal(
            item.get("discount_percentage", item.get("descuento_porcentaje"))
        )
        vat_percentage = item.get(
            "vat_percentage", item.get("iva_porcentaje", 21)
        )
        amounts = compute_line_amounts(
            quantity=quantity,
            unit_price=unit_price,
            discount_percentage=discount_percentage,
            vat_percentage=vat_percentage,
        )
        return {
            "product": product,
            "source_order_product": None,
            "quantity": money_to_float(amounts.quantity),
            "unit": str(item.get("unit") or "UN"),
            "unit_price": money_to_float(amounts.unit_price),
            "discount_percentage": money_to_float(amounts.discount_percentage),
            "net_subtotal": money_to_float(amounts.net_subtotal),
            "discount_amount": money_to_float(amounts.discount_amount),
            "net_taxable": money_to_float(amounts.net_taxable),
            "vat_percentage": money_to_float(amounts.vat_percentage),
            "vat_amount": money_to_float(amounts.vat_amount),
            "total": money_to_float(amounts.total),
            "observations": item.get("observations"),
        }

    @staticmethod
    def _totals_from_normalized_items(items: list[dict]) -> BudgetTotals:
        """Totales de cabecera derivados de los renglones ya calculados."""
        return compute_totals(
            LineAmounts(
                quantity=to_decimal(item["quantity"]),
                unit_price=to_decimal(item["unit_price"]),
                discount_percentage=to_decimal(item["discount_percentage"]),
                net_subtotal=to_decimal(item["net_subtotal"]),
                discount_amount=to_decimal(item["discount_amount"]),
                net_taxable=to_decimal(item["net_taxable"]),
                vat_percentage=to_decimal(item["vat_percentage"]),
                vat_amount=to_decimal(item["vat_amount"]),
                total=to_decimal(item["total"]),
            )
            for item in items
        )

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
