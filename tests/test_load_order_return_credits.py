import pytest

from conftest import _master_data, _valid_order_payload


def _issued_order_with_valued_line():
    from app.models.load_orders import LoadOrder, LoadOrderProduct
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="issue222")
    order = service.create_order(**_valid_order_payload(data))
    line = LoadOrderProduct.select().where(LoadOrderProduct.order == order).first()
    line.precio_neto_unitario = 100.0
    line.total = round(float(line.quantity) * 121.0, 2)
    line.save()
    service.change_status(order, LoadOrder.STATUS_ISSUED, reason="Emitida para crédito por devolución")
    return order, line


def test_closing_with_return_generates_credit_and_reduces_balance(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.ledger_query_service import client_balance
    from app.services.load_order_closure_service import LoadOrderClosureService

    order, line = _issued_order_with_valued_line()
    client = line.destination.client if line.destination_id else order.client
    balance_before = client_balance(client)
    quantity = min(float(line.quantity), 2.0)
    expected_credit = round((float(line.total) / float(line.quantity)) * quantity, 2)

    closure = LoadOrderClosureService(current_user="issue222").close_order(
        order,
        returns=[
            {
                "order_product": line,
                "quantity": quantity,
                "reason": "Mercadería rechazada",
            }
        ],
        no_payment_reason="Saldo en cuenta corriente",
    )

    movement = ClientAccountMovement.get(
        ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_RETURN_CREDIT
    )
    assert movement.client == client
    assert movement.load_order == order
    assert movement.total_amount == pytest.approx(-expected_credit)
    assert movement.reference == f"OC-{order.order_number:06d}"
    assert "Nota de crédito por devolución" in movement.description
    assert f"LoadOrderClosure:{closure.id}:ReturnCredit:{client.id}" == movement.source_ref
    assert client_balance(client) == pytest.approx(balance_before - expected_credit)


def test_return_credit_generation_is_idempotent_for_same_closure(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.load_order_closure_service import LoadOrderClosureService

    order, line = _issued_order_with_valued_line()
    service = LoadOrderClosureService(current_user="issue222")
    closure = service.close_order(
        order,
        returns=[{"order_product": line, "quantity": 1, "reason": "Rechazo"}],
        no_payment_reason="Saldo en cuenta corriente",
    )

    first = service.return_credits.generate_for_closure(closure)
    second = service.return_credits.generate_for_closure(closure)

    assert [row.id for row in first] == [row.id for row in second]
    assert (
        ClientAccountMovement.select()
        .where(ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_RETURN_CREDIT)
        .count()
        == 1
    )


def test_reopening_order_reverses_return_credit(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.ledger_query_service import client_balance
    from app.services.load_order_closure_service import LoadOrderClosureService

    order, line = _issued_order_with_valued_line()
    client = line.destination.client if line.destination_id else order.client
    balance_before = client_balance(client)
    service = LoadOrderClosureService(current_user="issue222")
    service.close_order(
        order,
        returns=[{"order_product": line, "quantity": 1, "reason": "Rechazo"}],
        no_payment_reason="Saldo en cuenta corriente",
    )
    balance_with_credit = client_balance(client)
    assert balance_with_credit < balance_before

    service.reopen_order(order, reason="Corregir devolución")

    original = ClientAccountMovement.get(
        ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_RETURN_CREDIT
    )
    reversal = ClientAccountMovement.get(
        ClientAccountMovement.movement_type
        == ClientAccountMovement.TYPE_RETURN_CREDIT_REVERSAL
    )
    assert reversal.reverses == original
    assert reversal.total_amount == pytest.approx(-original.total_amount)
    assert reversal.is_reversal is True
    assert client_balance(client) == pytest.approx(balance_before)


def test_return_credit_has_clear_statement_label(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.account_statement_print_service import MOVEMENT_TYPE_LABELS

    assert MOVEMENT_TYPE_LABELS[ClientAccountMovement.TYPE_RETURN_CREDIT] == (
        "Nota de crédito por devolución"
    )
    assert MOVEMENT_TYPE_LABELS[ClientAccountMovement.TYPE_RETURN_CREDIT_REVERSAL] == (
        "Reverso nota de crédito por devolución"
    )
