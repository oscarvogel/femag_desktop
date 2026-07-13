from pathlib import Path
from types import SimpleNamespace


def test_whatsapp_handler_generates_pdf_and_opens_chat(monkeypatch, tmp_path):
    from app.ui.desktop_app import FemagDesktopWindow

    client = SimpleNamespace(name="Cliente Uno", phone="0376 15 4123456")
    pdf_path = tmp_path / "extracto.pdf"
    opened = []
    messages = []
    fake_window = SimpleNamespace()
    monkeypatch.setattr(
        "app.ui.desktop_app.account_statement_print_service.export_account_statement",
        lambda selected, output: pdf_path,
    )
    monkeypatch.setattr(
        "app.ui.desktop_app.account_statement_share_service.build_whatsapp_url",
        lambda name, phone: "https://wa.me/5493764123456?text=extracto",
    )
    monkeypatch.setattr(
        "app.ui.desktop_app.webbrowser.open",
        lambda url: opened.append(url) or True,
    )
    monkeypatch.setattr(
        "app.ui.desktop_app.QMessageBox.information",
        lambda *_args: messages.append(_args[-1]),
    )

    FemagDesktopWindow._share_account_statement_whatsapp(fake_window, client)

    assert opened == ["https://wa.me/5493764123456?text=extracto"]
    assert str(pdf_path) in messages[-1]


def test_whatsapp_handler_reports_missing_phone(monkeypatch, tmp_path):
    from app.ui.desktop_app import FemagDesktopWindow

    warnings = []
    fake_window = SimpleNamespace()
    client = SimpleNamespace(name="Cliente Uno", phone=None)
    monkeypatch.setattr(
        "app.ui.desktop_app.QMessageBox.warning",
        lambda *_args: warnings.append(_args[-1]),
    )

    FemagDesktopWindow._share_account_statement_whatsapp(fake_window, client)

    assert "telefono" in warnings[-1].lower()


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
        "app.ui.desktop_app.QMessageBox.question",
        lambda *_args: QMessageBox.Yes,
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
            "recipient": "cliente@example.com",
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
        "app.ui.desktop_app.QMessageBox.question",
        lambda *_args: QMessageBox.No,
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
        "app.ui.desktop_app.QMessageBox.question",
        lambda *_args: QMessageBox.Yes,
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
