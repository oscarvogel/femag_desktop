import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_manual_budget_dialog_creates_budget_and_debt_without_load_order(db):
    from pytest import approx
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.budgets import Budget, BudgetItem
    from app.models.load_orders import LoadOrder
    from app.models.masters import Client, Product, TipoIVA
    from app.services.ledger_query_service import client_balance
    from app.ui.manual_budget_dialog import ManualBudgetDialog

    app = QApplication.instance() or QApplication([])
    iva = TipoIVA.iva_default()
    product = Product.create(
        name="Fécula presupuesto manual UI",
        unit="bolsa",
        precio_neto_base=1000,
        precio_lista_2=1500,
        tipo_iva=iva,
    )
    client = Client.create(
        name="Cliente presupuesto manual UI",
        cuit="30745100001",
        iva_condition="RI",
        lista_precios=2,
        descuento_porcentaje=10,
    )

    dialog = ManualBudgetDialog(client=client, current_user="admin")
    app.processEvents()

    assert dialog.product_combo.currentData() == product.id
    assert dialog.unit_price_input.value() == 1500
    assert dialog.discount_input.value() == 10
    assert dialog.vat_input.value() == iva.porcentaje

    dialog.quantity_input.setValue(2)
    dialog._add_item()
    dialog._confirm()
    app.processEvents()

    budget = dialog.budget()
    assert budget is not None
    assert budget.origin == Budget.ORIGIN_MANUAL
    assert budget.load_order_id is None
    assert LoadOrder.select().count() == 0
    assert BudgetItem.select().where(BudgetItem.budget == budget).count() == 1

    expected = (2 * 1500 * 0.90) * 1.21
    assert budget.total_amount == approx(expected)
    assert client_balance(client) == approx(expected)

    movement = ClientAccountMovement.get(ClientAccountMovement.budget == budget)
    assert movement.movement_type == ClientAccountMovement.TYPE_BUDGET_MANUAL
    assert movement.reference == budget.display_number
    assert movement.source_ref == f"Budget:{budget.id}"


def test_customer_ledger_manual_budget_button_dispatches_selected_client(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente botón presupuesto manual",
        cuit="30745100002",
        iva_condition="RI",
    )
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_OPENING_BALANCE,
        total_amount=100,
        currency="ARS",
        description="Saldo inicial",
        source_ref="opening:test-451",
        created_by="admin",
    )
    selected = []
    page = CustomerLedgerPage(
        current_user="admin",
        create_manual_budget_callback=selected.append,
    )
    app.processEvents()

    assert page.create_manual_budget_button.isEnabled()
    page.create_manual_budget_button.click()
    app.processEvents()

    assert selected == [client]


def test_customer_ledger_labels_manual_budget_movements(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente etiqueta presupuesto manual",
        cuit="30745100003",
        iva_condition="RI",
    )
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_BUDGET_MANUAL,
        total_amount=1210,
        currency="ARS",
        description="Presupuesto PRES-000001 - mercadería",
        source_ref="Budget:1",
        reference="PRES-000001",
        created_by="admin",
    )

    page = CustomerLedgerPage(current_user="admin")
    app.processEvents()

    labels = [
        page.movements_table.item(row, 1).text()
        for row in range(page.movements_table.rowCount())
    ]
    assert "Presupuesto manual" in labels


def test_customer_ledger_manual_budget_allows_zero_balance_client(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Client
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente sin saldo para presupuesto",
        cuit="30745100004",
        iva_condition="RI",
    )
    selected = []
    page = CustomerLedgerPage(
        current_user="admin",
        create_manual_budget_callback=selected.append,
    )
    app.processEvents()

    assert page.clients_table.rowCount() == 1
    assert "Cliente sin saldo para presupuesto" in page.clients_table.item(0, 0).text()
    assert page.clients_table.item(0, 1).text() == "$0.00"
    assert page.create_manual_budget_button.isEnabled()

    page.create_manual_budget_button.click()
    app.processEvents()

    assert selected == [client]
