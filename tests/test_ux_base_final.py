from pathlib import Path

from peewee import SqliteDatabase


def test_main_shell_spec_has_professional_daily_use_layout(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.main_window import MainWindow

    PermissionService().seed_defaults()
    user = AuthService().create_user("operador", "clave", "Administrador")

    shell = MainWindow(user=user, demo_mode=True).shell_spec

    assert shell.app_name == "FEMAG Desktop"
    assert shell.subtitle == "Gestión operativa local"
    assert shell.username == "operador"
    assert shell.profile == "Administrador"
    assert shell.connection_state == "Modo demo"
    assert shell.sidebar is not None
    assert shell.status_bar.last_backup
    assert shell.dashboard.title == "Dashboard operativo"


def test_sidebar_tree_uses_menu_service_permissions_and_friendly_placeholders(db):
    from app.services.auth_service import AuthService
    from app.services.menu_service import PLACEHOLDER_MESSAGE
    from app.services.permission_service import PermissionService
    from app.ui.menu import build_sidebar_tree_spec

    PermissionService().seed_defaults()
    user = AuthService().create_user("secretaria_ux", "clave", "Secretaria")

    sidebar = build_sidebar_tree_spec(user)
    sections = {section.title: section for section in sidebar.sections}
    modules = [item.title for section in sidebar.sections for item in section.items]
    operations = sections["Operaciones"].items
    load_orders = next(item for item in operations if item.title == "Órdenes de carga")
    f150 = next(item for item in operations if item.title == "F150")

    assert sidebar.active_route == "dashboard"
    assert modules == [
        "Dashboard",
        "Órdenes de carga",
        "Remitos",
        "F150",
        "Clientes",
        "Choferes",
        "Transportistas",
        "Productos",
        "Cuenta corriente",
        "Reportes",
        "Configuración",
    ]
    assert load_orders.route_key == "load_orders"
    assert load_orders.placeholder is False
    assert f150.placeholder is True
    assert f150.disabled_reason == PLACEHOLDER_MESSAGE
    assert "Sistema" not in sections


def test_dashboard_view_spec_groups_actions_cards_and_alerts(db):
    from app.ui.dashboard import DashboardService, future_module_message

    dashboard = DashboardService().view_spec(demo_mode=True)

    assert [action.title for action in dashboard.quick_actions][:3] == [
        "Nueva orden de carga",
        "Buscar orden",
        "Nuevo cliente",
    ]
    assert any(action.title == "F150" and action.message == future_module_message() for action in dashboard.quick_actions)
    assert "Órdenes creadas hoy" in dashboard.summary_cards
    assert "Choferes ocupados" in dashboard.summary_cards
    assert any("Modo demo" in alert for alert in dashboard.alerts)


def test_master_abm_specs_cover_required_entities_with_visible_labels():
    from app.ui.abm import build_master_abm_specs

    specs = {spec.title: spec for spec in build_master_abm_specs()}

    assert set(specs) == {"Clientes", "Productos", "Choferes", "Transportistas", "Camiones", "Tipos de pallets"}
    for spec in specs.values():
        assert spec.library == "pyqt5libs"
        assert spec.search_placeholder.startswith("Buscar en ")
        assert spec.empty_message.startswith("No hay registros")
        assert "Estado" in spec.fields
        assert spec.table_columns


def test_load_order_form_spec_matches_operational_sections():
    from app.ui.load_orders import build_load_order_form_spec, build_load_order_workspace_spec

    spec = build_load_order_form_spec()
    workspace = build_load_order_workspace_spec()

    assert [section.title for section in spec.sections] == ["Datos de la carga", "Transporte"]
    assert "Cliente / destinatario" in spec.detail_columns
    assert "Bolsas x 25 kg" in spec.detail_columns
    assert "Guardar e imprimir" in spec.primary_actions
    assert spec.driver_status_messages["blocked"] == "El chofer seleccionado ya tiene una carga activa."
    assert workspace.title == "Órdenes de carga"
    assert workspace.subtitle == "Gestione y controle las órdenes de carga del sistema"
    assert workspace.kpis == ("Pendientes", "Emitidas hoy", "Camiones en carga", "Entregas del día")
    assert workspace.toolbar_actions == ("Nuevo", "Editar", "Emitir", "Imprimir", "Anular", "Buscar")
    assert workspace.table_columns == (
        "N° orden",
        "Fecha",
        "Cliente",
        "Entrega",
        "Producto",
        "Pallets",
        "Chofer",
        "Transportista",
        "Estado",
    )
    assert "Dirección de entrega" in workspace.detail_fields
    assert "Camión / Acoplado" in workspace.detail_fields


def test_seed_demo_data_is_idempotent_and_creates_realistic_order(tmp_path):
    from app.config.database import bind_database
    from app.models.load_orders import LoadOrder, LoadOrderProduct
    from app.models.masters import Client, Driver, Product, Truck
    from scripts.seed_demo_data import DEMO_ORDER_NUMBER, seed_demo_data

    db_path = tmp_path / "demo.sqlite3"
    seed_demo_data(db_path)
    seed_demo_data(db_path)
    database = SqliteDatabase(db_path)
    bind_database(database)
    database.connect(reuse_if_open=True)

    assert Client.select().count() == 7
    assert Product.select().count() == 5
    assert Truck.get().domain == "RIA609 / CIE907"
    assert Driver.get(Driver.name == "GLIENKE EZEQUIEL").available is False
    assert LoadOrder.select().where(LoadOrder.order_number == DEMO_ORDER_NUMBER).count() == 1
    assert LoadOrderProduct.select().count() >= 4
    database.close()


def test_generate_ux_screenshots_creates_expected_pngs(tmp_path):
    from scripts.generate_ux_screenshots import generate_screenshots

    paths = generate_screenshots(tmp_path, db_path=tmp_path / "screenshots.sqlite3")

    assert len(paths) >= 4
    assert all(Path(path).exists() for path in paths)
    assert any(path.name == "02_dashboard_datos_demo.png" for path in paths)
    assert any(path.name == "08_ordenes_carga_variacion_a.png" for path in paths)
    assert any(path.name == "09_panel_detalle_orden.png" for path in paths)
    assert any(path.name == "12_placeholder_f150.png" for path in paths)


def test_run_desktop_app_without_demo_does_not_seed_uninitialized_database(monkeypatch):
    import app.ui.desktop_app as desktop_app

    class NoDatabasePermissionService:
        def seed_defaults(self):
            raise AssertionError("No debe sembrar permisos sin base inicializada.")

    class FakeApplication:
        def __init__(self, args):
            self.args = args

        @staticmethod
        def instance():
            return None

        def exec_(self):
            return 0

    class FakeWindow:
        def __init__(self, *, user, demo_mode):
            self.user = user
            self.demo_mode = demo_mode

        def show(self):
            return None

    monkeypatch.setattr(desktop_app, "PermissionService", NoDatabasePermissionService)
    monkeypatch.setattr(desktop_app, "QApplication", FakeApplication)
    monkeypatch.setattr(desktop_app, "FemagDesktopWindow", FakeWindow)
    monkeypatch.setattr(desktop_app, "_prepare_database", lambda *, demo_mode: None)

    assert desktop_app.run_desktop_app(demo_mode=False) == 0
