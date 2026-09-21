import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _manual_budget(db):
    from app.models.masters import Client, Product, TipoIVA
    from app.services.budget_service import BudgetService

    iva = TipoIVA.iva_default()
    product = Product.create(
        name="Fécula detalle #512",
        unit="bolsa",
        precio_neto_base=1000,
        tipo_iva=iva,
    )
    client = Client.create(
        name="Cliente detalle presupuesto",
        cuit="30777779512",
        iva_condition="RI",
    )
    budget = BudgetService("admin").create_manual(
        client=client,
        issue_date=date(2026, 9, 21),
        observations="Entrega coordinada",
        items=[
            {
                "product": product,
                "quantity": 2,
                "unit": "bolsa",
                "unit_price": 1000,
                "discount_percentage": 10,
                "vat_percentage": 21,
            }
        ],
    )
    return client, budget


def test_issue_512_budget_detail_resolves_and_renders(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.ui.ledger_document_detail_dialog import LedgerDocumentDetailDialog

    app = QApplication.instance() or QApplication([])
    _client, budget = _manual_budget(db)
    movement = ClientAccountMovement.get(ClientAccountMovement.budget == budget)

    kind, document = LedgerDocumentDetailDialog.resolve_document(movement)
    assert kind == "budget"
    assert document.id == budget.id
    assert LedgerDocumentDetailDialog.supports(movement)

    dialog = LedgerDocumentDetailDialog(movement)
    app.processEvents()

    assert budget.display_number in dialog.windowTitle()
    assert dialog.detail_table.rowCount() == 1
    assert dialog.detail_table.item(0, 0).text() == "Fécula detalle #512"
    assert dialog.detail_table.item(0, 1).text() == "2"
    assert dialog.budget_total_label.text() == f"$ {budget.total_amount:,.2f}"


def test_issue_512_payment_detail_resolves_and_renders_compound_payment(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.services.client_payment_service import ClientPaymentService
    from app.ui.ledger_document_detail_dialog import LedgerDocumentDetailDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente detalle recibo",
        cuit="30777779513",
        iva_condition="RI",
    )
    payment = ClientPaymentService("caja").register_compound_payment(
        client=client,
        payment_date=date(2026, 9, 21),
        details=[
            {"method": "efectivo", "amount": 400},
            {
                "method": "transferencia",
                "amount": 600,
                "reference": "TRX-512",
                "observations": "Banco",
            },
        ],
        observations="Pago combinado",
    )
    movement = ClientAccountMovement.get(ClientAccountMovement.payment == payment)

    kind, document = LedgerDocumentDetailDialog.resolve_document(movement)
    assert kind == "payment"
    assert document.id == payment.id

    dialog = LedgerDocumentDetailDialog(movement)
    app.processEvents()

    assert payment.receipt_number in dialog.windowTitle()
    assert dialog.detail_table.rowCount() == 2
    assert dialog.detail_table.item(1, 1).text() == "TRX-512"
    assert dialog.payment_total_label.text() == "$ 1,000.00"


def test_issue_512_customer_ledger_detail_button_and_double_click_use_same_action(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.ui import customer_ledger
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    _client, budget = _manual_budget(db)
    movement = ClientAccountMovement.get(ClientAccountMovement.budget == budget)

    opened = []

    def fake_exec(dialog):
        opened.append(dialog.movement.id)
        return 0

    monkeypatch.setattr(customer_ledger.LedgerDocumentDetailDialog, "exec_", fake_exec)

    page = CustomerLedgerPage(current_user="admin")
    app.processEvents()

    row = next(
        row
        for row in range(page.movements_table.rowCount())
        if page.movements_table.item(row, 0).data(Qt.UserRole + 1) == movement.id
    )
    page.movements_table.setCurrentCell(row, 0)
    app.processEvents()

    assert page.view_detail_button.isEnabled()
    assert page.document_detail_action.isEnabled()

    page.view_detail_button.click()
    page._on_open_document_detail(row, 0)

    assert opened == [movement.id, movement.id]


def test_issue_512_non_document_movement_disables_detail(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente sin documento detalle",
        cuit="30777779514",
        iva_condition="RI",
    )
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        total_amount=100,
        currency="ARS",
        description="Ajuste sin documento",
        source_ref="manual:512",
        created_by="admin",
    )

    page = CustomerLedgerPage(current_user="admin")
    app.processEvents()

    assert not page.view_detail_button.isEnabled()
    assert not page.document_detail_action.isEnabled()
