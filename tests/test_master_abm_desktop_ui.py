import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _set_combo(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


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

    table = window.findChild(QTableWidget, "newClientButtonTable")
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


def test_master_abm_documents_autoabm_debt():
    from app.ui.master_abm import AUTO_ABM_TECHNICAL_DEBT

    assert "do not instantiate pyqt5libs AutoABM yet" in AUTO_ABM_TECHNICAL_DEBT
    assert "permissions" in AUTO_ABM_TECHNICAL_DEBT
    assert "audit services" in AUTO_ABM_TECHNICAL_DEBT
