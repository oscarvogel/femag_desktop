from PyQt5.QtWidgets import QApplication, QPushButton, QTableWidget, QDialog

from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.security import User, UserProfile
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService
from app.ui import desktop_app as desktop
from app.ui.load_order_workspace_restore_extension import install_load_order_workspace_restore_extension


def test_restored_workspace_exposes_history_and_uses_annul_reason_dialog(db, monkeypatch):
    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="restore_audit_ui", password_hash="x", profile=profile)

    carrier = Carrier.create(name="Restore Audit Carrier")
    driver = Driver.create(name="Restore Audit Driver", carrier=carrier)
    truck = Truck.create(domain="RA472AA", carrier=carrier)
    client = Client.create(name="Restore Audit Client", cuit="30747210001", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Puerto Rico",
        address="Ruta restore 472",
    )
    product = Product.create(name="Restore Audit Product", unit="kg")

    order = LoadOrderService(current_user=user.username).create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [{"product": product, "quantity": 1}],
            }
        ],
        pallets=[],
    )

    install_load_order_workspace_restore_extension()
    monkeypatch.setattr(desktop.LoadOrderAnnulDialog, "exec_", lambda _dialog: QDialog.Accepted)
    monkeypatch.setattr(
        desktop.LoadOrderAnnulDialog,
        "reason",
        lambda _dialog: "Motivo desde workspace restaurado",
    )

    window = desktop.FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    table = window.findChild(QTableWidget, "loadOrdersTable")
    history_button = window.findChild(QPushButton, "historyLoadOrderButton")
    annul_button = window.findChild(QPushButton, "annulLoadOrderButton")

    assert table is not None
    assert history_button is not None
    assert annul_button is not None

    table.setCurrentCell(0, 0)
    annul_button.click()
    app.processEvents()

    reloaded = type(order).get_by_id(order.id)
    assert reloaded.status == type(order).STATUS_ANNULLED
