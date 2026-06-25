from pathlib import Path

from app.models.load_orders import LoadOrder
from app.services.audit_service import AuditService
from app.services.load_order_print_service import LoadOrderPrintService
from app.services.load_order_service import LoadOrderService


class LoadOrderOperationService:
    def __init__(
        self,
        current_user: str,
        *,
        prints_dir: str | Path = Path("docs") / "prints",
        audit_service: AuditService | None = None,
    ):
        self.current_user = current_user
        self.prints_dir = Path(prints_dir)
        self.audit_service = audit_service or AuditService()
        self.load_orders = LoadOrderService(current_user=current_user, audit_service=self.audit_service)
        self.prints = LoadOrderPrintService(current_user=current_user, audit_service=self.audit_service)

    def issue(self, order: LoadOrder) -> LoadOrder:
        order = LoadOrder.get_by_id(order.id)
        if order.status == LoadOrder.STATUS_ANNULLED:
            raise ValueError("No se puede emitir una orden anulada.")
        if order.status == LoadOrder.STATUS_CLOSED:
            raise ValueError("No se puede emitir una orden cerrada.")
        if order.status == LoadOrder.STATUS_ISSUED:
            raise ValueError("La orden ya esta emitida.")
        return self.load_orders.change_status(order, LoadOrder.STATUS_ISSUED, reason="Emitida desde pantalla")

    def print_order(self, order: LoadOrder) -> Path:
        order = self._require_printable(order)
        return self.prints.export_combined(order, self.prints_dir)

    def reprint_order(self, order: LoadOrder) -> Path:
        order = self._require_printable(order)
        return self.prints.export_combined(order, self.prints_dir, reprint=True)

    def annul(self, order: LoadOrder, *, can_annul: bool) -> LoadOrder:
        order = LoadOrder.get_by_id(order.id)
        if order.status == LoadOrder.STATUS_ANNULLED:
            raise ValueError("La orden ya esta anulada.")
        if order.status == LoadOrder.STATUS_CLOSED:
            raise ValueError("No se puede anular una orden cerrada.")
        return self.load_orders.annul_order(order, can_annul=can_annul, reason="Anulada desde pantalla")

    def _require_printable(self, order: LoadOrder) -> LoadOrder:
        order = LoadOrder.get_by_id(order.id)
        if order.status == LoadOrder.STATUS_PENDING:
            raise ValueError("Emita la orden antes de imprimir.")
        if order.status == LoadOrder.STATUS_ANNULLED:
            raise ValueError("No se puede imprimir una orden anulada.")
        if order.status == LoadOrder.STATUS_CLOSED:
            raise ValueError("No se puede imprimir una orden cerrada.")
        return order
