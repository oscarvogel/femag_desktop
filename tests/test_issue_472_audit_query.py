from datetime import datetime, timedelta

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


def test_audit_query_service_paginates_without_materializing_all_rows(db):
    base = datetime(2026, 9, 21, 12, 0)
    with db.atomic():
        for index in range(120):
            AuditLog.create(
                user="admin",
                occurred_at=base + timedelta(seconds=index),
                module="Auditoría",
                action="prueba",
                record_ref=f"Audit:{index}",
                new_value={"number": f"AUD-{index:04d}"},
            )

    service = AuditQueryService()

    first = service.search_page(page=0, page_size=50)
    second = service.search_page(page=1, page_size=50)
    third = service.search_page(page=2, page_size=50)

    assert len(first.rows) == 50
    assert first.has_previous is False
    assert first.has_next is True
    assert len(second.rows) == 50
    assert second.has_previous is True
    assert second.has_next is True
    assert len(third.rows) == 20
    assert third.has_previous is True
    assert third.has_next is False


def test_audit_query_page_navigates_50_rows_at_a_time(db):
    app = QApplication.instance() or QApplication([])
    base = datetime(2026, 9, 21, 12, 0)
    with db.atomic():
        for index in range(75):
            AuditLog.create(
                user="admin",
                occurred_at=base + timedelta(seconds=index),
                module="Auditoría",
                action="prueba",
                record_ref=f"Audit:{index}",
                new_value={"number": f"AUD-{index:04d}"},
            )

    page = AuditQueryPage()
    app.processEvents()

    assert page.table.rowCount() == 50
    assert page.previous_button.isEnabled() is False
    assert page.next_button.isEnabled() is True
    assert "Página 1" in page.results_label.text()

    page.next_page()
    app.processEvents()

    assert page.table.rowCount() == 25
    assert page.previous_button.isEnabled() is True
    assert page.next_button.isEnabled() is False
    assert "Página 2" in page.results_label.text()


def test_audit_query_page_search_preserves_formatted_load_order_reference(db):
    AuditLog.create(
        user="admin",
        occurred_at=datetime(2026, 9, 21, 13, 0),
        module="Órdenes de carga",
        action="emitir",
        record_ref="LoadOrder:154",
        new_value={"order_number": 154, "status": "Emitida"},
    )

    service = AuditQueryService()
    result = service.search_page(reference="OC-000154")

    assert len(result.rows) == 1
    assert service.display_reference(result.rows[0]) == "OC-000154"
