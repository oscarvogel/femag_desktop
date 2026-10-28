import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_admin_configures_server_url_from_desktop(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.services.webapp_configuration_service import WebappConfigurationService
    from app.ui.desktop_app import FemagDesktopWindow

    PermissionService().seed_defaults()
    admin = AuthService().create_initial_admin("admin-webapp", "secreto")

    app = QApplication.instance() or QApplication([])
    window = FemagDesktopWindow(user=admin, demo_mode=True)
    try:
        assert "webapp_configuration" in window._route_indexes
        page = window.stack.widget(window._route_indexes["webapp_configuration"])
        assert page.objectName() == "webappConfigurationPage"

        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
        page.url_input.setText("http://192.168.0.111:8000/")
        page._save()

        assert WebappConfigurationService.public_url() == "http://192.168.0.111:8000"
        assert "http://192.168.0.111:8000" in page.status.text()
    finally:
        window.close()

    assert app is not None
