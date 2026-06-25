import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _set_combo(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_load_order_desktop_ui_creates_order_from_visible_form(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QDoubleSpinBox, QPushButton, QTableWidget

    from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.auth_service import AuthService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    user = AuthService().create_user("ui_issue65", "demo", "Administrador")
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

    window = FemagDesktopWindow(user=user, demo_mode=True)
    window.stack.setCurrentIndex(window._route_indexes["load_orders"])
    app.processEvents()

    _set_combo(window.findChild(QComboBox, "loadOrderCarrierInput"), carrier.id)
    _set_combo(window.findChild(QComboBox, "loadOrderTruckInput"), truck.id)
    _set_combo(window.findChild(QComboBox, "loadOrderDriverInput"), driver.id)
    _set_combo(window.findChild(QComboBox, "loadOrderClientInput"), client.id)
    _set_combo(window.findChild(QComboBox, "loadOrderAddressInput"), address.id)
    _set_combo(window.findChild(QComboBox, "loadOrderProductInput"), product.id)
    window.findChild(QDoubleSpinBox, "loadOrderQuantityInput").setValue(125)

    window.findChild(QPushButton, "addLoadOrderClientButton").click()
    window.findChild(QTableWidget, "loadOrderDestinationDraftTable").setCurrentCell(0, 0)
    window.findChild(QPushButton, "addLoadOrderProductButton").click()
    window.findChild(QPushButton, "saveLoadOrderButton").click()

    assert LoadOrder.select().count() == 1
    assert LoadOrderDestination.select().count() == 1
    assert LoadOrderProduct.select().count() == 1
