from datetime import date

import pytest
from pytest import approx

from app.models.accounting import ClientAccountMovement
from app.models.payments import ClientPayment
from app.services.client_payment_service import ClientPaymentError, ClientPaymentService


def _make_client():
    from app.models.masters import Client

    return Client.create(name="Cliente Pago", cuit="30999999990", iva_condition="RI")


def test_register_payment_creates_payment_and_credit_movement(db):
    client = _make_client()
    service = ClientPaymentService(current_user="admin")

    payment = service.register_payment(client=client, amount=1234.5, method=ClientPayment.METHOD_CASH)

    assert payment.receipt_number == "REC-00000001"
    assert payment.amount == approx(1234.5)
    assert payment.client == client
    assert payment.created_by == "admin"

    movements = list(ClientAccountMovement.select())
    assert len(movements) == 1
    m = movements[0]
    assert m.movement_type == ClientAccountMovement.TYPE_PAYMENT
    assert m.client == client
    assert m.total_amount == approx(-1234.5)
    assert m.amount == approx(-1234.5)
    assert m.net_amount == approx(-1234.5)
    assert m.vat_amount == 0
    assert m.discount_amount == 0
    assert m.is_reversal is False
    assert m.payment == payment
    assert m.load_order is None
    assert "REC-00000001" in m.description


def test_receipt_number_is_correlative(db):
    client = _make_client()
    service = ClientPaymentService(current_user="admin")

    first = service.register_payment(client=client, amount=100)
    second = service.register_payment(client=client, amount=200)
    third = service.register_payment(client=client, amount=50)

    assert first.receipt_number == "REC-00000001"
    assert second.receipt_number == "REC-00000002"
    assert third.receipt_number == "REC-00000003"


def test_register_payment_rejects_zero_amount(db):
    client = _make_client()
    service = ClientPaymentService(current_user="admin")

    with pytest.raises(ClientPaymentError):
        service.register_payment(client=client, amount=0)


def test_register_payment_rejects_negative_amount(db):
    client = _make_client()
    service = ClientPaymentService(current_user="admin")

    with pytest.raises(ClientPaymentError):
        service.register_payment(client=client, amount=-10)


def test_register_payment_rejects_unknown_method(db):
    client = _make_client()
    service = ClientPaymentService(current_user="admin")

    with pytest.raises(ClientPaymentError):
        service.register_payment(client=client, amount=10, method="cripto")


def test_register_payment_requires_client(db):
    service = ClientPaymentService(current_user="admin")

    with pytest.raises(ClientPaymentError):
        service.register_payment(client=None, amount=10)


def test_payment_uses_explicit_date(db):
    client = _make_client()
    service = ClientPaymentService(current_user="admin")

    payment = service.register_payment(
        client=client,
        amount=10,
        payment_date=date(2026, 7, 1),
        method="transferencia",
        reference="TRF-001",
    )

    assert payment.payment_date == date(2026, 7, 1)
    assert payment.method == "transferencia"
    assert payment.reference == "TRF-001"