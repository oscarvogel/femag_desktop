import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QLineEdit

from app.ui.load_order_quick_search_extension import (
    _order_matches_quick_search,
    install_load_order_quick_search_extension,
)
from app.ui.load_order_workspace_restore_extension import (
    install_load_order_workspace_restore_extension,
)


def _demo_user(username):
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    return User.create(username=username, password_hash="x", profile=profile)


def test_quick_search_matches_operational_fields(db):
    from app.services.load_order_service import LoadOrderService
    from conftest import _master_data, _valid_order_payload

    user = _demo_user("quick_search_fields")
    data = _master_data()
    order = LoadOrderService(current_user=user.username).create_order(
        **_valid_order_payload(data)
    )

    assert _order_matches_quick_search(order, order.carrier.name)
    assert _order_matches_quick_search(order, order.driver.name)
    assert _order_matches_quick_search(order, order.truck.domain)
    assert _order_matches_quick_search(order, order.destinations[0].client.name)
    assert _order_matches_quick_search(order, order.products[0].product.name)


def test_quick_search_widget_is_added(db):
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    user = _demo_user("quick_search_widget")
    install_load_order_workspace_restore_extension()
    install_load_order_quick_search_extension()
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    quick = window.findChild(QLineEdit, "loadOrderQuickSearchInput")
    assert quick is not None
    assert "cliente" in quick.placeholderText().lower()
    assert "transportista" in quick.placeholderText().lower()
    assert "chofer" in quick.placeholderText().lower()
    assert "patente" in quick.placeholderText().lower()
    assert "artículo" in quick.placeholderText().lower()

    window.close()
