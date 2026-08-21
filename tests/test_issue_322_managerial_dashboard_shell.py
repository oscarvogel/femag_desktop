import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_managerial_dashboard_is_registered_in_desktop_shell_for_admin(db):
    from PyQt5.QtWidgets import QApplication

    import app.main  # noqa: F401 - installs the desktop dashboard extension.
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    PermissionService().seed_defaults()
    admin = AuthService().create_initial_admin("admin-dashboard", "secreto")
    app = QApplication.instance() or QApplication([])
    window = FemagDesktopWindow(user=admin, demo_mode=True)

    assert app is not None
    assert "managerial_dashboard" in window._route_indexes
    page = window.stack.widget(window._route_indexes["managerial_dashboard"])
    assert page.objectName() == "managerialDashboardPage"
    assert any(
        window.nav.item(index).text() == "Dashboard Gerencial"
        for index in range(window.nav.count())
    )
    window.close()
