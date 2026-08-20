from __future__ import annotations

from peewee import IntegrityError

from app.config.database import database_proxy
from app.models.base import utc_now
from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrder, LoadOrderClosure, LoadOrderProduct, LoadOrderReturnLine
from app.models.masters import Client
from app.models.payments import ClientPayment
from app.services.audit_service import AuditService
from app.services.client_payment_service import ClientPaymentService
from app.services.load_order_service import LoadOrderService


class LoadOrderClosureError(ValueError):
    pass


class LoadOrderClosureService:
    """Own the persisted close/reopen lifecycle of an issued load order."""

    PAYMENT_STATUS_UNPAID = "sin_pago"
    PAYMENT_STATUS_PARTIAL = "parcial"
    PAYMENT_STATUS_PAID = "cobrada"

    def __init__(self, current_user: str, audit_service: AuditService | None = None):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()
        self.load_orders = LoadOrderService(
            current_user=current_user,
            audit_service=self.audit_service,
        )
        self.payments = ClientPaymentService(
            current_user=current_user,
            audit_service=self.audit_service,
        )

    def close_order(
        self,
        order: LoadOrder,
        *,
        observations: str | None = None,
        payments: list[dict] | None = None,
        returns: list[dict] | None = None,
        no_payment_reason: str | None = None,
    ) -> LoadOrderClosure:
        order = self._require_order(order)
        if order.status != LoadOrder.STATUS_ISSUED:
            raise LoadOrderClosureError("Solo se pueden cerrar ordenes emitidas.")

        normalized_observations = (observations or "").strip() or None
        normalized_no_payment_reason = (no_payment_reason or "").strip() or None
        payment_specs = self._normalize_payment_specs(order, payments or [])
        return_specs = self._normalize_return_specs(order, returns or [])
        if not payment_specs and normalized_no_payment_reason is None:
            raise LoadOrderClosureError(
                "Debe registrar al menos un pago o indicar el motivo del cierre sin pago."
            )
        if payment_specs:
            normalized_no_payment_reason = None
        with database_proxy.atomic():
            order = LoadOrder.get_by_id(order.id)
            if order.status != LoadOrder.STATUS_ISSUED:
                raise LoadOrderClosureError("Solo se pueden cerrar ordenes emitidas.")
            if self.active_closure(order) is not None:
                raise LoadOrderClosureError("La orden ya tiene un cierre de entrega activo.")
            try:
                closure = LoadOrderClosure.create(
                    order=order,
                    status=LoadOrderClosure.STATUS_ACTIVE,
                    active_marker=True,
                    closed_by=self.current_user,
                    observations=normalized_observations,
                    no_payment_reason=normalized_no_payment_reason,
                )
            except IntegrityError as exc:
                raise LoadOrderClosureError("La orden ya tiene un cierre de entrega activo.") from exc
            for payment_spec in payment_specs:
                self.payments.register_payment(closure=closure, **payment_spec)
            for return_spec in return_specs:
                return_line = LoadOrderReturnLine.create(
                    closure=closure,
                    order_product=return_spec["order_product"],
                    client=return_spec["client"],
                    quantity=return_spec["quantity"],
                    reason=return_spec["reason"],
                    unit_price=return_spec["unit_price"],
                    credit_amount=return_spec["credit_amount"],
                    created_by=self.current_user,
                )
                self.audit_service.record(
                    user=self.current_user,
                    module="Ordenes de carga",
                    action="registrar devolucion",
                    record_ref=f"LoadOrderReturnLine:{return_line.id}",
                    new_value={
                        "closure_id": closure.id,
                        "order_id": order.id,
                        "order_product_id": return_line.order_product_id,
                        "client_id": return_line.client_id,
                        "quantity": return_line.quantity,
                        "reason": return_line.reason,
                        "credit_amount": return_line.credit_amount,
                    },
                )
            self.load_orders._change_status(
                order,
                LoadOrder.STATUS_CLOSED,
                reason="Cierre de entrega",
            )
            self.audit_service.record(
                user=self.current_user,
                module="Ordenes de carga",
                action="cerrar entrega",
                record_ref=f"LoadOrderClosure:{closure.id}",
                new_value={
                    "order_id": order.id,
                    "status": closure.status,
                    "observations": closure.observations,
                    "no_payment_reason": closure.no_payment_reason,
                    "payment_ids": [payment.id for payment in closure.payments],
                    "return_line_ids": [row.id for row in closure.return_lines],
                    "return_credit_amount": self.return_credit_total(closure),
                    "payment_status": self.payment_status(closure),
                },
            )
        return LoadOrderClosure.get_by_id(closure.id)

    def reopen_order(self, order: LoadOrder, *, reason: str) -> LoadOrder:
        order = self._require_order(order)
        normalized_reason = (reason or "").strip()
        if not normalized_reason:
            raise LoadOrderClosureError("Debe indicar el motivo de reapertura.")

        with database_proxy.atomic():
            order = LoadOrder.get_by_id(order.id)
            if order.status != LoadOrder.STATUS_CLOSED:
                raise LoadOrderClosureError("Solo se pueden reabrir ordenes cerradas.")
            closure = self.active_closure(order)
            if closure is None:
                raise LoadOrderClosureError("La orden cerrada no tiene un cierre de entrega activo.")
            if closure.payments.where(ClientPayment.status == ClientPayment.STATUS_ACTIVE).exists():
                raise LoadOrderClosureError(
                    "Debe anular los pagos activos del cierre antes de reabrir la entrega."
                )

            self.load_orders._change_status(
                order,
                LoadOrder.STATUS_ISSUED,
                reason=f"Reapertura de entrega: {normalized_reason}",
            )
            reopened_at = utc_now()
            closure.status = LoadOrderClosure.STATUS_REOPENED
            closure.active_marker = None
            closure.reopened_at = reopened_at
            closure.reopened_by = self.current_user
            closure.reopen_reason = normalized_reason
            closure.save()
            self.audit_service.record(
                user=self.current_user,
                module="Ordenes de carga",
                action="reabrir entrega",
                record_ref=f"LoadOrderClosure:{closure.id}",
                old_value={"status": LoadOrderClosure.STATUS_ACTIVE},
                new_value={
                    "order_id": order.id,
                    "status": closure.status,
                    "reopened_at": reopened_at.isoformat(timespec="seconds"),
                    "reopened_by": self.current_user,
                    "reason": normalized_reason,
                    "return_line_ids": [row.id for row in closure.return_lines],
                },
            )
        return LoadOrder.get_by_id(order.id)

    def payment_summary(self, closure: LoadOrderClosure) -> list[dict]:
        closure = LoadOrderClosure.get_by_id(closure.id)
        totals = self._order_totals_by_client(closure.order)
        paid_by_client = {client_id: 0.0 for client_id in totals}
        active_payments = ClientPayment.select().where(
            (ClientPayment.closure == closure)
            & (ClientPayment.status == ClientPayment.STATUS_ACTIVE)
        )
        for payment in active_payments:
            paid_by_client[payment.client_id] = round(
                paid_by_client.get(payment.client_id, 0.0) + float(payment.amount),
                2,
            )

        summary = []
        for client_id, total in totals.items():
            paid = paid_by_client.get(client_id, 0.0)
            balance = max(round(total - paid, 2), 0.0)
            if paid <= 0:
                status = self.PAYMENT_STATUS_UNPAID
            elif balance <= 0:
                status = self.PAYMENT_STATUS_PAID
            else:
                status = self.PAYMENT_STATUS_PARTIAL
            summary.append(
                {
                    "client": Client.get_by_id(client_id),
                    "total": total,
                    "paid": paid,
                    "balance": balance,
                    "status": status,
                }
            )
        return summary

    def payment_status(self, closure: LoadOrderClosure) -> str:
        statuses = {row["status"] for row in self.payment_summary(closure)}
        if statuses == {self.PAYMENT_STATUS_PAID}:
            return self.PAYMENT_STATUS_PAID
        if statuses == {self.PAYMENT_STATUS_UNPAID}:
            return self.PAYMENT_STATUS_UNPAID
        return self.PAYMENT_STATUS_PARTIAL

    def return_credit_total(self, closure: LoadOrderClosure) -> float:
        closure = LoadOrderClosure.get_by_id(closure.id)
        return round(sum(float(row.credit_amount) for row in closure.return_lines), 2)

    def active_closure(self, order: LoadOrder) -> LoadOrderClosure | None:
        order = self._require_order(order)
        return (
            LoadOrderClosure.select()
            .where(
                (LoadOrderClosure.order == order)
                & (LoadOrderClosure.active_marker == True)  # noqa: E712
                & (LoadOrderClosure.status == LoadOrderClosure.STATUS_ACTIVE)
            )
            .order_by(LoadOrderClosure.id.desc())
            .first()
        )

    def _require_order(self, order: LoadOrder) -> LoadOrder:
        if order is None or not isinstance(order, LoadOrder) or order.id is None:
            raise LoadOrderClosureError("Debe seleccionar una orden valida.")
        try:
            return LoadOrder.get_by_id(order.id)
        except LoadOrder.DoesNotExist as exc:
            raise LoadOrderClosureError("La orden seleccionada no existe.") from exc

    def _normalize_payment_specs(self, order: LoadOrder, payments: list[dict]) -> list[dict]:
        totals = self._order_totals_by_client(order)
        paid_by_client = {client_id: 0.0 for client_id in totals}
        normalized = []
        for spec in payments:
            client = spec.get("client")
            if not isinstance(client, Client) or client.id not in totals:
                raise LoadOrderClosureError("Cada pago debe corresponder a un cliente de la orden.")
            amount = round(float(spec.get("amount") or 0), 2)
            if amount <= 0:
                raise LoadOrderClosureError("El monto de cada pago debe ser mayor a cero.")
            paid_by_client[client.id] = round(paid_by_client[client.id] + amount, 2)
            if paid_by_client[client.id] > totals[client.id] + 0.009:
                raise LoadOrderClosureError(
                    f"Los pagos de {client.name} superan el total de la orden."
                )
            normalized.append(
                {
                    "client": client,
                    "amount": amount,
                    "payment_date": spec.get("payment_date"),
                    "method": spec.get("method", ClientPayment.METHOD_CASH),
                    "reference": (spec.get("reference") or "").strip() or None,
                    "observations": (spec.get("observations") or "").strip() or None,
                }
            )
        return normalized

    def _normalize_return_specs(self, order: LoadOrder, returns: list[dict]) -> list[dict]:
        normalized = []
        seen_line_ids = set()
        for spec in returns:
            line = spec.get("order_product")
            if not isinstance(line, LoadOrderProduct) or line.id is None:
                raise LoadOrderClosureError("Cada devolucion debe corresponder a un renglon de la orden.")
            try:
                line = LoadOrderProduct.get_by_id(line.id)
            except LoadOrderProduct.DoesNotExist as exc:
                raise LoadOrderClosureError("El renglon indicado para la devolucion no existe.") from exc
            if line.order_id != order.id:
                raise LoadOrderClosureError("No se puede devolver un renglon de otra orden.")
            if line.id in seen_line_ids:
                raise LoadOrderClosureError("Cada renglon puede registrarse una sola vez como devolucion.")
            seen_line_ids.add(line.id)
            quantity = round(float(spec.get("quantity") or 0), 3)
            if quantity <= 0:
                raise LoadOrderClosureError("La cantidad devuelta debe ser mayor a cero.")
            if quantity > float(line.quantity) + 0.0005:
                raise LoadOrderClosureError(
                    f"La devolucion de {line.product.name} supera la cantidad entregada."
                )
            reason = (spec.get("reason") or "").strip()
            if not reason:
                raise LoadOrderClosureError("Debe indicar el motivo de cada devolucion.")
            client = line.destination.client if line.destination_id else order.client
            if client is None:
                raise LoadOrderClosureError("El renglon devuelto no tiene cliente asociado.")
            unit_price = round(float(line.total) / float(line.quantity), 6) if line.quantity else 0.0
            credit_amount = round(unit_price * quantity, 2)
            normalized.append(
                {
                    "order_product": line,
                    "client": client,
                    "quantity": quantity,
                    "reason": reason,
                    "unit_price": unit_price,
                    "credit_amount": credit_amount,
                }
            )
        return normalized

    def _order_totals_by_client(self, order: LoadOrder) -> dict[int, float]:
        movements = ClientAccountMovement.select().where(
            (ClientAccountMovement.load_order == order)
            & (ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_LOAD_ORDER)
            & (ClientAccountMovement.is_reversal == False)  # noqa: E712
        )
        totals = {
            movement.client_id: round(float(movement.total_amount), 2)
            for movement in movements
        }
        if not totals:
            for line in order.products:
                client_id = (
                    line.destination.client_id
                    if line.destination_id is not None
                    else order.client_id
                )
                if client_id is not None:
                    totals[client_id] = round(
                        totals.get(client_id, 0.0) + float(line.total),
                        2,
                    )
        if not totals and order.client_id is not None:
            totals[order.client_id] = 0.0
        if not totals:
            raise LoadOrderClosureError("La orden no tiene clientes para registrar el cierre.")
        return totals
