import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_message_supports_multiple_recipients_and_confirmed_subject(tmp_path):
    from app.services.account_statement_mail_service import build_account_statement_message

    pdf_path = tmp_path / "extracto.pdf"
    pdf_path.write_bytes(b"%PDF-test")

    message = build_account_statement_message(
        client_name="Cliente Uno",
        recipients=["Pagos@Example.com", "admin@example.com", "pagos@example.com"],
        sender="cuentas@example.com",
        subject="Resumen agosto",
        pdf_path=pdf_path,
    )

    assert message["To"] == "pagos@example.com, admin@example.com"
    assert message["Subject"] == "Resumen agosto"
    assert next(message.iter_attachments()).get_payload(decode=True) == b"%PDF-test"


def test_active_email_options_exclude_inactive_and_put_primary_first(db):
    from app.models.masters import Client
    from app.services.client_email_service import ClientEmailService
    from app.ui.desktop_app import _active_client_email_options

    client = Client.create(name="Cliente destinatarios", cuit="30700000281", iva_condition="RI")
    service = ClientEmailService("admin_281")
    inactive = service.create(client=client, email="viejo@example.com")
    service.toggle_active(inactive)
    service.create(client=client, email="compras@example.com", label="Compras")
    service.create(
        client=client,
        email="pagos@example.com",
        label="Pagos",
        is_primary=True,
    )

    assert _active_client_email_options(client) == [
        ("pagos@example.com", "Pagos", True),
        ("compras@example.com", "Compras", False),
    ]


def test_recipient_dialog_preselects_primary_and_allows_multiple(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QLabel, QListWidget, QPushButton

    from app.ui.desktop_app import _AccountStatementRecipientsDialog

    app = QApplication.instance() or QApplication([])
    dialog = _AccountStatementRecipientsDialog(
        client_name="Cliente Uno",
        options=[
            ("principal@example.com", "Pagos", True),
            ("otro@example.com", "Compras", False),
        ],
    )
    recipients = dialog.findChild(QListWidget, "accountStatementRecipientsList")
    assert recipients.item(0).checkState() == Qt.Checked
    assert recipients.item(1).checkState() == Qt.Unchecked
    recipients.item(1).setCheckState(Qt.Checked)
    dialog.findChild(QPushButton, "confirmAccountStatementEmailButton").click()
    app.processEvents()

    assert dialog.result() == dialog.Accepted
    assert dialog.selected_recipients() == (
        "principal@example.com",
        "otro@example.com",
    )
    assert dialog.subject() == "Extracto de cuenta corriente - Cliente Uno"


def test_recipient_dialog_requires_at_least_one_destination(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QLabel, QListWidget, QPushButton

    from app.ui.desktop_app import _AccountStatementRecipientsDialog

    app = QApplication.instance() or QApplication([])
    dialog = _AccountStatementRecipientsDialog(
        client_name="Cliente Uno",
        options=[("principal@example.com", "", True)],
    )
    recipients = dialog.findChild(QListWidget, "accountStatementRecipientsList")
    recipients.item(0).setCheckState(Qt.Unchecked)
    dialog.findChild(QPushButton, "confirmAccountStatementEmailButton").click()
    app.processEvents()

    assert dialog.result() != dialog.Accepted
    assert "Seleccione" in dialog.findChild(
        QLabel, "accountStatementRecipientsFeedback"
    ).text()
