from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _manual_budget(client, product, *, amount: int = 1500):
    from app.services.budget_service import BudgetService

    return BudgetService(current_user="admin").create_manual(
        client=client,
        items=[
            {
                "product": product,
                "quantity": 2,
                "unit": "bolsa",
                "unit_price": amount,
                "vat_percentage": 21,
            }
        ],
    )


def _select_movement(page, movement):
    from PyQt5.QtCore import Qt

    row = next(
        index
        for index in range(page.movements_table.rowCount())
        if page.movements_table.item(index, 0).data(Qt.UserRole + 1) == movement.id
    )
    page.movements_table.setCurrentCell(row, 0)
    return row


def test_customer_ledger_can_reprint_selected_budget(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client, Product
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Reimpresion Presupuesto",
        cuit="30777774540",
        iva_condition="RI",
    )
    product = Product.create(name="Fecula reimpresion", unit="bolsa")
    budget = _manual_budget(client, product)
    movement = ClientAccountMovement.get(ClientAccountMovement.budget == budget)
    selected = []

    page = CustomerLedgerPage(
        current_user="admin",
        print_budget_callback=selected.append,
    )
    app.processEvents()
    _select_movement(page, movement)
    app.processEvents()

    assert page.print_budget_action.isEnabled()
    page.print_budget_action.trigger()

    assert selected == [movement]
    page.close()


def test_customer_ledger_disables_reprint_without_budget(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Movimiento Sin Presupuesto Reimpresion",
        cuit="30777774541",
        iva_condition="RI",
    )
    movement = ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        total_amount=100,
        currency="ARS",
        description="Ajuste",
        source_ref="issue452:no-budget",
        created_by="admin",
    )

    page = CustomerLedgerPage(
        current_user="admin",
        print_budget_callback=lambda _movement: None,
    )
    app.processEvents()
    _select_movement(page, movement)
    app.processEvents()

    assert not page.print_budget_action.isEnabled()
    page.close()


def test_customer_ledger_disables_reprint_without_callback(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client, Product
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Reimpresion Sin Callback",
        cuit="30777774542",
        iva_condition="RI",
    )
    product = Product.create(name="Fecula sin callback", unit="bolsa")
    budget = _manual_budget(client, product)
    movement = ClientAccountMovement.get(ClientAccountMovement.budget == budget)

    page = CustomerLedgerPage(current_user="admin")
    app.processEvents()
    _select_movement(page, movement)
    app.processEvents()

    assert not page.print_budget_action.isEnabled()
    page.close()


def test_customer_ledger_disables_reprint_on_budget_reversal(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client, Product
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Anulacion Presupuesto Reimpresion",
        cuit="30777774543",
        iva_condition="RI",
    )
    product = Product.create(name="Fecula anulacion", unit="bolsa")
    budget = _manual_budget(client, product)
    movement = ClientAccountMovement.create(
        client=client,
        budget=budget,
        movement_type=ClientAccountMovement.TYPE_BUDGET_MANUAL_REVERSAL,
        total_amount=100,
        currency="ARS",
        description="Anulacion presupuesto",
        source_ref=f"Budget:{budget.id}",
        is_reversal=True,
        created_by="admin",
    )

    page = CustomerLedgerPage(
        current_user="admin",
        print_budget_callback=lambda _movement: None,
    )
    app.processEvents()
    _select_movement(page, movement)
    app.processEvents()

    assert not page.print_budget_action.isEnabled()
    page.close()


def test_customer_ledger_can_reprint_load_order_budget_without_persisted_budget(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Carrier, Client, Driver, Truck
    from app.models.load_orders import LoadOrder
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Legacy Presupuesto Reimpresion",
        cuit="30777774544",
        iva_condition="RI",
    )
    carrier = Carrier.create(name="Transportista legacy 452")
    driver = Driver.create(name="Chofer legacy 452", carrier=carrier)
    truck = Truck.create(domain="LEG452", carrier=carrier)
    order = LoadOrder.create(
        order_number=45299,
        client=client,
        carrier=carrier,
        driver=driver,
        truck=truck,
        status=LoadOrder.STATUS_ISSUED,
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
        reference="OC legacy 452",
        created_by="admin",
    )

    selected = []
    page = CustomerLedgerPage(
        current_user="admin",
        print_budget_callback=selected.append,
    )
    app.processEvents()
    _select_movement(page, movement)
    app.processEvents()

    assert page.print_budget_action.isEnabled()
    page.print_budget_action.trigger()
    assert selected == [movement]
    page.close()


def test_reprinting_budget_keeps_number_and_does_not_change_balance(db, tmp_path):
    from app.models.accounting import ClientAccountMovement
    from app.models.budgets import Budget
    from app.models.masters import Client, Product
    from app.services.budget_print_service import BudgetPrintService

    client = Client.create(
        name="Cliente Reimpresion Sin Duplicar Deuda",
        cuit="30777774545",
        iva_condition="RI",
    )
    product = Product.create(name="Fecula reprint", unit="bolsa")
    budget = _manual_budget(client, product)
    service = BudgetPrintService(current_user="admin")

    def _debt() -> float:
        return sum(
            movement.total_amount
            for movement in ClientAccountMovement.select().where(
                ClientAccountMovement.client == client
            )
        )

    debt_before = _debt()
    movements_before = ClientAccountMovement.select().count()

    first = service.export_pdf(budget, tmp_path)
    second = service.export_pdf(budget, tmp_path)

    # Mismo documento y mismo numero interno: la reimpresion no crea nada nuevo.
    assert first.name == second.name == f"presupuesto_{budget.budget_number:06d}.pdf"
    assert first.exists() and first.stat().st_size > 0
    assert Budget.get_by_id(budget.id).budget_number == budget.budget_number
    assert Budget.select().count() == 1
    # La deuda del cliente no se duplica ni se altera al reimprimir.
    assert _debt() == debt_before
    assert ClientAccountMovement.select().count() == movements_before
