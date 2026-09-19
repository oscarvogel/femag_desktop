from datetime import datetime

from PyQt5.QtWidgets import QApplication

from app.models.audit import AuditLog
from app.services.audit_query_service import AuditQueryService
from app.ui.audit_query_page import AuditQueryPage


def test_audit_query_filters_by_module_user_action_and_reference(db):
    AuditLog.create(
        user="oscar",
        occurred_at=datetime(2026, 9, 19, 10, 0),
        module="Cuenta corriente",
        action="registrar_pago",
        record_ref="ClientPayment:1",
        new_value={
            "receipt_number": "REC-00000001",
            "amount": 1200,
        },
    )
    AuditLog.create(
        user="maria",
        occurred_at=datetime(2026, 9, 19, 11, 0),
        module="Remitos",
        action="emitir",
        record_ref="Remittance:1",
        new_value={
            "number": "REM-00000001",
            "status": "Emitido",
        },
    )

    service = AuditQueryService()

    assert len(service.search(module="Cuenta corriente")) == 1
    assert len(service.search(user="maria")) == 1
    assert len(service.search(action="emitir")) == 1
    rows = service.search(reference="REC-00000001")
    assert len(rows) == 1
    assert service.display_reference(rows[0]) == "REC-00000001"


def test_audit_query_page_renders_events(db):
    app = QApplication.instance() or QApplication([])
    AuditLog.create(
        user="audit_ui",
        module="Presupuestos",
        action="crear_manual",
        record_ref="Budget:7",
        new_value={
            "budget_number": 7,
            "status": "active",
            "total_amount": 2500,
        },
    )

    page = AuditQueryPage()
    app.processEvents()

    assert page.table.rowCount() == 1
    assert page.table.item(0, 1).text() == "Presupuestos"
    assert page.table.item(0, 2).text() == "PRES-000007"
    assert page.table.item(0, 3).text() == "audit_ui"
