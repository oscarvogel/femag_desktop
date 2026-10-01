import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace


def _ledger_page(**callbacks):
    from PyQt5.QtWidgets import QApplication

    from app.ui.customer_ledger import CustomerLedgerPage

    # La referencia debe sobrevivir: si el QApplication se libera, Qt aborta.
    app = QApplication.instance() or QApplication([])
    page = CustomerLedgerPage(current_user="admin", **callbacks)
    page._test_app = app
    return page


def _fake_window(tmp_path):
    """Ventana mínima con el helper real de exportacion enlazado."""
    from app.ui.desktop_app import FemagDesktopWindow

    window = SimpleNamespace(
        _print_output_dir=tmp_path,
        user=SimpleNamespace(id=1),
    )
    window._export_salesperson_portfolio = lambda summary: (
        FemagDesktopWindow._export_salesperson_portfolio(window, summary)
    )
    return window


def _salesperson(db, name="Luis", **kwargs):
    from app.models.masters import Salesperson

    values = {"name": name}
    values.update(kwargs)
    return Salesperson.create(**values)


def _client_with_movement(db, name, cuit, salesperson, amount):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client

    client = Client.create(
        name=name, cuit=cuit, iva_condition="RI", salesperson=salesperson
    )
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        total_amount=amount,
        description=f"Orden de carga demo {name}",
        source_ref=f"DEMO-{cuit}",
    )
    return client


def _summary(salesperson):
    return {
        "salesperson": salesperson,
        "rows": [],
        "label": salesperson.name,
        "slug": None,
    }


def test_portfolio_summary_respects_salesperson_filter(db):
    salesperson = _salesperson(db)
    other = _salesperson(db, name="Maria")
    _client_with_movement(db, "Cliente Luis", "30711100001", salesperson, 1000.0)
    _client_with_movement(db, "Cliente Maria", "30711100002", other, 2000.0)

    page = _ledger_page()
    page.refresh()
    page.salesperson_filter.setCurrentIndex(
        page.salesperson_filter.findData(salesperson.id)
    )

    summary = page.portfolio_summary()

    names = [row["client"].name for row in summary["rows"]]
    assert summary["salesperson"] == salesperson
    assert names == ["Cliente Luis"]
    assert summary["label"] == "Luis"


def test_portfolio_summary_respects_search_and_only_with_balance(db):
    salesperson = _salesperson(db)
    _client_with_movement(db, "Alimentos Guarani", "30711100011", salesperson, 500.0)
    zero = _client_with_movement(db, "Sin Deuda", "30711100012", salesperson, 0.0)

    page = _ledger_page()
    page.refresh()
    page.salesperson_filter.setCurrentIndex(
        page.salesperson_filter.findData(salesperson.id)
    )

    page.only_with_balance.setChecked(True)
    with_balance = page.portfolio_summary()
    assert [row["client"].name for row in with_balance["rows"]] == ["Alimentos Guarani"]

    page.only_with_balance.setChecked(False)
    page.search_input.setText("sin deuda")
    searched = page.portfolio_summary()
    assert [row["client"].name for row in searched["rows"]] == [zero.name]
    # El filtro de busqueda tambien manda sobre lo que entra al PDF.
    assert searched["rows"][0]["balance"] == 0.0


def test_portfolio_summary_without_single_seller(db):
    _salesperson(db)
    page = _ledger_page()
    page.refresh()

    summary = page.portfolio_summary()

    assert summary["salesperson"] is None
    assert summary["label"] == "Todos los vendedores"
    assert summary["slug"] == "todos"


def test_portfolio_summary_labels_unassigned_portfolio(db):
    page = _ledger_page()
    page.refresh()
    page.salesperson_filter.setCurrentIndex(
        page.salesperson_filter.findData("unassigned")
    )

    summary = page.portfolio_summary()

    assert summary["salesperson"] is None
    assert summary["label"] == "Sin asignar"
    assert summary["slug"] == "sin_asignar"


def test_print_action_is_enabled_even_without_a_selected_client(db):
    salesperson = _salesperson(db)
    page = _ledger_page(portfolio_print_callback=lambda summary: None)
    page.refresh()
    page.salesperson_filter.setCurrentIndex(
        page.salesperson_filter.findData(salesperson.id)
    )

    page._sync_more_actions()

    assert page._selected_client() is None
    assert page.portfolio_print_action.isEnabled()


def test_send_actions_are_disabled_without_a_single_seller(db):
    _salesperson(db)
    page = _ledger_page(
        portfolio_print_callback=lambda summary: None,
        portfolio_whatsapp_callback=lambda summary: None,
        portfolio_email_callback=lambda summary: None,
    )
    page.refresh()

    page._sync_more_actions()

    assert page.portfolio_print_action.isEnabled()
    assert not page.portfolio_whatsapp_action.isEnabled()
    assert not page.portfolio_email_action.isEnabled()


def test_send_actions_are_enabled_for_a_selected_seller(db):
    salesperson = _salesperson(db, phone="0376 15 4123456", email="luis@example.com")
    page = _ledger_page(
        portfolio_print_callback=lambda summary: None,
        portfolio_whatsapp_callback=lambda summary: None,
        portfolio_email_callback=lambda summary: None,
    )
    page.refresh()
    page.salesperson_filter.setCurrentIndex(
        page.salesperson_filter.findData(salesperson.id)
    )

    page._sync_more_actions()

    assert page.portfolio_whatsapp_action.isEnabled()
    assert page.portfolio_email_action.isEnabled()


def test_portfolio_print_handler_opens_generated_pdf(db, monkeypatch, tmp_path):
    from app.ui.desktop_app import FemagDesktopWindow

    salesperson = _salesperson(db)
    opened = []
    fake_window = _fake_window(tmp_path)
    monkeypatch.setattr(
        "app.ui.desktop_app._open_print_output", lambda path: opened.append(path)
    )

    FemagDesktopWindow._print_salesperson_portfolio(fake_window, _summary(salesperson))

    assert len(opened) == 1
    assert opened[0].name.startswith("resumen_cuenta_corriente_luis_")


def test_whatsapp_handler_sends_pdf_as_attachment(db, monkeypatch, tmp_path):
    from PyQt5.QtWidgets import QDialog

    from app.ui.desktop_app import FemagDesktopWindow

    salesperson = _salesperson(db, phone="0376 15 4123456")
    created = []
    started = []
    pdf_path = tmp_path / "resumen_cuenta_corriente_luis_20261001.pdf"
    pdf_path.write_bytes(b"%PDF-test")
    fake_service = SimpleNamespace(
        create_attempt=lambda **kwargs: created.append(kwargs) or SimpleNamespace(id=91)
    )
    fake_dialog = SimpleNamespace(
        exec_=lambda: QDialog.Accepted,
        phone=lambda: "+5493764123456",
        caption=lambda: "Resumen de cartera",
    )

    class FakeWorker:
        def __init__(self):
            self.signals = SimpleNamespace(
                succeeded=SimpleNamespace(connect=lambda _cb: None),
                failed=SimpleNamespace(connect=lambda _cb: None),
                finished=SimpleNamespace(connect=lambda _cb: None),
            )

    fake_worker = FakeWorker()
    fake_window = _fake_window(tmp_path)
    monkeypatch.setattr("app.ui.desktop_app.WhatsAppSendDialog", lambda **_kwargs: fake_dialog)
    monkeypatch.setattr("app.ui.desktop_app.WhatsAppEnvioService", lambda: fake_service)
    monkeypatch.setattr(
        "app.ui.desktop_app.salesperson_portfolio_print_service.export_salesperson_portfolio",
        lambda **_kwargs: pdf_path,
    )
    monkeypatch.setattr("app.ui.desktop_app.WhatsAppSendWorker", lambda **_kwargs: fake_worker)
    monkeypatch.setattr(
        "app.ui.desktop_app.QThreadPool.globalInstance",
        lambda: SimpleNamespace(start=lambda worker: started.append(worker)),
    )

    FemagDesktopWindow._share_salesperson_portfolio_whatsapp(
        fake_window, _summary(salesperson)
    )

    assert len(created) == 1
    assert created[0]["tipo_documento"] == "resumen_cuenta_vendedor"
    assert created[0]["documento_id"] == str(salesperson.id)
    assert created[0]["destinatario"] == "+5493764123456"
    # El PDF viaja como adjunto, no como enlace.
    assert created[0]["pdf_path"] == pdf_path
    assert started == [fake_worker]


def test_whatsapp_handler_explains_missing_phone(db, monkeypatch, tmp_path):
    from app.ui.desktop_app import FemagDesktopWindow

    salesperson = _salesperson(db, phone=None)
    warnings = []
    fake_window = _fake_window(tmp_path)
    monkeypatch.setattr(
        "app.ui.desktop_app.QMessageBox.warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )

    def _must_not_send():
        raise AssertionError("No se debe intentar enviar sin telefono.")

    monkeypatch.setattr("app.ui.desktop_app.WhatsAppEnvioService", _must_not_send)

    FemagDesktopWindow._share_salesperson_portfolio_whatsapp(
        fake_window, _summary(salesperson)
    )

    assert len(warnings) == 1
    title, message = warnings[0]
    assert title == "WhatsApp"
    assert "Luis" in message
    assert "telefono" in message.lower()


def test_email_handler_explains_missing_email(db, monkeypatch, tmp_path):
    from app.ui.desktop_app import FemagDesktopWindow

    salesperson = _salesperson(db, email=None)
    warnings = []
    started = []
    fake_window = _fake_window(tmp_path)
    monkeypatch.setattr(
        "app.ui.desktop_app.QMessageBox.warning",
        lambda _parent, title, message: warnings.append((title, message)),
    )
    monkeypatch.setattr(
        "app.ui.desktop_app._start_mail_worker", lambda worker: started.append(worker)
    )

    FemagDesktopWindow._email_salesperson_portfolio(
        fake_window, _summary(salesperson)
    )

    assert started == []
    assert len(warnings) == 1
    title, message = warnings[0]
    assert title == "Correo"
    assert "correo" in message.lower()


def test_email_handler_sends_summary_to_salesperson(db, monkeypatch, tmp_path):
    from app.ui.desktop_app import FemagDesktopWindow

    salesperson = _salesperson(db, email="Luis@Example.com")
    pdf_path = tmp_path / "resumen_cuenta_corriente_luis_20261001.pdf"
    pdf_path.write_bytes(b"%PDF-test")
    queued = []
    fake_window = _fake_window(tmp_path)
    monkeypatch.setattr(
        "app.ui.desktop_app.salesperson_portfolio_print_service.export_salesperson_portfolio",
        lambda **_kwargs: pdf_path,
    )
    monkeypatch.setattr(
        "app.ui.desktop_app._start_mail_worker", lambda worker: queued.append(worker)
    )
    monkeypatch.setattr("app.ui.desktop_app.QMessageBox.information", lambda *_args: None)

    FemagDesktopWindow._email_salesperson_portfolio(
        fake_window, _summary(salesperson)
    )

    assert len(queued) == 1
    worker = queued[0]
    assert worker.recipients == ("luis@example.com",)
    assert worker.pdf_path == pdf_path
    assert "Luis" in worker.subject
    # No es el texto del extracto de cliente: es el resumen de cartera.
    assert "resumen de cuenta corriente" in worker.body.lower()
    assert worker.body == worker.body.strip()
