import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_parameters_page_groups_current_and_future_settings(db):
    from PyQt5.QtWidgets import QApplication, QTabWidget

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_parameters_page", password_hash="x", profile=profile)

    window = FemagDesktopWindow(user=user, demo_mode=True)
    try:
        assert "parameters" in window._route_indexes
        window._navigate_to_route("parameters")
        app.processEvents()

        tabs = window.findChild(QTabWidget, "parametersTabs")
        assert tabs is not None
        labels = [tabs.tabText(index) for index in range(tabs.count())]
        assert labels == [
            "Numeración",
            "WhatsApp",
            "Servidor web",
            "Documentos fiscales",
        ]
        assert tabs.widget(0) is not None
        assert tabs.widget(1).objectName() == "whatsappConfigurationPage"
        assert tabs.widget(2).objectName() == "webappConfigurationPage"
        assert tabs.widget(3).objectName() == "fiscalConfigurationPage"
    finally:
        window.close()
