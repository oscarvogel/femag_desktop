"""#609 - Selector de tipo de reporte en Cuenta Corriente.

El operador elige entre `Resumido` (el reporte actual) y `Detallado`
(vendedor > cliente > movimientos) antes de generar el PDF.
"""

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


def _choose(monkeypatch, item, accepted=True):
    """Simula la eleccion del operador en el dialogo."""
    from PyQt5.QtWidgets import QInputDialog

    asked = {}

    def _get_item(parent, title, label, items, current=0, editable=False):
        asked["title"] = title
        asked["label"] = label
        asked["items"] = list(items)
        return item, accepted

    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(_get_item))
    return asked


def test_selector_offers_resumido_and_detallado(db, monkeypatch):
    salesperson = _salesperson(db)
    page = _ledger_page(portfolio_print_callback=lambda summary: None)
    page.refresh()
    page.salesperson_filter.setCurrentIndex(
        page.salesperson_filter.findData(salesperson.id)
    )
    asked = _choose(monkeypatch, "Resumido")

    page._on_portfolio_print()

    assert asked["items"] == ["Resumido", "Detallado"]


def test_summary_defaults_to_the_summarized_report(db):
    salesperson = _salesperson(db)
    page = _ledger_page(portfolio_print_callback=lambda summary: None)
    page.refresh()
    page.salesperson_filter.setCurrentIndex(
        page.salesperson_filter.findData(salesperson.id)
    )

    assert page.portfolio_summary()["report_type"] == "resumido"


def test_operator_can_select_the_detailed_report(db, monkeypatch):
    salesperson = _salesperson(db)
    received = []
    page = _ledger_page(portfolio_print_callback=received.append)
    page.refresh()
    page.salesperson_filter.setCurrentIndex(
        page.salesperson_filter.findData(salesperson.id)
    )
    _choose(monkeypatch, "Detallado")

    page._on_portfolio_print()

    assert len(received) == 1
    assert received[0]["report_type"] == "detallado"
    assert received[0]["salesperson"] == salesperson


def test_operator_can_select_the_summarized_report(db, monkeypatch):
    salesperson = _salesperson(db)
    received = []
    page = _ledger_page(portfolio_print_callback=received.append)
    page.refresh()
    page.salesperson_filter.setCurrentIndex(
        page.salesperson_filter.findData(salesperson.id)
    )
    _choose(monkeypatch, "Resumido")

    page._on_portfolio_print()

    assert received[0]["report_type"] == "resumido"


def test_cancelling_the_selector_generates_nothing(db, monkeypatch):
    salesperson = _salesperson(db)
    received = []
    page = _ledger_page(portfolio_print_callback=received.append)
    page.refresh()
    page.salesperson_filter.setCurrentIndex(
        page.salesperson_filter.findData(salesperson.id)
    )
    _choose(monkeypatch, "Resumido", accepted=False)

    page._on_portfolio_print()

    assert received == []
    # Cancelar no deja el tipo de reporte cambiado.
    assert page.portfolio_summary()["report_type"] == "resumido"


def test_the_selected_type_is_kept_for_the_send_actions(db, monkeypatch):
    """WhatsApp y correo usan el mismo helper de exportacion que la impresion."""
    salesperson = _salesperson(db)
    page = _ledger_page(portfolio_print_callback=lambda summary: None)
    page.refresh()
    page.salesperson_filter.setCurrentIndex(
        page.salesperson_filter.findData(salesperson.id)
    )
    _choose(monkeypatch, "Detallado")
    page._on_portfolio_print()

    assert page.portfolio_summary()["report_type"] == "detallado"


def test_print_handler_generates_the_detailed_pdf(db, monkeypatch, tmp_path):
    from app.ui.desktop_app import FemagDesktopWindow

    salesperson = _salesperson(db)
    opened = []
    window = _fake_window(tmp_path)
    monkeypatch.setattr(
        "app.ui.desktop_app._open_print_output", lambda path: opened.append(path)
    )

    FemagDesktopWindow._print_salesperson_portfolio(
        window,
        {
            "salesperson": salesperson,
            "rows": [],
            "label": salesperson.name,
            "slug": None,
            "report_type": "detallado",
        },
    )

    assert len(opened) == 1
    assert "detallado" in opened[0].name


def test_print_handler_keeps_the_summarized_pdf_by_default(db, monkeypatch, tmp_path):
    from app.ui.desktop_app import FemagDesktopWindow

    salesperson = _salesperson(db)
    opened = []
    window = _fake_window(tmp_path)
    monkeypatch.setattr(
        "app.ui.desktop_app._open_print_output", lambda path: opened.append(path)
    )

    FemagDesktopWindow._print_salesperson_portfolio(
        window,
        {
            "salesperson": salesperson,
            "rows": [],
            "label": salesperson.name,
            "slug": None,
        },
    )

    assert opened[0].name == "resumen_cuenta_corriente_luis_" + _today() + ".pdf"


def _today():
    from datetime import date

    return date.today().strftime("%Y%m%d")


def test_print_action_stays_enabled_without_a_selected_client(db, monkeypatch):
    """Elegir el tipo de reporte no puede depender de tener un cliente abierto."""
    salesperson = _salesperson(db)
    page = _ledger_page(portfolio_print_callback=lambda summary: None)
    page.refresh()
    page.salesperson_filter.setCurrentIndex(
        page.salesperson_filter.findData(salesperson.id)
    )
    _choose(monkeypatch, "Detallado")

    page._sync_more_actions()
    assert page._selected_client() is None
    assert page.portfolio_print_action.isEnabled()
