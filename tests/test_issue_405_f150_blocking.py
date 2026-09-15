import json
from datetime import date
from decimal import Decimal

import pytest

from app.importers.dgr_reference import DgrReferenceImporter
from app.models.dgr import DgrLocality
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.system import AppParameter
from app.services.f150_batch_service import F150BatchService, F150ValidationError
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


def _coded_setup(**overrides):
    DgrReferenceImporter().import_rows(DGR_ROWS)
    AppParameter.create(key="f150.origin", value=json.dumps({"locality_code": "2426"}))
    locality = DgrLocality.get(DgrLocality.code == "2457")
    client = Client.create(name="Cliente 405", cuit="30-63634545-4", iva_condition="RI")
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones",
        city="Puerto Rico", address="Ruta 12 km 8",
        locality=None if overrides.get("address_without_locality") else locality,
    )
    carrier = Carrier.create(
        name="Transporte 405", cuit="20-23737702-9",
        codigo=None if overrides.get("carrier_without_codigo") else "0004",
        tipo=None if overrides.get("carrier_without_tipo") else "DIR",
        locality=locality,
    )
    truck = Truck.create(
        domain="GET683", trailer_domain="KKV479", carrier=carrier,
        chassis_type=None if overrides.get("truck_without_types") else "1",
        trailer_type=None if overrides.get("truck_without_types") else "1",
    )
    driver = Driver.create(
        name="Chofer 405", carrier=carrier, usual_truck=truck,
        cuit="20-30717891-6", document="30717891", locality=locality,
    )
    product = Product.create(
        codigo="G-300", name="Almidon 405", unit="bolsa", precio_neto_base=18600.0,
        rh1=None if overrides.get("product_without_codes") else "2",
        rh2=None if overrides.get("product_without_codes") else "2",
        rh3=None if overrides.get("product_without_codes") else "19",
        rh4=None if overrides.get("product_without_codes") else "0",
        unidad_dgr=None if overrides.get("product_without_codes") else "U",
    )
    service = RemittanceService("admin")
    remittance = service.create_manual(
        client=client, delivery_address=address, carrier=carrier, truck=truck,
        driver=driver, physical_point_of_sale="0001", physical_number="4050",
        remittance_date=date(2026, 9, 7),
        items=[{"product": product, "quantity": Decimal("10")}],
    )
    return service.issue(remittance)


def test_complete_remittance_has_no_issues_and_generates(db, tmp_path):
    remittance = _coded_setup()
    assert F150BatchService.validation_issues(remittance) == []
    output = tmp_path / "f150-405.TXT"
    F150BatchService("admin").generate([remittance], output)
    assert output.exists()


def test_missing_origin_parameter_blocks(db):
    remittance = _coded_setup()
    AppParameter.delete().execute()
    issues = F150BatchService.validation_issues(remittance)
    assert "falta origen DGR (parámetro f150.origin)" in issues


def test_missing_destination_locality_blocks(db):
    remittance = _coded_setup(address_without_locality=True)
    issues = F150BatchService.validation_issues(remittance)
    assert "destino: falta localidad DGR" in issues


def test_missing_carrier_codes_block(db):
    remittance = _coded_setup(carrier_without_codigo=True, carrier_without_tipo=True)
    issues = F150BatchService.validation_issues(remittance)
    assert "transportista: falta tipo" in issues
    assert "transportista: falta código" in issues


def test_missing_truck_types_block(db):
    remittance = _coded_setup(truck_without_types=True)
    issues = F150BatchService.validation_issues(remittance)
    assert "camión: falta tipo de chasis" in issues
    assert "camión: falta tipo de acoplado" in issues


def test_missing_product_codes_block(db):
    remittance = _coded_setup(product_without_codes=True)
    issues = F150BatchService.validation_issues(remittance)
    assert any("sin rubros DGR" in issue for issue in issues)
    assert any("sin unidad DGR" in issue for issue in issues)


def test_demo_like_remittance_without_codes_is_rejected(db, tmp_path):
    client = Client.create(name="Cliente demo", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones",
        city="Posadas", address="Ruta 12",
    )
    carrier = Carrier.create(name="Transporte demo", cuit="30777777771")
    truck = Truck.create(domain="ABC123", carrier=carrier)
    driver = Driver.create(name="Chofer demo", carrier=carrier, document="DNI12345678")
    product = Product.create(codigo="G-300", name="Demo 405", unit="bolsa",
                             precio_neto_base=18600.0)
    service = RemittanceService("admin")
    remittance = service.create_manual(
        client=client, delivery_address=address, carrier=carrier, truck=truck,
        driver=driver, physical_point_of_sale="0001", physical_number="4051",
        remittance_date=date(2026, 9, 7),
        items=[{"product": product, "quantity": Decimal("500")}],
    )
    issued = service.issue(remittance)
    issues = F150BatchService.validation_issues(issued)
    assert "falta origen DGR (parámetro f150.origin)" in issues
    assert "destino: falta localidad DGR" in issues
    assert "transportista: falta tipo" in issues
    assert "camión: falta tipo de chasis" in issues
    with pytest.raises(F150ValidationError):
        F150BatchService("admin").generate([issued], tmp_path / "f150-405.TXT")
