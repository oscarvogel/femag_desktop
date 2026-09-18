from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_customer_ledger_can_send_selected_budget_by_whatsapp(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client, Product
    from app.services.budget_service import BudgetService
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Presupuesto WhatsApp",
        cuit="30777774530",
        iva_condition="RI",
        phone="+54 9 376 4555000",
    )
    product = Product.create(name="Fecula WA presupuesto", unit="bolsa")
    budget = BudgetService(current_user="admin").create_manual(
        client=client,
        items=[
            {
                "product": product,
                "quantity": 2,
                "unit": "bolsa",
                "unit_price": 1500,
                "vat_percentage": 21,
            }
        ],
    )
    movement = ClientAccountMovement.get(ClientAccountMovement.budget == budget)
    selected = []

    page = CustomerLedgerPage(
        current_user="admin",
        whatsapp_budget_callback=selected.append,
    )
    app.processEvents()

    row = next(
        index
        for index in range(page.movements_table.rowCount())
        if page.movements_table.item(index, 0).data(Qt.UserRole + 1) == movement.id
    )
    page.movements_table.setCurrentCell(row, 0)
    app.processEvents()

    assert page.whatsapp_budget_action.isEnabled()
    page.whatsapp_budget_action.trigger()

    assert selected == [movement]
    page.close()


def test_customer_ledger_disables_budget_whatsapp_without_budget(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Movimiento Sin Presupuesto",
        cuit="30777774531",
        iva_condition="RI",
    )
    movement = ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        total_amount=100,
        currency="ARS",
        description="Ajuste",
        source_ref="issue453:no-budget",
        created_by="admin",
    )

    page = CustomerLedgerPage(
        current_user="admin",
        whatsapp_budget_callback=lambda _budget: None,
    )
    app.processEvents()

    row = next(
        index
        for index in range(page.movements_table.rowCount())
        if page.movements_table.item(index, 0).data(Qt.UserRole + 1) == movement.id
    )
    page.movements_table.setCurrentCell(row, 0)
    app.processEvents()

    assert not page.whatsapp_budget_action.isEnabled()
    page.close()


def test_whatsapp_dialog_supports_budget_title_and_message(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.whatsapp_send import WhatsAppSendDialog

    app = QApplication.instance() or QApplication([])
    message = (
        "Hola Cliente. Le enviamos adjunto el presupuesto PRES-000123 de FEMAG "
        "con el detalle correspondiente. Ante cualquier consulta, quedamos a disposición."
    )
    dialog = WhatsAppSendDialog(
        client_name="Cliente",
        phone="+54 9 376 4555000",
        default_message=message,
        window_title="Enviar presupuesto por WhatsApp",
    )
    app.processEvents()

    assert dialog.windowTitle() == "Enviar presupuesto por WhatsApp"
    assert dialog.phone() == "+54 9 376 4555000"
    assert dialog.caption() == message
    dialog.close()


def test_customer_ledger_enables_budget_whatsapp_for_legacy_load_order_movement_without_budget(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.models.load_orders import LoadOrder
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Legacy Presupuesto",
        cuit="30777774532",
        iva_condition="RI",
    )
    order = LoadOrder.create(
        order_number=45399,
        client=client,
        status="emitida",
    )
    movement = ClientAccountMovement.create(
        client=client,
        load_order=order,
        budget=None,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        total_amount=100,
        currency="ARS",
        description="Movimiento legacy con OC",
        source_ref=f"LoadOrder:{order.id}",
        reference="OC legacy",
        created_by="admin",
    )

    selected = []
    page = CustomerLedgerPage(
        current_user="admin",
        whatsapp_budget_callback=selected.append,
    )
    app.processEvents()

    row = next(
        index
        for index in range(page.movements_table.rowCount())
        if page.movements_table.item(index, 0).data(Qt.UserRole + 1) == movement.id
    )
    page.movements_table.setCurrentCell(row, 0)
    app.processEvents()

    assert page.whatsapp_budget_action.isEnabled()
    page.whatsapp_budget_action.trigger()
    assert selected == [movement]
    page.close()
