from datetime import date, timedelta


def _credit_master_data(limit=None):
    from app.models.masters import Carrier, Client, Driver, Truck

    client = Client.create(
        name="Cliente Crédito",
        cuit="30700111222",
        iva_condition="RI",
        dias_plazo_pago=15,
        max_despachos_pendientes=limit,
    )
    carrier = Carrier.create(name="Transportista Crédito")
    driver = Driver.create(name="Chofer Crédito", carrier=carrier)
    truck = Truck.create(domain="CRD001", carrier=carrier)
    return client, carrier, driver, truck


def _order(client, carrier, driver, truck, number, status="Emitida"):
    from app.models.load_orders import LoadOrder

    return LoadOrder.create(
        order_number=number,
        date=date(2026, 8, 1),
        client=client,
        carrier=carrier,
        driver=driver,
        truck=truck,
        status=status,
        created_by="test",
    )


def _debit(client, order, amount, due_date=None):
    from app.models.accounting import ClientAccountMovement

    return ClientAccountMovement.create(
        client=client,
        load_order=order,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        total_amount=amount,
        movement_date=order.date,
        due_date=due_date or (order.date + timedelta(days=15)),
        description=f"OC-{order.order_number}",
        source_ref=f"LoadOrder:{order.id}",
        created_by="test",
    )


def _payment(client, order, amount):
    from app.models.accounting import ClientAccountMovement

    return ClientAccountMovement.create(
        client=client,
        load_order=order,
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
        total_amount=-amount,
        amount=-amount,
        description="Pago imputado",
        source_ref=f"Payment:{order.id}:{amount}",
        created_by="test",
    )


def test_client_without_limit_is_always_available(db):
    from app.services.client_credit_service import ClientCreditService

    client, carrier, driver, truck = _credit_master_data(limit=None)
    for number in (1, 2, 3):
        order = _order(client, carrier, driver, truck, number)
        _debit(client, order, 1000)

    status = ClientCreditService.status_for_client(client, as_of=date(2026, 8, 12))

    assert status.pending_dispatches == 3
    assert status.limit_dispatches is None
    assert status.state == ClientCreditService.STATE_AVAILABLE
    assert status.can_issue is True


def test_client_at_limit_cannot_issue_another_dispatch(db):
    from app.services.client_credit_service import ClientCreditService

    client, carrier, driver, truck = _credit_master_data(limit=2)
    for number in (1, 2):
        order = _order(client, carrier, driver, truck, number)
        _debit(client, order, 1000)

    status = ClientCreditService.status_for_client(client, as_of=date(2026, 8, 12))

    assert status.pending_dispatches == 2
    assert status.state == ClientCreditService.STATE_AT_LIMIT
    assert status.can_issue is False


def test_partial_payment_keeps_dispatch_pending_and_full_payment_releases_it(db):
    from app.services.client_credit_service import ClientCreditService

    client, carrier, driver, truck = _credit_master_data(limit=1)
    order = _order(client, carrier, driver, truck, 1)
    _debit(client, order, 1000)
    _payment(client, order, 400)

    partial = ClientCreditService.status_for_client(client, as_of=date(2026, 8, 12))
    assert partial.pending_dispatches == 1
    assert partial.pending_balance == 600
    assert partial.can_issue is False

    _payment(client, order, 600)
    paid = ClientCreditService.status_for_client(client, as_of=date(2026, 8, 12))
    assert paid.pending_dispatches == 0
    assert paid.pending_balance == 0
    assert paid.can_issue is True


def test_credit_status_reports_overdue_balance_and_next_due_date(db):
    from app.services.client_credit_service import ClientCreditService

    client, carrier, driver, truck = _credit_master_data(limit=3)
    overdue_order = _order(client, carrier, driver, truck, 1)
    future_order = _order(client, carrier, driver, truck, 2)
    _debit(client, overdue_order, 1500, due_date=date(2026, 8, 10))
    _debit(client, future_order, 900, due_date=date(2026, 8, 20))

    status = ClientCreditService.status_for_client(client, as_of=date(2026, 8, 12))

    assert status.pending_dispatches == 2
    assert status.pending_balance == 2400
    assert status.overdue_balance == 1500
    assert status.next_due_date == date(2026, 8, 20)


def test_exceeded_limit_is_reported_as_blocked(db):
    from app.services.client_credit_service import ClientCreditService

    client, carrier, driver, truck = _credit_master_data(limit=1)
    for number in (1, 2):
        order = _order(client, carrier, driver, truck, number)
        _debit(client, order, 1000)

    status = ClientCreditService.status_for_client(client, as_of=date(2026, 8, 12))

    assert status.pending_dispatches == 2
    assert status.state == ClientCreditService.STATE_BLOCKED
    assert status.can_issue is False


def test_annulled_order_does_not_consume_credit(db):
    from app.models.load_orders import LoadOrder
    from app.services.client_credit_service import ClientCreditService

    client, carrier, driver, truck = _credit_master_data(limit=1)
    order = _order(client, carrier, driver, truck, 1, status=LoadOrder.STATUS_ANNULLED)
    _debit(client, order, 1000)

    status = ClientCreditService.status_for_client(client, as_of=date(2026, 8, 12))

    assert status.pending_dispatches == 0
    assert status.can_issue is True


def test_assert_can_issue_explains_limit_and_overdue_debt(db):
    import pytest

    from app.services.client_credit_service import ClientCreditService

    client, carrier, driver, truck = _credit_master_data(limit=1)
    previous = _order(client, carrier, driver, truck, 1)
    _debit(client, previous, 1200, due_date=date(2026, 7, 31))
    candidate = _order(client, carrier, driver, truck, 2, status="Pendiente")
    candidate.date = date(2026, 8, 12)
    candidate.save()

    with pytest.raises(ValueError) as exc:
        ClientCreditService.assert_can_issue(candidate)

    message = str(exc.value)
    assert "crédito bloqueado" in message
    assert "1 despachos pendientes" in message
    assert "límite es 1" in message
    assert "Deuda vencida" in message
