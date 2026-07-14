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
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Client
    from app.ui.customer_payment_dialog import ClientPaymentDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente Dialog", cuit="30987654320", iva_condition="RI")

    dialog = ClientPaymentDialog(current_user="admin", preset_client=client)
    dialog.amount_input.setValue(250.0)
    dialog._on_accept()
    payment = dialog.registered_payment()
    assert payment is not None
    assert payment.amount == 250.0
    assert payment.client == client


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
