from PyQt5.QtWidgets import QApplication, QTableWidget

from app.models.audit import AuditLog
from app.models.load_orders import LoadOrder
from app.services.audit_history_service import AuditHistoryService
from app.services.load_order_service import LoadOrderService
from app.ui.audit_history_dialog import LoadOrderHistoryDialog
from conftest import _master_data, _valid_order_payload


def test_load_order_history_combines_status_and_audit_without_duplicates(db):
    data = _master_data()
    service = LoadOrderService(current_user="auditor")
    order = service.create_order(**_valid_order_payload(data))
    service.update_order(order, observations="Cambio operativo")
    service.change_status(order, LoadOrder.STATUS_ISSUED, reason="Lista para despacho")

    events = AuditHistoryService().load_order_history(order)

    assert [event.action for event in events].count("Orden creada") == 1
    assert [event.action for event in events].count("Orden emitida") == 1
    assert [event.action for event in events].count("Orden modificada") == 1
    assert not any(event.action == "Cambiar estado" for event in events)
    issued = next(event for event in events if event.action == "Orden emitida")
    assert issued.previous_status == LoadOrder.STATUS_PENDING
    assert issued.new_status == LoadOrder.STATUS_ISSUED
    assert issued.reason == "Lista para despacho"
    assert issued.user == "auditor"


def test_load_order_history_shows_annulment_reason_once(db):
    data = _master_data()
    service = LoadOrderService(current_user="admin_auditoria")
    order = service.create_order(**_valid_order_payload(data))
    service.annul_order(order, can_annul=True, reason="Transportista incorrecto")

    events = AuditHistoryService().load_order_history(order)

    annulments = [event for event in events if event.action == "Orden anulada"]
    assert len(annulments) == 1
    assert annulments[0].reason == "Transportista incorrecto"
    assert annulments[0].user == "admin_auditoria"


def test_load_order_history_dialog_renders_timeline(db):
    app = QApplication.instance() or QApplication([])
    data = _master_data()
    service = LoadOrderService(current_user="ui_auditoria")
    order = service.create_order(**_valid_order_payload(data))
    service.change_status(order, LoadOrder.STATUS_ISSUED, reason="Emitida para prueba")

    dialog = LoadOrderHistoryDialog(order)
    app.processEvents()
    table = dialog.findChild(QTableWidget, "loadOrderHistoryTable")

    assert table is not None
    actions = [table.item(row, 2).text() for row in range(table.rowCount())]
    assert actions.count("Orden creada") == 1
    assert actions.count("Orden emitida") == 1
    assert table.rowCount() >= 2


def test_history_keeps_non_status_audit_events(db):
    data = _master_data()
    order = LoadOrderService(current_user="auditor").create_order(**_valid_order_payload(data))
    AuditLog.create(
        user="auditor",
        module="Ordenes de carga",
        action="imprimir",
        record_ref=f"LoadOrder:{order.id}",
    )

    events = AuditHistoryService().load_order_history(order)

    assert any(event.action == "Orden impresa" for event in events)
