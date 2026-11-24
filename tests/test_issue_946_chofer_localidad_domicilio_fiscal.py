"""#946: choferes y transportistas con Localidad DGR y domicilio fiscal (Rentas).

Cristina reporto que la ficha del chofer decia "Localidad DGR: Sin asignar" y
que en el formulario de edicion no habia celda para cargar el domicilio que
figura en Rentas. Como el F150 exige la localidad DGR del chofer y del
transportista, el operador quedaba bloqueado sin ninguna pantalla donde
corregirlo.

Estos tests cubren tres cosas:

- el ABM guarda y relee la localidad DGR y el domicilio fiscal;
- el F150 escribe el domicilio fiscal (Rentas) y, si no esta, el domicilio
  actual como respaldo;
- la generacion avisa que faltan datos **antes** de escribir el TXT, diciendo
  que falta y donde se corrige.
"""

import json
from datetime import date
from decimal import Decimal

import pytest

from app.importers.dgr_reference import DgrReferenceImporter
from app.models.dgr import DgrLocality
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.system import AppParameter
from app.services.f150_batch_service import F150BatchService
from app.services.f150_encoder import F150ValidationError
from app.services.remittance_service import RemittanceService

DGR_ROWS = {
    "paises": [{"IDPAIS": 200, "NOMBRE": "ARGENTINA", "ABR": "ARG"}],
    "provincias": [{"CODIGO": 14, "DESCRIPCIO": "MISIONES"}],
    "locdgr": [
        {"IDLOCALIDA": 61, "CODIGODGR": 61, "PROVINCIA": 14, "DPTO": 10,
         "DESCRIPCIO": "PUERTO RICO"}
    ],
    "localidades": [
        {"CODIGO": "2457", "LOCALIDAD": "PUERTO RICO", "CODIGODGR": 61,
         "PAISDGR": 200, "PROVDGR": 14, "DEPA": 10, "PROVINCIA": "MISIONES"}
    ],
}

DOMICILIO_FISCAL_CHOFER = "AV SAN FRANCISCO DE PAULA 907"
DOMICILIO_RESPALDO_CHOFER = "L. N. ALEM"
DOMICILIO_FISCAL_TRANSPORTE = "LOTE 105 B UMBERTO BAH"
DOMICILIO_RESPALDO_TRANSPORTE = "RUTA 12 KM 8"


def _escenario(
    db,
    *,
    carrier_address=None,
    carrier_fiscal_address=None,
    driver_address=None,
    driver_fiscal_address=None,
    with_driver_locality=True,
    with_carrier_locality=True,
):
    DgrReferenceImporter().import_rows(DGR_ROWS)
    AppParameter.create(key="f150.origin", value=json.dumps({"locality_code": "2426"}))
    locality = DgrLocality.get(DgrLocality.code == "2457")
    client = Client.create(name="Cliente 946", cuit="30-63634545-4", iva_condition="RI")
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones",
        city="Puerto Rico", address="Ruta 12 km 8", locality=locality,
    )
    carrier = Carrier.create(
        name="Transporte 946", cuit="20-23737702-9", codigo="0004",
        tipo="DIR", locality=locality if with_carrier_locality else None,
        address=carrier_address, fiscal_address=carrier_fiscal_address,
    )
    truck = Truck.create(
        domain="GET683", trailer_domain="KKV479", carrier=carrier,
        chassis_type="1", trailer_type="1",
    )
    driver = Driver.create(
        name="GIMENEZ JORGE ARIEL", carrier=carrier, usual_truck=truck,
        cuit="23-22840465-9", document="22840465",
        locality=locality if with_driver_locality else None,
        address=driver_address, fiscal_address=driver_fiscal_address,
    )
    product = Product.create(
        codigo="G-300", name="Almidon 946", unit="bolsa", precio_neto_base=18600.0,
        rh1="2", rh2="2", rh3="19", rh4="0", unidad_dgr="U",
    )
    service = RemittanceService("admin")
    remittance = service.create_manual(
        client=client, delivery_address=address, carrier=carrier, truck=truck,
        driver=driver, physical_point_of_sale="0001", physical_number="946",
        remittance_date=date(2026, 11, 23),
        items=[{"product": product, "quantity": Decimal("500")}],
    )
    return service.issue(remittance)


def _header(output):
    return output.read_bytes().decode("cp1252").splitlines()[0].split("@")


def test_abm_chofer_guarda_localidad_y_domicilio_fiscal(db):
    """La celda que faltaba: sin ella el operador no podia completar el F150."""
    from PyQt5.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton

    from app.ui.master_abm import DriverEntryDialog

    app = QApplication.instance() or QApplication([])
    DgrReferenceImporter().import_rows(DGR_ROWS)
    locality = DgrLocality.get(DgrLocality.code == "2457")
    carrier = Carrier.create(name="Transporte UI 946", cuit="20-23737702-9")

    dialog = DriverEntryDialog(current_user="admin")
    dialog.findChild(QComboBox, "driverCarrierInput").setCurrentIndex(
        dialog.findChild(QComboBox, "driverCarrierInput").findData(carrier.id)
    )
    dialog.findChild(QLineEdit, "driverNameInput").setText("Chofer UI 946")
    dialog.findChild(QLineEdit, "driverFiscalAddressInput").setText(
        DOMICILIO_FISCAL_CHOFER
    )
    dialog.findChild(QLineEdit, "driverAddressInput").setText(DOMICILIO_RESPALDO_CHOFER)
    combo = dialog.findChild(QComboBox, "driverLocalityInput")
    combo.setCurrentIndex(combo.findData(locality.id))
    dialog.findChild(QPushButton, "saveDriverButton").click()

    driver = Driver.get(Driver.name == "Chofer UI 946")
    assert driver.locality_id == locality.id
    assert driver.fiscal_address == DOMICILIO_FISCAL_CHOFER
    assert driver.address == DOMICILIO_RESPALDO_CHOFER

    # Al editar de nuevo, las dos celdas vuelven con lo que se guardo.
    edit = DriverEntryDialog(current_user="admin", record_id=driver.id)
    assert edit.findChild(QLineEdit, "driverFiscalAddressInput").text() == (
        DOMICILIO_FISCAL_CHOFER
    )
    combo = edit.findChild(QComboBox, "driverLocalityInput")
    assert combo.currentData() == locality.id


def test_abm_transportista_guarda_localidad_y_domicilio_fiscal(db):
    from PyQt5.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton

    from app.ui.master_abm import CarrierEntryDialog

    app = QApplication.instance() or QApplication([])
    DgrReferenceImporter().import_rows(DGR_ROWS)
    locality = DgrLocality.get(DgrLocality.code == "2457")

    dialog = CarrierEntryDialog(current_user="admin")
    dialog.findChild(QLineEdit, "carrierNameInput").setText("Transporte UI 946")
    dialog.findChild(QLineEdit, "carrierFiscalAddressInput").setText(
        DOMICILIO_FISCAL_TRANSPORTE
    )
    dialog.findChild(QLineEdit, "carrierAddressInput").setText(
        DOMICILIO_RESPALDO_TRANSPORTE
    )
    combo = dialog.findChild(QComboBox, "carrierLocalityInput")
    combo.setCurrentIndex(combo.findData(locality.id))
    dialog.findChild(QPushButton, "saveCarrierButton").click()

    carrier = Carrier.get(Carrier.name == "Transporte UI 946")
    assert carrier.locality_id == locality.id
    assert carrier.fiscal_address == DOMICILIO_FISCAL_TRANSPORTE
    assert carrier.address == DOMICILIO_RESPALDO_TRANSPORTE


def test_localidad_sin_elegir_no_se_inventa_una(db):
    """El combo arranca vacio: no se asigna la primera localidad de la lista."""
    from PyQt5.QtWidgets import QApplication, QComboBox

    from app.ui.master_abm import DriverEntryDialog

    app = QApplication.instance() or QApplication([])
    DgrReferenceImporter().import_rows(DGR_ROWS)

    dialog = DriverEntryDialog(current_user="admin")
    combo = dialog.findChild(QComboBox, "driverLocalityInput")
    assert combo.currentData() is None


def test_f150_escribe_el_domicilio_fiscal_del_chofer_y_del_transportista(db, tmp_path):
    """El domicilio fiscal (Rentas) es el que va al F150 (#792, igual que clientes)."""
    remittance = _escenario(
        db,
        carrier_address=DOMICILIO_RESPALDO_TRANSPORTE,
        carrier_fiscal_address=DOMICILIO_FISCAL_TRANSPORTE,
        driver_address=DOMICILIO_RESPALDO_CHOFER,
        driver_fiscal_address=DOMICILIO_FISCAL_CHOFER,
    )
    output = tmp_path / "f150-946.TXT"
    F150BatchService("admin").generate([remittance], output)
    header = _header(output)
    assert header[13] == DOMICILIO_FISCAL_TRANSPORTE
    assert header[31] == DOMICILIO_FISCAL_CHOFER


def test_f150_usa_el_domicilio_actual_como_respaldo(db, tmp_path):
    """Los choferes importados no tienen domicilio fiscal: no se rompe nada."""
    remittance = _escenario(
        db,
        carrier_address=DOMICILIO_RESPALDO_TRANSPORTE,
        driver_address=DOMICILIO_RESPALDO_CHOFER,
    )
    output = tmp_path / "f150-946.TXT"
    F150BatchService("admin").generate([remittance], output)
    header = _header(output)
    assert header[13] == DOMICILIO_RESPALDO_TRANSPORTE
    assert header[31] == DOMICILIO_RESPALDO_CHOFER


def test_validacion_no_bloquea_con_domicilio_fiscal_sin_respaldo(db):
    remittance = _escenario(
        db,
        carrier_fiscal_address=DOMICILIO_FISCAL_TRANSPORTE,
        driver_fiscal_address=DOMICILIO_FISCAL_CHOFER,
    )
    assert F150BatchService.validation_issues(remittance) == []


def test_validacion_bloquea_sin_localidad_y_nombra_al_chofer(db):
    """El error tiene que decir de quien es, no solo que algo falta."""
    remittance = _escenario(
        db,
        carrier_address=DOMICILIO_RESPALDO_TRANSPORTE,
        driver_address=DOMICILIO_RESPALDO_CHOFER,
        with_driver_locality=False,
    )
    issues = F150BatchService.validation_issues(remittance)
    assert any(
        issue.startswith("chofer: falta localidad DGR")
        and "GIMENEZ JORGE ARIEL" in issue
        for issue in issues
    )


def test_generacion_avisa_que_faltan_datos_antes_de_escribir(db, tmp_path):
    """No se abre el dialogo de guardado ni se escribe un TXT incompleto."""
    remittance = _escenario(
        db,
        carrier_address=DOMICILIO_RESPALDO_TRANSPORTE,
        driver_address=DOMICILIO_RESPALDO_CHOFER,
        with_driver_locality=False,
    )
    output = tmp_path / "f150-946.TXT"
    with pytest.raises(F150ValidationError) as error:
        F150BatchService("admin").generate([remittance], output)
    message = str(error.value)
    assert message.startswith("Faltan datos para generar el F150:")
    assert "chofer: falta localidad DGR" in message
    assert "GIMENEZ JORGE ARIEL" in message
    assert not output.exists()


def test_mensaje_pendiente_explica_donde_corregir():
    """El operador tiene que saber donde corregir, no solo que algo falta."""
    message = F150BatchService.pending_message(
        "0001-946", ["chofer: falta localidad DGR — GIMENEZ JORGE ARIEL"]
    )
    assert "0001-946" in message
    assert "chofer: falta localidad DGR — GIMENEZ JORGE ARIEL" in message
    assert "Maestros" in message
    assert "Choferes" in message
    assert "Corregir datos DGR" in message
