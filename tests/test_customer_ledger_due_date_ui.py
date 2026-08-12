import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_customer_ledger_shows_load_order_due_date(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente vencimiento UI",
        cuit="30700256257",
        iva_condition="RI",
        dias_plazo_pago=15,
    )
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        amount=1000,
        total_amount=1000,
        movement_date=date(2026, 8, 12),
        due_date=date(2026, 8, 27),
        description="Movimiento con vencimiento",
        source_ref="UI-DUE-256",
        created_by="issue256",
    )

    page = CustomerLedgerPage(current_user="issue256")
    app.processEvents()

    assert page.movements_table.columnCount() == 7
    assert page.movements_table.horizontalHeaderItem(1).text() == "Tipo"
    assert page.movements_table.horizontalHeaderItem(6).text() == "Vencimiento"
    assert page.movements_table.item(0, 6).text() == "27/08/2026"
