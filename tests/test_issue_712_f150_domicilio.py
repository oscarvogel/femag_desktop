"""#712: el domicilio del transportista y del chofer llegan al F150.

El formato exige esos dos campos (13 y 31 de la cabecera C) y el legacy los
trae, pero el modelo no los tenia: `Carrier` y `Driver` no guardaban domicilio,
el importador no mapeaba `DOMICILIO` de los DBF y la validacion no los exigia.
"""

import json
from datetime import date
from decimal import Decimal

import pytest

from app.importers.dgr_reference import DgrReferenceImporter
from app.importers.legacy_dbf import LegacyDbfMasterImporter
from app.models.dgr import DgrLocality
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.remittances import Remittance
from app.models.system import AppParameter
from app.services.f150_batch_service import F150BatchService
from app.services.f150_encoder import F150ValidationError
from app.services.master_service import MasterService
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

# Valores tomados de transporte.dbf y chofer.dbf, con el caracter CP1252 que
# el legacy escribe tal cual ("B\u00ba" es el ordinal, no un signo grado).
DOMICILIO_TRANSPORTE = "LOTE 105 B\u00ba OTTO BAHR"
DOMICILIO_CHOFER = "SAN FRANCISCO DE PAULA 907"


def _escenario(db, *, carrier_address, driver_address):
    DgrReferenceImporter().import_rows(DGR_ROWS)
    AppParameter.create(key="f150.origin", value=json.dumps({"locality_code": "2426"}))
    locality = DgrLocality.get(DgrLocality.code == "2457")
    client = Client.create(name="Cliente 712", cuit="30-63634545-4", iva_condition="RI")
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones",
        city="Puerto Rico", address="Ruta 12 km 8", locality=locality,
    )
    carrier = Carrier.create(
        name="Transporte 712", cuit="20-23737702-9", codigo="0004",
        tipo="DIR", locality=locality, address=carrier_address,
    )
    truck = Truck.create(
        domain="GET683", trailer_domain="KKV479", carrier=carrier,
        chassis_type="1", trailer_type="1",
    )
    driver = Driver.create(
        name="Chofer 712", carrier=carrier, usual_truck=truck,
        cuit="20-30717891-6", document="30717891", locality=locality,
        address=driver_address,
    )
    product = Product.create(
        codigo="G-300", name="Almidon 712", unit="bolsa", precio_neto_base=18600.0,
        rh1="2", rh2="2", rh3="19", rh4="0", unidad_dgr="U",
    )
    service = RemittanceService("admin")
    remittance = service.create_manual(
        client=client, delivery_address=address, carrier=carrier, truck=truck,
        driver=driver, physical_point_of_sale="0001", physical_number="712",
        remittance_date=date(2026, 10, 16),
        items=[{"product": product, "quantity": Decimal("500")}],
    )
    return service.issue(remittance)


def test_import_captures_domicilio_de_transporte_y_chofer(db):
    """`transporte.dbf` y `chofer.dbf` traen DOMICILIO; antes no se mapeaba."""
    LegacyDbfMasterImporter().import_rows({
        "carriers": [{"CODIGO": "0006", "NOMBRE": "Transporte 712",
                      "CUIT": "20-18525520-5", "TIPO": "DIR",
                      "DOMICILIO": DOMICILIO_TRANSPORTE}],
        "drivers": [{"CODIGO": "0031", "NOMBRE": "Chofer 712",
                     "CUIT": "23-22840465-9", "TRANSP": "0006",
                     "DOMICILIO": DOMICILIO_CHOFER}],
    })
    carrier = Carrier.get(Carrier.name == "Transporte 712")
    driver = Driver.get(Driver.name == "Chofer 712")
    assert carrier.address == DOMICILIO_TRANSPORTE
    assert driver.address == DOMICILIO_CHOFER


def test_import_colapsa_espacios_sobrantes_del_dbf(db):
    """El DBF es texto libre de ancho fijo y a veces trae relleno."""
    LegacyDbfMasterImporter().import_rows({
        "carriers": [{"CODIGO": "0006", "NOMBRE": "Transporte 712",
                      "DOMICILIO": "  AV 9 DE JULIO   "}],
    })
    assert Carrier.get(Carrier.name == "Transporte 712").address == "AV 9 DE JULIO"


def test_generacion_escribe_domicilio_en_campo_13_y_31(db, tmp_path):
    """Los dos campos que el formato exige y que antes salian vacios."""
    remittance = _escenario(
        db, carrier_address=DOMICILIO_TRANSPORTE, driver_address=DOMICILIO_CHOFER
    )
    output = tmp_path / "f150-712.TXT"
    F150BatchService("admin").generate([remittance], output)
    header = output.read_bytes().decode("cp1252").splitlines()[0].split("@")
    # Con el prefijo en la posicion 0, el domicilio del transportista es el 13
    # y el del chofer el 31.
    assert header[13] == DOMICILIO_TRANSPORTE
    assert header[31] == DOMICILIO_CHOFER


def test_validacion_reporta_falta_de_domicilio(db):
    remittance = _escenario(db, carrier_address=None, driver_address=None)
    issues = F150BatchService.validation_issues(remittance)
    assert "transportista: falta domicilio" in issues
    assert "chofer: falta domicilio" in issues


def test_generacion_bloquea_sin_domicilio(db, tmp_path):
    """Decision del operador: bloquear con mensaje claro, no generar incompleto."""
    remittance = _escenario(db, carrier_address=None, driver_address=None)
    with pytest.raises(F150ValidationError) as error:
        F150BatchService("admin").generate([remittance], tmp_path / "f150-712.TXT")
    message = str(error.value)
    assert "0001-00000712" in message
    assert "transportista: falta domicilio" in message
    assert "chofer: falta domicilio" in message


def test_domicilio_cargado_a_mano_habilita_la_generacion(db, tmp_path):
    """Los choferes de la operacion no estan en chofer.dbf: se cargan a mano."""
    MasterService("admin").create_carrier(
        "Transporte manual", cuit="20-18525520-5", address=DOMICILIO_TRANSPORTE
    )
    carrier = Carrier.get(Carrier.name == "Transporte manual")
    driver = MasterService("admin").create_driver(
        "Chofer manual", carrier=carrier, document="22840465",
        address=DOMICILIO_CHOFER,
    )
    assert carrier.address == DOMICILIO_TRANSPORTE
    assert driver.address == DOMICILIO_CHOFER

    remittance = _escenario(
        db, carrier_address=DOMICILIO_TRANSPORTE, driver_address=DOMICILIO_CHOFER
    )
    assert F150BatchService.validation_issues(remittance) == []


def test_remito_emitido_no_se_derrama_por_exigir_domicilio(db):
    """Exigir el domicilio es al generar el F150, no al emitir el remito."""
    remittance = _escenario(db, carrier_address=None, driver_address=None)
    assert remittance.status == Remittance.STATUS_ISSUED