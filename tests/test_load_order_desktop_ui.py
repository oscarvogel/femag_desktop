import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _set_combo(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_load_order_desktop_ui_creates_order_from_modal_flow(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QComboBox, QDialog, QPushButton, QTableWidget

    from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog, LoadOrderProductDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Transporte UI")
    driver = Driver.create(name="Chofer UI", carrier=carrier)
    truck = Truck.create(domain="UI123AA", carrier=carrier)
    client = Client.create(name="Cliente UI", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta UI",
    )
    product = Product.create(name="Producto UI", unit="kg")

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue65"), "ui_issue65")
    app.processEvents()

    _set_combo(dialog.findChild(QComboBox, "loadOrderCarrierInput"), carrier.id)
    _set_combo(dialog.findChild(QComboBox, "loadOrderTruckInput"), truck.id)
    _set_combo(dialog.findChild(QComboBox, "loadOrderDriverInput"), driver.id)
    _set_combo(dialog.findChild(QComboBox, "loadOrderClientInput"), client.id)
    _set_combo(dialog.findChild(QComboBox, "loadOrderAddressInput"), address.id)

    dialog.findChild(QPushButton, "addLoadOrderClientButton").click()
    dialog.findChild(QTableWidget, "loadOrderDestinationDraftTable").setCurrentCell(0, 0)

    def accept_product(product_dialog):
        product_dialog.product = {
            "product_id": product.id,
            "product_label": product.name,
            "quantity": 125,
            "unit": product.unit,
        }
        return QDialog.Accepted

    monkeypatch.setattr(LoadOrderProductDialog, "exec_", accept_product)
    dialog.findChild(QPushButton, "addLoadOrderProductButton").click()
    dialog.findChild(QPushButton, "saveLoadOrderButton").click()

    assert dialog.created_order is not None
    assert LoadOrder.select().count() == 1
    assert LoadOrderDestination.select().count() == 1
    assert LoadOrderProduct.select().count() == 1


def test_load_order_dialog_filters_delivery_addresses_by_selected_client(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Client, ClientAddress
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    client_a = Client.create(name="Cliente A UI", cuit="30700000001", iva_condition="RI")
    client_b = Client.create(name="Cliente B UI", cuit="30700000002", iva_condition="RI")
    address_a = ClientAddress.create(
        client=client_a,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta A",
    )
    address_b = ClientAddress.create(
        client=client_b,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Ruta B",
    )

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue65"), "ui_issue65")
    app.processEvents()

    client_combo = dialog.findChild(QComboBox, "loadOrderClientInput")
    address_combo = dialog.findChild(QComboBox, "loadOrderAddressInput")
    _set_combo(client_combo, client_a.id)

    assert address_combo.findData(address_a.id) >= 0
    assert address_combo.findData(address_b.id) == -1

    _set_combo(client_combo, client_b.id)

    assert address_combo.findData(address_a.id) == -1
    assert address_combo.findData(address_b.id) >= 0


def test_load_order_dialog_selects_carrier_and_trucks_from_selected_driver(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Carrier, Driver, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier_a = Carrier.create(name="Transporte A UI")
    carrier_b = Carrier.create(name="Transporte B UI")
    driver_a = Driver.create(name="Chofer A UI", carrier=carrier_a)
    driver_b = Driver.create(name="Chofer B UI", carrier=carrier_b)
    truck_a = Truck.create(domain="TRK-A", carrier=carrier_a)
    truck_b = Truck.create(domain="TRK-B", carrier=carrier_b)

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue65"), "ui_issue65")
    app.processEvents()

    carrier_combo = dialog.findChild(QComboBox, "loadOrderCarrierInput")
    driver_combo = dialog.findChild(QComboBox, "loadOrderDriverInput")
    truck_combo = dialog.findChild(QComboBox, "loadOrderTruckInput")
    assert carrier_combo.isEnabled() is False

    _set_combo(driver_combo, driver_b.id)

    assert carrier_combo.currentData() == carrier_b.id
    assert truck_combo.findData(truck_a.id) == -1
    assert truck_combo.findData(truck_b.id) >= 0

    _set_combo(driver_combo, driver_a.id)

    assert carrier_combo.currentData() == carrier_a.id
    assert truck_combo.findData(truck_a.id) >= 0
    assert truck_combo.findData(truck_b.id) == -1


def test_load_order_page_operates_emit_reprint_and_annul_feedback(db, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QTableWidget

    from app.models.load_orders import LoadOrder
    from app.models.security import User, UserProfile
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_ui", password_hash="x", profile=profile)
    carrier = Carrier.create(name="Transporte UI")
    driver = Driver.create(name="Chofer UI", carrier=carrier)
    truck = Truck.create(domain="UI123AA", carrier=carrier)
    client = Client.create(name="Cliente UI", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta UI",
    )
    product = Product.create(name="Producto UI", unit="kg")
    order = LoadOrderService(current_user=user.username).create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[{"client": client, "delivery_address": address, "products": [{"product": product, "quantity": 1}]}],
        pallets=[],
    )
    monkeypatch.setattr("app.ui.desktop_app.LOAD_ORDER_PRINTS_DIR", tmp_path)

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    table = window.findChild(QTableWidget, "loadOrdersTable")
    feedback = window.findChild(QLabel, "loadOrderFeedback")
    status = window.findChild(QLabel, "detailOrderStatus")
    table.setCurrentCell(0, 0)

    window.findChild(QPushButton, "issueLoadOrderButton").click()
    app.processEvents()
    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_ISSUED
    assert "emitida" in feedback.text().lower()
    assert status.text() == "Emitida"

    window.findChild(QPushButton, "printLoadOrderButton").click()
    app.processEvents()
    assert "vista a4" in feedback.text().lower()
    assert list(tmp_path.glob("orden_y_resumen_*.html"))

    window.findChild(QPushButton, "printLoadOrderButton").click()
    app.processEvents()
    assert "reimpresion" in feedback.text().lower()
    assert "Reimpresion" in next(tmp_path.glob("orden_y_resumen_*.html")).read_text(encoding="utf-8")

    window.findChild(QPushButton, "annulLoadOrderButton").click()
    app.processEvents()
    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_ANNULLED
    assert status.text() == "Anulada"


def test_load_order_page_has_single_print_action_and_real_search_filter(db, tmp_path, monkeypatch):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QTableWidget

    from app.models.security import User, UserProfile
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_search_ui", password_hash="x", profile=profile)
    carrier = Carrier.create(name="Transporte Buscar UI")
    driver_a = Driver.create(name="Chofer Buscar UI A", carrier=carrier)
    truck_a = Truck.create(domain="BUS123", carrier=carrier)
    driver_b = Driver.create(name="Chofer Buscar UI B", carrier=carrier)
    truck_b = Truck.create(domain="BUS456", carrier=carrier)
    product = Product.create(name="Producto Buscar UI", unit="kg")
    client_a = Client.create(name="Cliente Norte Buscar", cuit="30712345001", iva_condition="RI")
    address_a = ClientAddress.create(
        client=client_a,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Norte",
    )
    client_b = Client.create(name="Cliente Sur Buscar", cuit="30712345002", iva_condition="RI")
    address_b = ClientAddress.create(
        client=client_b,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Ruta Sur",
    )
    service = LoadOrderService(current_user=user.username)
    order_a = service.create_order(
        carrier=carrier,
        driver=driver_a,
        truck=truck_a,
        destinations=[{"client": client_a, "delivery_address": address_a, "products": [{"product": product, "quantity": 1}]}],
        pallets=[],
    )
    service.create_order(
        carrier=carrier,
        driver=driver_b,
        truck=truck_b,
        destinations=[{"client": client_b, "delivery_address": address_b, "products": [{"product": product, "quantity": 2}]}],
        pallets=[],
    )
    monkeypatch.setattr("app.ui.desktop_app.LOAD_ORDER_PRINTS_DIR", tmp_path)

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    search_input = window.findChild(QLineEdit, "loadOrderSearchInput")
    search_button = window.findChild(QPushButton, "searchLoadOrderButton")
    reprint_button = window.findChild(QPushButton, "reprintLoadOrderButton")
    table = window.findChild(QTableWidget, "loadOrdersTable")
    feedback = window.findChild(QLabel, "loadOrderFeedback")

    assert search_input is not None
    assert reprint_button is None or not reprint_button.isVisible()
    assert window.findChild(QPushButton, "printLoadOrderButton").text() == "Imprimir / Reimprimir"
    assert table.rowCount() == 2

    search_input.setText("Norte")
    search_button.click()
    app.processEvents()

    assert table.rowCount() == 1
    assert table.item(0, 0).data(Qt.UserRole) == order_a.id
    assert "1 resultado" in feedback.text().lower()


def test_load_order_page_blocks_annul_without_permission(db):
    from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QTableWidget

    from app.models.load_orders import LoadOrder
    from app.models.security import User, UserProfile
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Secretaria")
    user = User.create(username="secretaria_ui", password_hash="x", profile=profile)
    carrier = Carrier.create(name="Transporte UI")
    driver = Driver.create(name="Chofer UI", carrier=carrier)
    truck = Truck.create(domain="UI123AA", carrier=carrier)
    client = Client.create(name="Cliente UI", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta UI",
    )
    product = Product.create(name="Producto UI", unit="kg")
    order = LoadOrderService(current_user=user.username).create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[{"client": client, "delivery_address": address, "products": [{"product": product, "quantity": 1}]}],
        pallets=[],
    )

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    window.findChild(QTableWidget, "loadOrdersTable").setCurrentCell(0, 0)
    window.findChild(QPushButton, "annulLoadOrderButton").click()
    app.processEvents()

    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_PENDING
    assert "permiso" in window.findChild(QLabel, "loadOrderFeedback").text().lower()
