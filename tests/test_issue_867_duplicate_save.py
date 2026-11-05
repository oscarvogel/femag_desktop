import pytest


@pytest.mark.parametrize("kind", ["payment", "debit", "credit"])
def test_reentrant_and_repeated_save_creates_one_record(db, monkeypatch, kind):
    from PyQt5.QtWidgets import QApplication
    from app.models.masters import Client
    from app.models.accounting import ClientAccountMovement
    from app.models.payments import ClientPayment
    from app.ui.customer_payment_dialog import ClientPaymentDialog
    from app.ui.client_manual_debit_dialog import ClientManualDebitDialog
    from app.ui.client_manual_credit_dialog import ClientManualCreditDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente prueba", cuit="30123456780", iva_condition="RI")
    cls, method = {
        "payment": (ClientPaymentDialog, "register_compound_payment"),
        "debit": (ClientManualDebitDialog, "register_manual_debit"),
        "credit": (ClientManualCreditDialog, "register_manual_credit"),
    }[kind]
    dialog = cls(current_user="test", preset_client=client)
    dialog.amount_input.setValue(100)
    if kind != "payment":
        dialog.description_input.setText("Ajuste de prueba")
    original = getattr(dialog.service, method)
    calls = []
    def reentrant(**kwargs):
        calls.append(1)
        assert not dialog._save_button.isEnabled()
        dialog._on_accept()
        return original(**kwargs)
    monkeypatch.setattr(dialog.service, method, reentrant)
    dialog._on_accept()
    dialog._on_accept()
    assert len(calls) == 1
    assert ClientAccountMovement.select().count() == 1
    assert ClientPayment.select().count() == (1 if kind == "payment" else 0)
    # A new operation with the same values remains valid.
    second = cls(current_user="test", preset_client=client)
    second.amount_input.setValue(100)
    if kind != "payment":
        second.description_input.setText("Ajuste de prueba")
    second._on_accept()
    assert ClientAccountMovement.select().count() == 2


def test_payment_audit_failure_rolls_back_payment_and_movement(db):
    from app.models.masters import Client
    from app.models.accounting import ClientAccountMovement
    from app.models.payments import ClientPayment
    from app.services.client_payment_service import ClientPaymentService
    class FailingAudit:
        def record(self, **kwargs):
            raise RuntimeError("audit failed")
    client = Client.create(name="Cliente prueba", cuit="30123456780", iva_condition="RI")
    with pytest.raises(RuntimeError, match="audit failed"):
        ClientPaymentService("test", audit_service=FailingAudit()).register_payment(client=client, amount=100)
    assert ClientPayment.select().count() == 0
    assert ClientAccountMovement.select().count() == 0


def test_annul_one_of_equal_payments_leaves_other_active(db):
    from app.models.masters import Client
    from app.models.accounting import ClientAccountMovement
    from app.models.payments import ClientPayment
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.services.client_payment_service import ClientPaymentService, ClientPaymentError
    from app.services.ledger_query_service import client_balance
    PermissionService().seed_defaults()
    admin = AuthService().create_user("admin_867", "secreto", "Administrador")
    client = Client.create(name="Cliente prueba", cuit="30123456780", iva_condition="RI")
    service = ClientPaymentService(admin.username)
    first = service.register_payment(client=client, amount=100)
    second = service.register_payment(client=client, amount=100)
    service.annul_payment(first, authorized_by=admin, reason="Duplicado")
    assert ClientPayment.get_by_id(first.id).status == ClientPayment.STATUS_ANNULLED
    assert ClientPayment.get_by_id(second.id).status == ClientPayment.STATUS_ACTIVE
    assert client_balance(client) == pytest.approx(-100)
    with pytest.raises(ClientPaymentError):
        service.annul_payment(first, authorized_by=admin, reason="Segundo intento")
    assert ClientAccountMovement.select().count() == 3


def test_idempotency_key_returns_same_payment_once(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.models.payments import ClientPayment, ClientPaymentDetail
    from app.services.client_payment_service import ClientPaymentService

    client = Client.create(name="Cliente idempotente", cuit="30123456781", iva_condition="RI")
    service = ClientPaymentService("test")

    first = service.register_compound_payment(
        client=client,
        details=[{"method": "efectivo", "amount": 100}],
        idempotency_key="pago-867-a",
    )
    second = service.register_compound_payment(
        client=client,
        details=[{"method": "efectivo", "amount": 100}],
        idempotency_key="pago-867-a",
    )

    assert second.id == first.id
    assert ClientPayment.select().count() == 1
    assert ClientPaymentDetail.select().count() == 1
    assert ClientAccountMovement.select().count() == 1


def test_same_idempotency_key_with_other_amount_is_rejected(db):
    from app.models.masters import Client
    from app.services.client_payment_service import (
        ClientPaymentError,
        ClientPaymentService,
    )

    client = Client.create(name="Cliente idempotente 2", cuit="30123456782", iva_condition="RI")
    service = ClientPaymentService("test")
    service.register_compound_payment(
        client=client,
        details=[{"method": "efectivo", "amount": 100}],
        idempotency_key="pago-867-b",
    )

    with pytest.raises(ClientPaymentError, match="idempotencia"):
        service.register_compound_payment(
            client=client,
            details=[{"method": "efectivo", "amount": 200}],
            idempotency_key="pago-867-b",
        )


def test_different_keys_allow_legitimate_equal_payments(db):
    from app.models.masters import Client
    from app.models.payments import ClientPayment
    from app.services.client_payment_service import ClientPaymentService

    client = Client.create(name="Cliente idempotente 3", cuit="30123456783", iva_condition="RI")
    service = ClientPaymentService("test")

    first = service.register_compound_payment(
        client=client,
        details=[{"method": "efectivo", "amount": 100}],
        idempotency_key="pago-867-c",
    )
    second = service.register_compound_payment(
        client=client,
        details=[{"method": "efectivo", "amount": 100}],
        idempotency_key="pago-867-d",
    )

    assert first.id != second.id
    assert ClientPayment.select().count() == 2


def test_client_payment_idempotency_index_exists(db):
    from app.config.schema import ensure_runtime_schema

    ensure_runtime_schema(db)
    indexes = db.get_indexes("clientpayment")
    assert any(
        index.unique and set(index.columns) == {"idempotency_key"}
        for index in indexes
    )


def test_concurrent_key_hits_unique_index_and_returns_existing(db, monkeypatch):
    from datetime import date

    from app.models.masters import Client
    from app.models.payments import ClientPayment
    from app.services.client_payment_service import ClientPaymentService

    client = Client.create(name="Cliente idempotente 5", cuit="30123456785", iva_condition="RI")
    existing = ClientPayment.create(
        receipt_number="REC-RACE-0001",
        idempotency_key="pago-867-race",
        client=client,
        payment_date=date.today(),
        amount=100,
        method="efectivo",
        created_by="otra-instancia",
    )
    service = ClientPaymentService("test")
    calls = {"count": 0}
    original_lookup = ClientPayment.get_or_none

    def lookup_only_after_insert(idempotency_key):
        calls["count"] += 1
        if calls["count"] == 1:
            return None
        return original_lookup(
            ClientPayment.idempotency_key == idempotency_key
        )

    monkeypatch.setattr(service, "_payment_for_key", lookup_only_after_insert)

    result = service.register_compound_payment(
        client=client,
        details=[{"method": "efectivo", "amount": 100}],
        idempotency_key="pago-867-race",
    )

    assert result.id == existing.id
    assert ClientPayment.select().count() == 1


def test_payment_dialog_reuses_key_after_uncertain_failure(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.models.masters import Client
    from app.services.client_payment_service import ClientPaymentError
    from app.ui.customer_payment_dialog import ClientPaymentDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente idempotente 4", cuit="30123456784", iva_condition="RI")
    dialog = ClientPaymentDialog(current_user="test", preset_client=client)
    dialog.amount_input.setValue(100)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)

    original = dialog.service.register_compound_payment
    keys = []

    def flaky(**kwargs):
        keys.append(kwargs["idempotency_key"])
        if len(keys) == 1:
            raise ClientPaymentError("resultado de commit incierto")
        return original(**kwargs)

    monkeypatch.setattr(dialog.service, "register_compound_payment", flaky)

    dialog._on_accept()
    app.processEvents()
    assert dialog.registered_payment() is None

    dialog._on_accept()
    app.processEvents()
    assert dialog.registered_payment() is not None
    assert keys[0] == keys[1]
