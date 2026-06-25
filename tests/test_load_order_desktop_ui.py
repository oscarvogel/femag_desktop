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
