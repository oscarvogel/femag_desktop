from datetime import datetime
from pathlib import Path

from app.models.audit import AuditLog
from app.models.load_orders import LoadOrder
from app.services.account_ledger_service import AccountLedgerService
from app.services.audit_service import AuditService
from app.services.client_credit_service import ClientCreditService
from app.services.qr_load_order_print_service import ConsolidatedLoadOrderPrintService
from app.services.load_order_service import LoadOrderService


class LoadOrderOperationService:
    def __init__(
        self,
        current_user: str,
        *,
        prints_dir: str | Path = Path("outputs") / "load_orders",
        audit_service: AuditService | None = None,
    ):
        self.current_user = current_user
        self.prints_dir = Path(prints_dir)
        self.audit_service = audit_service or AuditService()
        self.load_orders = LoadOrderService(current_user=current_user, audit_service=self.audit_service)
        self.prints = ConsolidatedLoadOrderPrintService(current_user=current_user, audit_service=self.audit_service)
        self.account_ledger = AccountLedgerService(current_user=current_user, audit_service=self.audit_service)

    def issue(self, order: LoadOrder) -> LoadOrder:
        order = LoadOrder.get_by_id(order.id)
        if order.status == LoadOrder.STATUS_ANNULLED:
            raise ValueError("No se puede emitir una orden anulada.")
        if order.status == LoadOrder.STATUS_CLOSED:
            raise ValueError("No se puede emitir una orden cerrada.")
        if order.status == LoadOrder.STATUS_ISSUED:
            raise ValueError("La orden ya esta emitida.")
        composition = self.load_orders.composition(order)
        if not composition.can_issue:
            details = " ".join(issue.message for issue in composition.issues)
            raise ValueError(f"No se puede emitir la orden: {details}")
        ClientCreditService.assert_can_issue(order)
        issued = self.load_orders.change_status(order, LoadOrder.STATUS_ISSUED, reason="Emitida desde pantalla")
        self.account_ledger.generate_for_load_order(issued)
        return issued

    def print_order(self, order: LoadOrder) -> Path:
        order = self._require_printable(order)
        return self.prints.export_pdf(order, self.prints_dir)

    def reprint_order(self, order: LoadOrder, *, can_reprint: bool) -> Path:
        if not can_reprint:
            raise PermissionError("No tiene permiso para reimprimir órdenes de carga.")
        order = LoadOrder.get_by_id(order.id)
        record_ref = f"LoadOrder:{order.id}"
        original_exists = (
            AuditLog.select()
            .where(
                AuditLog.module == "Ordenes de carga",
                AuditLog.action == "imprimir",
                AuditLog.record_ref == record_ref,
            )
            .exists()
        )
        if not original_exists:
            raise ValueError("Primero debe imprimir la orden original.")
        copy_number = (
            AuditLog.select()
            .where(
                AuditLog.module == "Ordenes de carga",
                AuditLog.action == "reimprimir",
                AuditLog.record_ref == record_ref,
            )
            .count()
            + 1
        )
        return self.prints.export_reprint(
            order,
            self.prints_dir,
            copy_number=copy_number,
            reprinted_at=datetime.now(),
        )

    def annul(self, order: LoadOrder, *, can_annul: bool) -> LoadOrder:
        order = LoadOrder.get_by_id(order.id)
        if order.status == LoadOrder.STATUS_ANNULLED:
            raise ValueError("La orden ya esta anulada.")
        if order.status == LoadOrder.STATUS_CLOSED:
            raise ValueError("No se puede anular una orden cerrada.")
        annulled = self.load_orders.annul_order(order, can_annul=can_annul, reason="Anulada desde pantalla")
        self.account_ledger.reverse_for_load_order(annulled)
        return annulled

    def export_budgets(self, order: LoadOrder) -> list[Path]:
        order = LoadOrder.get_by_id(order.id)
        return self.prints.export_budgets(order, self.prints_dir)

    def export_combined_budget(self, order: LoadOrder) -> Path:
        order = LoadOrder.get_by_id(order.id)
        return self.prints.export_combined_budget(order, self.prints_dir)

    def _require_printable(self, order: LoadOrder) -> LoadOrder:
        order = LoadOrder.get_by_id(order.id)
        if order.status == LoadOrder.STATUS_CLOSED:
            raise ValueError("No se puede imprimir una orden cerrada.")
        return order
