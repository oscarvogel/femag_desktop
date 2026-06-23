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
    from app.models.masters import Client, Product
    from app.ui.dashboard import DashboardService, future_module_message

    Client.create(name="Cliente", cuit="30222222229", iva_condition="RI")
    Product.create(name="Fecula", unit="kg")

    summary = DashboardService().summary()

    assert summary["clientes"] == 1
    assert summary["productos"] == 1
    assert future_module_message() == "Funcionalidad prevista para una próxima entrega."


def test_app_smoke_command_runs():
    completed = subprocess.run(
        [sys.executable, "-m", "app.main", "--smoke"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "FEMAG smoke OK" in completed.stdout
