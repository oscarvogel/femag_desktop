import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_APP = None


def _application():
    global _APP
    from PyQt5.QtWidgets import QApplication

    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_carrier_detail_navigates_to_driver_and_back_restores_tab(db):
    from PyQt5.QtWidgets import QTableWidget

    from app.models.masters import Carrier, Driver
    from app.ui.master_detail_dialogs import CarrierDetailDialog

    _application()
    carrier = Carrier.create(name="Carrier Navegacion")
    Driver.create(name="A Driver Navegacion", carrier=carrier, document="80000001")
    Driver.create(name="Z Driver Navegacion", carrier=carrier, document="80000002")
    dialog = CarrierDetailDialog(current_user="ui_800_nav", record_id=carrier.id)
    dialog.tabs.setCurrentIndex(1)
    table = dialog.findChild(QTableWidget, "carrierDetailDriversTable")
    assert table.rowCount() == 2
    table.setCurrentCell(1, 0)

    table.itemDoubleClicked.emit(table.item(1, 0))

    assert dialog.objectName() == "driverDetailDialog"
    assert "Z Driver Navegacion" in dialog.windowTitle()
    assert dialog.back_button.isEnabled()

    dialog.back_button.click()

    assert dialog.objectName() == "carrierDetailDialog"
    assert dialog.tabs.currentIndex() == 1
    assert dialog.tabs.tabText(1).startswith("Choferes")
    restored_table = dialog.findChild(QTableWidget, "carrierDetailDriversTable")
    assert restored_table.currentRow() == 1
    assert dialog.back_button.isEnabled() is False
    dialog.close()


def test_carrier_detail_navigates_to_truck_and_enter_key_works(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QTableWidget

    from app.models.masters import Carrier, Truck
    from app.ui.master_detail_dialogs import CarrierDetailDialog

    app = _application()
    carrier = Carrier.create(name="Carrier Camiones Navegacion")
    Truck.create(domain="NAV800", carrier=carrier)
    dialog = CarrierDetailDialog(current_user="ui_800_nav", record_id=carrier.id)
    dialog.tabs.setCurrentIndex(2)
    table = dialog.findChild(QTableWidget, "carrierDetailTrucksTable")
    assert table.rowCount() == 1
    table.setCurrentCell(0, 0)

    QTest.keyClick(table, Qt.Key_Return)

    assert dialog.objectName() == "truckDetailDialog"
    assert "NAV800" in dialog.windowTitle()
    dialog.back_button.click()
    assert dialog.objectName() == "carrierDetailDialog"
    assert dialog.tabs.currentIndex() == 2
    dialog.close()
    app.processEvents()


def test_driver_detail_opens_carrier_and_habitual_truck(db):
    from PyQt5.QtWidgets import QPushButton

    from app.models.masters import Carrier, Driver, Truck
    from app.ui.master_detail_dialogs import DriverDetailDialog

    _application()
    carrier = Carrier.create(name="Carrier Relaciones Chofer")
    truck = Truck.create(domain="CHN800", trailer_domain="CHN801", carrier=carrier)
    driver = Driver.create(name="Chofer Relaciones", carrier=carrier, usual_truck=truck)

    dialog = DriverDetailDialog(current_user="ui_800_nav", record_id=driver.id)

    dialog.findChild(QPushButton, "driverDetailOpenCarrierButton").click()
    assert dialog.objectName() == "carrierDetailDialog"
    assert "Carrier Relaciones Chofer" in dialog.windowTitle()
    dialog.back_button.click()
    assert dialog.objectName() == "driverDetailDialog"

    dialog.findChild(QPushButton, "driverDetailOpenTruckButton").click()
    assert dialog.objectName() == "truckDetailDialog"
    assert "CHN800" in dialog.windowTitle()
    dialog.close()


def test_driver_relation_buttons_are_disabled_without_relations(db):
    from PyQt5.QtWidgets import QPushButton

    from app.models.masters import Driver
    from app.ui.master_detail_dialogs import DriverDetailDialog

    _application()
    driver = Driver.create(name="Chofer Sin Relaciones")
    dialog = DriverDetailDialog(current_user="ui_800_nav", record_id=driver.id)

    assert (
        dialog.findChild(QPushButton, "driverDetailOpenCarrierButton").isEnabled()
        is False
    )
    assert (
        dialog.findChild(QPushButton, "driverDetailOpenTruckButton").isEnabled()
        is False
    )
    dialog.close()


def test_truck_detail_opens_carrier_and_habitual_driver(db):
    from PyQt5.QtWidgets import QPushButton, QTableWidget

    from app.models.masters import Carrier, Driver, Truck
    from app.ui.master_detail_dialogs import TruckDetailDialog

    _application()
    carrier = Carrier.create(name="Carrier Camion Navegacion")
    truck = Truck.create(domain="TRN800", carrier=carrier)
    Driver.create(name="Chofer Habitual Navegacion", usual_truck=truck)

    dialog = TruckDetailDialog(current_user="ui_800_nav", record_id=truck.id)

    dialog.findChild(QPushButton, "truckDetailOpenCarrierButton").click()
    assert dialog.objectName() == "carrierDetailDialog"
    assert "Carrier Camion Navegacion" in dialog.windowTitle()
    dialog.back_button.click()
    assert dialog.objectName() == "truckDetailDialog"

    table = dialog.findChild(QTableWidget, "truckDetailDriversTable")
    assert table.rowCount() == 1
    dialog.tabs.setCurrentIndex(1)
    table.setCurrentCell(0, 0)
    table.itemDoubleClicked.emit(table.item(0, 0))

    assert dialog.objectName() == "driverDetailDialog"
    assert "Chofer Habitual Navegacion" in dialog.windowTitle()
    dialog.back_button.click()
    assert dialog.objectName() == "truckDetailDialog"
    assert dialog.tabs.currentIndex() == 1
    dialog.close()


def test_navigation_uses_one_dialog_and_a_back_stack(db):
    from PyQt5.QtWidgets import QPushButton

    from app.models.masters import Carrier, Driver, Truck
    from app.ui.master_detail_dialogs import CarrierDetailDialog

    _application()
    carrier = Carrier.create(name="Carrier Pila Navegacion")
    truck = Truck.create(domain="STK800", carrier=carrier)
    driver = Driver.create(name="Chofer Pila Navegacion", carrier=carrier, usual_truck=truck)
    dialog = CarrierDetailDialog(current_user="ui_800_nav", record_id=carrier.id)
    dialog_id = id(dialog)

    dialog.navigate_to("driver", driver.id)
    dialog.findChild(QPushButton, "driverDetailOpenCarrierButton").click()

    assert id(dialog) == dialog_id
    assert len(dialog._history) == 2
    assert dialog.objectName() == "carrierDetailDialog"

    dialog.back_button.click()
    assert dialog.objectName() == "driverDetailDialog"
    dialog.back_button.click()
    assert dialog.objectName() == "carrierDetailDialog"
    assert dialog.back_button.isEnabled() is False
    dialog.close()


def test_detail_cards_remain_read_only_and_offer_no_edit_actions(db):
    from PyQt5.QtWidgets import QPushButton

    from app.models.masters import Carrier, Client
    from app.ui.master_detail_dialogs import CarrierDetailDialog, ClientDetailDialog

    _application()
    client = Client.create(name="Cliente Solo Lectura", cuit="30700000810", iva_condition="RI")
    carrier = Carrier.create(name="Carrier Solo Lectura")

    for dialog in (
        ClientDetailDialog(current_user="ui_800_nav", record_id=client.id),
        CarrierDetailDialog(current_user="ui_800_nav", record_id=carrier.id),
    ):
        action_names = {
            button.objectName() for button in dialog.findChildren(QPushButton)
        }
        assert "editClientButton" not in action_names
        assert "editCarrierButton" not in action_names
        assert "closeMasterDetailButton" in action_names
        assert "backMasterDetailButton" in action_names
        assert dialog.edit_button.isEnabled() is False
        dialog.close()


def test_read_only_user_can_open_a_detail_card_without_editing(db, monkeypatch):
    from PyQt5.QtWidgets import QPushButton, QTableWidget

    from app.models.masters import Carrier
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui import master_abm

    _application()
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Solo consulta")
    user = User.create(username="ui_800_readonly", password_hash="x", profile=profile)
    carrier = Carrier.create(name="Carrier Solo Consulta")
    calls: list[int] = []

    class FakeDialog:
        def __init__(self, *, current_user, record_id, parent=None, **kwargs):
            calls.append(record_id)

        def exec_(self):
            return 0

    monkeypatch.setattr(master_abm, "CarrierDetailDialog", FakeDialog)
    config = master_abm.master_abm_configs()["carriers"]
    page = master_abm.build_master_abm_page(
        config=config,
        user=user,
        current_user=user.username,
    )
    table = page.findChild(QTableWidget, "newCarrierButtonTable")
    edit_button = page.findChild(QPushButton, "editCarrierButton")
    row = next(
        row for row in range(table.rowCount())
        if table.item(row, 0).text() == "Carrier Solo Consulta"
    )
    table.setCurrentCell(row, 0)

    table.itemDoubleClicked.emit(table.item(row, 0))

    assert calls == [carrier.id]
    assert edit_button.isEnabled() is False
