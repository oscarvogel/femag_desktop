from tests.test_load_orders import _multi_client_data, _valid_order_payload


def test_issued_load_order_generates_traceable_account_movement(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.load_orders import LoadOrder
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))

    issued = LoadOrderOperationService(current_user="admin").issue(order)

    movement = ClientAccountMovement.get()
    assert issued.status == LoadOrder.STATUS_ISSUED
    assert movement.client == data["client"]
    assert movement.load_order == issued
    assert movement.movement_type == ClientAccountMovement.TYPE_LOAD_ORDER
    assert movement.amount == 0
    assert movement.currency == "ARS"
    assert movement.is_reversal is False
    assert movement.description == "Orden de carga OC-000001 - movimiento documental sin importe comercial"


def test_multi_client_load_order_generates_one_documental_movement_per_client(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [{"product": data["product"], "quantity": 100}],
            },
            {
                "client": data["client"],
                "delivery_address": data["other_destination"],
                "products": [{"product": data["other_product"], "quantity": 40}],
            },
            {
                "client": data["other_client"],
                "delivery_address": data["other_address"],
                "products": [{"product": data["third_product"], "quantity": 6}],
            },
        ],
        pallets=[],
    )

    LoadOrderOperationService(current_user="admin").issue(order)

    movements = list(ClientAccountMovement.select().order_by(ClientAccountMovement.client))
    assert len(movements) == 2
    assert [movement.client.name for movement in movements] == ["Cliente FEMAG", "Cliente Sur"]
    assert all(movement.load_order.id == order.id for movement in movements)
    assert all(movement.source_ref == f"LoadOrder:{order.id}" for movement in movements)


def test_account_ledger_generation_is_idempotent(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.account_ledger_service import AccountLedgerService
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))
    issued = LoadOrderOperationService(current_user="admin").issue(order)

    AccountLedgerService(current_user="admin").generate_for_load_order(issued)

    assert ClientAccountMovement.select().count() == 1


def test_annulling_load_order_reverses_account_movements(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.load_orders import LoadOrder
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))
    operations = LoadOrderOperationService(current_user="admin")
    issued = operations.issue(order)

    annulled = operations.annul(issued, can_annul=True)

    movements = list(ClientAccountMovement.select().order_by(ClientAccountMovement.id))
    assert annulled.status == LoadOrder.STATUS_ANNULLED
    assert len(movements) == 2
    assert movements[0].movement_type == ClientAccountMovement.TYPE_LOAD_ORDER
    assert movements[1].movement_type == ClientAccountMovement.TYPE_LOAD_ORDER_REVERSAL
    assert movements[1].reverses == movements[0]
    assert movements[1].is_reversal is True
    assert movements[1].amount == 0


def test_annulling_twice_does_not_duplicate_reversal_movements(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.account_ledger_service import AccountLedgerService
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))
    operations = LoadOrderOperationService(current_user="admin")
    issued = operations.issue(order)
    annulled = operations.annul(issued, can_annul=True)

    AccountLedgerService(current_user="admin").reverse_for_load_order(annulled)

    assert ClientAccountMovement.select().count() == 2
