from pathlib import Path
from types import SimpleNamespace


def test_whatsapp_handler_generates_pdf_and_queues_gateway_send(monkeypatch, tmp_path):
    from PyQt5.QtWidgets import QDialog
    from app.ui.desktop_app import FemagDesktopWindow

    client = SimpleNamespace(id=9, name="Cliente Uno", phone="0376 15 4123456")
    pdf_path = tmp_path / "extracto.pdf"
    created = []
    started = []
    fake_service = SimpleNamespace(
        create_attempt=lambda **kwargs: created.append(kwargs) or SimpleNamespace(id=77)
    )
    fake_dialog = SimpleNamespace(
        exec_=lambda: QDialog.Accepted,
        phone=lambda: "+54 9 376 4123456",
        caption=lambda: "Extracto FEMAG",
    )
    class FakeWorker:
        def __init__(self):
            self.signals = SimpleNamespace(
                succeeded=SimpleNamespace(connect=lambda _cb: None),
                failed=SimpleNamespace(connect=lambda _cb: None),
                finished=SimpleNamespace(connect=lambda _cb: None),
            )

    fake_worker = FakeWorker()
    fake_window = SimpleNamespace(
        _print_output_dir=tmp_path,
        user=SimpleNamespace(id=1),
        stack=SimpleNamespace(currentWidget=lambda: None),
    )

    monkeypatch.setattr("app.ui.desktop_app.WhatsAppSendDialog", lambda **_kwargs: fake_dialog)
    monkeypatch.setattr("app.ui.desktop_app.WhatsAppEnvioService", lambda: fake_service)
    monkeypatch.setattr(
        "app.ui.desktop_app.account_statement_print_service.export_account_statement",
        lambda selected, output: pdf_path,
    )
    monkeypatch.setattr("app.ui.desktop_app.WhatsAppSendWorker", lambda **_kwargs: fake_worker)
    monkeypatch.setattr(
        "app.ui.desktop_app.QThreadPool.globalInstance",
        lambda: SimpleNamespace(start=lambda worker: started.append(worker)),
    )

    FemagDesktopWindow._share_account_statement_whatsapp(fake_window, client)

    assert len(created) == 1
    assert created[0]["tipo_documento"] == "extracto_cuenta"
    assert created[0]["documento_id"] == "9"
    assert created[0]["destinatario"] == "+54 9 376 4123456"
    assert created[0]["caption"] == "Extracto FEMAG"
    assert created[0]["pdf_path"] == pdf_path
    assert started == [fake_worker]


def test_whatsapp_handler_reports_configuration_error(monkeypatch, tmp_path):
    from PyQt5.QtWidgets import QDialog
    from app.ui.desktop_app import FemagDesktopWindow

    warnings = []
    fake_window = SimpleNamespace(
        _print_output_dir=tmp_path,
        user=SimpleNamespace(id=1),
        stack=SimpleNamespace(currentWidget=lambda: None),
    )
    client = SimpleNamespace(id=9, name="Cliente Uno", phone=None)
    fake_dialog = SimpleNamespace(
        exec_=lambda: QDialog.Accepted,
        phone=lambda: "+54 9 376 4123456",
        caption=lambda: "Extracto FEMAG",
    )

    monkeypatch.setattr("app.ui.desktop_app.WhatsAppSendDialog", lambda **_kwargs: fake_dialog)
    monkeypatch.setattr(
        "app.ui.desktop_app.WhatsAppEnvioService",
        lambda: (_ for _ in ()).throw(RuntimeError("Falta configurar WHATSAPP_API_KEY.")),
    )
    monkeypatch.setattr(
        "app.ui.desktop_app.QMessageBox.warning",
        lambda *_args: warnings.append(_args[-1]),
    )

    FemagDesktopWindow._share_account_statement_whatsapp(fake_window, client)

    assert warnings == ["Falta configurar WHATSAPP_API_KEY."]


def test_email_handler_confirms_and_sends_pdf(monkeypatch, tmp_path):
    from PyQt5.QtWidgets import QMessageBox

    from app.ui.desktop_app import FemagDesktopWindow

    client = SimpleNamespace(name="Cliente Uno", email="cliente@example.com")
    pdf_path = tmp_path / "extracto.pdf"
    sent = []
    started = []
    messages = []
    fake_window = SimpleNamespace(_print_output_dir=tmp_path)
    monkeypatch.setattr(
        "app.ui.desktop_app.account_statement_print_service.export_account_statement",
        lambda selected, output: pdf_path,
    )
    monkeypatch.setattr(
        "app.ui.desktop_app._AccountStatementRecipientsDialog",
        lambda **_kwargs: SimpleNamespace(
            exec_=lambda: QMessageBox.Accepted,
            selected_recipients=lambda: ("cliente@example.com",),
            subject=lambda: "Extracto de cuenta corriente - Cliente Uno",
        ),
    )
    monkeypatch.setattr(
        "app.ui.desktop_app.account_statement_mail_service.send_account_statement",
        lambda **kwargs: sent.append(kwargs),
    )
    monkeypatch.setattr(
        "app.ui.desktop_app._start_mail_worker",
        lambda worker: started.append(worker),
    )
    monkeypatch.setattr(
        "app.ui.desktop_app.QMessageBox.information",
        lambda *_args: messages.append(_args[-1]),
    )

    FemagDesktopWindow._email_account_statement(fake_window, client)

    assert sent == []
    assert len(started) == 1
    started[0].run()
    assert sent == [
        {
            "client_name": "Cliente Uno",
            "recipients": ("cliente@example.com",),
            "subject": "Extracto de cuenta corriente - Cliente Uno",
            "pdf_path": pdf_path,
        }
    ]
    assert "enviado" in messages[-1].lower()


def test_email_handler_does_not_send_when_user_cancels(monkeypatch, tmp_path):
    from PyQt5.QtWidgets import QMessageBox

    from app.ui.desktop_app import FemagDesktopWindow

    sent = []
    fake_window = SimpleNamespace(_print_output_dir=tmp_path)
    client = SimpleNamespace(name="Cliente Uno", email="cliente@example.com")
    monkeypatch.setattr(
        "app.ui.desktop_app._AccountStatementRecipientsDialog",
        lambda **_kwargs: SimpleNamespace(exec_=lambda: QMessageBox.Rejected),
    )
    monkeypatch.setattr(
        "app.ui.desktop_app.account_statement_mail_service.send_account_statement",
        lambda **kwargs: sent.append(kwargs),
    )

    FemagDesktopWindow._email_account_statement(fake_window, client)

    assert sent == []


def test_email_handler_reports_background_send_error(monkeypatch, tmp_path):
    from PyQt5.QtWidgets import QMessageBox

    from app.ui.desktop_app import FemagDesktopWindow

    warnings = []
    fake_window = SimpleNamespace(_print_output_dir=tmp_path)
    client = SimpleNamespace(name="Cliente Uno", email="cliente@example.com")
    pdf_path = tmp_path / "extracto.pdf"
    monkeypatch.setattr(
        "app.ui.desktop_app._AccountStatementRecipientsDialog",
        lambda **_kwargs: SimpleNamespace(
            exec_=lambda: QMessageBox.Accepted,
            selected_recipients=lambda: ("cliente@example.com",),
            subject=lambda: "Extracto de cuenta corriente - Cliente Uno",
        ),
    )
    monkeypatch.setattr(
        "app.ui.desktop_app.account_statement_print_service.export_account_statement",
        lambda selected, output: pdf_path,
    )
    monkeypatch.setattr(
        "app.ui.desktop_app.account_statement_mail_service.send_account_statement",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("SMTP no disponible")),
    )
    monkeypatch.setattr(
        "app.ui.desktop_app._start_mail_worker",
        lambda worker: worker.run(),
    )
    monkeypatch.setattr(
        "app.ui.desktop_app.QMessageBox.warning",
        lambda *_args: warnings.append(_args[-1]),
    )

    FemagDesktopWindow._email_account_statement(fake_window, client)

    assert warnings == ["SMTP no disponible"]
