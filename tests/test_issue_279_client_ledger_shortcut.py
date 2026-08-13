import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _admin_user(username: str):
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    return User.create(username=username, password_hash="x", profile=profile)


def test_client_list_ledger_action_requires_a_selected_client(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.ui.master_abm import build_client_abm_page

    app = QApplication.instance() or QApplication([])
    page = build_client_abm_page(
        user=_admin_user("admin_empty_279"),
        current_user="admin_empty_279",
        view_ledger_callback=lambda _client: None,
    )
    app.processEvents()

    button = page.findChild(QPushButton, "viewClientLedgerButton")
    assert button is not None
    assert not button.isEnabled()


def test_client_list_opens_ledger_with_client_selected_and_loaded(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QTableWidget

    from app.models.masters import Client
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente acceso directo",
        cuit="30700000279",
        iva_condition="RI",
    )
    window = FemagDesktopWindow(user=_admin_user("admin_ui_279"), demo_mode=True)
    window._navigate_to_route("clients")
    app.processEvents()

    button = window.findChild(QPushButton, "viewClientLedgerButton")
    assert button is not None
    assert button.isEnabled()
    button.click()
    app.processEvents()

    assert window.stack.currentIndex() == window._route_indexes["customer_ledger"]
    ledger_table = window.findChild(QTableWidget, "customerLedgerClientsTable")
    assert ledger_table.rowCount() == 1
    selected = ledger_table.item(ledger_table.currentRow(), 0)
    assert selected.data(Qt.UserRole) == client.id
    assert selected.text() == client.name
    assert window.findChild(QLabel, "customerLedgerDetailHeader").text().endswith(
        client.name
    )
    assert window.findChild(QLabel, "customerLedgerBalanceValue").text() == "$0.00"
