from datetime import date

import pytest

from app.models.masters import Client
from app.services.client_agenda_service import add_entry, find_entries


def test_schema_creates_agenda_table_on_existing_database(db):
    from app.config.schema import ensure_runtime_schema
    from app.models.client_agenda import ClientAgendaEntry

    db.drop_tables([ClientAgendaEntry])
    ensure_runtime_schema(db)
    ensure_runtime_schema(db)
    client = Client.create(name="Migrado", iva_condition="RI")
    add_entry(client.id, date(2026, 1, 1), "Prueba", "admin")
    assert len(find_entries(client.id)) == 1


def test_agenda_isolated_and_filters_inclusive(db):
    a = Client.create(name="Uno", iva_condition="RI")
    b = Client.create(name="Dos", iva_condition="RI")
    add_entry(a.id, date(2026, 1, 1), "Llamada por pago", "ana")
    add_entry(a.id, date(2026, 1, 31), "Otro pago", "ana")
    add_entry(a.id, date(2026, 2, 1), "Pago posterior", "ana")
    add_entry(b.id, date(2026, 1, 1), "Pago ajeno", "ana")
    entries = find_entries(a.id, "pago", date(2026, 1, 1), date(2026, 1, 31))
    assert [entry.text for entry in entries] == ["Otro pago", "Llamada por pago"]
    assert len(find_entries(a.id, date_from=date(2026, 2, 1))) == 1
    assert len(find_entries(a.id, date_to=date(2026, 1, 1))) == 1
    with pytest.raises(ValueError):
        find_entries(a.id, date_from=date(2026, 2, 1), date_to=date(2026, 1, 1))
    with pytest.raises(ValueError):
        add_entry(a.id, date.today(), "  ", "ana")


def test_agenda_dialog_save_and_reopen(db):
    from PyQt5.QtWidgets import QApplication
    from app.ui.client_agenda_dialog import ClientAgendaDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente", iva_condition="RI")
    dialog = ClientAgendaDialog(client.id, "ana")
    dialog.entry_text.setPlainText("Primera visita")
    dialog.save_entry()
    reopened = ClientAgendaDialog(client.id, "ana")
    assert reopened.table.rowCount() == 1
    assert reopened.table.item(0, 1).text() == "Primera visita"
    reopened.search.setText("inexistente")
    reopened.refresh()
    assert reopened.table.rowCount() == 0
    assert app is not None


def test_access_from_payment_and_order_preserves_drafts(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication
    from app.services.load_order_service import LoadOrderService
    from app.ui.customer_payment_dialog import ClientPaymentDialog
    from app.ui.desktop_app import LoadOrderEntryDialog
    import app.ui.client_agenda_dialog as agenda

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente agenda", iva_condition="RI")
    opened = []

    class FakeAgenda:
        def __init__(self, client_id, user, parent):
            opened.append((client_id, user))

        def exec_(self):
            return 0

    monkeypatch.setattr(agenda, "ClientAgendaDialog", FakeAgenda)
    payment = ClientPaymentDialog(current_user="caja", preset_client=client)
    payment.amount_input.setValue(123)
    payment._open_agenda()
    assert payment.amount_input.value() == 123
    order = LoadOrderEntryDialog(LoadOrderService(current_user="ventas"), "ventas")
    order.client_combo.setCurrentIndex(order.client_combo.findData(client.id))
    order.observations_input.setText("borrador")
    order._open_client_agenda()
    assert order.observations_input.text() == "borrador"
    assert opened == [(client.id, "caja"), (client.id, "ventas")]
    assert app is not None


def test_order_list_chooses_the_correct_client(db, monkeypatch):
    from conftest import _multi_client_data
    from PyQt5.QtWidgets import QApplication, QInputDialog, QPushButton
    from app.models.security import User, UserProfile
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow
    import app.ui.client_agenda_dialog as agenda

    app = QApplication.instance() or QApplication([])
    data = _multi_client_data()
    PermissionService().seed_defaults()
    user = User.create(username="ventas", password_hash="x", profile=UserProfile.get(UserProfile.name == "Administrador"))
    LoadOrderService(current_user="ventas").create_order(
        carrier=data["carrier"], driver=data["driver"], truck=data["truck"],
        destinations=[
            {"client": data["client"], "delivery_address": data["address"], "products": [{"product": data["product"], "quantity": 1}]},
            {"client": data["other_client"], "delivery_address": data["other_address"], "products": [{"product": data["other_product"], "quantity": 1}]},
        ], pallets=[],
    )
    opened = []

    class FakeAgenda:
        def __init__(self, client_id, user, parent):
            opened.append(client_id)
        def exec_(self):
            return 0

    monkeypatch.setattr(agenda, "ClientAgendaDialog", FakeAgenda)
    monkeypatch.setattr(QInputDialog, "getItem", lambda parent, title, label, options, *args: (next(x for x in options if f"ID {data['other_client'].id})" in x), True))
    window = FemagDesktopWindow(user=user, demo_mode=True)
    window.findChild(QPushButton, "ordersClientAgendaButton").click()
    assert opened == [data["other_client"].id]
    window.close()
    assert app is not None


def test_client_list_agenda_button_enabled_on_selection(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QPushButton, QTableWidget
    from app.models.masters import Client
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.master_abm import build_client_abm_page
    import app.ui.client_agenda_dialog as agenda

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    user = User.create(
        username="agenda_abm",
        password_hash="x",
        profile=UserProfile.get(UserProfile.name == "Administrador"),
    )
    page = build_client_abm_page(user=user, current_user=user.username)
    table = page.findChild(QTableWidget, "clientTable")
    button = page.findChild(QPushButton, "clientAgendaButton")
    assert button is not None
    assert not button.isEnabled()

    client = Client.create(
        name="Cliente agenda ABM", cuit="30700000872", iva_condition="RI"
    )
    page.refresh()
    table.setCurrentCell(0, 0)
    app.processEvents()
    assert button.isEnabled()

    opened = []

    class FakeAgenda:
        def __init__(self, client_id, current_user, parent):
            opened.append(client_id)

        def exec_(self):
            return 0

    monkeypatch.setattr(agenda, "ClientAgendaDialog", FakeAgenda)
    button.click()
    assert opened == [client.id]
    assert app is not None


def test_access_from_ledger_and_client_detail(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication
    from app.ui.customer_ledger import CustomerLedgerPage
    from app.ui.master_detail_dialogs import ClientDetailDialog
    import app.ui.client_agenda_dialog as agenda

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Agenda en ficha", iva_condition="RI")
    opened = []

    class FakeAgenda:
        def __init__(self, client_id, user, parent):
            opened.append(client_id)
        def exec_(self):
            return 0

    monkeypatch.setattr(agenda, "ClientAgendaDialog", FakeAgenda)
    ledger = CustomerLedgerPage(current_user="admin")
    ledger._open_agenda()
    detail = ClientDetailDialog(record_id=client.id, current_user="admin")
    detail._open_agenda()
    assert opened == [client.id, client.id]
    assert app is not None
