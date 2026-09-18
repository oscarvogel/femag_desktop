from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models.audit import AuditLog
from app.models.load_orders import LoadOrder, LoadOrderStatusHistory


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
            if row.action in {"crear", "cambiar estado", "anular"}:
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
