from PyQt5.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit, QTableWidget

from app.ui.desktop_app import FemagDesktopWindow
from app.ui.load_order_workspace_restore_extension import (
    install_load_order_workspace_restore_extension,
)


def test_load_order_workspace_restore_is_installed():
    install_load_order_workspace_restore_extension()
    assert FemagDesktopWindow._load_order_page.__module__ == (
        "app.ui.load_order_workspace_restore_extension"
    )


def test_restored_workspace_contract(db):
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="workspace_restore", password_hash="x", profile=profile)

    app = QApplication.instance() or QApplication([])
    install_load_order_workspace_restore_extension()
    window = FemagDesktopWindow(user=user, demo_mode=True)
    window.show()
    app.processEvents()

    load_orders = window.findChild(QTableWidget, "loadOrdersTable")
    assert load_orders is not None
    assert load_orders.columnCount() == 7

    assert window.findChild(QLineEdit, "loadOrderNumberFilter") is not None
    assert window.findChild(QComboBox, "loadOrderClientFilter") is not None
    assert window.findChild(QCheckBox, "loadOrderDateFilterEnabled") is not None
    assert window.findChild(QLineEdit, "loadOrderSearchInput") is None

    window.close()
