def test_remittance_page_exposes_both_creation_paths(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.ui.remittances import RemittancesPage

    app = QApplication.instance() or QApplication([])
    page = RemittancesPage(current_user="ui_remittances")
    app.processEvents()

    assert page.findChild(QPushButton, "newRemittanceButton").isEnabled()
    assert page.findChild(QPushButton, "remittanceFromOrderButton").isEnabled()
    assert page.table.columnCount() == 8


def test_manual_dialog_saves_independent_draft(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.remittances import Remittance
    from app.services.remittance_service import RemittanceService
    from app.ui.remittances import RemittanceEntryDialog
    from tests.conftest import _master_data

    app = QApplication.instance() or QApplication([])
    _master_data()
    dialog = RemittanceEntryDialog(RemittanceService(current_user="ui_manual"))
    dialog.save()
    app.processEvents()

    saved = Remittance.get()
    assert dialog.result() == dialog.Accepted
    assert saved.source_order is None
    assert saved.status == Remittance.STATUS_DRAFT


def test_desktop_registers_real_remittance_route(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="ui_route_remittances", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    assert "remittances" in window._route_indexes
    window._navigate_to_route("remittances")
    assert window._current_route == "remittances"
