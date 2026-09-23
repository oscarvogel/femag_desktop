import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_managerial_dashboard_opens_inside_grouped_desktop_shell_for_admin(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.managerial_dashboard_extension import (
        install_managerial_dashboard_extension,
        uninstall_managerial_dashboard_extension,
    )

    install_managerial_dashboard_extension()
    try:
        PermissionService().seed_defaults()
        admin = AuthService().create_initial_admin("admin-dashboard", "secreto")

        app = QApplication.instance() or QApplication([])
        window = FemagDesktopWindow(user=admin, demo_mode=True)

        row = next(
            index
            for index in range(window.nav.count())
            if window.nav.item(index).data(Qt.UserRole) == "managerial_dashboard"
        )
        window._navigate(row)

        assert app is not None
        assert "managerial_dashboard" in window._route_indexes
        assert window.nav.item(row).text().strip() == "Resumen gerencial"
        page = window.stack.widget(window._route_indexes["managerial_dashboard"])
        assert page.objectName() == "managerialDashboardPage"
        from PyQt5.QtWidgets import QPushButton
        assert page.findChild(QPushButton, "managerialSendSummaryButton") is not None
        assert page.findChild(QPushButton, "managerialOpenHtmlButton") is not None
        window.close()
    finally:
        uninstall_managerial_dashboard_extension()
