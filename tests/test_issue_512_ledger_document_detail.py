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
    assert dialog.order_reference_label.text() == "—"
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
    from PyQt5.QtCore import Qt
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


def test_issue_512_load_order_detail_resolves_from_movement_fk(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.ledger_document_detail_dialog import LedgerDocumentDetailDialog

    app = QApplication.instance() or QApplication([])
    product = Product.create(name="Producto OC #512", unit="kg")
    client = Client.create(
        name="Cliente OC detalle",
        cuit="30777779515",
        iva_condition="RI",
    )
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12 km 8",
    )
    carrier = Carrier.create(name="Transportista #512")
    driver = Driver.create(name="Chofer #512", carrier=carrier)
    truck = Truck.create(domain="DET512", carrier=carrier)
    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [{"product": product, "quantity": 15}],
            }
        ],
        pallets=[],
    )
    movement = ClientAccountMovement.create(
        client=client,
        load_order=order,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        total_amount=5000,
        currency="ARS",
        movement_date=date(2026, 9, 21),
        description="Despacho asociado",
        source_ref=f"LoadOrder:{order.id}",
        reference=f"OC-{order.order_number:06d}",
        created_by="admin",
    )

    kind, document = LedgerDocumentDetailDialog.resolve_document(movement)
    assert kind == "load_order_budget"
    assert document.id == order.id

    dialog = LedgerDocumentDetailDialog(movement)
    app.processEvents()

    assert f"OC-{order.order_number:06d}" in dialog.windowTitle()
    assert dialog.order_reference_label.text() == f"OC-{order.order_number:06d}"
    assert dialog.detail_table.rowCount() == 1
    assert dialog.detail_table.item(0, 0).text() == product.name
    assert dialog.detail_table.item(0, 1).text() == "15"
    assert dialog.budget_total_label.text() == "$ 5,000.00"


def test_issue_512_historical_payment_without_fk_has_read_only_detail(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.ui.ledger_document_detail_dialog import LedgerDocumentDetailDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente pago histórico",
        cuit="30777779516",
        iva_condition="RI",
    )
    movement = ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
        total_amount=-100955352.96,
        currency="ARS",
        movement_date=date(2026, 8, 31),
        description="Cobro parcial demo para Dashboard Gerencial",
        source_ref="legacy-payment:7",
        reference="DEMO-PAGO-7",
        created_by="demo",
    )

    kind, document = LedgerDocumentDetailDialog.resolve_document(movement)
    assert kind == "payment_movement"
    assert document.id == movement.id
    assert LedgerDocumentDetailDialog.supports(movement)

    dialog = LedgerDocumentDetailDialog(movement)
    app.processEvents()

    assert "DEMO-PAGO-7" in dialog.windowTitle()
    assert dialog.payment_total_label.text() == "$ 100,955,352.96"


def test_issue_462_legacy_load_order_detail_filters_rows_to_movement_client(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.ledger_document_detail_dialog import LedgerDocumentDetailDialog

    app = QApplication.instance() or QApplication([])
    iva = TipoIVA.iva_default()
    product_a = Product.create(
        name="Producto cliente A #462",
        unit="kg",
        precio_neto_base=1000,
        tipo_iva=iva,
    )
    product_b = Product.create(
        name="Producto cliente B #462",
        unit="kg",
        precio_neto_base=2000,
        tipo_iva=iva,
    )
    client_a = Client.create(name="Cliente A #462", cuit="30777779462", iva_condition="RI")
    client_b = Client.create(name="Cliente B #462", cuit="30777779463", iva_condition="RI")
    address_a = ClientAddress.create(
        client=client_a,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Destino A",
    )
    address_b = ClientAddress.create(
        client=client_b,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Destino B",
    )
    carrier = Carrier.create(name="Transportista #462")
    driver = Driver.create(name="Chofer #462", carrier=carrier)
    truck = Truck.create(domain="LEG462", carrier=carrier)
    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client_a,
                "delivery_address": address_a,
                "products": [{"product": product_a, "quantity": 3}],
            },
            {
                "client": client_b,
                "delivery_address": address_b,
                "products": [{"product": product_b, "quantity": 7}],
            },
        ],
        pallets=[],
    )
    movement = ClientAccountMovement.create(
        client=client_a,
        load_order=order,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        total_amount=3630,
        net_amount=3000,
        discount_amount=0,
        vat_amount=630,
        currency="ARS",
        movement_date=date(2026, 9, 17),
        description="Movimiento legacy OC multi-cliente",
        source_ref=f"LoadOrder:{order.id}",
        reference=f"OC-{order.order_number:06d}",
        created_by="admin",
    )

    dialog = LedgerDocumentDetailDialog(movement)
    app.processEvents()

    assert dialog.detail_table.rowCount() == 1
    assert dialog.detail_table.item(0, 0).text() == product_a.name
    assert product_b.name not in {
        dialog.detail_table.item(row, 0).text()
        for row in range(dialog.detail_table.rowCount())
    }


def test_issue_462_legacy_movement_prefers_persisted_budget_for_same_client(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
    from app.services.budget_service import BudgetService
    from app.services.load_order_service import LoadOrderService
    from app.ui.ledger_document_detail_dialog import LedgerDocumentDetailDialog

    iva = TipoIVA.iva_default()
    product = Product.create(
        name="Producto presupuesto persistido #462",
        unit="kg",
        precio_neto_base=1500,
        tipo_iva=iva,
    )
    client = Client.create(name="Cliente presupuesto #462", cuit="30777779464", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Eldorado",
        address="Destino presupuesto",
    )
    carrier = Carrier.create(name="Transportista presupuesto #462")
    driver = Driver.create(name="Chofer presupuesto #462", carrier=carrier)
    truck = Truck.create(domain="PRE462", carrier=carrier)
    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [{"product": product, "quantity": 4}],
            }
        ],
        pallets=[],
    )
    budget = BudgetService("admin").ensure_for_load_order_client(order, client)
    movement = ClientAccountMovement.create(
        client=client,
        load_order=order,
        budget=None,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        total_amount=budget.total_amount,
        net_amount=budget.net_amount,
        discount_amount=budget.discount_amount,
        vat_amount=budget.vat_amount,
        currency="ARS",
        movement_date=date(2026, 9, 17),
        description="Movimiento legacy sin budget_id",
        source_ref=f"LoadOrder:{order.id}",
        reference=f"OC-{order.order_number:06d}",
        created_by="admin",
    )

    kind, document = LedgerDocumentDetailDialog.resolve_document(movement)

    assert kind == "budget"
    assert document.id == budget.id
    assert document.client_id == client.id
    assert document.load_order_id == order.id
