import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_dashboard_buttons_are_connected(db):
    from PyQt5.QtWidgets import QApplication, QLineEdit, QPushButton, QTableWidget

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_dashboard", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    new_order_btn = window.findChild(QPushButton, "dashboardNuevaordendecarga")
    search_btn = window.findChild(QPushButton, "dashboardBuscarorden")
    new_client_btn = window.findChild(QPushButton, "dashboardNuevocliente")

    assert new_order_btn is not None, "Falta boton 'Nueva orden de carga' en dashboard"
    assert new_order_btn.isEnabled()
    assert search_btn is not None, "Falta boton 'Buscar orden' en dashboard"
    assert search_btn.isEnabled()
    assert new_client_btn is not None, "Falta boton 'Nuevo cliente' en dashboard"
    assert new_client_btn.isEnabled()


def test_dashboard_new_load_order_navigates_and_opens_dialog(db):
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QDialog, QPushButton

    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    Carrier.create(name="Transporte Test")
    Driver.create(name="Chofer Test", carrier=Carrier.get())
    Truck.create(domain="TEST111", carrier=Carrier.get())
    client = Client.create(name="Cliente Test", cuit="30111111119", iva_condition="RI")
    ClientAddress.create(client=client, address_type="entrega", province="Misiones", city="Posadas", address="Calle Test")
    Product.create(name="Producto Test", unit="kg")

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_new_order", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    dialog_opened = []

    def on_dialog():
        dlg = app.activeModalWidget()
        if dlg and isinstance(dlg, QDialog):
            dialog_opened.append(True)
            dlg.reject()

    QTimer.singleShot(200, on_dialog)

    btn = window.findChild(QPushButton, "dashboardNuevaordendecarga")
    assert btn is not None
    btn.click()
    app.processEvents()

    assert window._current_route == "load_orders"
    assert len(dialog_opened) == 1


def test_dashboard_search_load_order_navigates_and_focuses_search(db):
    from PyQt5.QtWidgets import QApplication, QLineEdit, QPushButton

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_search", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    btn = window.findChild(QPushButton, "dashboardBuscarorden")
    assert btn is not None
    btn.click()
    app.processEvents()

    assert window._current_route == "load_orders"
    search_input = window.findChild(QLineEdit, "loadOrderSearchInput")
    assert search_input is not None


def test_dashboard_new_client_navigates_and_opens_dialog(db):
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication, QDialog, QPushButton

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_new_client", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    dialog_opened = []

    def on_dialog():
        dlg = app.activeModalWidget()
        if dlg and isinstance(dlg, QDialog):
            dialog_opened.append(True)
            dlg.reject()

    QTimer.singleShot(200, on_dialog)

    btn = window.findChild(QPushButton, "dashboardNuevocliente")
    assert btn is not None
    btn.click()
    app.processEvents()

    assert window._current_route == "clients"
    assert len(dialog_opened) == 1


def test_disabled_dashboard_buttons_have_no_action(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_disabled", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    remittance_btn = window.findChild(QPushButton, "dashboardRegistrarremito")
    f150_btn = window.findChild(QPushButton, "dashboardF150")
    assert remittance_btn is not None
    assert f150_btn is not None
    assert not remittance_btn.isEnabled()
    assert not f150_btn.isEnabled()

    # Registrar pago y Cuenta corriente ahora navegan a pantallas reales (issue #144).
    payment_btn = window.findChild(QPushButton, "dashboardRegistrarpago")
    cc_btn = window.findChild(QPushButton, "dashboardCuentacorriente")
    assert payment_btn is not None
    assert cc_btn is not None
    assert payment_btn.isEnabled()
    assert cc_btn.isEnabled()
