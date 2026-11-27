"""Importacion de la cuenta corriente de productores desde femagfab (#957).

Junta en una sola accion los tres pasos que ya existian por separado:

1. el maestro de proveedores (#938, ``SupplierImportService``);
2. los tickets y pagares con saldo (#939, ``SupplierDocumentImportService``);
3. la apertura del libro con un saldo inicial por documento (#940).

Los tres son idempotentes, asi que la accion se puede repetir: lo ya importado
no se duplica y un documento ya importado no se vuelve a leer del legacy (desde
ese momento sus pagos se registran en FEMAG Desktop). femagfab solo se lee.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.security import User
from app.services.audit_service import AuditService
from app.services.permission_service import PermissionService
from app.services.supplier_document_import_service import (
    SupplierDocumentImportReport,
    SupplierDocumentImportService,
)
from app.services.supplier_import_service import (
    SupplierImportReport,
    SupplierImportService,
)
from app.services.supplier_ledger_service import (
    AUDIT_MODULE,
    MENU_SECTION,
    MENU_TITLE,
    SupplierLedgerService,
)


def _money(value) -> str:
    """Importe con el formato de la pantalla: 1.696.085,45."""
    text = f"{value:,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


class SupplierSyncError(RuntimeError):
    pass


def can_import_from_femagfab(user: User | None) -> bool:
    if user is None or not getattr(user, "active", False):
        return False
    if PermissionService.is_administrator(user):
        return True
    return PermissionService().has_permission(user, MENU_SECTION, "importar", MENU_TITLE)


@dataclass(frozen=True)
class SupplierSyncResult:
    suppliers: SupplierImportReport
    documents: SupplierDocumentImportReport
    openings_created: int

    def summary_lines(self) -> list[str]:
        suppliers = self.suppliers
        documents = self.documents
        return [
            f"Productores: {suppliers.created} nuevos, {suppliers.merged} unificados por nombre, "
            f"{suppliers.updated} actualizados, {suppliers.unchanged} sin cambios, "
            f"{suppliers.skipped_count} descartados.",
            f"Documentos: {documents.imported_tickets} tickets y {documents.imported_notes} pagarés "
            f"nuevos; {documents.already_imported} ya estaban importados.",
            f"Excluidos por falta de datos: {documents.excluded_count} por "
            f"$ {_money(documents.excluded_amount)}.",
            f"Saldos iniciales abiertos en el libro: {self.openings_created}.",
        ]


class FemagFabSupplierSyncService:
    def __init__(self, source=None, audit_service: AuditService | None = None):
        if source is None:
            from app.importers.femagfab import FemagFabSource

            source = FemagFabSource()
        self.source = source
        self.audit_service = audit_service or AuditService()

    def run(self, *, user: User) -> SupplierSyncResult:
        if not can_import_from_femagfab(user):
            raise PermissionError("No tiene permiso para importar productores desde femagfab.")
        if getattr(self.source, "configured", True) is False:
            raise SupplierSyncError(
                "La conexión a femagfab no está configurada en este puesto."
            )
        try:
            suppliers = SupplierImportService(source=self.source).import_suppliers()
            documents = SupplierDocumentImportService(source=self.source).import_documents()
        except PermissionError:
            raise
        except Exception as exc:  # noqa: BLE001 - se informa al operador
            raise SupplierSyncError(f"No se pudo leer femagfab: {exc}") from exc
        openings = SupplierLedgerService(user.username).open_ledger_from_imports()
        result = SupplierSyncResult(
            suppliers=suppliers, documents=documents, openings_created=openings
        )
        self.audit_service.record(
            user=user.username,
            module=AUDIT_MODULE,
            action="importar_femagfab",
            record_ref="femagfab:proveedores",
            new_value={
                "suppliers_created": suppliers.created,
                "suppliers_merged": suppliers.merged,
                "suppliers_updated": suppliers.updated,
                "tickets_imported": documents.imported_tickets,
                "notes_imported": documents.imported_notes,
                "already_imported": documents.already_imported,
                "excluded": documents.excluded_count,
                "excluded_amount": str(documents.excluded_amount),
                "openings_created": openings,
            },
            observation="Importación de productores y documentos desde femagfab.",
        )
        return result
