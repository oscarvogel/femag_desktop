import os
from conftest import _complete_order_for_issue

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_customer_ledger_page_renders_with_movement(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
    from app.services.client_payment_service import ClientPaymentService
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    iva = TipoIVA.iva_default()
    product = Product.create(name="Test", unit="kg", precio_neto_base=1000.0, tipo_iva=iva)
    client = Client.create(name="Cliente UI", cuit="30123456780", iva_condition="RI")
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones", city="Posadas", address="Ruta 12"
    )
    carrier = Carrier.create(name="Carrier")
    driver = Driver.create(name="Driver", carrier=carrier)
    truck = Truck.create(domain="UI01", carrier=carrier)

    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[{"client": client, "delivery_address": address, "products": [{"product": product, "quantity": 10}]}],
        pallets=[],
    )
    _complete_order_for_issue(order)
    LoadOrderOperationService(current_user="admin").issue(order)
    ClientPaymentService(current_user="admin").register_payment(client=client, amount=5000)

    page = CustomerLedgerPage(current_user="admin", register_payment_callback=lambda *a, **k: None)
    assert page.clients_table.rowCount() >= 1
    assert page.detail_balance.text().startswith("$")
    assert page.detail_movements.text() != "0"
    assert page.movements_table.rowCount() >= 2


def test_payment_dialog_opens_and_registers(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Client
    from app.ui.customer_payment_dialog import ClientPaymentDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente Dialog", cuit="30987654320", iva_condition="RI")

    dialog = ClientPaymentDialog(current_user="admin", preset_client=client)
    assert dialog.client_combo.isEditable()
    assert dialog.client_combo.completer().filterMode() == Qt.MatchContains
    assert dialog.method_combo.isEditable()
    dialog.amount_input.setValue(250.0)
    dialog._on_accept()
    payment = dialog.registered_payment()
    assert payment is not None
    assert payment.amount == 250.0
    assert payment.client == client


def test_manual_debit_dialog_opens_and_registers_required_fields(db):
    from PyQt5.QtCore import QDate
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Client
    from app.ui.client_manual_debit_dialog import ClientManualDebitDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Débito Dialog",
        cuit="30987654217",
        iva_condition="RI",
    )
    dialog = ClientManualDebitDialog(current_user="caja", preset_client=client)
    dialog.date_input.setDate(QDate(2026, 8, 7))
    dialog.amount_input.setValue(5000)
    dialog.description_input.setText("Interés por mora")
    dialog.reference_input.setText("ND-217")
    dialog._on_accept()

    movement = dialog.registered_debit()
    assert movement is not None
    assert movement.client == client
    assert movement.total_amount == 5000
    assert movement.movement_date.isoformat() == "2026-08-07"
    assert movement.description == "Interés por mora"
    assert movement.reference == "ND-217"


def test_customer_ledger_share_buttons_dispatch_selected_client(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Contacto",
        cuit="30777777770",
        iva_condition="RI",
        phone="0376 15 4123456",
        email="cliente@example.com",
    )
    ClientAccountMovement.create(
        client=client,
        movement_type="load_order_documental",
        total_amount=100,
        currency="ARS",
        description="Movimiento",
        source_ref="test:1",
        created_by="admin",
    )
    whatsapp_clients = []
    email_clients = []
    page = CustomerLedgerPage(
        current_user="admin",
        whatsapp_statement_callback=whatsapp_clients.append,
        email_statement_callback=email_clients.append,
    )
    app.processEvents()

    assert page.whatsapp_statement_button.isEnabled()
    assert page.email_statement_button.isEnabled()
    page.whatsapp_statement_button.click()
    page.email_statement_button.click()

    assert whatsapp_clients == [client]
    assert email_clients == [client]


def test_customer_ledger_share_buttons_require_callbacks(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente", cuit="30777777771", iva_condition="RI")
    ClientAccountMovement.create(
        client=client,
        movement_type="load_order_documental",
        total_amount=100,
        currency="ARS",
        description="Movimiento",
        source_ref="test:2",
        created_by="admin",
    )

    page = CustomerLedgerPage(current_user="admin")
    app.processEvents()

    assert not page.whatsapp_statement_button.isEnabled()
    assert not page.email_statement_button.isEnabled()


def test_customer_ledger_prints_and_annuls_selected_payment(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Client
    from app.models.payments import ClientPayment
    from app.services.auth_service import AuthService
    from app.services.client_payment_service import ClientPaymentService
    from app.services.ledger_query_service import client_balance
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Acciones Pago",
        cuit="30777777772",
        iva_condition="RI",
    )
    payment_service = ClientPaymentService(current_user="caja")
    payment = payment_service.register_payment(client=client, amount=850)
    admin = AuthService().create_user(
        "admin_acciones_pago",
        "secreto",
        "Administrador",
    )
    printed = []

    def annul(selected):
        payment_service.annul_payment(
            selected,
            authorized_by=admin,
            reason="Duplicado",
        )

    page = CustomerLedgerPage(
        current_user="caja",
        print_receipt_callback=printed.append,
        annul_payment_callback=annul,
        can_annul_payments=True,
    )
    app.processEvents()

    payment_row = next(
        row
        for row in range(page.movements_table.rowCount())
        if page.movements_table.item(row, 0).data(Qt.UserRole) == payment.id
    )
    page.movements_table.setCurrentCell(payment_row, 0)
    app.processEvents()

    assert page.print_receipt_button.isEnabled()
    assert page.annul_payment_button.isHidden() is False
    assert page.annul_payment_button.isEnabled()
    page.print_receipt_button.click()
    assert printed == [payment]

    page.annul_payment_button.click()
    app.processEvents()

    payment = ClientPayment.get_by_id(payment.id)
    assert payment.status == ClientPayment.STATUS_ANNULLED
    assert client_balance(client) == 0
    type_labels = [
        page.movements_table.item(row, 1).text()
        for row in range(page.movements_table.rowCount())
    ]
    assert "Pago anulado" in type_labels
    assert "Anulación de pago" in type_labels


def test_customer_ledger_hides_annul_action_without_permission(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Client
    from app.services.client_payment_service import ClientPaymentService
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Sin Anulación",
        cuit="30777777773",
        iva_condition="RI",
    )
    payment = ClientPaymentService(current_user="caja").register_payment(
        client=client,
        amount=100,
    )
    page = CustomerLedgerPage(
        current_user="caja",
        print_receipt_callback=lambda _payment: None,
        annul_payment_callback=lambda _payment: None,
        can_annul_payments=False,
    )
    payment_row = next(
        row
        for row in range(page.movements_table.rowCount())
        if page.movements_table.item(row, 0).data(Qt.UserRole) == payment.id
    )
    page.movements_table.setCurrentCell(payment_row, 0)
    app.processEvents()

    assert page.print_receipt_button.isEnabled()
    assert page.annul_payment_button.isHidden()


def test_customer_ledger_registers_and_reverses_manual_debit(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.services.client_manual_debit_service import ClientManualDebitService
    from app.services.ledger_query_service import client_balance
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Acciones Débito",
        cuit="30777777217",
        iva_condition="RI",
    )
    service = ClientManualDebitService(current_user="caja")

    def register(selected):
        service.register_manual_debit(
            client=selected,
            amount=5000,
            description="Ajuste operativo",
            reference="AJ-5000",
        )

    page = CustomerLedgerPage(
        current_user="caja",
        register_manual_debit_callback=register,
        reverse_manual_debit_callback=service.reverse_manual_debit,
    )
    # La página sólo lista clientes con movimientos; crear el primero y refrescar.
    register(client)
    page.refresh()
    app.processEvents()

    assert page.register_manual_debit_button.isEnabled()
    assert page.detail_balance.text() == "$5,000.00"
    debit_row = next(
        row
        for row in range(page.movements_table.rowCount())
        if page.movements_table.item(row, 1).text() == "Débito manual"
    )
    assert page.movements_table.item(debit_row, 2).text() == "AJ-5000"
    page.movements_table.setCurrentCell(debit_row, 0)
    app.processEvents()
    assert page.reverse_manual_debit_button.isEnabled()

    page.reverse_manual_debit_button.click()
    app.processEvents()

    assert client_balance(client) == 0
    assert ClientAccountMovement.select().count() == 2
    labels = [
        page.movements_table.item(row, 1).text()
        for row in range(page.movements_table.rowCount())
    ]
    assert labels == ["Débito manual", "Reverso débito manual"]
    original_row = next(
        row
        for row in range(page.movements_table.rowCount())
        if page.movements_table.item(row, 1).text() == "Débito manual"
    )
    page.movements_table.setCurrentCell(original_row, 0)
    app.processEvents()
    assert not page.reverse_manual_debit_button.isEnabled()


def test_customer_ledger_can_start_first_manual_debit_without_existing_movements(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Client
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    Client.create(
        name="Cliente Sin Movimientos",
        cuit="30777779217",
        iva_condition="RI",
    )
    presets = []
    page = CustomerLedgerPage(
        current_user="caja",
        register_manual_debit_callback=presets.append,
    )
    app.processEvents()

    assert page.clients_table.rowCount() == 0
    assert page.register_manual_debit_button.isEnabled()
    page.register_manual_debit_button.click()
    assert presets == [None]


def test_desktop_wires_manual_debit_actions_into_customer_ledger(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Client
    from app.services.auth_service import AuthService
    from app.services.client_manual_debit_service import ClientManualDebitService
    from app.ui.customer_ledger import CustomerLedgerPage
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    user = AuthService().create_user("admin_debito_ui", "secreto", "Administrador")
    client = Client.create(
        name="Cliente Débito Desktop",
        cuit="30777778217",
        iva_condition="RI",
    )
    ClientManualDebitService(current_user=user.username).register_manual_debit(
        client=client,
        amount=100,
        description="Ajuste de integración",
    )
    window = FemagDesktopWindow(user=user, demo_mode=True)
    window._navigate_to_route("customer_ledger")
    page = window.stack.currentWidget()

    assert isinstance(page, CustomerLedgerPage)
    assert page.register_manual_debit_callback == window._open_manual_debit_dialog
    assert page.reverse_manual_debit_callback == window._reverse_manual_debit
    assert page.register_manual_debit_button.isEnabled()
    window.close()


def test_admin_authorization_dialog_accepts_valid_admin(db):
    from PyQt5.QtWidgets import QApplication, QDialog

    from app.services.auth_service import AuthService
    from app.ui.admin_authorization_dialog import AdminAuthorizationDialog

    app = QApplication.instance() or QApplication([])
    admin = AuthService().create_user(
        "admin_dialog_pago",
        "secreto",
        "Administrador",
    )
    dialog = AdminAuthorizationDialog()
    dialog.username_input.setText(admin.username)
    dialog.password_input.setText("secreto")
    dialog.reason_input.setText("Corrección de caja")
    dialog._on_accept()
    app.processEvents()

    assert dialog.result() == QDialog.Accepted
    assert dialog.authorized_user() == admin
    assert dialog.reason() == "Corrección de caja"
