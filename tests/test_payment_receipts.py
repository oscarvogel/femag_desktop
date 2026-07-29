from pypdf import PdfReader
import pytest
from pytest import approx


def _pdf_text(path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def _client():
    from app.models.masters import Client

    return Client.create(
        name="Cliente Recibo",
        cuit="30700000123",
        iva_condition="RI",
    )


def test_admin_authorization_accepts_only_active_administrator(db):
    from app.services.auth_service import AuthService

    service = AuthService()
    admin = service.create_user("admin_recibos", "secreto", "Administrador")
    service.create_user("secretaria_recibos", "secreto", "Secretaria")

    assert service.authorize_administrator("admin_recibos", "secreto") == admin
    assert service.authorize_administrator("admin_recibos", "incorrecta") is None
    assert service.authorize_administrator("secretaria_recibos", "secreto") is None

    admin.active = False
    admin.save()
    assert service.authorize_administrator("admin_recibos", "secreto") is None


def test_annul_payment_requires_admin_and_creates_accounting_reversal(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.audit import AuditLog
    from app.models.payments import ClientPayment
    from app.services.auth_service import AuthService
    from app.services.client_payment_service import ClientPaymentError, ClientPaymentService
    from app.services.ledger_query_service import client_balance

    auth = AuthService()
    admin = auth.create_user("admin_anulacion", "secreto", "Administrador")
    secretary = auth.create_user("secretaria_anulacion", "secreto", "Secretaria")
    client = _client()
    service = ClientPaymentService(current_user="operador")
    payment = service.register_payment(client=client, amount=1250)

    assert client_balance(client) == approx(-1250)
    with pytest.raises(PermissionError, match="administrador"):
        service.annul_payment(payment, authorized_by=secretary)

    annulled = service.annul_payment(
        payment,
        authorized_by=admin,
        reason="Pago cargado por duplicado",
    )

    assert annulled.status == ClientPayment.STATUS_ANNULLED
    assert annulled.annulled_by == admin.username
    assert annulled.annulment_reason == "Pago cargado por duplicado"
    assert annulled.annulled_at is not None
    assert client_balance(client) == approx(0)

    movements = list(
        ClientAccountMovement.select().order_by(ClientAccountMovement.id)
    )
    assert [movement.movement_type for movement in movements] == [
        ClientAccountMovement.TYPE_PAYMENT,
        ClientAccountMovement.TYPE_PAYMENT_REVERSAL,
    ]
    assert [movement.total_amount for movement in movements] == approx([-1250, 1250])
    assert movements[1].is_reversal is True
    assert movements[1].reverses == movements[0]
    assert movements[1].payment == payment

    audit = AuditLog.get(
        AuditLog.action == "anular_pago",
        AuditLog.record_ref == f"ClientPayment:{payment.id}",
    )
    assert audit.new_value["annulled_by"] == admin.username
    assert audit.new_value["reversal_movement_id"] == movements[1].id

    with pytest.raises(ClientPaymentError, match="ya está anulado"):
        service.annul_payment(payment, authorized_by=admin)
    assert ClientAccountMovement.select().count() == 2


def test_receipt_pdf_shows_payment_and_annulment_state(db, tmp_path):
    from app.models.audit import AuditLog
    from app.services.auth_service import AuthService
    from app.services.account_statement_print_service import export_account_statement
    from app.services.client_payment_service import ClientPaymentService
    from app.services.payment_receipt_print_service import PaymentReceiptPrintService

    admin = AuthService().create_user("admin_pdf_recibo", "secreto", "Administrador")
    payment_service = ClientPaymentService(current_user="caja")
    payment = payment_service.register_payment(
        client=_client(),
        amount=2500.5,
        method="transferencia",
        reference="TRF-9988",
        observations="Pago de prueba",
    )
    printer = PaymentReceiptPrintService(current_user="caja")

    active_path = printer.export_pdf(payment, tmp_path / "activo")
    active_text = _pdf_text(active_path)

    assert active_path.name == "recibo_REC-00000001.pdf"
    assert "RECIBO DE PAGO" in active_text
    assert "REC-00000001" in active_text
    assert "Cliente Recibo" in active_text
    assert "Transferencia" in active_text
    assert "TRF-9988" in active_text
    assert "ANULADO" not in active_text

    payment_service.annul_payment(
        payment,
        authorized_by=admin,
        reason="Comprobante duplicado",
    )
    annulled_path = printer.export_pdf(payment, tmp_path / "anulado")
    annulled_text = _pdf_text(annulled_path)

    assert "ANULADO" in annulled_text
    assert "admin_pdf_recibo" in annulled_text
    assert "Comprobante duplicado" in annulled_text
    statement_text = _pdf_text(
        export_account_statement(payment.client, tmp_path / "extracto")
    )
    assert "Pago anulado" in statement_text
    assert "Anulación de pago" in statement_text
    assert (
        AuditLog.select()
        .where(
            AuditLog.action == "imprimir_recibo",
            AuditLog.record_ref == f"ClientPayment:{payment.id}",
        )
        .count()
        == 2
    )
