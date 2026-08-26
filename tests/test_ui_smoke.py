
    assert load_order_item.placeholder is False
    assert remittance_item.placeholder is False
    assert summary_item.placeholder is True


def test_sidebar_spec_groups_operations_and_masters(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.menu import build_sidebar_tree_spec

    PermissionService().seed_defaults()
    user = AuthService().create_user("admin_transport_menu", "clave", "Administrador")

    principal = build_sidebar_tree_spec(user).sections[0]
    operations = next(item for item in principal.items if item.title == "Operaciones")
    masters = next(item for item in principal.items if item.title == "Maestros")

    assert [child.title for child in operations.children] == ["Órdenes de carga", "Remitos", "F150"]
    assert [child.route_key for child in operations.children] == ["load_orders", "remittances", "placeholder"]
    assert [child.title for child in masters.children] == [
        "Clientes",
        "Productos",
        "Precios por lista",
        "Tipos de IVA",
        "Transportistas",
        "Choferes",
        "Camiones",
    ]
    assert [child.route_key for child in masters.children] == [
        "clients",
        "products",
        "product_price_bulk",
        "vat_types",
        "carriers",
        "drivers",
        "trucks",
    ]


def test_sidebar_accordion_keeps_only_one_group_expanded(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_sidebar_accordion", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)

    window._toggle_sidebar_group("Operaciones")
    assert window._expanded_sidebar_groups == {"Operaciones"}
    window._toggle_sidebar_group("Maestros")
    app.processEvents()

    assert window._expanded_sidebar_groups == {"Maestros"}


def test_sidebar_spec_exposes_vat_types_crud(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.menu import build_sidebar_tree_spec

    PermissionService().seed_defaults()
    user = AuthService().create_user("admin_vat_types_menu", "clave", "Administrador")

    principal = build_sidebar_tree_spec(user).sections[0]
    masters = next(item for item in principal.items if item.title == "Maestros")
    vat_types = next(item for item in masters.children if item.title == "Tipos de IVA")

    assert vat_types.placeholder is False
    assert vat_types.route_key == "vat_types"


def test_sidebar_spec_exposes_legacy_dbf_import_page(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.menu import build_sidebar_tree_spec

    PermissionService().seed_defaults()
    user = AuthService().create_user("admin_import_menu", "clave", "Administrador")

    principal = build_sidebar_tree_spec(user).sections[0]
    system = next(item for item in principal.items if item.title == "Sistema")
    import_item = next(item for item in system.children if item.title == "Importación DBF")

    assert import_item.placeholder is False
    assert import_item.route_key == "legacy_dbf_import"


def test_admin_sidebar_exposes_remittance_numbering_configuration(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.menu import build_sidebar_tree_spec

    PermissionService().seed_defaults()
    user = AuthService().create_user("admin_remittance_config", "clave", "Administrador")

    principal = build_sidebar_tree_spec(user).sections[0]
    system = next(item for item in principal.items if item.title == "Sistema")
    config = next(item for item in system.children if item.title == "Configuración")

    assert config.placeholder is False
    assert config.route_key == "remittance_series"


def test_sidebar_places_customer_ledger_after_managerial_block(db):
    from app.services.auth_service import AuthService
    from app.services.menu_service import set_managerial_dashboard_menu_enabled
    from app.services.permission_service import PermissionService
    from app.ui.menu import build_sidebar_tree_spec

    PermissionService().seed_defaults()
    user = AuthService().create_user("admin_sidebar_order", "clave", "Administrador")

    set_managerial_dashboard_menu_enabled(True)
    try:
        principal = build_sidebar_tree_spec(user).sections[0]
        titles = [item.title for item in principal.items]
        managerial = next(item for item in principal.items if item.title == "Dashboard Gerencial")

        assert [child.title for child in managerial.children] == [
            "Resumen gerencial",
            "Ventas y despachos",
            "Cuenta corriente y deuda vencida",
        ]
        assert [child.route_key for child in managerial.children] == [
            "managerial_dashboard",
            "managerial_sales_dispatch",
            "managerial_account_risk",
        ]
        assert titles.index("Cuenta corriente") == titles.index("Maestros") + 1
        assert titles.index("Avisos") == titles.index("Cuenta corriente") + 1
        assert titles.index("Sistema") == titles.index("Avisos") + 1
    finally:
        set_managerial_dashboard_menu_enabled(False)


def test_app_smoke_command_runs():
    completed = subprocess.run(
        [sys.executable, "-m", "app.main", "--smoke"],
        text=True,
        capture_output=True,
        check=False,
    )
