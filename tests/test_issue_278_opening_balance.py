import os
from datetime import date

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_register_opening_balance_persists_identifiable_audited_movement(db):
    from app.models.audit import AuditLog
    from app.models.masters import Client
    from app.services.client_opening_balance_service import ClientOpeningBalanceService

    client = Client.create(name="Cliente apertura", cuit="30700000278", iva_condition="RI")

    movement = ClientOpeningBalanceService("admin_278").register(
        client=client,
        amount=1250.75,
        balance_type="debit",
        currency="ars",
        movement_date=date(2026, 8, 13),
    )

    assert movement.movement_type == "opening_balance"
    assert movement.total_amount == 1250.75
    assert movement.currency == "ARS"
    assert movement.movement_date == date(2026, 8, 13)
    assert movement.description == "Saldo inicial de apertura - Débito (ARS)"
    assert movement.reference == "APERTURA-DEBITO-ARS"
    assert movement.created_by == "admin_278"
    audit = AuditLog.get(AuditLog.record_ref == f"ClientAccountMovement:{movement.id}")
    assert audit.user == "admin_278"
    assert audit.action == "registrar_saldo_inicial"
    assert audit.new_value["currency"] == "ARS"
    assert audit.new_value["balance_type"] == "debit"


def test_register_opening_balance_rejects_duplicate_for_client_and_currency(db):
    from app.models.masters import Client
    from app.services.client_opening_balance_service import (
        ClientOpeningBalanceError,
        ClientOpeningBalanceService,
    )

    client = Client.create(name="Cliente duplicado", cuit="30700001278", iva_condition="RI")
    service = ClientOpeningBalanceService("admin_278")
    service.register(client=client, amount=100, currency="ARS")

    with pytest.raises(ClientOpeningBalanceError, match="ya tiene saldo inicial en ARS"):
        service.register(client=client, amount=200, currency="ARS")

    usd = service.register(
        client=client,
        amount=50,
        balance_type="credit",
        currency="USD",
    )
    assert usd.currency == "USD"
    assert usd.total_amount == -50
    assert usd.description == "Saldo inicial de apertura - Crédito (USD)"
    assert usd.reference == "APERTURA-CREDITO-USD"


def test_clients_action_registers_once_and_disables_immediately(db):
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QPushButton

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente UI apertura", cuit="30700002278", iva_condition="RI")
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_ui_278", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    button = window.findChild(QPushButton, "addClientOpeningBalanceButton")
    assert button is not None
    assert button.isEnabled()

    def fill_dialog():
        dialog = app.activeModalWidget()
        assert dialog.objectName() == "clientOpeningBalanceDialog"
        type_input = dialog.findChild(QComboBox, "clientOpeningBalanceTypeInput")
        type_input.setCurrentIndex(type_input.findData("credit"))
        dialog.findChild(QDoubleSpinBox, "clientOpeningBalanceAmountInput").setValue(800)
        dialog.findChild(QPushButton, "saveClientOpeningBalanceButton").click()

    QTimer.singleShot(0, fill_dialog)
    button.click()
    app.processEvents()

    movement = ClientAccountMovement.get(
        (ClientAccountMovement.client == client)
        & (ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_OPENING_BALANCE)
    )
    assert movement.total_amount == -800
    assert movement.reference == "APERTURA-CREDITO-ARS"
    assert not button.isEnabled()

    from app.ui.customer_ledger import CustomerLedgerPage

    ledger = CustomerLedgerPage(current_user="admin_ui_278")
    app.processEvents()
    assert ledger.movements_table.rowCount() == 1
    assert ledger.movements_table.item(0, 1).text() == "Saldo inicial"
    assert ledger.movements_table.item(0, 2).text() == "APERTURA-CREDITO-ARS"
    assert ledger.movements_table.item(0, 3).text() == (
        "Saldo inicial de apertura - Crédito (ARS)"
    )
    assert ledger.detail_balance.text() == "$-800.00"
