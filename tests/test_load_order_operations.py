from pathlib import Path

import pytest

from tests.test_load_orders import _valid_order_payload, _master_data


def test_operational_flow_emits_prints_reprints_and_annuls_order(db, tmp_path):
    from app.models.audit import AuditLog
    from app.models.load_orders import LoadOrder
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))
    operations = LoadOrderOperationService(current_user="admin", prints_dir=tmp_path)

    issued = operations.issue(order)
    first_print = operations.print_order(issued)
    reprint = operations.reprint_order(issued)
    annulled = operations.annul(issued, can_annul=True)

    assert issued.status == LoadOrder.STATUS_ISSUED
    assert Path(first_print).exists()
    assert Path(reprint).exists()
    assert "Reimpresion" in Path(reprint).read_text(encoding="utf-8")
    assert annulled.status == LoadOrder.STATUS_ANNULLED
    assert AuditLog.select().where(AuditLog.action == "imprimir").count() == 1
    assert AuditLog.select().where(AuditLog.action == "reimprimir").count() == 1


def test_operational_flow_rejects_printing_before_issue(db, tmp_path):
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))

    with pytest.raises(ValueError, match="Emita la orden"):
        LoadOrderOperationService(current_user="admin", prints_dir=tmp_path).print_order(order)


def test_operational_flow_rejects_reissuing_or_printing_annulled_order(db, tmp_path):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))
    operations = LoadOrderOperationService(current_user="admin", prints_dir=tmp_path)
    annulled = operations.annul(order, can_annul=True)

    with pytest.raises(ValueError, match="anulada"):
        operations.issue(annulled)
    with pytest.raises(ValueError, match="anulada"):
        operations.print_order(annulled)
    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_ANNULLED


def test_operational_flow_requires_permission_to_annul(db, tmp_path):
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="secretaria").create_order(**_valid_order_payload(data))

    with pytest.raises(PermissionError, match="permiso"):
        LoadOrderOperationService(current_user="secretaria", prints_dir=tmp_path).annul(order, can_annul=False)
