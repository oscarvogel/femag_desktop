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
    driver = Driver.create(name="Juan Perez", carrier=carrier)
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
    remittance_item = next(
        item for section in build_menu(user) for item in section.items if item.title == "Remitos"
    )
    summary_item = next(
        item
        for section in build_menu(user)
        for item in section.items
        if item.title == "Hoja resumen / sobre de carga"
    )

    assert load_order_item.placeholder is False
    assert remittance_item.placeholder is True
    assert summary_item.placeholder is True


def test_sidebar_spec_groups_transport_abms(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.menu import build_sidebar_tree_spec

    PermissionService().seed_defaults()
    user = AuthService().create_user("admin_transport_menu", "clave", "Administrador")

    principal = build_sidebar_tree_spec(user).sections[0]
    transport = next(item for item in principal.items if item.title == "Transporte")

    assert [child.title for child in transport.children] == ["Transportistas", "Choferes", "Camiones"]
    assert [child.route_key for child in transport.children] == ["carriers", "drivers", "trucks"]
    assert "Choferes" not in [item.title for item in principal.items]
    assert "Transportistas" not in [item.title for item in principal.items]
    assert "Camiones" not in [item.title for item in principal.items]


def test_sidebar_spec_exposes_legacy_dbf_import_page(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.menu import build_sidebar_tree_spec

    PermissionService().seed_defaults()
    user = AuthService().create_user("admin_import_menu", "clave", "Administrador")

    principal = build_sidebar_tree_spec(user).sections[0]
    import_item = next(item for item in principal.items if item.title == "Importación DBF")

    assert import_item.placeholder is False
    assert import_item.route_key == "legacy_dbf_import"


def test_app_smoke_command_runs():
    completed = subprocess.run(
        [sys.executable, "-m", "app.main", "--smoke"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "FEMAG smoke OK" in completed.stdout


def test_global_styles_include_polished_combo_controls():
    from app.ui.desktop_app import STYLES

    assert "QComboBox" in STYLES
    assert "QComboBox::drop-down" in STYLES
    assert "chevron-down.svg" in STYLES
    assert "QComboBox QAbstractItemView" in STYLES
    assert "QDateEdit" in STYLES


def test_global_styles_include_polished_form_controls():
    from app.ui.desktop_app import STYLES

    assert "QLineEdit" in STYLES
    assert "QTextEdit" in STYLES
    assert "QPlainTextEdit" in STYLES
    assert "QSpinBox" in STYLES
    assert "QDoubleSpinBox" in STYLES
    assert "QSpinBox::up-button" in STYLES
    assert "QDoubleSpinBox::down-button" in STYLES


def test_app_ui_flag_runs_ui_launcher(monkeypatch):
    from app import main as app_main

    calls = []

    def fake_run_ui(*, demo_mode: bool = False) -> int:
        calls.append(demo_mode)
        return 0

    monkeypatch.setattr(app_main, "run_ui", fake_run_ui)

    assert app_main.main(["--ui"]) == 0
    assert calls == [False]


def test_app_demo_ui_flag_runs_ui_launcher_with_demo_data(monkeypatch):
    from app import main as app_main

    calls = []

    def fake_run_ui(*, demo_mode: bool = False) -> int:
        calls.append(demo_mode)
        return 0

    monkeypatch.setattr(app_main, "run_ui", fake_run_ui)

    assert app_main.main(["--demo-ui"]) == 0
    assert calls == [True]


def test_app_ui_flag_reports_launch_error(monkeypatch, capsys):
    from app import main as app_main

    def fake_run_ui(*, demo_mode: bool = False) -> int:
        raise RuntimeError("PyQt5 no esta instalado")

    monkeypatch.setattr(app_main, "run_ui", fake_run_ui)

    assert app_main.main(["--ui"]) == 1
    captured = capsys.readouterr()
    assert "No se pudo abrir FEMAG Desktop UI" in captured.err
    assert "PyQt5 no esta instalado" in captured.err


def test_runtime_ui_prepares_schema_for_existing_local_database(tmp_path, monkeypatch):
    from peewee import SqliteDatabase

    from app.config.database import bind_database
    from app.ui import desktop_app

    database_path = tmp_path / "runtime.sqlite3"
    database = SqliteDatabase(str(database_path), pragmas={"foreign_keys": 1})
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.execute_sql(
        """
        CREATE TABLE client (
            id INTEGER PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            cuit VARCHAR(255) NOT NULL,
            iva_condition VARCHAR(255) NOT NULL,
            active BOOL DEFAULT 1,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    database.execute_sql(
        """
        CREATE TABLE clientaddress (
            id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL,
            address_type VARCHAR(255) NOT NULL,
            province VARCHAR(255) NOT NULL,
            city VARCHAR(255) NOT NULL,
            address VARCHAR(255) NOT NULL,
            is_primary BOOL DEFAULT 0,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    database.close()

    def fake_initialize_runtime_database():
        runtime_database = SqliteDatabase(str(database_path), pragmas={"foreign_keys": 1})
        bind_database(runtime_database)
        return runtime_database

    monkeypatch.setattr(desktop_app, "initialize_runtime_database", fake_initialize_runtime_database)

    prepared = desktop_app._prepare_database(demo_mode=False)

    try:
        column_names = {column.name for column in prepared.get_columns("clientaddress")}
        assert "active" in column_names
    finally:
        if prepared is not None and not prepared.is_closed():
            prepared.close()
