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
    dialog = TransportSetupDialog(current_user="issue264")

    dialog.findChild(QLineEdit, "transportSetupCarrierNameInput").setText("Transporte 264")
    dialog.findChild(QLineEdit, "transportSetupCarrierCuitInput").setText("30700264001")
    dialog.findChild(QLineEdit, "transportSetupTruckDomainInput").setText("af 264 zz")
    dialog.findChild(QLineEdit, "transportSetupTrailerDomainInput").setText("ac 264 aa")
    dialog.findChild(QLineEdit, "transportSetupDriverNameInput").setText("Chofer 264")
    dialog.findChild(QLineEdit, "transportSetupDriverDocumentInput").setText("26426426")
    dialog.findChild(QPushButton, "saveTransportSetupButton").click()
    app.processEvents()

    carrier = Carrier.get(Carrier.name == "Transporte 264")
    truck = Truck.get(Truck.domain == "AF264ZZ")
    driver = Driver.get(Driver.name == "Chofer 264")

    assert dialog.result() == dialog.Accepted
    assert carrier.cuit == "30700264001"
    assert truck.carrier == carrier
    assert truck.trailer_domain == "AC264AA"
    assert driver.carrier == carrier
    assert driver.usual_truck == truck
    assert driver.document == "26426426"


def test_guided_transport_setup_reuses_existing_carrier_and_truck(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton

    from app.models.masters import Carrier, Driver, Truck
    from app.ui.transport_setup_extension import TransportSetupDialog

    app = QApplication.instance() or QApplication([])
    carrier = Carrier.create(name="Transporte existente 264", cuit="30700264002")
    truck = Truck.create(domain="EX264AA", carrier=carrier)

    dialog = TransportSetupDialog(current_user="issue264")
    _set_combo(dialog.findChild(QComboBox, "transportSetupCarrierInput"), carrier.id)
    dialog.findChild(QLineEdit, "transportSetupTruckDomainInput").setText("ex-264-aa")
    dialog.findChild(QLineEdit, "transportSetupDriverNameInput").setText("Segundo chofer 264")
    dialog.findChild(QPushButton, "saveTransportSetupButton").click()
    app.processEvents()

    driver = Driver.get(Driver.name == "Segundo chofer 264")

    assert dialog.result() == dialog.Accepted
    assert Carrier.select().where(Carrier.name == "Transporte existente 264").count() == 1
    assert Truck.select().where(Truck.domain == "EX264AA").count() == 1
    assert driver.carrier == carrier
    assert driver.usual_truck == truck


def test_transport_master_pages_expose_guided_setup_button_by_permission(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.master_abm import build_master_abm_page, master_abm_configs

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()

    admin_profile = UserProfile.get(UserProfile.name == "Administrador")
    admin = User.create(username="admin_issue264", password_hash="x", profile=admin_profile)
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
    readonly = User.create(username="readonly_issue264", password_hash="x", profile=readonly_profile)
    readonly_page = build_master_abm_page(
        config=master_abm_configs()["carriers"],
        user=readonly,
        current_user=readonly.username,
    )
    app.processEvents()

    readonly_button = readonly_page.findChild(QPushButton, "transportSetupButtonnewCarrierButton")
    assert readonly_button is not None
    assert readonly_button.isEnabled() is False
