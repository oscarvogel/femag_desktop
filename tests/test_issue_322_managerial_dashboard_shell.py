import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_managerial_dashboard_opens_local_html_from_desktop_shell_for_admin(db, monkeypatch):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    import app.main  # noqa: F401 - installs the desktop dashboard extension.
    from app.reports.managerial_dashboard_html import ManagerialDashboardHtmlReport
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    PermissionService().seed_defaults()
    admin = AuthService().create_initial_admin("admin-dashboard", "secreto")
    opened = []
    monkeypatch.setattr(ManagerialDashboardHtmlReport, "open", lambda self: opened.append(True))

    app = QApplication.instance() or QApplication([])
    window = FemagDesktopWindow(user=admin, demo_mode=True)

    row = next(
        index
        for index in range(window.nav.count())
        if window.nav.item(index).data(Qt.UserRole) == "managerial_dashboard"
    )
    window._navigate(row)

    assert app is not None
    assert opened == [True]
    assert "managerial_dashboard" not in window._route_indexes
    assert window.nav.item(row).text() == "Dashboard Gerencial"
    window.close()
