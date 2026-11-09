from datetime import date, timedelta

import pytest

from app.models.accounting import ClientAccountMovement
from app.models.audit import AuditLog
from app.models.masters import Client
from app.services.account_date_rules import (
    MAX_FUTURE_DAYS,
    AccountDateError,
    validate_movement_date,
)
from app.services.account_ledger_service import AccountLedgerService
from app.services.client_manual_credit_service import (
    ClientManualCreditError,
    ClientManualCreditService,
)
from app.services.client_manual_debit_service import (
    ClientManualDebitError,
    ClientManualDebitService,
)
from app.services.client_opening_balance_service import (
    ClientOpeningBalanceError,
    ClientOpeningBalanceService,
)


def _client() -> Client:
    return Client.create(
        name="Cliente fecha movimiento",
        cuit="30777777777",
        iva_condition="RI",
    )


def test_validate_movement_date_accepts_past_today_and_limit():
    today = date(2026, 11, 7)

    assert validate_movement_date(date(2026, 8, 31), today=today) == date(2026, 8, 31)
    assert validate_movement_date(today, today=today) == today
    assert (
        validate_movement_date(today + timedelta(days=MAX_FUTURE_DAYS), today=today)
        == today + timedelta(days=MAX_FUTURE_DAYS)
    )


def test_validate_movement_date_rejects_far_future_and_too_old():
    today = date(2026, 11, 7)

    with pytest.raises(AccountDateError):
        validate_movement_date(today + timedelta(days=MAX_FUTURE_DAYS + 1), today=today)
    with pytest.raises(AccountDateError):
        validate_movement_date(date(1999, 12, 31), today=today)


def test_manual_debit_rejects_far_future_date(db):
    client = _client()
    future = date.today() + timedelta(days=MAX_FUTURE_DAYS + 1)

    with pytest.raises(ClientManualDebitError):
        ClientManualDebitService(current_user="caja").register_manual_debit(
            client=client,
            amount=1000,
            description="Prueba",
            debit_date=future,
        )

    assert ClientAccountMovement.select().count() == 0


def test_manual_credit_rejects_far_future_date(db):
    client = _client()
    future = date.today() + timedelta(days=MAX_FUTURE_DAYS + 1)

    with pytest.raises(ClientManualCreditError):
        ClientManualCreditService(current_user="caja").register_manual_credit(
            client=client,
            amount=1000,
            description="Prueba",
            credit_date=future,
        )

    assert ClientAccountMovement.select().count() == 0


def test_opening_balance_rejects_far_future_date(db):
    client = _client()
    future = date.today() + timedelta(days=MAX_FUTURE_DAYS + 1)

    with pytest.raises(ClientOpeningBalanceError):
        ClientOpeningBalanceService(current_user="admin").register(
            client=client,
            amount=1000,
            movement_date=future,
        )

    assert ClientAccountMovement.select().count() == 0


def test_correct_movement_date_updates_and_audits_without_changing_balance(db):
    client = _client()
    movement = ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        amount=1800000,
        net_amount=1800000,
        discount_amount=0,
        vat_amount=0,
        total_amount=1800000,
        currency="ARS",
        movement_date=date.today() + timedelta(days=300),
        description="SALDO",
        source_ref="ManualDebit:test-899",
        is_reversal=False,
        created_by="test",
    )
    service = AccountLedgerService(current_user="admin")

    corrected = service.correct_movement_date(
        movement,
        date(2026, 8, 31),
        reason="Corrección de fecha por error de carga.",
    )

    assert corrected.movement_date == date(2026, 8, 31)
    assert AuditLog.select().where(AuditLog.action == "corregir_fecha_movimiento").count() == 1
    audit = AuditLog.get(AuditLog.action == "corregir_fecha_movimiento")
    assert audit.record_ref == f"ClientAccountMovement:{movement.id}"
    assert audit.old_value["movement_date"] == (date.today() + timedelta(days=300)).isoformat()
    assert audit.new_value["movement_date"] == "2026-08-31"
    total = sum(
        row.total_amount for row in ClientAccountMovement.select().where(
            ClientAccountMovement.client == client
        )
    )
    assert total == 1800000

    service.correct_movement_date(corrected, date(2026, 8, 31))
    assert AuditLog.select().where(AuditLog.action == "corregir_fecha_movimiento").count() == 1


def test_manual_debit_dialog_caps_future_date(db):
    from PyQt5.QtCore import QDate
    from PyQt5.QtWidgets import QApplication

    from app.ui.client_manual_debit_dialog import ClientManualDebitDialog

    app = QApplication.instance() or QApplication([])
    dialog = ClientManualDebitDialog(current_user="admin")

    assert dialog.date_input.maximumDate() == QDate.currentDate().addDays(MAX_FUTURE_DAYS)
