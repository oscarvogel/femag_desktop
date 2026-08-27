from conftest import _master_data


def _order(number=1, *, qr_token=None, data=None):
    from app.models.load_orders import LoadOrder

    data = data or _master_data()
    values = {
        "order_number": number,
        "client": data["client"],
        "delivery_address": data["address"],
        "carrier": data["carrier"],
        "driver": data["driver"],
        "truck": data["truck"],
    }
    if qr_token is not None:
        values["qr_token"] = qr_token
    return LoadOrder.create(**values)


def test_new_load_order_gets_opaque_qr_token(db):
    data = _master_data()
    first = _order(1, data=data)
    second = _order(2, data=data)

    assert first.qr_token
    assert second.qr_token
    assert first.qr_token != second.qr_token
    assert len(first.qr_token) >= 32
    assert first.qr_token != str(first.order_number)


def test_historical_order_without_token_is_backfilled_on_use(db):
    order = _order(1, qr_token="")
    order.qr_token = None
    order.save(only=[order.__class__.qr_token])

    payload = order.qr_payload()
    persisted = order.__class__.get_by_id(order.id)

    assert payload == f"FEMAG:LOAD_ORDER:{persisted.qr_token}"
    assert persisted.qr_token


def test_operational_print_service_builds_qr_from_opaque_token(db):
    from reportlab.graphics.shapes import Drawing

    from app.services.qr_load_order_print_service import ConsolidatedLoadOrderPrintService

    order = _order(1)
    service = ConsolidatedLoadOrderPrintService(current_user="admin")

    qr = service._qr_drawing(order)

    assert isinstance(qr, Drawing)
    assert qr.width > 0
    assert qr.height > 0
    assert service._qr_payload(order) == f"FEMAG:LOAD_ORDER:{order.qr_token}"


def test_operation_service_uses_qr_print_service(db, tmp_path):
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.qr_load_order_print_service import ConsolidatedLoadOrderPrintService

    service = LoadOrderOperationService(current_user="admin", prints_dir=tmp_path)

    assert isinstance(service.prints, ConsolidatedLoadOrderPrintService)
