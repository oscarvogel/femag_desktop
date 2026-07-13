from pathlib import Path

import pytest


SMTP_ENV = {
    "FEMAG_SMTP_HOST": "smtp.example.com",
    "FEMAG_SMTP_PORT": "587",
    "FEMAG_SMTP_USER": "mailer@example.com",
    "FEMAG_SMTP_PASSWORD": "secret-value",
    "FEMAG_SMTP_FROM": "cuentas@example.com",
    "FEMAG_SMTP_USE_TLS": "true",
}


def test_smtp_settings_load_from_environment():
    from app.services.account_statement_mail_service import SmtpSettings

    settings = SmtpSettings.from_env(SMTP_ENV)

    assert settings.host == "smtp.example.com"
    assert settings.port == 587
    assert settings.username == "mailer@example.com"
    assert settings.password == "secret-value"
    assert settings.sender == "cuentas@example.com"
    assert settings.use_tls is True


def test_smtp_settings_report_missing_configuration_without_values():
    from app.services.account_statement_mail_service import MailConfigurationError, SmtpSettings

    with pytest.raises(MailConfigurationError) as exc_info:
        SmtpSettings.from_env({"FEMAG_SMTP_PASSWORD": "do-not-show"})

    message = str(exc_info.value)
    assert "FEMAG_SMTP_HOST" in message
    assert "FEMAG_SMTP_FROM" in message
    assert "do-not-show" not in message


def test_build_message_attaches_pdf(tmp_path):
    from app.services.account_statement_mail_service import build_account_statement_message

    pdf_path = tmp_path / "extracto_cliente.pdf"
    pdf_path.write_bytes(b"%PDF-test")

    message = build_account_statement_message(
        client_name="Cliente Uno",
        recipient="cliente@example.com",
        sender="cuentas@example.com",
        pdf_path=pdf_path,
    )

    assert message["To"] == "cliente@example.com"
    assert message["From"] == "cuentas@example.com"
    assert "Cliente Uno" in message["Subject"]
    attachment = next(message.iter_attachments())
    assert attachment.get_filename() == "extracto_cliente.pdf"
    assert attachment.get_content_type() == "application/pdf"
    assert attachment.get_payload(decode=True) == b"%PDF-test"


def test_build_message_rejects_missing_recipient(tmp_path):
    from app.services.account_statement_mail_service import build_account_statement_message

    pdf_path = tmp_path / "extracto.pdf"
    pdf_path.write_bytes(b"%PDF-test")

    with pytest.raises(ValueError, match="correo"):
        build_account_statement_message(
            client_name="Cliente",
            recipient="",
            sender="cuentas@example.com",
            pdf_path=pdf_path,
        )


class FakeSmtp:
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.tls_started = False
        self.login_args = None
        self.message = None
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def starttls(self):
        self.tls_started = True

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.message = message


def test_send_account_statement_uses_tls_login_and_attachment(tmp_path):
    from app.services.account_statement_mail_service import SmtpSettings, send_account_statement

    FakeSmtp.instances.clear()
    pdf_path = tmp_path / "extracto.pdf"
    pdf_path.write_bytes(b"%PDF-test")
    settings = SmtpSettings.from_env(SMTP_ENV)

    send_account_statement(
        client_name="Cliente Uno",
        recipient="cliente@example.com",
        pdf_path=pdf_path,
        settings=settings,
        smtp_factory=FakeSmtp,
    )

    smtp = FakeSmtp.instances[-1]
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.example.com", 587, 20)
    assert smtp.tls_started is True
    assert smtp.login_args == ("mailer@example.com", "secret-value")
    assert smtp.message["To"] == "cliente@example.com"


def test_send_error_does_not_expose_smtp_password(tmp_path):
    from app.services.account_statement_mail_service import (
        AccountStatementMailError,
        SmtpSettings,
        send_account_statement,
    )

    class BrokenSmtp:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("server rejected secret-value")

    pdf_path = tmp_path / "extracto.pdf"
    pdf_path.write_bytes(b"%PDF-test")

    with pytest.raises(AccountStatementMailError) as exc_info:
        send_account_statement(
            client_name="Cliente",
            recipient="cliente@example.com",
            pdf_path=pdf_path,
            settings=SmtpSettings.from_env(SMTP_ENV),
            smtp_factory=BrokenSmtp,
        )

    assert "secret-value" not in str(exc_info.value)
