from datetime import date
from decimal import Decimal

import pytest

from app.models.audit import AuditLog
from app.models.f150 import F150Batch, F150BatchRemittance
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.remittances import Remittance
from app.services.f150_batch_service import F150BatchService
from app.services.f150_encoder import F150ValidationError
from app.services.remittance_service import RemittanceService


def _issued_remittance():
    client = Client.create(name="Cliente F150", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12 km 8",
    )
    carrier = Carrier.create(name="Transporte F150", cuit="30777777770")
    truck = Truck.create(domain="AB123CD", trailer_domain="AC456EF", carrier=carrier)
    driver = Driver.create(
        name="Chofer F150",
        carrier=carrier,
        usual_truck=truck,
        cuit="20123456789",
        document="12345678",
    )
    product = Product.create(
        codigo="ALM",
        name="Almidon F150",
        unit="KG",
        precio_neto_base=12.5,
    )
    service = RemittanceService("admin")
    remittance = service.create_manual(
        client=client,
        delivery_address=address,
        carrier=carrier,
        truck=truck,
        driver=driver,
        physical_point_of_sale="0001",
        physical_number="1068",
        remittance_date=date(2026, 8, 23),
        items=[{"product": product, "quantity": Decimal("1250")}],
    )
    return service.issue(remittance)


def test_generate_persists_batch_snapshot_audit_and_file(db, tmp_path):
    remittance = _issued_remittance()
    output = tmp_path / "f150-20260823.TXT"
    batch = F150BatchService("admin").generate(
        [remittance], output, process_date=date(2026, 8, 23)
    )
    assert batch.batch_number == "F150-00000001"
    assert batch.remittance_count == 1
    assert batch.detail_count == 1
    assert output.exists()
    lines = output.read_bytes().decode("cp1252").splitlines()
    assert lines[0].startswith("C1F15023082026@1@12@0001@")
    assert lines[1].endswith("@ALM@KG@1,250@12.50@15,625.00@")
    inclusion = F150BatchRemittance.get()
    assert inclusion.remittance_id == remittance.id
    assert inclusion.snapshot["identity"] == "0001-00001068"
    audit = AuditLog.get(AuditLog.module == "F150")
    assert audit.action == "generar"


def test_generate_rejects_remittance_already_included(db, tmp_path):
    remittance = _issued_remittance()
    service = F150BatchService("admin")
    service.generate([remittance], tmp_path / "first.TXT")
    with pytest.raises(F150ValidationError, match="ya fue incluido"):
        service.generate([remittance], tmp_path / "second.TXT")
    assert F150Batch.select().count() == 1


def test_validation_rejects_draft_and_missing_transport_data(db):
    remittance = _issued_remittance()
    remittance.status = Remittance.STATUS_DRAFT
    remittance.carrier = None
    remittance.carrier_cuit = None
    remittance.save()
    issues = F150BatchService.validation_issues(remittance)
    assert "debe estar emitido" in issues
    assert "falta transportista con CUIT" in issues
