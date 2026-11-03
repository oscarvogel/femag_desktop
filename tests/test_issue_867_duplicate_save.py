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
