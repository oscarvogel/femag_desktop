import subprocess
import sys


def test_menu_filters_items_by_permission(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.menu import build_menu

    PermissionService().seed_defaults()
    viewer = AuthService().create_user("consulta", "clave", "Solo consulta")

    menu = build_menu(viewer)

    assert "Sistema" not in [section.title for section in menu if section.items]
    assert any(item.title == "Clientes" for section in menu for item in section.items)


def test_dashboard_counts_and_future_placeholder(db):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService
    from app.ui.dashboard import DashboardService, future_module_message

    Client.create(name="Cliente", cuit="30222222229", iva_condition="RI")
    Product.create(name="Fecula", unit="kg")
    client = Client.create(name="Cliente orden", cuit="30333333339", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12",
    )
    product = Product.create(name="Almidon", unit="kg")
    carrier = Carrier.create(name="Transporte Norte")
    driver = Driver.create(name="Juan Perez")
    truck = Truck.create(domain="AB123CD", carrier=carrier)
    LoadOrderService(current_user="admin").create_order(
        client=client,
        delivery_address=address,
        carrier=carrier,
        driver=driver,
        truck=truck,
        products=[{"product": product, "quantity": 100}],
        pallets=[],
    )

    summary = DashboardService().summary()

    assert summary["clientes"] == 2
    assert summary["productos"] == 2
    assert summary["ordenes_hoy"] == 1
    assert summary["ordenes_pendientes"] == 1
    assert summary["choferes_bloqueados"] == 1
    assert summary["acceso_rapido_nueva_orden"] == "Nueva orden de carga"
    assert future_module_message() == "Funcionalidad prevista para una próxima entrega."


def test_menu_marks_load_orders_as_real_module(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.menu import build_menu

    PermissionService().seed_defaults()
    user = AuthService().create_user("secretaria", "clave", "Secretaria")

    load_order_item = next(
        item
        for section in build_menu(user)
        for item in section.items
        if item.title == "Órdenes de carga"
    )
    f150_item = next(
        item
        for section in build_menu(user)
        for item in section.items
        if item.title == "F150"
    )

    assert load_order_item.placeholder is False
    assert f150_item.placeholder is True


def test_app_smoke_command_runs():
    completed = subprocess.run(
        [sys.executable, "-m", "app.main", "--smoke"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "FEMAG smoke OK" in completed.stdout


def test_desktop_load_orders_page_is_functional_and_data_backed(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QTableWidget

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.auth_service import AuthService
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    PermissionService().seed_defaults()
    user = AuthService().create_user("operador_ui", "clave", "Administrador")
    client = Client.create(name="Cliente UI", cuit="30999999991", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12 km 7",
        is_primary=True,
    )
    carrier = Carrier.create(name="Transporte UI")
    driver = Driver.create(name="Chofer UI")
    truck = Truck.create(domain="UI123AA", carrier=carrier)
    product = Product.create(name="Fecula UI", unit="kg")
    LoadOrderService(current_user="admin").create_order(
        client=client,
        delivery_address=address,
        carrier=carrier,
        driver=driver,
        truck=truck,
        products=[{"product": product, "quantity": 500}],
        pallets=[],
    )

    app = QApplication.instance() or QApplication([])
    window = FemagDesktopWindow(user=user, demo_mode=True)
    page = window.findChild(type(window.stack), None).widget(window._route_indexes["load_orders"])
    table = page.findChild(QTableWidget, "loadOrdersTable")
    detail = page.findChild(QLabel, "detailOrderNumber")
    buttons = {button.objectName() for button in page.findChildren(QPushButton)}

    assert app is not None
    assert table.rowCount() == 1
    assert table.item(0, 2).text() == "Cliente UI"
    assert table.item(0, 4).text() == "Fecula UI"
    assert table.item(0, 7).text() == "Transporte UI"
    assert detail.text() == table.item(0, 0).text()
    assert {
        "newLoadOrderButton",
        "editLoadOrderButton",
        "issueLoadOrderButton",
        "printLoadOrderButton",
        "annulLoadOrderButton",
        "searchLoadOrderButton",
        "detailEditButton",
        "detailHistoryButton",
    } <= buttons
