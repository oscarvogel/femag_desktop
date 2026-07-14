import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _set_combo(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def _assert_combo_disabled(combo):
    assert not combo.isEnabled(), f"Expected {combo.objectName()} to be disabled"


def _complete_order_for_issue(order, current_user):
    from app.services.load_order_service import LoadOrderService

    allocations = []
    for line in order.products:
        product = line.product
        if product.peso_unitario_kg == 0:
            product.peso_unitario_kg = 1
            product.save()
        allocations.append(
            {
                "client": line.destination.client,
                "delivery_address": line.destination.delivery_address,
                "product": product,
                "quantity": line.quantity,
            }
        )
    LoadOrderService(current_user=current_user).update_order(
        order,
        pallets=[{"sequence": 1, "pallet_type": None, "allocations": allocations}],
    )
    return order


def test_load_order_dialog_integrates_pallet_cards_and_persists_draft(db):
    from decimal import Decimal

    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.load_orders import LoadOrderPalletAllocation
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Transporte UI kilos")
    driver = Driver.create(name="Chofer UI kilos", carrier=carrier)
    truck = Truck.create(domain="KGUI123", carrier=carrier)
    client = Client.create(name="Cliente UI kilos", cuit="30712345991", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta kilos",
    )
    product = Product.create(
        name="Producto UI kilos",
        unit="bolsa",
        peso_unitario_kg=Decimal("25.000"),
    )
    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_kilos"), "ui_kilos")
    app.processEvents()

    assert [button.text().split("  ", 1)[1] for button in dialog.step_buttons] == [
        "Transporte",
        "Destinos",
        "Productos",
        "Pallets",
        "Revisar",
    ]
    _set_combo(dialog.findChild(QComboBox, "loadOrderDriverInput"), driver.id)
    _set_combo(dialog.findChild(QComboBox, "loadOrderTruckInput"), truck.id)
    dialog.destinations = [
        {
            "client_id": client.id,
            "address_id": address.id,
            "client_label": client.name,
            "address_label": address.address,
            "products": [
                {
                    "product_id": product.id,
                    "product_label": product.name,
                    "quantity": 40,
                    "unit": product.unit,
                    "precio_neto_unitario": 0,
                    "descuento_porcentaje": 0,
                    "iva_porcentaje": 21,
                    "total": 0,
                }
            ],
        }
    ]
    dialog._render_destinations()
    dialog.pallet_widget.add_pallet()
    dialog.pallet_widget.add_allocation(1, address.id, product.id, 40)

    assert dialog.pallet_widget.total_kg_label.text() == "1.000,000 kg"
    dialog._save()

    assert dialog.created_order is not None
    assert LoadOrderPalletAllocation.select().count() == 1
    assert dialog.service.composition(dialog.created_order).total_kg == Decimal("1000.000")

    edit = LoadOrderEntryDialog(dialog.service, "ui_kilos", order=dialog.created_order)
    app.processEvents()
    assert edit.pallet_widget.total_kg_label.text() == "1.000,000 kg"
    assert edit.pallet_widget.card_for_sequence(1).property("compositionState") == "complete"


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


def test_load_order_dialog_enables_save_only_when_required_data_is_complete(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QComboBox, QDialog, QPushButton, QTableWidget

    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog, LoadOrderProductDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Transporte Save Ready")
    driver = Driver.create(name="Chofer Save Ready", carrier=carrier)
    truck = Truck.create(domain="SR123AA", carrier=carrier)
    client = Client.create(name="Cliente Save Ready", cuit="30712345001", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Save Ready",
    )
    product = Product.create(name="Producto Save Ready", unit="kg")

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_save_ready"), "ui_save_ready")
    app.processEvents()
    save_button = dialog.findChild(QPushButton, "saveLoadOrderButton")

    assert save_button is not None
    assert save_button.isEnabled() is False

    _set_combo(dialog.findChild(QComboBox, "loadOrderDriverInput"), driver.id)
    _set_combo(dialog.findChild(QComboBox, "loadOrderTruckInput"), truck.id)
    app.processEvents()

    assert save_button.isEnabled() is False

    _set_combo(dialog.findChild(QComboBox, "loadOrderClientInput"), client.id)
    _set_combo(dialog.findChild(QComboBox, "loadOrderAddressInput"), address.id)
    dialog.findChild(QPushButton, "addLoadOrderClientButton").click()
    app.processEvents()

    assert save_button.isEnabled() is False

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
    app.processEvents()

    assert save_button.isEnabled() is True

    dialog.findChild(QTableWidget, "loadOrderProductDraftTable").setCurrentCell(0, 0)
    dialog.findChild(QPushButton, "removeLoadOrderProductButton").click()
    app.processEvents()

    assert save_button.isEnabled() is False


def test_load_order_dialog_selects_new_destination_for_next_product(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QComboBox, QDialog, QPushButton, QTableWidget

    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog, LoadOrderProductDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Transporte Multi Destino")
    Driver.create(name="Chofer Multi Destino", carrier=carrier)
    Truck.create(domain="MD123AA", carrier=carrier)
    product = Product.create(name="Producto Multi Destino", unit="kg")
    client_a = Client.create(name="Cliente Multi A", cuit="30712345011", iva_condition="RI")
    address_a = ClientAddress.create(
        client=client_a,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Multi A",
    )
    client_b = Client.create(name="Cliente Multi B", cuit="30712345012", iva_condition="RI")
    address_b = ClientAddress.create(
        client=client_b,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Ruta Multi B",
    )

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_multi_dest"), "ui_multi_dest")
    app.processEvents()

    _set_combo(dialog.findChild(QComboBox, "loadOrderClientInput"), client_a.id)
    _set_combo(dialog.findChild(QComboBox, "loadOrderAddressInput"), address_a.id)
    dialog.findChild(QPushButton, "addLoadOrderClientButton").click()

    _set_combo(dialog.findChild(QComboBox, "loadOrderClientInput"), client_b.id)
    _set_combo(dialog.findChild(QComboBox, "loadOrderAddressInput"), address_b.id)
    dialog.findChild(QPushButton, "addLoadOrderClientButton").click()
    app.processEvents()

    destination_table = dialog.findChild(QTableWidget, "loadOrderDestinationDraftTable")
    assert destination_table.currentRow() == 1

    def accept_product(product_dialog):
        product_dialog.product = {
            "product_id": product.id,
            "product_label": product.name,
            "quantity": 50,
            "unit": product.unit,
        }
        return QDialog.Accepted

    monkeypatch.setattr(LoadOrderProductDialog, "exec_", accept_product)
    dialog.findChild(QPushButton, "addLoadOrderProductButton").click()
    app.processEvents()

    assert dialog.destinations[0]["products"] == []
    assert len(dialog.destinations[1]["products"]) == 1


def test_product_dialog_prefills_price_from_client_price_list(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QDoubleSpinBox

    from app.models.masters import Client, Product
    from app.ui.desktop_app import LoadOrderProductDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente Lista UI", cuit="30700001001", iva_condition="RI", lista_precios=3)
    product = Product.create(
        name="Producto Lista UI",
        unit="kg",
        precio_lista_1=100.0,
        precio_lista_2=120.0,
        precio_lista_3=140.0,
        precio_lista_4=160.0,
    )

    dialog = LoadOrderProductDialog(client=client)
    app.processEvents()
    _set_combo(dialog.findChild(QComboBox, "productDialogProductInput"), product.id)
    app.processEvents()

    assert dialog.findChild(QDoubleSpinBox, "productDialogPrecioInput").value() == 140.0


def test_load_order_dialog_layout_keeps_work_sections_readable(db):
    from PyQt5.QtWidgets import QApplication, QPushButton, QStackedWidget, QTableWidget, QWidget

    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue89"), "ui_issue89")
    app.processEvents()

    assert dialog.minimumWidth() >= 980
    # Issue #131: el alto minimo bajo de 760 a 600 para que el dialogo entre
    # en pantallas chicas; el QScrollArea central absorbe el overflow.
    assert 600 <= dialog.minimumHeight() < 760
    steps = dialog.findChild(QWidget, "loadOrderEntryStepList")
    stack = dialog.findChild(QStackedWidget, "loadOrderEntryStepStack")
    step_buttons = [dialog.findChild(QPushButton, f"loadOrderStepButton{index}") for index in range(5)]
    previous_button = dialog.findChild(QPushButton, "previousLoadOrderStepButton")
    next_button = dialog.findChild(QPushButton, "nextLoadOrderStepButton")
    assert steps is not None
    assert stack is not None
    assert steps.maximumWidth() <= 190
    assert [button.text() for button in step_buttons] == [
        "1  Transporte",
        "2  Destinos",
        "3  Productos",
        "4  Pallets",
        "5  Revisar",
    ]
    assert all(button.property("stepNav") is True for button in step_buttons)
    assert step_buttons[0].isChecked() is True
    assert stack.count() == 5
    assert previous_button.isEnabled() is False
    assert next_button.isEnabled() is True
    next_button.click()
    app.processEvents()
    assert step_buttons[1].isChecked() is True
    assert stack.currentIndex() == 1
    assert previous_button.isEnabled() is True
    assert dialog.findChild(QTableWidget, "loadOrderDestinationDraftTable").minimumHeight() >= 180
    assert dialog.findChild(QTableWidget, "loadOrderProductDraftTable").minimumHeight() >= 160
    assert dialog.findChild(QTableWidget, "loadOrderReviewTable") is not None


def test_load_order_dialog_keeps_save_and_cancel_visible_at_minimum_height(db):
    """Issue #131: en pantallas de ~720px de alto util el dialogo no debe
    recortar los botones Guardar/Cancelar del pie del formulario."""
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue131"), "ui_issue131")
    dialog.resize(1100, dialog.minimumHeight())
    app.processEvents()

    save_button = dialog.findChild(QPushButton, "saveLoadOrderButton")
    cancel_button = dialog.findChild(QPushButton, "cancelLoadOrderButton")
    assert save_button is not None
    assert cancel_button is not None

    dialog_height = dialog.height()
    save_bottom = save_button.mapToParent(save_button.rect().bottomLeft()).y()
    cancel_bottom = cancel_button.mapToParent(cancel_button.rect().bottomLeft()).y()
    assert save_bottom <= dialog_height, (
        f"El boton Guardar se sale del dialogo: bottom={save_bottom}, "
        f"dialog_height={dialog_height}"
    )
    assert cancel_bottom <= dialog_height, (
        f"El boton Cancelar se sale del dialogo: bottom={cancel_bottom}, "
        f"dialog_height={dialog_height}"
    )


def test_load_order_dialog_initial_height_fits_client_monitor(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue137"), "ui_issue137")
    app.processEvents()

    assert dialog.height() <= 680


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
    from PyQt5.QtWidgets import QApplication, QComboBox, QLabel

    from app.models.masters import Driver
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    driver = Driver.create(name="Chofer Sin Transporte", carrier=None, cuit="20123456783")

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue65"), "ui_issue65")
    app.processEvents()

    driver_combo = dialog.findChild(QComboBox, "loadOrderDriverInput")
    carrier_combo = dialog.findChild(QComboBox, "loadOrderCarrierInput")
    truck_combo = dialog.findChild(QComboBox, "loadOrderTruckInput")
    feedback = dialog.findChild(QLabel, "loadOrderDialogFeedback")

    _set_combo(driver_combo, driver.id)
    app.processEvents()

    assert carrier_combo.currentData() is None
    assert truck_combo.count() == 1
    assert feedback.text() == "El chofer seleccionado no tiene transportista asociado."


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
    _complete_order_for_issue(order, user.username)
    monkeypatch.setattr("app.ui.desktop_app.LOAD_ORDER_PRINTS_DIR", tmp_path)
    opened_outputs = []
    monkeypatch.setattr("app.ui.desktop_app._open_print_output", lambda path: opened_outputs.append(path))

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    table = window.findChild(QTableWidget, "loadOrdersTable")
    feedback = window.findChild(QLabel, "loadOrderFeedback")
    table.setCurrentCell(0, 0)

    headers = [table.horizontalHeaderItem(column).text() for column in range(table.columnCount())]
    assert "Camión / patente" in headers
    truck_column = headers.index("Camión / patente")
    assert table.item(0, truck_column).text() == "UI123AA"

    window.findChild(QPushButton, "issueLoadOrderButton").click()
    app.processEvents()
    assert LoadOrder.get_by_id(order.id).status == LoadOrder.STATUS_ISSUED
    assert "emitida" in feedback.text().lower()
    assert table.cellWidget(1, 0).property("detailLabels")["status"].text() == "Emitida"
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
    assert table.cellWidget(1, 0).property("detailLabels")["status"].text() == "Anulada"
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


def test_load_order_detail_panel_keeps_long_summary_readable(db):
    from PyQt5.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QScrollArea, QTableWidget

    from app.models.load_orders import LoadOrder
    from app.models.security import User, UserProfile
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow, LoadOrderDetailDialog

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_detail_readable_ui", password_hash="x", profile=profile)
    carrier = Carrier.create(name="ISSUE169 Transportista Norte con nombre largo")
    driver = Driver.create(name="ISSUE169 Chofer Demo con nombre largo", carrier=carrier)
    truck = Truck.create(domain="I69ABC", carrier=carrier)
    client = Client.create(name="ISSUE169 Cliente Norte con nombre largo", cuit="30700016901", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 14 kilometro 169 acceso norte",
    )
    product = Product.create(name="ISSUE169 Producto forestal con descripcion larga", unit="kg")
    product_b = Product.create(name="ISSUE169 Segundo producto", unit="bolsas")
    LoadOrderService(current_user=user.username).create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [{"product": product, "quantity": 42}, {"product": product_b, "quantity": 7}],
            }
        ],
        pallets=[],
    )

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    window.findChild(QTableWidget, "loadOrdersTable").setCurrentCell(0, 0)
    app.processEvents()

    metrics = window.findChild(QLabel, "loadOrderMetricsStrip")
    table = window.findChild(QTableWidget, "loadOrdersTable")
    panel = window.findChild(QFrame, "loadOrderInlineDetailPanel")
    button = window.findChild(QPushButton, "viewLoadOrderDetailButton")
    labels: dict[str, QLabel] = panel.property("detailLabels")

    assert window.findChild(QScrollArea, "loadOrderKpiScroll") is None
    assert "Pendientes: " in metrics.text()
    assert "Emitidas hoy: " in metrics.text()
    assert table.rowCount() == 2
    assert table.cellWidget(1, 0) is panel
    assert table.rowSpan(1, 0) == 1
    assert table.columnSpan(1, 0) == table.columnCount()
    assert button.isEnabled() is True
    assert not button.icon().isNull()
    assert not window.findChild(QPushButton, "newLoadOrderButton").icon().isNull()
    assert labels["summary"].wordWrap() is True
    assert labels["transport"].wordWrap() is True
    assert "ISSUE169 Cliente Norte" in labels["summary"].text()
    assert "Posadas" in labels["summary"].text()
    assert "ISSUE169 Chofer Demo" in labels["transport"].text()

    dialog = LoadOrderDetailDialog(LoadOrder.select().first(), window)
    detail_table = dialog.findChild(QTableWidget, "loadOrderDetailItemsTable")
    assert dialog.findChild(QLabel, "detailOrderNumber").text() == "OC-000001"
    assert detail_table.rowCount() == 2
    assert [detail_table.horizontalHeaderItem(i).text() for i in range(detail_table.columnCount())] == [
        "Cliente",
        "Destino",
        "Producto",
        "Cantidad",
        "Unidad",
    ]
    assert detail_table.item(0, 2).text() == "ISSUE169 Producto forestal con descripcion larga"
    assert detail_table.item(1, 2).text() == "ISSUE169 Segundo producto"


def test_load_order_page_opens_combined_budget_pdf_for_all_clients(db, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QTableWidget

    from app.models.security import User, UserProfile
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_budget_all_ui", password_hash="x", profile=profile)
    carrier = Carrier.create(name="Transporte Budget UI")
    driver = Driver.create(name="Chofer Budget UI", carrier=carrier)
    truck = Truck.create(domain="BUD123", carrier=carrier)
    product_a = Product.create(name="Producto Budget A", unit="kg")
    product_b = Product.create(name="Producto Budget B", unit="bolsas")
    client_a = Client.create(name="Cliente Budget A", cuit="30700018801", iva_condition="RI")
    address_a = ClientAddress.create(
        client=client_a,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Budget A",
    )
    client_b = Client.create(name="Cliente Budget B", cuit="30700018802", iva_condition="RI")
    address_b = ClientAddress.create(
        client=client_b,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Ruta Budget B",
    )
    LoadOrderService(current_user=user.username).create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {"client": client_a, "delivery_address": address_a, "products": [{"product": product_a, "quantity": 10}]},
            {"client": client_b, "delivery_address": address_b, "products": [{"product": product_b, "quantity": 20}]},
        ],
        pallets=[],
    )
    monkeypatch.setattr("app.ui.desktop_app.LOAD_ORDER_PRINTS_DIR", tmp_path)
    opened_outputs = []
    monkeypatch.setattr("app.ui.desktop_app._open_print_output", lambda path: opened_outputs.append(path))

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    window.findChild(QTableWidget, "loadOrdersTable").setCurrentCell(0, 0)
    window.findChild(QPushButton, "budgetLoadOrderButton").click()
    app.processEvents()

    budget_paths = sorted(tmp_path.glob("presupuestos_orden_*.pdf"))
    feedback = window.findChild(QLabel, "loadOrderFeedback").text()

    assert len(budget_paths) == 1
    assert opened_outputs == budget_paths
    assert "presupuestos_orden_1_" in feedback


def test_load_order_page_refreshes_detail_selection_before_budgeting(db, tmp_path, monkeypatch):
    from pypdf import PdfReader
    from PyQt5.QtWidgets import QApplication, QPushButton, QTableWidget

    from app.models.security import User, UserProfile
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_budget_selection_ui", password_hash="x", profile=profile)
    carrier = Carrier.create(name="Transporte Selection UI")
    driver_a = Driver.create(name="Chofer Selection A", carrier=carrier)
    driver_b = Driver.create(name="Chofer Selection B", carrier=carrier)
    truck_a = Truck.create(domain="SEL123A", carrier=carrier)
    truck_b = Truck.create(domain="SEL123B", carrier=carrier)
    product = Product.create(name="Producto Selection", unit="kg")
    client_a = Client.create(name="Cliente Selection A", cuit="30700028801", iva_condition="RI")
    address_a = ClientAddress.create(
        client=client_a,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta Selection A",
    )
    client_b = Client.create(name="Cliente Selection B", cuit="30700028802", iva_condition="RI")
    address_b = ClientAddress.create(
        client=client_b,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Ruta Selection B",
    )
    client_c = Client.create(name="Cliente Selection C", cuit="30700028803", iva_condition="RI")
    address_c = ClientAddress.create(
        client=client_c,
        address_type="entrega",
        province="Misiones",
        city="Eldorado",
        address="Ruta Selection C",
    )
    service = LoadOrderService(current_user=user.username)
    first_order = service.create_order(
        carrier=carrier,
        driver=driver_a,
        truck=truck_a,
        destinations=[{"client": client_a, "delivery_address": address_a, "products": [{"product": product, "quantity": 1}]}],
        pallets=[],
    )
    second_order = service.create_order(
        carrier=carrier,
        driver=driver_b,
        truck=truck_b,
        destinations=[
            {"client": client_b, "delivery_address": address_b, "products": [{"product": product, "quantity": 2}]},
            {"client": client_c, "delivery_address": address_c, "products": [{"product": product, "quantity": 3}]},
        ],
        pallets=[],
    )
    monkeypatch.setattr("app.ui.desktop_app.LOAD_ORDER_PRINTS_DIR", tmp_path)
    opened_outputs = []
    monkeypatch.setattr("app.ui.desktop_app._open_print_output", lambda path: opened_outputs.append(path))

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    table = window.findChild(QTableWidget, "loadOrdersTable")

    assert table.item(0, 0).data(256) == second_order.id
    assert table.cellWidget(1, 0).property("detailLabels")["number"].text() == "OC-000002"

    table.setCurrentCell(2, 0)
    app.processEvents()

    assert table.item(1, 0).data(256) == first_order.id
    assert table.cellWidget(2, 0).property("detailLabels")["number"].text() == "OC-000001"

    table.setCurrentCell(0, 0)
    app.processEvents()
    window.findChild(QPushButton, "budgetLoadOrderButton").click()
    app.processEvents()

    assert len(opened_outputs) == 1
    reader = PdfReader(str(opened_outputs[0]))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Cliente Selection B" in text
    assert "Cliente Selection C" in text


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
    _complete_order_for_issue(order, user.username)
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


def test_load_order_page_treats_legacy_unissued_status_as_actionable(db):
    from PyQt5.QtWidgets import QApplication, QPushButton, QTableWidget

    from app.models.load_orders import LoadOrder
    from app.models.security import User, UserProfile
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_legacy_draft_ui", password_hash="x", profile=profile)
    carrier = Carrier.create(name="Transporte No Emitida UI")
    driver = Driver.create(name="Chofer No Emitida UI", carrier=carrier)
    truck = Truck.create(domain="BOR123", carrier=carrier)
    client = Client.create(name="Cliente No Emitida UI", cuit="30700008830", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta No Emitida",
    )
    product = Product.create(name="Producto No Emitida UI", unit="kg")
    order = LoadOrderService(current_user=user.username).create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[{"client": client, "delivery_address": address, "products": [{"product": product, "quantity": 1}]}],
        pallets=[],
    )
    order.status = "Preparacion"
    order.save()

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    window.findChild(QTableWidget, "loadOrdersTable").setCurrentCell(0, 0)
    app.processEvents()

    assert window.findChild(QPushButton, "issueLoadOrderButton").isEnabled() is True
    assert window.findChild(QPushButton, "editLoadOrderButton").isEnabled() is True


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
    _complete_order_for_issue(order, user.username)
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
    assert table.rowCount() == 3

    search_input.setText("Norte")
    search_button.click()
    app.processEvents()

    assert table.rowCount() == 2
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
def test_load_order_dialog_shows_feedback_when_driver_has_inactive_carrier(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QLabel

    from app.models.masters import Carrier, Driver, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Transporte Inactivo UI", active=False)
    driver = Driver.create(name="Chofer Carrier Inactivo", carrier=carrier)
    Truck.create(domain="INACTIVO", carrier=carrier)

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue98"), "ui_issue98")
    app.processEvents()

    driver_combo = dialog.findChild(QComboBox, "loadOrderDriverInput")
    carrier_combo = dialog.findChild(QComboBox, "loadOrderCarrierInput")
    truck_combo = dialog.findChild(QComboBox, "loadOrderTruckInput")
    _set_combo(driver_combo, driver.id)
    app.processEvents()

    assert carrier_combo.currentData() is None
    assert truck_combo.currentData() is None
    feedback = dialog.findChild(QLabel, "loadOrderDialogFeedback")
    assert "inactivo" in feedback.text()


def test_load_order_dialog_shows_feedback_when_no_compatible_trucks(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QLabel

    from app.models.masters import Carrier, Driver
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Transporte Sin Camion UI", active=True)
    driver = Driver.create(name="Chofer Sin Camion", carrier=carrier)

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue98"), "ui_issue98")
    app.processEvents()

    driver_combo = dialog.findChild(QComboBox, "loadOrderDriverInput")
    carrier_combo = dialog.findChild(QComboBox, "loadOrderCarrierInput")
    truck_combo = dialog.findChild(QComboBox, "loadOrderTruckInput")
    _set_combo(driver_combo, driver.id)
    app.processEvents()

    assert carrier_combo.currentData() == carrier.id
    assert truck_combo.currentData() is None
    feedback = dialog.findChild(QLabel, "loadOrderDialogFeedback")
    assert "camiones" in feedback.text()


def test_load_order_dialog_auto_selects_single_compatible_truck(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Carrier, Driver, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Transporte Unico Truck UI", active=True)
    driver = Driver.create(name="Chofer Unico Truck", carrier=carrier)
    truck = Truck.create(domain="UNICO", carrier=carrier)

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="ui_issue98"), "ui_issue98")
    app.processEvents()

    driver_combo = dialog.findChild(QComboBox, "loadOrderDriverInput")
    truck_combo = dialog.findChild(QComboBox, "loadOrderTruckInput")
    _set_combo(driver_combo, driver.id)
    app.processEvents()

    assert truck_combo.currentData() == truck.id
