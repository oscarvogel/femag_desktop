from datetime import date

import pytest
from pypdf import PdfReader
from pytest import approx

from app.models.accounting import ClientAccountMovement
from app.models.audit import AuditLog
from app.models.masters import Client
from app.services.client_manual_credit_service import (
    ClientManualCreditError,
    ClientManualCreditService,
)
from app.services.ledger_query_service import client_balance


def _client(name="Cliente Crédito Manual"):
    return Client.create(name=name, cuit="30700000288", iva_condition="RI")


def test_register_manual_credit_reduces_balance_and_audits(db):
    client = _client()
    movement = ClientManualCreditService(current_user="caja").register_manual_credit(
        client=client,
        amount=1250,
        credit_date=date(2026, 8, 13),
        description="Bonificación comercial",
        reference="NC-MAN-001",
        observations="Aprobada por gerencia",
    )

    assert movement.movement_type == ClientAccountMovement.TYPE_MANUAL_CREDIT
    assert movement.amount == approx(-1250)
    assert movement.total_amount == approx(-1250)
    assert movement.movement_date == date(2026, 8, 13)
    assert movement.description == "Bonificación comercial"
    assert movement.reference == "NC-MAN-001"
    assert movement.observations == "Aprobada por gerencia"
    assert movement.source_ref == f"ManualCredit:{movement.id}"
    assert movement.load_order is None
    assert movement.payment is None
    assert movement.is_reversal is False
    assert client_balance(client) == approx(-1250)

    audit = AuditLog.get(AuditLog.action == "registrar_credito_manual")
    assert audit.user == "caja"
    assert audit.record_ref == f"ClientAccountMovement:{movement.id}"
    assert audit.new_value["amount"] == approx(-1250)
    assert audit.new_value["movement_date"] == "2026-08-13"
    assert audit.new_value["reference"] == "NC-MAN-001"
    assert audit.new_value["observations"] == "Aprobada por gerencia"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"client": None, "amount": 1, "description": "Ajuste"}, "cliente"),
        ({"amount": 0, "description": "Ajuste"}, "mayor a cero"),
        ({"amount": 0.001, "description": "Ajuste"}, "mayor a cero"),
        ({"amount": -1, "description": "Ajuste"}, "mayor a cero"),
        ({"amount": float("nan"), "description": "Ajuste"}, "mayor a cero"),
        ({"amount": 1, "description": "   "}, "concepto"),
    ],
)
def test_register_manual_credit_validates_required_fields(db, kwargs, message):
    client = _client()
    values = {"client": client, **kwargs}

    with pytest.raises(ClientManualCreditError, match=message):
        ClientManualCreditService(current_user="caja").register_manual_credit(**values)

    assert ClientAccountMovement.select().count() == 0


def test_reverse_manual_credit_restores_balance_and_prevents_double_reversal(db):
    client = _client()
    service = ClientManualCreditService(current_user="caja")
    original = service.register_manual_credit(
        client=client,
        amount=1250,
        description="Descuento especial",
        reference="NC-55",
        observations="Acuerdo comercial",
    )

    reversal = service.reverse_manual_credit(
        original,
        reversal_date=date(2026, 8, 14),
    )

    assert reversal.movement_type == ClientAccountMovement.TYPE_MANUAL_CREDIT_REVERSAL
    assert reversal.total_amount == approx(1250)
    assert reversal.movement_date == date(2026, 8, 14)
    assert reversal.reference == "NC-55"
    assert reversal.observations == "Acuerdo comercial"
    assert reversal.is_reversal is True
    assert reversal.reverses == original
    assert client_balance(client) == approx(0)

    audit = AuditLog.get(AuditLog.action == "reversar_credito_manual")
    assert audit.record_ref == f"ClientAccountMovement:{original.id}"
    assert audit.new_value["reversal_movement_id"] == reversal.id

    with pytest.raises(ClientManualCreditError, match="ya fue reversado"):
        service.reverse_manual_credit(original)
    assert ClientAccountMovement.select().count() == 2


def test_reverse_manual_credit_rejects_other_movement_types(db):
    client = _client()
    movement = ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
        total_amount=-100,
        description="Pago",
        source_ref="Payment:test",
    )

    with pytest.raises(ClientManualCreditError, match="no es un crédito manual"):
        ClientManualCreditService(current_user="caja").reverse_manual_credit(movement)


def test_register_manual_credit_rolls_back_when_audit_fails(db):
    class FailingAudit:
        def record(self, **_kwargs):
            raise RuntimeError("audit unavailable")

    client = _client()
    service = ClientManualCreditService(
        current_user="caja", audit_service=FailingAudit()
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        service.register_manual_credit(
            client=client,
            amount=100,
            description="Ajuste",
        )

    assert ClientAccountMovement.select().count() == 0


def test_manual_credit_dialog_captures_all_fields(db):
    from PyQt5.QtWidgets import QApplication, QDialog

    from app.ui.client_manual_credit_dialog import ClientManualCreditDialog

    app = QApplication.instance() or QApplication([])
    client = _client()
    dialog = ClientManualCreditDialog(current_user="caja", preset_client=client)
    dialog.amount_input.setValue(800)
    dialog.description_input.setText("Devolución acordada")
    dialog.reference_input.setText("DEV-288")
    dialog.observations_input.setText("Sin movimiento de stock")
    dialog._on_accept()
    app.processEvents()

    assert dialog.result() == QDialog.Accepted
    movement = dialog.registered_credit()
    assert movement is not None
    assert movement.client == client
    assert movement.total_amount == approx(-800)
    assert movement.reference == "DEV-288"
    assert movement.observations == "Sin movimiento de stock"


def test_customer_ledger_registers_displays_and_reverses_manual_credit(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = _client()
    service = ClientManualCreditService(current_user="caja")

    def register(selected):
        service.register_manual_credit(
            client=selected,
            amount=800,
            description="Bonificación",
            reference="NC-288",
            observations="Cliente frecuente",
        )

    page = CustomerLedgerPage(
        current_user="caja",
        register_manual_credit_callback=register,
        reverse_manual_credit_callback=service.reverse_manual_credit,
    )
    register(client)
    page.refresh()
    app.processEvents()

    assert page.register_manual_credit_button.isEnabled()
    assert page.detail_balance.text() == "$-800.00"
    credit_row = next(
        row
        for row in range(page.movements_table.rowCount())
        if page.movements_table.item(row, 1).text() == "Crédito manual"
    )
    assert page.movements_table.item(credit_row, 2).text() == "NC-288"
    assert (
        page.movements_table.item(credit_row, 3).text()
        == "Bonificación — Cliente frecuente"
    )
    page.movements_table.setCurrentCell(credit_row, 0)
    app.processEvents()
    assert page.reverse_manual_credit_button.isEnabled()
    assert not page.reverse_manual_debit_button.isEnabled()

    page.reverse_manual_credit_button.click()
    app.processEvents()

    assert client_balance(client) == approx(0)
    labels = [
        page.movements_table.item(row, 1).text()
        for row in range(page.movements_table.rowCount())
    ]
    assert labels == ["Crédito manual", "Reverso crédito manual"]
    original_row = next(
        row
        for row in range(page.movements_table.rowCount())
        if page.movements_table.item(row, 1).text() == "Crédito manual"
    )
    page.movements_table.setCurrentCell(original_row, 0)
    app.processEvents()
    assert not page.reverse_manual_credit_button.isEnabled()


def test_customer_ledger_can_start_first_manual_credit_without_movements(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    Client.create(
        name="Cliente Sin Movimientos Crédito",
        cuit="30700001288",
        iva_condition="RI",
    )
    presets = []
    page = CustomerLedgerPage(
        current_user="caja",
        register_manual_credit_callback=presets.append,
    )
    app.processEvents()

    assert page.clients_table.rowCount() == 0
    assert page.register_manual_credit_button.isEnabled()
    page.register_manual_credit_button.click()
    assert presets == [None]


def test_desktop_wires_manual_credit_actions_into_customer_ledger(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.auth_service import AuthService
    from app.ui.customer_ledger import CustomerLedgerPage
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    user = AuthService().create_user("admin_credito_ui", "secreto", "Administrador")
    client = _client("Cliente Crédito Desktop")
    ClientManualCreditService(current_user=user.username).register_manual_credit(
        client=client,
        amount=100,
        description="Ajuste de integración",
    )
    window = FemagDesktopWindow(user=user, demo_mode=True)
    window._navigate_to_route("customer_ledger")
    page = window.stack.currentWidget()

    assert isinstance(page, CustomerLedgerPage)
    assert page.register_manual_credit_callback == window._open_manual_credit_dialog
    assert page.reverse_manual_credit_callback == window._reverse_manual_credit
    assert page.register_manual_credit_button.isEnabled()
    window.close()


def test_account_statement_includes_manual_credit_and_reversal(db, tmp_path):
    from app.services import account_statement_print_service

    client = _client("Cliente Crédito PDF")
    service = ClientManualCreditService(current_user="caja")
    credit = service.register_manual_credit(
        client=client,
        amount=800,
        description="Bonificación",
        reference="NC-PDF-288",
        observations="Cliente frecuente",
    )
    service.reverse_manual_credit(credit)

    pdf_path = account_statement_print_service.export_account_statement(client, tmp_path)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)

    assert "Crédito manual" in text
    assert "Reverso crédito" in text
    assert "NC-PDF-288" in text
    assert "Bonificación" in text
    assert "Cliente frecuente" in text
    assert "-800.00" in text
