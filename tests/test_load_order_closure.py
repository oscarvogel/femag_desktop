import pytest

from conftest import _master_data, _valid_order_payload


def _issued_order():
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin_cierre")
    order = service.create_order(**_valid_order_payload(data))
    service.change_status(order, LoadOrder.STATUS_ISSUED, reason="Emitida para entrega")
    return data, order


def test_close_order_persists_active_closure_and_releases_driver(db):
    from app.models.audit import AuditLog
    from app.models.load_orders import LoadOrder, LoadOrderClosure, LoadOrderStatusHistory
    from app.services.load_order_closure_service import LoadOrderClosureService

    data, order = _issued_order()

    closure = LoadOrderClosureService(current_user="admin_cierre").close_order(
        order,
        observations="Entrega conforme",
        no_payment_reason="Queda en cuenta corriente",
    )

    reloaded_order = LoadOrder.get_by_id(order.id)
    assert reloaded_order.status == LoadOrder.STATUS_CLOSED
    assert closure.order == order
    assert closure.status == LoadOrderClosure.STATUS_ACTIVE
    assert closure.active_marker is True
    assert closure.closed_by == "admin_cierre"
    assert closure.observations == "Entrega conforme"
    assert closure.is_active is True
    assert type(data["driver"]).get_by_id(data["driver"].id).available is True
    assert LoadOrderStatusHistory.get(
        (LoadOrderStatusHistory.order == order)
        & (LoadOrderStatusHistory.new_status == LoadOrder.STATUS_CLOSED)
    ).observation == "Cierre de entrega"
    assert AuditLog.select().where(
        (AuditLog.action == "cerrar entrega")
        & (AuditLog.record_ref == f"LoadOrderClosure:{closure.id}")
    ).exists()


def test_close_order_rejects_pending_and_direct_status_change(db):
    from app.models.load_orders import LoadOrder, LoadOrderClosure
    from app.services.load_order_closure_service import (
        LoadOrderClosureError,
        LoadOrderClosureService,
    )
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))

    with pytest.raises(LoadOrderClosureError, match="emitidas"):
        LoadOrderClosureService(current_user="admin").close_order(order)
    with pytest.raises(ValueError, match="LoadOrderClosureService"):
        LoadOrderService(current_user="admin").change_status(order, LoadOrder.STATUS_CLOSED)

    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_PENDING
    assert LoadOrderClosure.select().count() == 0


def test_reopen_order_preserves_history_and_allows_new_closure_cycle(db):
    from app.models.load_orders import LoadOrder, LoadOrderClosure
    from app.services.load_order_closure_service import LoadOrderClosureService

    data, order = _issued_order()
    service = LoadOrderClosureService(current_user="admin_cierre")
    first_closure = service.close_order(order, no_payment_reason="Queda en cuenta corriente")

    with pytest.raises(ValueError, match="reapertura.*LoadOrderClosureService"):
        service.load_orders.change_status(order, LoadOrder.STATUS_ISSUED)

    reopened = service.reopen_order(order, reason="Corregir mercaderia entregada")

    first_closure = LoadOrderClosure.get_by_id(first_closure.id)
    assert reopened.status == LoadOrder.STATUS_ISSUED
    assert first_closure.status == LoadOrderClosure.STATUS_REOPENED
    assert first_closure.active_marker is None
    assert first_closure.reopened_at is not None
    assert first_closure.reopened_by == "admin_cierre"
    assert first_closure.reopen_reason == "Corregir mercaderia entregada"
    assert first_closure.is_active is False
    assert type(data["driver"]).get_by_id(data["driver"].id).available is False

    second_closure = service.close_order(
        reopened,
        observations="Segundo cierre",
        no_payment_reason="Queda en cuenta corriente",
    )

    assert second_closure.id != first_closure.id
    assert second_closure.is_active is True
    assert LoadOrderClosure.select().where(LoadOrderClosure.order == order).count() == 2
    assert service.active_closure(order) == second_closure


def test_reopen_order_requires_reason_and_rolls_back_if_driver_is_busy(db):
    from app.models.load_orders import LoadOrder, LoadOrderClosure
    from app.services.load_order_closure_service import (
        LoadOrderClosureError,
        LoadOrderClosureService,
    )
    from app.services.load_order_service import LoadOrderService

    data, order = _issued_order()
    closures = LoadOrderClosureService(current_user="admin_cierre")
    closure = closures.close_order(order, no_payment_reason="Queda en cuenta corriente")

    with pytest.raises(LoadOrderClosureError, match="motivo"):
        closures.reopen_order(order, reason="  ")

    LoadOrderService(current_user="otro").create_order(**_valid_order_payload(data))

    with pytest.raises(ValueError, match="chofer.*bloqueado"):
        closures.reopen_order(order, reason="Reintentar entrega")

    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_CLOSED
    closure = LoadOrderClosure.get_by_id(closure.id)
    assert closure.status == LoadOrderClosure.STATUS_ACTIVE
    assert closure.active_marker is True
    assert closure.reopened_at is None
