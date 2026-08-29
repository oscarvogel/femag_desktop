def test_topbar_avisos_button_opens_dropdown(db):
    import os
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt5.QtWidgets import QApplication, QPushButton, QWidget
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_dropdown", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()
    btn = window.findChild(QPushButton, "avisoButton")
    assert btn is not None
    btn.click()
    app.processEvents()
    dropdown = window.findChild(QWidget, "avisoDropdown")
    assert dropdown is not None and not dropdown.isHidden()
