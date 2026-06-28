import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _set_combo(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def _assert_combo_disabled(combo):
    assert not combo.isEnabled(), f"Expected {combo.objectName()} to be disabled"


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

    driver_combo = dialog.findChild(QComboBox, "loadOrderDriverInput")
    carrier_combo = dialog.findChild(QComboBox, "loadOrderCarrierInput")
    truck_combo = dialog.findChild(QComboBox, "loadOrderTruckInput")

    _assert_combo_disabled(carrier_combo)

    _set_combo(driver_combo, driver.id)
    app.processEvents()

    assert carrier_combo.currentData() == carrier.id
    assert truck_combo.findData(truck.id) >= 0
    _set_combo(truck_combo, truck.id)

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


def test_load_order_dialog_layout_keeps_work_sections_readable(db):
    from PyQt5.QtWidgets import QApplication, QScrollArea, QSplitter, QTableWidget

    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue89"), "ui_issue89")
    app.processEvents()

    assert dialog.minimumWidth() >= 980
    assert dialog.minimumHeight() >= 760
    assert dialog.findChild(QScrollArea, "loadOrderEntryScrollArea") is not None
    assert dialog.findChild(QSplitter, "loadOrderEntryWorkSplitter") is not None
    assert dialog.findChild(QTableWidget, "loadOrderDestinationDraftTable").minimumHeight() >= 180
    assert dialog.findChild(QTableWidget, "loadOrderProductDraftTable").minimumHeight() >= 160


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


def test_load_order_dialog_driver_autofills_carrier_and_filters_trucks(db):
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

    _assert_combo_disabled(carrier_combo)
    assert driver_combo.findData(driver_a.id) >= 0
    assert driver_combo.findData(driver_b.id) >= 0

    _set_combo(driver_combo, driver_b.id)
    app.processEvents()

    assert carrier_combo.currentData() == carrier_b.id
    assert truck_combo.findData(truck_a.id) == -1
    assert truck_combo.findData(truck_b.id) >= 0

    _set_combo(driver_combo, driver_a.id)
    app.processEvents()

    assert carrier_combo.currentData() == carrier_a.id
    assert truck_combo.findData(truck_a.id) >= 0
    assert truck_combo.findData(truck_b.id) == -1


def test_load_order_dialog_rejects_driver_without_carrier(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Carrier, Driver, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Transporte Test UI")
    driver = Driver.create(name="Chofer Sin Transporte", carrier=carrier)
    truck = Truck.create(domain="TRK-TEST", carrier=carrier)
    carrier.delete_instance()

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue65"), "ui_issue65")
    app.processEvents()

    driver_combo = dialog.findChild(QComboBox, "loadOrderDriverInput")
    carrier_combo = dialog.findChild(QComboBox, "loadOrderCarrierInput")
    truck_combo = dialog.findChild(QComboBox, "loadOrderTruckInput")

    _set_combo(driver_combo, driver.id)
    app.processEvents()

    assert carrier_combo.currentData() is None
    assert truck_combo.findData(truck.id) == -1


def test_load_order_dialog_truck_filtered_by_driver_carrier(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QPushButton

    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Transporte Correcto UI")
    other_carrier = Carrier.create(name="Otro Transporte UI")
    driver = Driver.create(name="Chofer Correcto UI", carrier=carrier)
    correct_truck = Truck.create(domain="TRK-CORRECTO", carrier=carrier)
    wrong_truck = Truck.create(domain="TRK-AJENO", carrier=other_carrier)

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue65"), "ui_issue65")
    app.processEvents()

    driver_combo = dialog.findChild(QComboBox, "loadOrderDriverInput")
    truck_combo = dialog.findChild(QComboBox, "loadOrderTruckInput")

    _set_combo(driver_combo, driver.id)
    app.processEvents()

    assert truck_combo.findData(correct_truck.id) >= 0
    assert truck_combo.findData(wrong_truck.id) == -1


def test_load_order_page_operates_emit_print_again_and_annul_feedback(db, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QTableWidget

    from app.models.accounting import ClientAccountMovement
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
    opened_outputs = []
    monkeypatch.setattr("app.ui.desktop_app._open_print_output", lambda path: opened_outputs.append(path))

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    table = window.findChild(QTableWidget, "loadOrdersTable")
    feedback = window.findChild(QLabel, "loadOrderFeedback")
    status = window.findChild(QLabel, "detailOrderStatus")
    table.setCurrentCell(0, 0)

    headers = [table.horizontalHeaderItem(column).text() for column in range(table.columnCount())]
    assert "Camión / patente" in headers
    truck_column = headers.index("Camión / patente")
    assert table.item(0, truck_column).text() == "UI123AA"

    window.findChild(QPushButton, "issueLoadOrderButton").click()
    app.processEvents()
    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_ISSUED
    assert "emitida" in feedback.text().lower()
    assert status.text() == "Emitida"
    assert (
        ClientAccountMovement.select()
        .where((ClientAccountMovement.load_order == order) & (ClientAccountMovement.is_reversal == False))  # noqa: E712
        .count()
        == 1
    )

    window.findChild(QPushButton, "printLoadOrderButton").click()
    app.processEvents()
    assert "pdf generado correctamente" in feedback.text().lower()
    pdf_path = next(tmp_path.glob("orden_carga_*.pdf"))
    assert opened_outputs == [pdf_path]
    assert str(pdf_path) in feedback.text()
    assert pdf_path.read_bytes().startswith(b"%PDF")

    window.findChild(QPushButton, "printLoadOrderButton").click()
    app.processEvents()
    assert "pdf generado correctamente" in feedback.text().lower()
    assert opened_outputs == [pdf_path, pdf_path]

    window.findChild(QPushButton, "annulLoadOrderButton").click()
    app.processEvents()
    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_ANNULLED
    assert status.text() == "Anulada"
    assert (
        ClientAccountMovement.select()
        .where((ClientAccountMovement.load_order == order) & (ClientAccountMovement.is_reversal == True))  # noqa: E712
        .count()
        == 1
    )

    window.findChild(QPushButton, "printLoadOrderButton").click()
    app.processEvents()
    assert "pdf generado correctamente" in feedback.text().lower()
    assert opened_outputs == [pdf_path, pdf_path, pdf_path]


def test_load_order_print_feedback_survives_pdf_viewer_failure(db, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QTableWidget

    from app.models.security import User, UserProfile
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_print_open_failure", password_hash="x", profile=profile)
    carrier = Carrier.create(name="Transporte PDF UI")
    driver = Driver.create(name="Chofer PDF UI", carrier=carrier)
    truck = Truck.create(domain="PDF123", carrier=carrier)
    client = Client.create(name="Cliente PDF UI", cuit="30712345009", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta PDF",
    )
    product = Product.create(name="Producto PDF UI", unit="kg")
    LoadOrderService(current_user=user.username).create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[{"client": client, "delivery_address": address, "products": [{"product": product, "quantity": 1}]}],
        pallets=[],
    )
    monkeypatch.setattr("app.ui.desktop_app.LOAD_ORDER_PRINTS_DIR", tmp_path)

    def fail_open(_path):
        raise OSError("visor no disponible")

    monkeypatch.setattr("app.ui.desktop_app._open_print_output", fail_open)

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    window.findChild(QTableWidget, "loadOrdersTable").setCurrentCell(0, 0)
    window.findChild(QPushButton, "printLoadOrderButton").click()
    app.processEvents()

    pdf_path = next(tmp_path.glob("orden_carga_*.pdf")).resolve()
    feedback = window.findChild(QLabel, "loadOrderFeedback").text()

    assert pdf_path.exists()
    assert "PDF generado correctamente" in feedback
    assert str(pdf_path) in feedback
    assert "No se pudo abrir automaticamente" in feedback


def test_load_order_page_edits_pending_order_adding_destination_and_product(db, monkeypatch):
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QComboBox, QDialog, QPushButton, QTableWidget

    from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
    from app.models.security import User, UserProfile
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow, LoadOrderProductDialog

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_edit_order_ui", password_hash="x", profile=profile)
    carrier = Carrier.create(name="Transporte Editar UI")
    driver = Driver.create(name="Chofer Editar UI", carrier=carrier)
    truck = Truck.create(domain="EDI123", carrier=carrier)
    product_a = Product.create(name="Producto Editar A", unit="kg")
    product_b = Product.create(name="Producto Editar B", unit="bolsas")
    client_a = Client.create(name="Cliente Editar A", cuit="30700008801", iva_condition="RI")
    address_a = ClientAddress.create(
        client=client_a,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta A",
    )
    client_b = Client.create(name="Cliente Editar B", cuit="30700008802", iva_condition="RI")
    address_b = ClientAddress.create(
        client=client_b,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Ruta B",
    )
    order = LoadOrderService(current_user=user.username).create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client_a,
                "delivery_address": address_a,
                "products": [{"product": product_a, "quantity": 10}],
            }
        ],
        pallets=[],
    )

    def accept_product(product_dialog):
        product_dialog.product = {
            "product_id": product_b.id,
            "product_label": product_b.name,
            "quantity": 7,
            "unit": product_b.unit,
        }
        return QDialog.Accepted

    monkeypatch.setattr(LoadOrderProductDialog, "exec_", accept_product)

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    window.findChild(QTableWidget, "loadOrdersTable").setCurrentCell(0, 0)

    def fill_edit_dialog():
        dialog = app.activeModalWidget()
        assert dialog is not None
        assert dialog.findChild(QTableWidget, "loadOrderDestinationDraftTable").rowCount() == 1
        _set_combo(dialog.findChild(QComboBox, "loadOrderClientInput"), client_b.id)
        _set_combo(dialog.findChild(QComboBox, "loadOrderAddressInput"), address_b.id)
        dialog.findChild(QPushButton, "addLoadOrderClientButton").click()
        dialog.findChild(QTableWidget, "loadOrderDestinationDraftTable").setCurrentCell(1, 0)
        dialog.findChild(QPushButton, "addLoadOrderProductButton").click()
        dialog.findChild(QPushButton, "saveLoadOrderButton").click()

    QTimer.singleShot(0, fill_edit_dialog)
    window.findChild(QPushButton, "editLoadOrderButton").click()
    app.processEvents()

    assert LoadOrder.get_by_id(order.id).order_number == order.order_number
    assert LoadOrderDestination.select().where(LoadOrderDestination.order == order).count() == 2
    assert LoadOrderProduct.select().where(LoadOrderProduct.order == order).count() == 2
    assert "VARIOS" in window.findChild(QTableWidget, "loadOrdersTable").item(0, 2).text()


def test_load_order_page_disables_emit_and_edit_for_issued_order(db):
    from PyQt5.QtWidgets import QApplication, QPushButton, QTableWidget

    from app.models.security import User, UserProfile
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_issued_actions_ui", password_hash="x", profile=profile)
    carrier = Carrier.create(name="Transporte Emitida UI")
    driver = Driver.create(name="Chofer Emitida UI", carrier=carrier)
    truck = Truck.create(domain="EMI123", carrier=carrier)
    client = Client.create(name="Cliente Emitida UI", cuit="30700008803", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Emitida",
    )
    product = Product.create(name="Producto Emitida UI", unit="kg")
    order = LoadOrderService(current_user=user.username).create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[{"client": client, "delivery_address": address, "products": [{"product": product, "quantity": 1}]}],
        pallets=[],
    )
    LoadOrderOperationService(current_user=user.username).issue(order)

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    window.findChild(QTableWidget, "loadOrdersTable").setCurrentCell(0, 0)
    app.processEvents()

    issue_button = window.findChild(QPushButton, "issueLoadOrderButton")
    edit_button = window.findChild(QPushButton, "editLoadOrderButton")

    assert issue_button.isEnabled() is False
    assert edit_button.isEnabled() is False
    assert "emitida" in issue_button.toolTip().lower()
    assert "pendientes" in edit_button.toolTip().lower()


def test_load_order_page_closes_issued_order_and_releases_driver(db):
    from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QTableWidget

    from app.models.load_orders import LoadOrder
    from app.models.security import User, UserProfile
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_close_issued_ui", password_hash="x", profile=profile)
    carrier = Carrier.create(name="Transporte Cierre UI")
    driver = Driver.create(name="Chofer Cierre UI", carrier=carrier)
    truck = Truck.create(domain="CIE123", carrier=carrier)
    client = Client.create(name="Cliente Cierre UI", cuit="30700008804", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Cierre",
    )
    product = Product.create(name="Producto Cierre UI", unit="kg")
    order = LoadOrderService(current_user=user.username).create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[{"client": client, "delivery_address": address, "products": [{"product": product, "quantity": 1}]}],
        pallets=[],
    )
    LoadOrderOperationService(current_user=user.username).issue(order)

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    window.findChild(QTableWidget, "loadOrdersTable").setCurrentCell(0, 0)
    app.processEvents()

    close_button = window.findChild(QPushButton, "closeLoadOrderButton")
    assert close_button.isEnabled() is True

    close_button.click()
    app.processEvents()

    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_CLOSED
    assert Driver.get_by_id(driver.id).available is True
    assert "cerrada" in window.findChild(QLabel, "loadOrderFeedback").text().lower()


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
    assert window.findChild(QPushButton, "printLoadOrderButton").text() == "Imprimir"
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


def test_load_order_dialog_excludes_inactive_delivery_addresses(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Client, ClientAddress
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente Inactivo UI", cuit="30700000003", iva_condition="RI")
    active_address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Activa",
    )
    inactive_address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Ruta Inactiva",
        active=False,
    )

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue97"), "ui_issue97")
    app.processEvents()

    client_combo = dialog.findChild(QComboBox, "loadOrderClientInput")
    address_combo = dialog.findChild(QComboBox, "loadOrderAddressInput")
    _set_combo(client_combo, client.id)
    app.processEvents()

    assert address_combo.findData(active_address.id) >= 0
    assert address_combo.findData(inactive_address.id) == -1


def test_load_order_dialog_auto_selects_single_delivery_address(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Client, ClientAddress
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente Unico UI", cuit="30700000004", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Unica",
    )

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue97"), "ui_issue97")
    app.processEvents()

    client_combo = dialog.findChild(QComboBox, "loadOrderClientInput")
    address_combo = dialog.findChild(QComboBox, "loadOrderAddressInput")
    _set_combo(client_combo, client.id)
    app.processEvents()

    assert address_combo.currentData() == address.id


def test_load_order_dialog_shows_feedback_when_no_active_addresses(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QLabel

    from app.models.masters import Client, ClientAddress
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente Sin Lugar UI", cuit="30700000005", iva_condition="RI")
    ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Inactiva",
        active=False,
    )

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue97"), "ui_issue97")
    app.processEvents()

    client_combo = dialog.findChild(QComboBox, "loadOrderClientInput")
    address_combo = dialog.findChild(QComboBox, "loadOrderAddressInput")
    _set_combo(client_combo, client.id)
    app.processEvents()

    assert address_combo.currentData() is None
    feedback = dialog.findChild(QLabel, "loadOrderDialogFeedback")
    assert "no tiene lugares de entrega activos" in feedback.text()


def test_demo_seed_client_1_has_two_active_addresses(db):
    from app.models.masters import Client
    from app.ui.desktop_app import _address_options, _seed_demo_masters

    _seed_demo_masters()

    client_1 = Client.get(Client.cuit == "30777777772")
    assert client_1.name == "Demo 1"

    options = _address_options(client_id=client_1.id)
    assert len(options) == 2
    labels = [label for _id, label in options]
    assert any("Posadas" in label for label in labels)
    assert any("Eldorado" in label for label in labels)


def test_demo_seed_client_2_has_one_active_address(db):
    from app.models.masters import Client
    from app.ui.desktop_app import _address_options, _seed_demo_masters

    _seed_demo_masters()

    client = Client.get(Client.cuit == "30777777773")
    assert client.name == "Demo 2"

    options = _address_options(client_id=client.id)
    assert len(options) == 1
    label = options[0][1]
    assert "Garuhape" in label


def test_demo_seed_client_inactive_has_no_active_addresses(db):
    from app.models.masters import Client, ClientAddress
    from app.ui.desktop_app import _address_options, _seed_demo_masters

    _seed_demo_masters()

    client = Client.get(Client.cuit == "30777777774")
    assert client.name == "Sin Entregas Activas"

    total_addresses = ClientAddress.select().where(ClientAddress.client == client).count()
    assert total_addresses == 1
    active_count = ClientAddress.select().where(
        (ClientAddress.client == client) & (ClientAddress.active == True)
    ).count()
    assert active_count == 0

    options = _address_options(client_id=client.id)
    assert len(options) == 0


def test_demo_seed_address_options_without_client_returns_all_active(db):
    from app.ui.desktop_app import _address_options, _seed_demo_masters

    _seed_demo_masters()

    options = _address_options(client_id=None)
    assert len(options) == 3


def test_demo_load_order_dialog_shows_correct_addresses_per_client(db):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication, QComboBox, QLabel

    from app.models.masters import Client
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog, _seed_demo_masters

    _seed_demo_masters()

    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="demo"), "demo")
    app.processEvents()

    client_combo = dialog.findChild(QComboBox, "loadOrderClientInput")
    address_combo = dialog.findChild(QComboBox, "loadOrderAddressInput")
    feedback = dialog.findChild(QLabel, "loadOrderDialogFeedback")

    client_1 = Client.get(Client.cuit == "30777777772")
    client_2 = Client.get(Client.cuit == "30777777773")
    client_inactive = Client.get(Client.cuit == "30777777774")

    _set_combo(client_combo, client_1.id)
    app.processEvents()
    assert address_combo.count() > 1
    items = [address_combo.itemText(i) for i in range(address_combo.count())]
    assert any("Posadas" in item for item in items)
    assert any("Eldorado" in item for item in items)

    _set_combo(client_combo, client_2.id)
    app.processEvents()
    assert address_combo.currentText() != "-- Seleccione --"
    assert "Garuhape" in address_combo.currentText()

    _set_combo(client_combo, client_inactive.id)
    app.processEvents()
    assert address_combo.currentData() is None
    assert "no tiene lugares de entrega activos" in feedback.text()

    _set_combo(client_combo, client_1.id)
    app.processEvents()
    assert address_combo.count() > 1


def test_demo_seed_inactive_address_excluded_from_all_clients(db):
    from app.models.masters import Client, ClientAddress
    from app.ui.desktop_app import _address_options, _seed_demo_masters

    _seed_demo_masters()

    client = Client.get(Client.cuit == "30777777774")
    inactive_address = ClientAddress.get(
        ClientAddress.client == client, ClientAddress.active == False
    )

    all_options = _address_options(client_id=None)
    ids = [opt_id for opt_id, _label in all_options]
    assert inactive_address.id not in ids
