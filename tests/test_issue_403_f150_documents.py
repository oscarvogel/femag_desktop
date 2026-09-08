from datetime import date
from decimal import Decimal

import pytest

from app.models.dgr import DgrCountry, DgrLocality
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.system import AppParameter
from app.services.f150_batch_service import F150BatchService
from app.services.f150_encoder import F150ValidationError
from app.services.remittance_service import RemittanceService


def test_format_cuit_applies_legacy_dashes():
    assert F150BatchService._format_cuit("30777777770") == "30-77777777-0"
    assert F150BatchService._format_cuit("20-30717891-6") == "20-30717891-6"
    assert F150BatchService._format_cuit("") == ""
    assert F150BatchService._format_cuit("ABC") == "ABC"


def test_driver_document_derives_from_cuit_like_vfp():
    derive = F150BatchService._driver_document_number
    assert derive("20-30717891-6", "") == "30717891"
    assert derive("20123456789", "otra") == "12345678"
    assert derive("", "DNI12345678") == "12345678"
    assert derive("", "") == ""
    assert derive("ABC", "") == ""


def _issued_remittance(*, driver_cuit="20123456789", driver_document="12345678"):
    country = DgrCountry.create(legacy_id=200, name="ARGENTINA", abbr="ARG")
    locality = DgrLocality.create(
        code="0061", name="PUERTO RICO", dgr_id=61, dgr_code=61,
        department_code=10, province_code=14, country=country,
    )
    AppParameter.create(key="f150.origin", value='{"locality_code": "0002"}')
    client = Client.create(name="Cliente 403", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones",
        city="Posadas", address="Ruta 12 km 8", locality=locality,
    )
    carrier = Carrier.create(
        name="Transporte 403", cuit="30777777770", codigo="0001",
        tipo="DIR", locality=locality,
    )
    truck = Truck.create(
        domain="AB123CD", carrier=carrier, chassis_type="1", trailer_type="1",
    )
    driver = Driver.create(
        name="Chofer 403", carrier=carrier, usual_truck=truck,
        cuit=driver_cuit, document=driver_document, locality=locality,
    )
    product = Product.create(
        codigo="ALM", name="Almidon 403", unit="KG", precio_neto_base=12.5,
        rh1="2", rh2="2", rh3="19", rh4="0", unidad_dgr="KG",
    )
    service = RemittanceService("admin")
    remittance = service.create_manual(
        client=client, delivery_address=address, carrier=carrier, truck=truck,
        driver=driver, physical_point_of_sale="0001", physical_number="4030",
        remittance_date=date(2026, 9, 7),
        items=[{"product": product, "quantity": Decimal("10")}],
    )
    return service.issue(remittance)


def test_generate_emits_dashed_cuits_and_derived_document(db, tmp_path):
    remittance = _issued_remittance()
    output = tmp_path / "f150-403.TXT"
    F150BatchService("admin").generate([remittance], output)
    content = output.read_bytes().decode("cp1252")
    assert "@30-77777777-0@" in content
    assert "@30-71234567-8@" in content
    assert "@20-12345678-9@DNI@12345678@" in content


def test_generate_rejects_driver_without_usable_document(db, tmp_path):
    remittance = _issued_remittance()
    driver = remittance.driver
    driver.cuit = ""
    driver.document = ""
    driver.save()
    remittance.driver_document = ""
    remittance.save()
    with pytest.raises(F150ValidationError, match="falta CUIT o documento"):
        F150BatchService("admin").generate([remittance], tmp_path / "f150-403.TXT")


def test_generate_rejects_malformed_driver_cuit_without_document(db, tmp_path):
    remittance = _issued_remittance(driver_cuit="ABC", driver_document="")
    with pytest.raises(F150ValidationError, match="falta CUIT o documento"):
        F150BatchService("admin").generate([remittance], tmp_path / "f150-403.TXT")
