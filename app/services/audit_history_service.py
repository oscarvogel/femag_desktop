from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models.audit import AuditLog
from app.models.accounting import ClientAccountMovement
from app.models.budgets import Budget
from app.models.load_orders import LoadOrder, LoadOrderStatusHistory
from app.models.payments import ClientPayment
from app.models.remittances import Remittance


@dataclass(frozen=True)
class AuditHistoryEvent:
    occurred_at: datetime
    user: str | None
    action: str
    previous_status: str | None = None
    new_status: str | None = None
    reason: str | None = None
    detail: str | None = None
    source: str = "audit"


class AuditHistoryService:
    """Read-only projection of business history from existing audit sources."""

    LOAD_ORDER_MODULE = "Ordenes de carga"

    def load_order_history(self, order: LoadOrder) -> list[AuditHistoryEvent]:
        order = LoadOrder.get_by_id(order.id)
        events: list[AuditHistoryEvent] = []

        for row in (
            LoadOrderStatusHistory.select()
            .where(LoadOrderStatusHistory.order == order)
            .order_by(LoadOrderStatusHistory.created_at, LoadOrderStatusHistory.id)
        ):
            if row.old_status is None:
                action = "Orden creada"
            elif row.new_status == LoadOrder.STATUS_ISSUED:
                action = "Orden emitida"
            elif row.new_status == LoadOrder.STATUS_ANNULLED:
                action = "Orden anulada"
            elif row.new_status == LoadOrder.STATUS_CLOSED:
                action = "Orden cerrada"
            else:
                action = "Cambio de estado"
            events.append(
                AuditHistoryEvent(
                    occurred_at=row.created_at,
                    user=row.user,
                    action=action,
                    previous_status=row.old_status,
                    new_status=row.new_status,
                    reason=row.observation,
                    source="status_history",
                )
            )

        record_ref = f"LoadOrder:{order.id}"
        audit_rows = (
            AuditLog.select()
            .where(
                AuditLog.module == self.LOAD_ORDER_MODULE,
                AuditLog.record_ref == record_ref,
            )
            .order_by(AuditLog.occurred_at, AuditLog.id)
        )
        for row in audit_rows:
            # Creation/status changes are already represented by LoadOrderStatusHistory.
            # Driver lock/release events remain in AuditLog as technical trace, but are
            # intentionally hidden from the business timeline shown to users.
            if row.action in {
                "crear",
                "cambiar estado",
                "anular",
                "bloquear chofer",
                "liberar chofer",
            }:
                continue
            events.append(
                AuditHistoryEvent(
                    occurred_at=row.occurred_at,
                    user=row.user,
                    action=self._friendly_action(row.action),
                    reason=row.observation,
                    detail=self._detail_from_audit(row),
                    source="audit",
                )
            )

        return sorted(events, key=lambda event: event.occurred_at)


    def remittance_history(self, remittance: Remittance) -> list[AuditHistoryEvent]:
        remittance = Remittance.get_by_id(remittance.id)
        return self._audit_record_history(
            module="Remitos",
            record_ref=f"Remittance:{remittance.id}",
            labels={
                "crear": "Remito creado",
                "modificar": "Remito modificado",
                "emitir": "Remito emitido",
                "anular": "Remito anulado",
                "imprimir": "Remito impreso",
                "reimprimir": "Remito reimpreso",
            },
            fallback_detail=(
                f"{remittance.remittance_number} · {remittance.client_name}"
            ),
        )

    def payment_history(self, payment: ClientPayment) -> list[AuditHistoryEvent]:
        payment = ClientPayment.get_by_id(payment.id)
        return self._audit_record_history(
            module="Cuenta corriente",
            record_ref=f"ClientPayment:{payment.id}",
            labels={
                "registrar_pago": "Pago registrado",
                "anular_pago": "Pago anulado",
            },
            fallback_detail=(
                f"{payment.receipt_number} · {payment.client.name} · "
                f"$ {payment.amount:,.2f}"
            ),
        )

    def account_movement_history(
        self, movement: ClientAccountMovement
    ) -> list[AuditHistoryEvent]:
        movement = ClientAccountMovement.get_by_id(movement.id)
        original = movement.reverses if movement.is_reversal and movement.reverses_id else movement
        return self._audit_record_history(
            module="Cuenta corriente",
            record_ref=f"ClientAccountMovement:{original.id}",
            labels={
                "registrar_debito_manual": "Débito manual registrado",
                "reversar_debito_manual": "Débito manual reversado",
                "registrar_credito_manual": "Crédito manual registrado",
                "reversar_credito_manual": "Crédito manual reversado",
            },
            fallback_detail=(
                f"{original.client.name} · $ {abs(original.total_amount):,.2f} · "
                f"{original.description}"
            ),
        )

    def budget_history(self, budget: Budget) -> list[AuditHistoryEvent]:
        budget = Budget.get_by_id(budget.id)
        return self._audit_record_history(
            module="Presupuestos",
            record_ref=f"Budget:{budget.id}",
            labels={
                "crear_desde_orden": "Presupuesto creado desde orden",
                "crear_manual": "Presupuesto manual creado",
                "imprimir": "Presupuesto impreso",
                "anular_manual": "Presupuesto anulado",
            },
            fallback_detail=(
                f"{budget.display_number} · {budget.client.name} · "
                f"$ {budget.total_amount:,.2f}"
            ),
        )

    def _audit_record_history(
        self,
        *,
        module: str,
        record_ref: str,
        labels: dict[str, str],
        fallback_detail: str | None = None,
    ) -> list[AuditHistoryEvent]:
        rows = (
            AuditLog.select()
            .where(AuditLog.module == module, AuditLog.record_ref == record_ref)
            .order_by(AuditLog.occurred_at, AuditLog.id)
        )
        events: list[AuditHistoryEvent] = []
        for row in rows:
            old_value = row.old_value if isinstance(row.old_value, dict) else {}
            new_value = row.new_value if isinstance(row.new_value, dict) else {}
            previous_status = old_value.get("status")
            new_status = new_value.get("status")
            reason = (
                row.observation
                or new_value.get("reason")
                or new_value.get("annulment_reason")
            )
            detail = self._financial_detail(new_value) or fallback_detail
            events.append(
                AuditHistoryEvent(
                    occurred_at=row.occurred_at,
                    user=row.user,
                    action=labels.get(
                        row.action,
                        row.action.replace("_", " ").strip().capitalize(),
                    ),
                    previous_status=str(previous_status) if previous_status else None,
                    new_status=str(new_status) if new_status else None,
                    reason=str(reason) if reason else None,
                    detail=detail,
                    source="audit",
                )
            )
        return events

    @staticmethod
    def _financial_detail(value: dict) -> str | None:
        parts: list[str] = []
        amount = value.get("amount")
        total = value.get("total_amount")
        receipt = value.get("receipt_number")
        reference = value.get("reference")
        if receipt:
            parts.append(str(receipt))
        if reference:
            parts.append(str(reference))
        numeric = total if total is not None else amount
        if numeric is not None:
            try:
                parts.append(f"$ {abs(float(numeric)):,.2f}")
            except (TypeError, ValueError):
                pass
        return " · ".join(parts) or None

    @staticmethod
    def _friendly_action(action: str) -> str:
        labels = {
            "modificar": "Orden modificada",
            "imprimir": "Orden impresa",
            "reimprimir": "Orden reimpresa",
            "exportar_excel": "Excel exportado",
            "exportar_xlsx": "Excel exportado",
        }
        return labels.get(action, action.replace("_", " ").strip().capitalize())

    @staticmethod
    def _detail_from_audit(row: AuditLog) -> str | None:
        if row.action == "modificar":
            return "Se actualizaron datos de la orden."
        if row.action in {"imprimir", "reimprimir"}:
            return "Documento generado desde FEMAG."
        if row.action in {"exportar_excel", "exportar_xlsx"}:
            return "Se generó el archivo editable de la orden."
        return None
