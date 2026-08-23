import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _issued_remittance():
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.remittance_service import RemittanceService

    client = Client.create(name="Cliente UI F150", cuit="30712345001", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta UI F150",
    )
    carrier = Carrier.create(name="Transporte UI F150", cuit="30712345002")
    truck = Truck.create(domain="F150UI", trailer_domain="F150AC", carrier=carrier)
    driver = Driver.create(
        name="Chofer UI F150",
        carrier=carrier,
        cuit="20123456001",
        document="12345670",
    )
    product = Product.create(
        codigo="P-F150",
        name="Producto UI F150",
        unit="KG",
        precio_neto_base=10,
    )
    service = RemittanceService("admin_f150_ui")
    remittance = service.create_manual(
        client=client,
        delivery_address=address,
        carrier=carrier,
        truck=truck,
        driver=driver,
        physical_point_of_sale="0001",
        physical_number="1",
        remittance_date=date.today(),
        items=[{"product": product, "quantity": Decimal("2")}],
    )
    return service.issue(remittance)


def test_f150_page_is_reachable_and_generates_selected_batch(db, tmp_path, monkeypatch):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton, QTableWidget

    from app.models.f150 import F150Batch
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    _issued_remittance()
    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_f150_ui", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    window._navigate_to_route("f150")
    app.processEvents()

    assert window._current_route == "f150"
    table = window.findChild(QTableWidget, "f150RemittancesTable")
    history = window.findChild(QTableWidget, "f150HistoryTable")
    generate = window.findChild(QPushButton, "generateF150Button")
    assert table is not None and table.rowCount() == 1
    assert history is not None and history.rowCount() == 0
    assert table.item(0, 8).text() == "Listo"

    output = tmp_path / "ui-f150.TXT"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(output), "TXT"))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    table.item(0, 0).setCheckState(Qt.Checked)
    generate.click()
    app.processEvents()

    assert output.exists()
    assert F150Batch.select().count() == 1
    assert history.rowCount() == 1
    assert table.rowCount() == 0
