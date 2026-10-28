import os
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_APP = None


def _application():
    global _APP
    from PyQt5.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


def _admin_user(username: str):
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    return User.create(username=username, password_hash="x", profile=profile)


def _find_row(table, column: int, text: str) -> int:
    for row in range(table.rowCount()):
        if table.item(row, column).text() == text:
            return row
    raise AssertionError(f"Row with {text!r} not found")


def test_client_detail_shows_stored_data_addresses_and_emails(db):
    from PyQt5.QtWidgets import QLabel, QTableWidget

    from app.models.masters import Client, ClientAddress, ClientEmail, Salesperson
    from app.ui.master_detail_dialogs import ClientDetailDialog

    _application()
    salesperson = Salesperson.create(name="Vendedor Ficha")
    client = Client.create(
        name="Cliente Ficha",
        cuit="30700000800",
        iva_condition="Responsable Inscripto",
        phone="3764000000",
        email="cliente@example.com",
        contact="Ana",
        salesperson=salesperson,
        lista_precios=2,
        descuento_porcentaje=7.5,
        dias_plazo_pago=15,
        max_despachos_pendientes=3,
    )
    ClientAddress.create(
        client=client,
        address_type="fiscal",
        province="Misiones",
        city="Posadas",
        address="Calle Fiscal 1",
        is_primary=True,
    )
    ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Eldorado",
        address="Calle Entrega 2",
    )
    ClientAddress.create(
        client=client,
        address_type="fiscal_entrega",
        province="Misiones",
        city="Obera",
        address="Calle Compartida 3",
        active=False,
    )
    ClientEmail.create(
        client=client,
        email="otro@example.com",
        label="Compras",
        is_primary=True,
    )

    dialog = ClientDetailDialog(current_user="ui_800", record_id=client.id)

    assert dialog.windowTitle() == "Ficha de cliente - Cliente Ficha"
    assert dialog.findChild(QLabel, "clientDetailIdValue").text() == str(client.id)
    assert dialog.findChild(QLabel, "clientDetailNameValue").text() == "Cliente Ficha"
    assert dialog.findChild(QLabel, "clientDetailCuitValue").text() == "30700000800"
    assert dialog.findChild(QLabel, "clientDetailSalespersonValue").text() == "Vendedor Ficha"
    assert dialog.findChild(QLabel, "clientDetailPriceListValue").text() == "Lista 2"
    assert dialog.findChild(QLabel, "clientDetailDiscountValue").text() == "7.5%"
    assert dialog.findChild(QLabel, "clientDetailPaymentDaysValue").text() == "15 días"
    assert dialog.findChild(QLabel, "clientDetailMaxPendingValue").text() == "3"
    assert dialog.findChild(QLabel, "clientDetailActiveValue").text() == "Activo"

    address_table = dialog.findChild(QTableWidget, "clientDetailAddressesTable")
    assert address_table.rowCount() == 3
    assert {
        address_table.item(row, 0).text() for row in range(address_table.rowCount())
    } == {"Fiscal", "Entrega", "Fiscal / Entrega"}
    assert {
        address_table.item(row, 7).text() for row in range(address_table.rowCount())
    } == {"Activo", "Inactivo"}
    assert "Calle Compartida 3" in {
        address_table.item(row, 2).text() for row in range(address_table.rowCount())
    }

    email_table = dialog.findChild(QTableWidget, "clientDetailEmailsTable")
    assert email_table.rowCount() == 1
    assert email_table.item(0, 0).text() == "otro@example.com"
    assert email_table.item(0, 2).text() == "Sí"

    dialog.close()


def test_carrier_detail_lists_only_its_drivers_and_trucks(db):
    from PyQt5.QtWidgets import QLabel, QTableWidget

    from app.models.masters import Carrier, Driver, Truck
    from app.ui.master_detail_dialogs import CarrierDetailDialog

    _application()
    carrier = Carrier.create(
        name="Transportista Ficha",
        cuit="30700000801",
        phone="3764111111",
        codigo="T-800",
        tipo="Camión",
        address="Ruta 12",
        active=False,
    )
    Driver.create(name="Chofer Asociado", carrier=carrier, document="30000001")
    Driver.create(name="Chofer Ajeno", carrier=None, document="30000002")
    Truck.create(
        domain="FIC800",
        trailer_domain="FIC801",
        carrier=carrier,
        chassis_type="Semirremolque",
        trailer_type="Acoplado",
        max_load_kg=Decimal("30000.500"),
    )

    dialog = CarrierDetailDialog(current_user="ui_800", record_id=carrier.id)

    assert "(inactivo)" in dialog.windowTitle()
    assert dialog.findChild(QLabel, "carrierDetailIdValue").text() == str(carrier.id)
    assert dialog.findChild(QLabel, "carrierDetailNameValue").text() == "Transportista Ficha"
    assert dialog.findChild(QLabel, "carrierDetailCodeValue").text() == "T-800"
    assert dialog.findChild(QLabel, "carrierDetailTypeValue").text() == "Camión"
    assert dialog.findChild(QLabel, "carrierDetailActiveValue").text() == "Inactivo"

    drivers_table = dialog.findChild(QTableWidget, "carrierDetailDriversTable")
    assert drivers_table.rowCount() == 1
    assert drivers_table.item(0, 0).text() == "Chofer Asociado"
    assert drivers_table.item(0, 1).text() == "30000001"

    trucks_table = dialog.findChild(QTableWidget, "carrierDetailTrucksTable")
    assert trucks_table.rowCount() == 1
    assert trucks_table.item(0, 0).text() == "FIC800"
    assert trucks_table.item(0, 1).text() == "FIC801"
    assert trucks_table.item(0, 3).text() == "30000.500 kg"

    dialog.close()


def test_driver_detail_shows_unassigned_relations_and_real_ones(db):
    from PyQt5.QtWidgets import QLabel

    from app.models.masters import Carrier, Driver, Truck
    from app.ui.master_detail_dialogs import DriverDetailDialog

    _application()
    driver = Driver.create(
        name="Chofer Ficha",
        document="30111222",
        phone="3764222222",
        address="Calle Chofer 1",
        available=False,
    )

    dialog = DriverDetailDialog(current_user="ui_800", record_id=driver.id)

    assert dialog.findChild(QLabel, "driverDetailIdValue").text() == str(driver.id)
    assert dialog.findChild(QLabel, "driverDetailDocumentValue").text() == "30111222"
    assert dialog.findChild(QLabel, "driverDetailAvailableValue").text() == "No disponible"
    assert dialog.findChild(QLabel, "driverDetailCarrierValue").text() == "Sin asignar"
    assert dialog.findChild(QLabel, "driverDetailTruckValue").text() == "Sin asignar"
    dialog.close()

    carrier = Carrier.create(name="Transportista Chofer Ficha")
    truck = Truck.create(domain="CHF800", trailer_domain="CHF801", carrier=carrier)
    driver.carrier = carrier
    driver.usual_truck = truck
    driver.save()

    dialog = DriverDetailDialog(current_user="ui_800", record_id=driver.id)

    assert (
        dialog.findChild(QLabel, "driverDetailCarrierValue").text()
        == "Transportista Chofer Ficha"
    )
    assert dialog.findChild(QLabel, "driverDetailTruckValue").text() == "CHF800"
    assert dialog.findChild(QLabel, "driverDetailTrailerValue").text() == "CHF801"
    dialog.close()


def test_truck_detail_lists_only_habitual_drivers(db):
    from PyQt5.QtWidgets import QLabel, QTableWidget

    from app.models.masters import Carrier, Driver, Truck
    from app.ui.master_detail_dialogs import TruckDetailDialog

    _application()
    carrier = Carrier.create(name="Transportista Camión Ficha")
    truck = Truck.create(domain="CAM800", trailer_domain="CAM801", carrier=carrier)
    other_truck = Truck.create(domain="CAM900", carrier=carrier)
    Driver.create(name="Chofer Habitual", usual_truck=truck, document="40000001")
    Driver.create(
        name="Chofer De Otro Camión", usual_truck=other_truck, document="40000002"
    )

    dialog = TruckDetailDialog(current_user="ui_800", record_id=truck.id)

    assert dialog.findChild(QLabel, "truckDetailIdValue").text() == str(truck.id)
    assert dialog.findChild(QLabel, "truckDetailDomainValue").text() == "CAM800"
    assert (
        dialog.findChild(QLabel, "truckDetailCarrierValue").text()
        == "Transportista Camión Ficha"
    )
    drivers_table = dialog.findChild(QTableWidget, "truckDetailDriversTable")
    assert drivers_table.rowCount() == 1
    assert drivers_table.item(0, 0).text() == "Chofer Habitual"
    assert drivers_table.item(0, 1).text() == "40000001"
    dialog.close()


def test_enter_and_double_click_on_client_grid_open_detail_and_keep_selection(
    db, monkeypatch
):
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QLineEdit, QTableWidget

    from app.models.masters import Client
    from app.ui import master_abm

    app = _application()
    Client.create(name="A Cliente Ficha", cuit="30700000802", iva_condition="RI")
    selected_client = Client.create(
        name="B Cliente Ficha", cuit="30700000803", iva_condition="RI"
    )
    user = _admin_user("ui_800_client_grid")
    page = master_abm.build_client_abm_page(user=user, current_user=user.username)
    table = page.findChild(QTableWidget, "clientTable")
    search = page.findChild(QLineEdit, "clientSearchInput")
    search.setText("B Cliente")
    app.processEvents()

    row = _find_row(table, 0, "B Cliente Ficha")
    table.setCurrentCell(row, 0)
    assert table.editTriggers() == QTableWidget.NoEditTriggers
    calls: list[int] = []

    class FakeDialog:
        def __init__(self, *, current_user, record_id, parent=None, **kwargs):
            calls.append(record_id)

        def exec_(self):
            return 0

    monkeypatch.setattr(master_abm, "ClientDetailDialog", FakeDialog)

    table.itemDoubleClicked.emit(table.item(row, 0))
    QTest.keyClick(table, Qt.Key_Return)

    assert calls == [selected_client.id, selected_client.id]
    assert table.currentRow() == row
    assert search.text() == "B Cliente"
    assert table.selectedItems()


def test_master_grids_open_their_specific_detail_card(db, monkeypatch):
    from PyQt5.QtWidgets import QTableWidget

    from app.models.masters import Carrier, Driver, Truck
    from app.ui import master_abm

    app = _application()
    carrier = Carrier.create(name="Transportista Activación", cuit="30700000804")
    driver = Driver.create(name="Chofer Activación", carrier=carrier)
    truck = Truck.create(domain="ACT800", carrier=carrier)
    user = _admin_user("ui_800_master_grids")
    calls: list[tuple[str, int]] = []

    def make_fake_dialog(name: str):
        class FakeDialog:
            def __init__(self, *, current_user, record_id, parent=None, **kwargs):
                calls.append((name, record_id))

            def exec_(self):
                return 0

        return FakeDialog

    for dialog_name in (
        "CarrierDetailDialog",
        "DriverDetailDialog",
        "TruckDetailDialog",
    ):
        monkeypatch.setattr(master_abm, dialog_name, make_fake_dialog(dialog_name))

    cases = (
        ("carriers", "newCarrierButtonTable", "Transportista Activación", carrier.id),
        ("drivers", "newDriverButtonTable", "Chofer Activación", driver.id),
        ("trucks", "newTruckButtonTable", "ACT800", truck.id),
    )
    for route, table_name, row_text, expected_id in cases:
        configs = master_abm.master_abm_configs()
        page = master_abm.build_master_abm_page(
            config=configs[route],
            user=user,
            current_user=user.username,
        )
        table = page.findChild(QTableWidget, table_name)
        row = _find_row(table, 0, row_text)
        table.setCurrentCell(row, 0)
        assert table.editTriggers() == QTableWidget.NoEditTriggers
        table.itemDoubleClicked.emit(table.item(row, 0))
        assert calls[-1][1] == expected_id

    assert [name for name, _record_id in calls] == [
        "CarrierDetailDialog",
        "DriverDetailDialog",
        "TruckDetailDialog",
    ]


def test_master_configs_declare_detail_cards_for_the_four_master_grids():
    from app.ui.master_abm import master_abm_configs
    from app.ui.master_detail_dialogs import (
        CarrierDetailDialog,
        ClientDetailDialog,
        DriverDetailDialog,
        TruckDetailDialog,
    )

    configs = master_abm_configs()

    assert configs["clients"].detail_dialog_class is ClientDetailDialog
    assert configs["carriers"].detail_dialog_class is CarrierDetailDialog
    assert configs["drivers"].detail_dialog_class is DriverDetailDialog
    assert configs["trucks"].detail_dialog_class is TruckDetailDialog
    assert configs["products"].detail_dialog_class is None
