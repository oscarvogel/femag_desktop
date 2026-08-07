from datetime import date

import pytest
from pytest import approx

from app.models.accounting import ClientAccountMovement
from app.models.audit import AuditLog
from app.models.masters import Client
from app.services.client_manual_debit_service import (
    ClientManualDebitError,
    ClientManualDebitService,
)
from app.services.ledger_query_service import client_balance


def _client(name="Cliente Débito"):
    return Client.create(name=name, cuit="30700000217", iva_condition="RI")


def test_register_manual_debit_impacts_balance_and_audits(db):
    client = _client()
    movement = ClientManualDebitService(current_user="caja").register_manual_debit(
        client=client,
        amount=5000,
        debit_date=date(2026, 8, 7),
        description="Interés por mora",
        reference="ND-0007",
    )

    assert movement.movement_type == ClientAccountMovement.TYPE_MANUAL_DEBIT
    assert movement.total_amount == approx(5000)
    assert movement.amount == approx(5000)
    assert movement.movement_date == date(2026, 8, 7)
    assert movement.description == "Interés por mora"
    assert movement.reference == "ND-0007"
    assert movement.source_ref == f"ManualDebit:{movement.id}"
    assert movement.load_order is None
    assert movement.payment is None
    assert movement.is_reversal is False
    assert client_balance(client) == approx(5000)

    audit = AuditLog.get(AuditLog.action == "registrar_debito_manual")
    assert audit.user == "caja"
    assert audit.record_ref == f"ClientAccountMovement:{movement.id}"
    assert audit.new_value["amount"] == approx(5000)
    assert audit.new_value["movement_date"] == "2026-08-07"
    assert audit.new_value["reference"] == "ND-0007"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"client": None, "amount": 1, "description": "Ajuste"}, "cliente"),
        ({"amount": 0, "description": "Ajuste"}, "mayor a cero"),
        ({"amount": -1, "description": "Ajuste"}, "mayor a cero"),
        ({"amount": 1, "description": "   "}, "descripción"),
    ],
)
def test_register_manual_debit_validates_required_fields(db, kwargs, message):
    client = _client()
    values = {"client": client, **kwargs}

    with pytest.raises(ClientManualDebitError, match=message):
        ClientManualDebitService(current_user="caja").register_manual_debit(**values)

    assert ClientAccountMovement.select().count() == 0


def test_reverse_manual_debit_restores_balance_and_audits(db):
    client = _client()
    service = ClientManualDebitService(current_user="caja")
    original = service.register_manual_debit(
        client=client,
        amount=5000,
        description="Nota de débito manual",
        reference="ND-55",
    )

    reversal = service.reverse_manual_debit(
        original,
        reversal_date=date(2026, 8, 8),
    )

    assert reversal.movement_type == ClientAccountMovement.TYPE_MANUAL_DEBIT_REVERSAL
    assert reversal.total_amount == approx(-5000)
    assert reversal.movement_date == date(2026, 8, 8)
    assert reversal.reference == "ND-55"
    assert reversal.is_reversal is True
    assert reversal.reverses == original
    assert client_balance(client) == approx(0)

    audit = AuditLog.get(AuditLog.action == "reversar_debito_manual")
    assert audit.record_ref == f"ClientAccountMovement:{original.id}"
    assert audit.new_value["reversal_movement_id"] == reversal.id

    with pytest.raises(ClientManualDebitError, match="ya fue reversado"):
        service.reverse_manual_debit(original)
    assert ClientAccountMovement.select().count() == 2


def test_reverse_manual_debit_rejects_other_movement_types(db):
    client = _client()
    movement = ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
        total_amount=-100,
        description="Pago",
        source_ref="Payment:test",
    )

    with pytest.raises(ClientManualDebitError, match="no es un débito manual"):
        ClientManualDebitService(current_user="caja").reverse_manual_debit(movement)


def test_register_manual_debit_rolls_back_when_audit_fails(db):
    class FailingAudit:
        def record(self, **_kwargs):
            raise RuntimeError("audit unavailable")

    client = _client()
    service = ClientManualDebitService(current_user="caja", audit_service=FailingAudit())

    with pytest.raises(RuntimeError, match="audit unavailable"):
        service.register_manual_debit(
            client=client,
            amount=100,
            description="Ajuste",
        )

    assert ClientAccountMovement.select().count() == 0
