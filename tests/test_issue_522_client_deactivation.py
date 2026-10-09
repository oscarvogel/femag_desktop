import pytest


def _set_combo_data(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_client_service_deactivates_without_deleting_and_filters_selectable_clients(db):
    from app.models.masters import Client
    from app.services.client_service import ClientService

    active = Client.create(name="Cliente activo 522", cuit="30700000522", iva_condition="RI")
    inactive = Client.create(name="Cliente inactivo 522", cuit="30700010522", iva_condition="RI")

    service = ClientService(current_user="issue522")
    service.set_active(inactive, False)

    assert Client.get_by_id(inactive.id).active is False
    assert {client.id for client in service.active_clients_query()} == {active.id}

    service.set_active(inactive, True)
    assert Client.get_by_id(inactive.id).active is True
    assert {client.id for client in service.active_clients_query()} == {active.id, inactive.id}


def test_client_entry_dialog_edits_active_state(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QPushButton

    from app.models.masters import Client
    from app.ui.master_abm import ClientEntryDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente UI 522", cuit="30700020522", iva_condition="RI")

    dialog = ClientEntryDialog(current_user="issue522_ui", record_id=client.id)
    state = dialog.active_combo
    assert isinstance(state, QComboBox)
    assert state.objectName() == "clientActiveInput"
    assert state.currentData() is True

    _set_combo_data(state, False)
    dialog.findChild(QPushButton, "saveClientButton").click()
    app.processEvents()

    assert Client.get_by_id(client.id).active is False

    edit = ClientEntryDialog(current_user="issue522_ui", record_id=client.id)
    state = edit.active_combo
    assert isinstance(state, QComboBox)
    assert state.objectName() == "clientActiveInput"
    assert state.currentData() is False
    _set_combo_data(state, True)
    edit.findChild(QPushButton, "saveClientButton").click()
    app.processEvents()

    assert Client.get_by_id(client.id).active is True


def test_load_order_and_payment_selectors_exclude_inactive_clients(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Client
    from app.ui.customer_payment_dialog import ClientPaymentDialog
    from app.ui.load_orders import _client_options

    app = QApplication.instance() or QApplication([])
    active = Client.create(name="Seleccionable 522", cuit="30700030522", iva_condition="RI")
    inactive = Client.create(
        name="No seleccionable 522",
        cuit="30700040522",
        iva_condition="RI",
        active=False,
    )

    order_ids = {option.id for option in _client_options()}
    assert active.id in order_ids
    assert inactive.id not in order_ids

    dialog = ClientPaymentDialog(current_user="issue522_payment")
    combo = dialog.findChild(QComboBox, "clientPaymentClientCombo")
    assert combo.findData(active.id) >= 0
    assert combo.findData(inactive.id) == -1


def test_manual_budget_rejects_inactive_client(db):
    from app.models.masters import Client
    from app.services.budget_service import BudgetService

    client = Client.create(
        name="Cliente presupuesto inactivo 522",
        cuit="30700050522",
        iva_condition="RI",
        active=False,
    )

    with pytest.raises(ValueError, match="inactivo"):
        BudgetService(current_user="issue522_budget").create_manual(
            client=client,
            items=[],
        )
