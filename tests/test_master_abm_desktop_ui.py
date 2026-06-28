import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _set_combo(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def _navigate_to_route(window, route):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QListWidget

    nav = window.findChild(QListWidget, "sidebar")
    assert nav is not None

    def select_visible_route() -> bool:
        for row in range(nav.count()):
            item = nav.item(row)
            if item.data(Qt.UserRole) == route:
                nav.setCurrentRow(row)
                return True
        return False

    if select_visible_route():
        return
    for row in range(nav.count()):
        item = nav.item(row)
        if item.data(Qt.UserRole) == "group:Transporte":
            nav.setCurrentRow(row)
            break
    if select_visible_route():
        return
    raise AssertionError(f"Route not found in sidebar: {route}")


def _admin_window(username: str):
    from PyQt5.QtWidgets import QApplication

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username=username, password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    return app, window


def _run_modal(app, trigger, fill_dialog):
    from PyQt5.QtCore import QTimer

    def fill_active_dialog():
        dialog = app.activeModalWidget()
        assert dialog is not None
        fill_dialog(dialog)

    QTimer.singleShot(0, fill_active_dialog)
    trigger()
    app.processEvents()


def test_minimal_master_dialogs_create_load_order_ready_data(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton

    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.master_abm import (
        CarrierEntryDialog,
        ClientAddressEntryDialog,
        ClientEntryDialog,
        DriverEntryDialog,
        ProductEntryDialog,
        TruckEntryDialog,
    )

    app = QApplication.instance() or QApplication([])

    client_dialog = ClientEntryDialog(current_user="ui_issue70")
    client_dialog.findChild(QLineEdit, "clientNameInput").setText("Cliente UI 70")
    client_dialog.findChild(QLineEdit, "clientCuitInput").setText("30700000070")
    client_dialog.findChild(QLineEdit, "clientIvaInput").setText("RI")
    client_dialog.findChild(QPushButton, "saveClientButton").click()

    client = Client.get(Client.name == "Cliente UI 70")
    client_edit = ClientEntryDialog(current_user="ui_issue70", record_id=client.id)
    client_edit.findChild(QLineEdit, "clientNameInput").setText("Cliente UI 70 Editado")
    client_edit.findChild(QPushButton, "saveClientButton").click()
    client = Client.get_by_id(client.id)

    address_dialog = ClientAddressEntryDialog(current_user="ui_issue70")
    _set_combo(address_dialog.findChild(QComboBox, "addressClientInput"), client.id)
    address_dialog.findChild(QLineEdit, "addressProvinceInput").setText("Misiones")
    address_dialog.findChild(QLineEdit, "addressCityInput").setText("Posadas")
    address_dialog.findChild(QLineEdit, "addressStreetInput").setText("Ruta UI 70")
    address_dialog.findChild(QPushButton, "saveAddressButton").click()
    address = ClientAddress.get(ClientAddress.client == client)
    address_edit = ClientAddressEntryDialog(current_user="ui_issue70", record_id=address.id)
    address_edit.findChild(QLineEdit, "addressStreetInput").setText("Ruta UI 70 Editada")
    address_edit.findChild(QPushButton, "saveAddressButton").click()

    carrier_dialog = CarrierEntryDialog(current_user="ui_issue70")
    carrier_dialog.findChild(QLineEdit, "carrierNameInput").setText("Transporte UI 70")
    carrier_dialog.findChild(QLineEdit, "carrierCuitInput").setText("30770000070")
    carrier_dialog.findChild(QPushButton, "saveCarrierButton").click()

    carrier = Carrier.get(Carrier.name == "Transporte UI 70")
    carrier_edit = CarrierEntryDialog(current_user="ui_issue70", record_id=carrier.id)
    carrier_edit.findChild(QLineEdit, "carrierNameInput").setText("Transporte UI 70 Editado")
    carrier_edit.findChild(QPushButton, "saveCarrierButton").click()
    carrier = Carrier.get_by_id(carrier.id)

    driver_dialog = DriverEntryDialog(current_user="ui_issue70")
    _set_combo(driver_dialog.findChild(QComboBox, "driverCarrierInput"), carrier.id)
    driver_dialog.findChild(QLineEdit, "driverNameInput").setText("Chofer UI 70")
    driver_dialog.findChild(QLineEdit, "driverDocumentInput").setText("12370")
    driver_dialog.findChild(QPushButton, "saveDriverButton").click()
    driver = Driver.get(Driver.name == "Chofer UI 70")
    driver_edit = DriverEntryDialog(current_user="ui_issue70", record_id=driver.id)
    driver_edit.findChild(QLineEdit, "driverNameInput").setText("Chofer UI 70 Editado")
    driver_edit.findChild(QPushButton, "saveDriverButton").click()

    truck_dialog = TruckEntryDialog(current_user="ui_issue70")
    _set_combo(truck_dialog.findChild(QComboBox, "truckCarrierInput"), carrier.id)
    truck_dialog.findChild(QLineEdit, "truckDomainInput").setText("UI70AA")
    truck_dialog.findChild(QPushButton, "saveTruckButton").click()
    truck = Truck.get(Truck.domain == "UI70AA")
    truck_edit = TruckEntryDialog(current_user="ui_issue70", record_id=truck.id)
    truck_edit.findChild(QLineEdit, "truckDomainInput").setText("UI70BB")
    truck_edit.findChild(QPushButton, "saveTruckButton").click()

    product_dialog = ProductEntryDialog(current_user="ui_issue70")
    product_dialog.findChild(QLineEdit, "productNameInput").setText("Producto UI 70")
    product_dialog.findChild(QLineEdit, "productUnitInput").setText("kg")
    product_dialog.findChild(QPushButton, "saveProductButton").click()
    product = Product.get(Product.name == "Producto UI 70")
    product_edit = ProductEntryDialog(current_user="ui_issue70", record_id=product.id)
    product_edit.findChild(QLineEdit, "productNameInput").setText("Producto UI 70 Editado")
    product_edit.findChild(QPushButton, "saveProductButton").click()

    address = ClientAddress.get(ClientAddress.client == client)
    driver = Driver.get_by_id(driver.id)
    truck = Truck.get_by_id(truck.id)
    product = Product.get_by_id(product.id)
    order = LoadOrderService(current_user="ui_issue70").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [{"product": product, "quantity": 10}],
            }
        ],
        pallets=[],
    )

    assert client.name == "Cliente UI 70 Editado"
    assert address.client == client
    assert address.address == "Ruta UI 70 Editada"
    assert carrier.name == "Transporte UI 70 Editado"
    assert driver.name == "Chofer UI 70 Editado"
    assert driver.carrier == carrier
    assert truck.domain == "UI70BB"
    assert truck.carrier == carrier
    assert product.name == "Producto UI 70 Editado"
    assert order.id is not None


def test_desktop_exposes_minimal_master_abm_pages(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_issue70", password_hash="x", profile=profile)

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    expected_buttons = (
        "newClientButton",
        "editClientButton",
        "newAddressButton",
        "editAddressButton",
        "newProductButton",
        "editProductButton",
        "newDriverButton",
        "editDriverButton",
        "newCarrierButton",
        "editCarrierButton",
        "newTruckButton",
        "editTruckButton",
    )

    for object_name in expected_buttons:
        button = window.findChild(QPushButton, object_name)
        assert button is not None
        assert button.isEnabled()

    readonly_profile = UserProfile.get(UserProfile.name == "Solo consulta")
    readonly_user = User.create(username="readonly_issue70", password_hash="x", profile=readonly_profile)
    readonly_window = FemagDesktopWindow(user=readonly_user, demo_mode=True)
    app.processEvents()

    assert readonly_window.findChild(QPushButton, "newClientButton").isEnabled() is False
    assert readonly_window.findChild(QPushButton, "editClientButton").isEnabled() is False
    assert readonly_window.findChild(QPushButton, "newTruckButton").isEnabled() is False
    assert readonly_window.findChild(QPushButton, "editTruckButton").isEnabled() is False
    assert readonly_window._route_indexes["load_orders"] >= 0


def test_desktop_sidebar_groups_transport_abms_without_breaking_routes(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QListWidget, QPushButton

    app, window = _admin_window("admin_issue85")
    nav = window.findChild(QListWidget, "sidebar")
    assert nav is not None

    rows = [nav.item(row) for row in range(nav.count())]
    transport_row = next(row for row, item in enumerate(rows) if item.text() == "Transporte")
    assert nav.item(transport_row).data(Qt.UserRole) == "group:Transporte"

    nav.setCurrentRow(transport_row)
    app.processEvents()
    rows = [nav.item(row) for row in range(nav.count())]
    labels = [item.text().strip() for item in rows]
    transport_index = labels.index("Transporte")
    assert labels[transport_index + 1 : transport_index + 4] == ["Transportistas", "Choferes", "Camiones"]

    _navigate_to_route(window, "carriers")
    assert window.stack.currentIndex() == window._route_indexes["carriers"]
    assert window.findChild(QPushButton, "newCarrierButton") is not None

    _navigate_to_route(window, "drivers")
    assert window.stack.currentIndex() == window._route_indexes["drivers"]
    assert window.findChild(QPushButton, "newDriverButton") is not None

    _navigate_to_route(window, "trucks")
    assert window.stack.currentIndex() == window._route_indexes["trucks"]
    assert window.findChild(QPushButton, "newTruckButton") is not None

    _navigate_to_route(window, "load_orders")
    assert window.stack.currentIndex() == window._route_indexes["load_orders"]


def test_clients_abm_page_creates_edits_and_refreshes_grid(db):
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QDialog, QLineEdit, QPushButton, QTableWidget

    from app.models.masters import Client
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_clients_abm", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    table = window.findChild(QTableWidget, "clientTable")
    assert table is not None
    assert table.rowCount() == 0

    def fill_new_client():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        dialog.findChild(QLineEdit, "clientNameInput").setText("Cliente Demo UI")
        dialog.findChild(QLineEdit, "clientCuitInput").setText("30700000991")
        dialog.findChild(QLineEdit, "clientIvaInput").setText("RI")
        dialog.findChild(QPushButton, "saveClientButton").click()

    QTimer.singleShot(0, fill_new_client)
    window.findChild(QPushButton, "newClientButton").click()
    app.processEvents()

    client = Client.get(Client.cuit == "30700000991")
    assert client.name == "Cliente Demo UI"
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "Cliente Demo UI"

    def fill_edit_client():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        dialog.findChild(QLineEdit, "clientNameInput").setText("Cliente Demo UI Editado")
        dialog.findChild(QPushButton, "saveClientButton").click()

    QTimer.singleShot(0, fill_edit_client)
    window.findChild(QPushButton, "editClientButton").click()
    app.processEvents()

    client = Client.get_by_id(client.id)
    assert client.name == "Cliente Demo UI Editado"
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "Cliente Demo UI Editado"


def test_trucks_abm_page_creates_edits_and_refreshes_grid(db):
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtWidgets import QApplication, QComboBox, QDialog, QLabel, QLineEdit, QPushButton, QTableWidget

    from app.models.masters import Carrier, Truck
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.master_abm import CarrierEntryDialog

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_trucks_abm", password_hash="x", profile=profile)

    carrier_dialog = CarrierEntryDialog(current_user=user.username)
    carrier_dialog.findChild(QLineEdit, "carrierNameInput").setText("Transporte Camiones UI")
    carrier_dialog.findChild(QPushButton, "saveCarrierButton").click()
    carrier = Carrier.get(Carrier.name == "Transporte Camiones UI")

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    _navigate_to_route(window, "trucks")
    app.processEvents()

    assert window.stack.currentIndex() == window._route_indexes["trucks"]
    table = window.findChild(QTableWidget, "newTruckButtonTable")
    feedback = window.findChild(QLabel, "newTruckButtonFeedback")
    assert table is not None
    assert feedback is not None
    assert table.rowCount() == 0
    assert window.findChild(QPushButton, "newTruckButton").isEnabled()

    def fill_new_truck():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        assert dialog.objectName() == "truckEntryDialog"
        _set_combo(dialog.findChild(QComboBox, "truckCarrierInput"), carrier.id)
        dialog.findChild(QLineEdit, "truckDomainInput").setText("abm123")
        dialog.findChild(QPushButton, "saveTruckButton").click()

    QTimer.singleShot(0, fill_new_truck)
    window.findChild(QPushButton, "newTruckButton").click()
    app.processEvents()

    truck = Truck.get(Truck.domain == "ABM123")
    assert truck.carrier == carrier
    assert truck.active is True
    assert table.rowCount() == 1
    assert table.item(0, 0).data(Qt.UserRole) == truck.id
    assert table.item(0, 0).text() == "ABM123"
    assert table.item(0, 1).text() == "Transporte Camiones UI"
    assert table.item(0, 2).text() == "Activo"

    def fill_edit_truck():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        dialog.findChild(QLineEdit, "truckDomainInput").setText("abm456")
        _set_combo(dialog.findChild(QComboBox, "truckActiveInput"), False)
        dialog.findChild(QPushButton, "saveTruckButton").click()

    QTimer.singleShot(0, fill_edit_truck)
    window.findChild(QPushButton, "editTruckButton").click()
    app.processEvents()

    truck = Truck.get_by_id(truck.id)
    assert truck.domain == "ABM456"
    assert truck.active is False
    assert table.rowCount() == 1
    assert table.item(0, 0).text() == "ABM456"
    assert table.item(0, 2).text() == "Inactivo"


def test_truck_dialog_without_carriers_shows_clear_message(db):
    from PyQt5.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

    from app.ui.master_abm import TruckEntryDialog

    app = QApplication.instance() or QApplication([])
    dialog = TruckEntryDialog(current_user="ui_no_carriers")
    dialog.findChild(QLineEdit, "truckDomainInput").setText("SINCAR")
    dialog.findChild(QPushButton, "saveTruckButton").click()

    assert dialog.findChild(QLabel, "masterDialogFeedback").text() == (
        "Debe cargar un transportista antes de crear un camión."
    )


def test_truck_created_from_abm_can_be_used_in_load_order_grid(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit, QPushButton, QTableWidget

    from app.models.load_orders import LoadOrder
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.models.security import User, UserProfile
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow, LoadOrderEntryDialog, LoadOrderProductDialog
    from app.ui.master_abm import CarrierEntryDialog, DriverEntryDialog, TruckEntryDialog

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_truck_order_abm", password_hash="x", profile=profile)

    carrier_dialog = CarrierEntryDialog(current_user=user.username)
    carrier_dialog.findChild(QLineEdit, "carrierNameInput").setText("Transporte Orden UI")
    carrier_dialog.findChild(QPushButton, "saveCarrierButton").click()
    carrier = Carrier.get(Carrier.name == "Transporte Orden UI")

    driver_dialog = DriverEntryDialog(current_user=user.username)
    _set_combo(driver_dialog.findChild(QComboBox, "driverCarrierInput"), carrier.id)
    driver_dialog.findChild(QLineEdit, "driverNameInput").setText("Chofer Orden UI")
    driver_dialog.findChild(QPushButton, "saveDriverButton").click()
    driver = Driver.get(Driver.name == "Chofer Orden UI")

    truck_dialog = TruckEntryDialog(current_user=user.username)
    _set_combo(truck_dialog.findChild(QComboBox, "truckCarrierInput"), carrier.id)
    truck_dialog.findChild(QLineEdit, "truckDomainInput").setText("ORD123")
    truck_dialog.findChild(QPushButton, "saveTruckButton").click()
    truck = Truck.get(Truck.domain == "ORD123")

    client = Client.create(name="Cliente Orden UI", cuit="30700000992", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Orden UI",
    )
    product = Product.create(name="Producto Orden UI", unit="kg")

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user=user.username), user.username)
    app.processEvents()
    _set_combo(dialog.findChild(QComboBox, "loadOrderDriverInput"), driver.id)
    app.processEvents()
    assert dialog.findChild(QComboBox, "loadOrderTruckInput").findData(truck.id) >= 0
    _set_combo(dialog.findChild(QComboBox, "loadOrderTruckInput"), truck.id)
    _set_combo(dialog.findChild(QComboBox, "loadOrderClientInput"), client.id)
    _set_combo(dialog.findChild(QComboBox, "loadOrderAddressInput"), address.id)
    dialog.findChild(QPushButton, "addLoadOrderClientButton").click()
    dialog.findChild(QTableWidget, "loadOrderDestinationDraftTable").setCurrentCell(0, 0)

    def accept_product(product_dialog):
        product_dialog.product = {
            "product_id": product.id,
            "product_label": product.name,
            "quantity": 12,
            "unit": product.unit,
        }
        return QDialog.Accepted

    monkeypatch.setattr(LoadOrderProductDialog, "exec_", accept_product)
    dialog.findChild(QPushButton, "addLoadOrderProductButton").click()
    dialog.findChild(QPushButton, "saveLoadOrderButton").click()

    assert dialog.created_order is not None
    assert LoadOrder.select().count() == 1
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    _navigate_to_route(window, "load_orders")
    app.processEvents()
    table = window.findChild(QTableWidget, "loadOrdersTable")
    headers = [table.horizontalHeaderItem(column).text() for column in range(table.columnCount())]
    truck_column = headers.index("Camión / patente")

    assert table.rowCount() == 1
    assert table.item(0, truck_column).text() == "ORD123"


def test_carriers_abm_page_creates_edits_and_refreshes_grid(db):
    from PyQt5.QtWidgets import QLineEdit, QPushButton, QTableWidget

    from app.models.masters import Carrier

    app, window = _admin_window("admin_carriers_abm")
    table = window.findChild(QTableWidget, "newCarrierButtonTable")
    assert table is not None
    assert table.rowCount() == 0

    def fill_new(dialog):
        dialog.findChild(QLineEdit, "carrierNameInput").setText("Transporte Demo UI")
        dialog.findChild(QLineEdit, "carrierCuitInput").setText("30700000992")
        dialog.findChild(QPushButton, "saveCarrierButton").click()

    _run_modal(app, lambda: window.findChild(QPushButton, "newCarrierButton").click(), fill_new)
    carrier = Carrier.get(Carrier.cuit == "30700000992")
    assert carrier.name == "Transporte Demo UI"
    assert table.item(0, 0).text() == "Transporte Demo UI"

    def fill_edit(dialog):
        dialog.findChild(QLineEdit, "carrierNameInput").setText("Transporte Demo UI Editado")
        dialog.findChild(QPushButton, "saveCarrierButton").click()

    table.setCurrentCell(0, 0)
    _run_modal(app, lambda: window.findChild(QPushButton, "editCarrierButton").click(), fill_edit)
    carrier = Carrier.get_by_id(carrier.id)
    assert carrier.name == "Transporte Demo UI Editado"
    assert table.item(0, 0).text() == "Transporte Demo UI Editado"


def test_drivers_abm_page_creates_edits_with_carrier_combo(db):
    from PyQt5.QtWidgets import QComboBox, QLineEdit, QPushButton, QTableWidget

    from app.models.masters import Carrier, Driver

    carrier = Carrier.create(name="Transportista Chofer UI")
    app, window = _admin_window("admin_drivers_abm")
    table = window.findChild(QTableWidget, "newDriverButtonTable")
    assert table is not None

    def fill_new(dialog):
        _set_combo(dialog.findChild(QComboBox, "driverCarrierInput"), carrier.id)
        dialog.findChild(QLineEdit, "driverNameInput").setText("Chofer Demo UI")
        dialog.findChild(QLineEdit, "driverDocumentInput").setText("DNI123")
        dialog.findChild(QPushButton, "saveDriverButton").click()

    _run_modal(app, lambda: window.findChild(QPushButton, "newDriverButton").click(), fill_new)
    driver = Driver.get(Driver.document == "DNI123")
    assert driver.name == "Chofer Demo UI"
    assert driver.carrier == carrier
    assert table.item(0, 1).text() == "Transportista Chofer UI"

    def fill_edit(dialog):
        dialog.findChild(QLineEdit, "driverNameInput").setText("Chofer Demo UI Editado")
        dialog.findChild(QPushButton, "saveDriverButton").click()

    table.setCurrentCell(0, 0)
    _run_modal(app, lambda: window.findChild(QPushButton, "editDriverButton").click(), fill_edit)
    driver = Driver.get_by_id(driver.id)
    assert driver.name == "Chofer Demo UI Editado"
    assert table.item(0, 0).text() == "Chofer Demo UI Editado"


def test_trucks_abm_page_creates_edits_with_carrier_combo(db):
    from PyQt5.QtWidgets import QComboBox, QLineEdit, QPushButton, QTableWidget

    from app.models.masters import Carrier, Truck

    carrier = Carrier.create(name="Transportista Camion UI")
    app, window = _admin_window("admin_trucks_abm")
    table = window.findChild(QTableWidget, "newTruckButtonTable")
    assert table is not None

    def fill_new(dialog):
        _set_combo(dialog.findChild(QComboBox, "truckCarrierInput"), carrier.id)
        dialog.findChild(QLineEdit, "truckDomainInput").setText("lun123")
        dialog.findChild(QPushButton, "saveTruckButton").click()

    _run_modal(app, lambda: window.findChild(QPushButton, "newTruckButton").click(), fill_new)
    truck = Truck.get(Truck.domain == "LUN123")
    assert truck.carrier == carrier
    assert table.item(0, 0).text() == "LUN123"
    assert table.item(0, 1).text() == "Transportista Camion UI"

    def fill_edit(dialog):
        dialog.findChild(QLineEdit, "truckDomainInput").setText("lun456")
        dialog.findChild(QPushButton, "saveTruckButton").click()

    table.setCurrentCell(0, 0)
    _run_modal(app, lambda: window.findChild(QPushButton, "editTruckButton").click(), fill_edit)
    truck = Truck.get_by_id(truck.id)
    assert truck.domain == "LUN456"
    assert table.item(0, 0).text() == "LUN456"


def test_products_abm_page_creates_edits_and_refreshes_grid(db):
    from PyQt5.QtWidgets import QLineEdit, QPushButton, QTableWidget

    from app.models.masters import Product

    app, window = _admin_window("admin_products_abm")
    table = window.findChild(QTableWidget, "newProductButtonTable")
    assert table is not None

    def fill_new(dialog):
        dialog.findChild(QLineEdit, "productNameInput").setText("Producto Demo UI")
        dialog.findChild(QLineEdit, "productUnitInput").setText("bolsas")
        dialog.findChild(QPushButton, "saveProductButton").click()

    _run_modal(app, lambda: window.findChild(QPushButton, "newProductButton").click(), fill_new)
    product = Product.get(Product.name == "Producto Demo UI")
    assert product.unit == "bolsas"
    assert table.item(0, 0).text() == "Producto Demo UI"

    def fill_edit(dialog):
        dialog.findChild(QLineEdit, "productNameInput").setText("Producto Demo UI Editado")
        dialog.findChild(QPushButton, "saveProductButton").click()

    table.setCurrentCell(0, 0)
    _run_modal(app, lambda: window.findChild(QPushButton, "editProductButton").click(), fill_edit)
    product = Product.get_by_id(product.id)
    assert product.name == "Producto Demo UI Editado"
    assert table.item(0, 0).text() == "Producto Demo UI Editado"


def test_master_abm_documents_autoabm_debt():
    from app.ui.master_abm import AUTO_ABM_TECHNICAL_DEBT

    assert "do not instantiate pyqt5libs AutoABM yet" in AUTO_ABM_TECHNICAL_DEBT
    assert "permissions" in AUTO_ABM_TECHNICAL_DEBT
    assert "audit services" in AUTO_ABM_TECHNICAL_DEBT


def test_client_abm_page_shows_addresses_for_selected_client(db):
    from PyQt5.QtWidgets import QTableWidget

    from app.models.masters import Client, ClientAddress

    client = Client.create(name="Z Cliente Places", cuit="30700000993", iva_condition="RI")
    ClientAddress.create(client=client, address_type="entrega", province="Misiones", city="Posadas", address="Ruta A")
    ClientAddress.create(client=client, address_type="entrega", province="Misiones", city="Eldorado", address="Ruta B")

    app, window = _admin_window("admin_client_places")

    client_table = window.findChild(QTableWidget, "clientTable")
    assert client_table is not None

    row_count = client_table.rowCount()
    target_row = None
    for r in range(row_count):
        if client_table.item(r, 0).text() == "Z Cliente Places":
            target_row = r
            break
    assert target_row is not None, "Client not found in client table"
    client_table.setCurrentCell(target_row, 0)
    app.processEvents()

    places_table = window.findChild(QTableWidget, "clientPlacesTable")
    assert places_table is not None
    assert places_table.rowCount() == 2
    headers = [places_table.horizontalHeaderItem(c).text() for c in range(places_table.columnCount())]
    assert "Estado" in headers
    addr_items = [places_table.item(r, 0).text() for r in range(places_table.rowCount())]
    assert "Ruta A" in addr_items
    assert "Ruta B" in addr_items


def test_client_abm_can_add_address_from_client_page(db):
    from PyQt5.QtWidgets import QComboBox, QLineEdit, QPushButton, QTableWidget

    from app.models.masters import Client, ClientAddress

    client = Client.create(name="Z Cliente Add Place", cuit="30700000994", iva_condition="RI")
    app, window = _admin_window("admin_add_place")

    client_table = window.findChild(QTableWidget, "clientTable")
    target_row = None
    for r in range(client_table.rowCount()):
        if client_table.item(r, 0).text() == "Z Cliente Add Place":
            target_row = r
            break
    assert target_row is not None
    client_table.setCurrentCell(target_row, 0)
    app.processEvents()

    def fill_place(dialog):
        _set_combo(dialog.findChild(QComboBox, "addressTypeInput"), "entrega")
        dialog.findChild(QLineEdit, "addressProvinceInput").setText("Misiones")
        dialog.findChild(QLineEdit, "addressCityInput").setText("Posadas")
        dialog.findChild(QLineEdit, "addressStreetInput").setText("Ruta Nueva")
        dialog.findChild(QPushButton, "saveAddressButton").click()

    _run_modal(app, lambda: window.findChild(QPushButton, "addClientPlaceButton").click(), fill_place)

    address = ClientAddress.get(ClientAddress.address == "Ruta Nueva")
    assert address.client.id == client.id
    assert address.active is True
    places_table = window.findChild(QTableWidget, "clientPlacesTable")
    assert places_table.rowCount() == 1
    assert places_table.item(0, 0).text() == "Ruta Nueva"


def test_client_abm_can_edit_existing_address(db):
    from PyQt5.QtWidgets import QLineEdit, QPushButton, QTableWidget

    from app.models.masters import Client, ClientAddress

    client = Client.create(name="Z Cliente Edit Place", cuit="30700000995", iva_condition="RI")
    ClientAddress.create(client=client, address_type="entrega", province="Misiones", city="Posadas", address="Ruta Original")
    app, window = _admin_window("admin_edit_place")

    client_table = window.findChild(QTableWidget, "clientTable")
    for r in range(client_table.rowCount()):
        if client_table.item(r, 0).text() == "Z Cliente Edit Place":
            client_table.setCurrentCell(r, 0)
            break
    app.processEvents()

    places_table = window.findChild(QTableWidget, "clientPlacesTable")
    assert places_table.rowCount() == 1
    assert places_table.item(0, 0).text() == "Ruta Original"
    places_table.setCurrentCell(0, 0)

    def fill_edit(dialog):
        dialog.findChild(QLineEdit, "addressStreetInput").setText("Ruta Editada")
        dialog.findChild(QPushButton, "saveAddressButton").click()

    _run_modal(app, lambda: window.findChild(QPushButton, "editClientPlaceButton").click(), fill_edit)

    address = ClientAddress.get(ClientAddress.client == client)
    assert address.address == "Ruta Editada"
    assert places_table.item(0, 0).text() == "Ruta Editada"


def test_client_abm_can_toggle_address_active_from_page(db):
    from PyQt5.QtWidgets import QPushButton, QTableWidget

    from app.models.masters import Client, ClientAddress

    client = Client.create(name="Z Cliente Toggle", cuit="30700000996", iva_condition="RI")
    ClientAddress.create(client=client, address_type="entrega", province="Misiones", city="Posadas", address="Ruta Toggle")
    app, window = _admin_window("admin_toggle_place")

    client_table = window.findChild(QTableWidget, "clientTable")
    for r in range(client_table.rowCount()):
        if client_table.item(r, 0).text() == "Z Cliente Toggle":
            client_table.setCurrentCell(r, 0)
            break
    app.processEvents()

    places_table = window.findChild(QTableWidget, "clientPlacesTable")
    assert places_table.rowCount() == 1
    assert places_table.item(0, 3).text() == "Activo"
    places_table.setCurrentCell(0, 0)

    toggle_btn = window.findChild(QPushButton, "toggleClientPlaceButton")
    toggle_btn.click()
    app.processEvents()

    address = ClientAddress.get(ClientAddress.client == client)
    assert address.active is False
    assert places_table.item(0, 3).text() == "Inactivo"

    toggle_btn.click()
    app.processEvents()

    address = ClientAddress.get(ClientAddress.client == client)
    assert address.active is True
    assert places_table.item(0, 3).text() == "Activo"


def test_client_abm_shows_inactive_and_active_addresses(db):
    from PyQt5.QtWidgets import QTableWidget

    from app.models.masters import Client, ClientAddress

    client = Client.create(name="Z Cliente Mixed", cuit="30700000997", iva_condition="RI")
    ClientAddress.create(client=client, address_type="entrega", province="Misiones", city="Posadas", address="Ruta Activa")
    ClientAddress.create(client=client, address_type="entrega", province="Misiones", city="Eldorado", address="Ruta Inactiva", active=False)
    app, window = _admin_window("admin_mixed_places")

    client_table = window.findChild(QTableWidget, "clientTable")
    for r in range(client_table.rowCount()):
        if client_table.item(r, 0).text() == "Z Cliente Mixed":
            client_table.setCurrentCell(r, 0)
            break
    app.processEvents()

    places_table = window.findChild(QTableWidget, "clientPlacesTable")
    assert places_table.rowCount() == 2
    statuses = [places_table.item(r, 3).text() for r in range(places_table.rowCount())]
    assert "Activo" in statuses
    assert "Inactivo" in statuses
