import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _set_combo(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_guided_transport_setup_creates_related_carrier_truck_and_driver(db):
    from PyQt5.QtWidgets import QApplication, QLineEdit, QPushButton

    from app.models.masters import Carrier, Driver, Truck
    from app.ui.transport_setup_extension import TransportSetupDialog

    app = QApplication.instance() or QApplication([])
    dialog = TransportSetupDialog(current_user="issue266")

    dialog.findChild(QLineEdit, "transportSetupCarrierNameInput").setText("Transporte 266")
    dialog.findChild(QLineEdit, "transportSetupCarrierCuitInput").setText("30700266001")
    dialog.findChild(QLineEdit, "transportSetupTruckDomainInput").setText("af 266 zz")
    dialog.findChild(QLineEdit, "transportSetupTrailerDomainInput").setText("ac 266 aa")
    dialog.findChild(QLineEdit, "transportSetupDriverNameInput").setText("Chofer 266")
    dialog.findChild(QLineEdit, "transportSetupDriverDocumentInput").setText("26626626")
    dialog.findChild(QPushButton, "saveTransportSetupButton").click()
    app.processEvents()

    carrier = Carrier.get(Carrier.name == "Transporte 266")
    truck = Truck.get(Truck.domain == "AF266ZZ")
    driver = Driver.get(Driver.name == "Chofer 266")

    assert dialog.result() == dialog.Accepted
    assert carrier.cuit == "30700266001"
    assert truck.carrier == carrier
    assert truck.trailer_domain == "AC266AA"
    assert driver.carrier == carrier
    assert driver.usual_truck == truck
    assert driver.document == "26626626"


def test_guided_transport_setup_selects_existing_carrier_truck_and_driver(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QPushButton

    from app.models.masters import Carrier, Driver, Truck
    from app.ui.transport_setup_extension import TransportSetupDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Transporte existente 266", cuit="30700266002")
    truck = Truck.create(domain="EX266AA", carrier=carrier)
    driver = Driver.create(name="Chofer existente 266", carrier=carrier)

    dialog = TransportSetupDialog(current_user="issue266", initial_carrier_id=carrier.id)
    _set_combo(dialog.findChild(QComboBox, "transportSetupTruckInput"), truck.id)
    _set_combo(dialog.findChild(QComboBox, "transportSetupDriverInput"), driver.id)
    dialog.findChild(QPushButton, "saveTransportSetupButton").click()
    app.processEvents()

    driver = Driver.get_by_id(driver.id)

    assert dialog.result() == dialog.Accepted
    assert Carrier.select().where(Carrier.name == "Transporte existente 266").count() == 1
    assert Truck.select().where(Truck.domain == "EX266AA").count() == 1
    assert driver.carrier == carrier
    assert driver.usual_truck == truck


def test_guided_transport_setup_warns_and_reassigns_existing_relations(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QLabel, QPushButton

    from app.models.masters import Carrier, Driver, Truck
    from app.ui.transport_setup_extension import TransportSetupDialog

    app = QApplication.instance() or QApplication([])
    old_carrier = Carrier.create(name="Transporte anterior 266")
    new_carrier = Carrier.create(name="Transporte destino 266")
    old_truck = Truck.create(domain="OLD266", carrier=old_carrier)
    new_truck = Truck.create(domain="NEW266", carrier=new_carrier)
    driver = Driver.create(
        name="Chofer a reasignar 266",
        carrier=old_carrier,
        usual_truck=old_truck,
    )

    dialog = TransportSetupDialog(current_user="issue266", initial_carrier_id=new_carrier.id)
    _set_combo(dialog.findChild(QComboBox, "transportSetupTruckInput"), old_truck.id)
    _set_combo(dialog.findChild(QComboBox, "transportSetupDriverInput"), driver.id)
    app.processEvents()

    truck_warning = dialog.findChild(QLabel, "transportSetupTruckWarning").text()
    driver_warning = dialog.findChild(QLabel, "transportSetupDriverWarning").text()
    assert "Transporte anterior 266" in truck_warning
    assert "reasignará" in truck_warning
    assert "Transporte anterior 266" in driver_warning
    assert "reasignará" in driver_warning

    # Cambiamos explícitamente a otra patente del destino y comprobamos también
    # que se informa el cambio del camión habitual del chofer.
    _set_combo(dialog.findChild(QComboBox, "transportSetupTruckInput"), new_truck.id)
    app.processEvents()
    driver_warning = dialog.findChild(QLabel, "transportSetupDriverWarning").text()
    assert "camión habitual actual" in driver_warning

    # Volvemos a seleccionar la patente que estaba en la otra empresa para
    # verificar la reasignación completa solicitada por el operador.
    _set_combo(dialog.findChild(QComboBox, "transportSetupTruckInput"), old_truck.id)
    dialog.findChild(QPushButton, "saveTransportSetupButton").click()
    app.processEvents()

    old_truck = Truck.get_by_id(old_truck.id)
    driver = Driver.get_by_id(driver.id)
    assert dialog.result() == dialog.Accepted
    assert old_truck.carrier == new_carrier
    assert driver.carrier == new_carrier
    assert driver.usual_truck == old_truck


def test_transport_setup_uses_standard_autocomplete_and_initial_context(db):
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.models.masters import Carrier, Driver, Truck
    from app.ui.combo_autocomplete import AUTOCOMPLETE_PROPERTY
    from app.ui.transport_setup_extension import TransportSetupDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Autocomplete 266")
    truck = Truck.create(domain="AUTO266", carrier=carrier)
    driver = Driver.create(name="Chofer autocomplete 266", carrier=carrier, usual_truck=truck)

    dialog = TransportSetupDialog(
        current_user="issue266",
        initial_carrier_id=carrier.id,
        initial_truck_id=truck.id,
        initial_driver_id=driver.id,
    )
    app.processEvents()

    carrier_combo = dialog.findChild(QComboBox, "transportSetupCarrierInput")
    truck_combo = dialog.findChild(QComboBox, "transportSetupTruckInput")
    driver_combo = dialog.findChild(QComboBox, "transportSetupDriverInput")

    assert carrier_combo.property(AUTOCOMPLETE_PROPERTY) is True
    assert truck_combo.property(AUTOCOMPLETE_PROPERTY) is True
    assert driver_combo.property(AUTOCOMPLETE_PROPERTY) is True
    assert carrier_combo.currentData() == carrier.id
    assert truck_combo.currentData() == truck.id
    assert driver_combo.currentData() == driver.id


def test_selected_transport_row_is_used_as_dialog_context(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Carrier
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.master_abm import build_master_abm_page, master_abm_configs
    from app.ui.transport_setup_extension import _selected_transport_context

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_context_266", password_hash="x", profile=profile)
    carrier = Carrier.create(name="Transportista seleccionado 266")

    page = build_master_abm_page(
        config=master_abm_configs()["carriers"],
        user=user,
        current_user=user.username,
    )
    app.processEvents()

    controller = page.master_table_controller
    for row in range(controller.table.rowCount()):
        item = controller.table.item(row, 0)
        if item is not None and item.data(0x0100) == carrier.id:
            controller.table.setCurrentCell(row, 0)
            break

    carrier_id, truck_id, driver_id = _selected_transport_context(page, "Transportistas")
    assert carrier_id == carrier.id
    assert truck_id is None
    assert driver_id is None


def test_transport_master_pages_expose_guided_setup_button_by_permission(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.master_abm import build_master_abm_page, master_abm_configs

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()

    admin_profile = UserProfile.get(UserProfile.name == "Administrador")
    admin = User.create(username="admin_issue266", password_hash="x", profile=admin_profile)
    admin_page = build_master_abm_page(
        config=master_abm_configs()["carriers"],
        user=admin,
        current_user=admin.username,
    )
    app.processEvents()

    admin_button = admin_page.findChild(QPushButton, "transportSetupButtonnewCarrierButton")
    assert admin_button is not None
    assert admin_button.isEnabled() is True

    readonly_profile = UserProfile.get(UserProfile.name == "Solo consulta")
    readonly = User.create(username="readonly_issue266", password_hash="x", profile=readonly_profile)
    readonly_page = build_master_abm_page(
        config=master_abm_configs()["carriers"],
        user=readonly,
        current_user=readonly.username,
    )
    app.processEvents()

    readonly_button = readonly_page.findChild(QPushButton, "transportSetupButtonnewCarrierButton")
    assert readonly_button is not None
    assert readonly_button.isEnabled() is False
