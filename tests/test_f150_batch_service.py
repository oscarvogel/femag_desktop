from datetime import date
from decimal import Decimal

import pytest

from app.models.audit import AuditLog
from app.models.dgr import DgrCountry, DgrLocality
from app.models.f150 import F150Batch, F150BatchRemittance
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.remittances import Remittance
from app.models.system import AppParameter
from app.services.f150_batch_service import F150BatchService
from app.services.f150_encoder import F150ValidationError
from app.services.remittance_service import RemittanceService


def _issued_remittance():
    country = DgrCountry.create(legacy_id=200, name="ARGENTINA", abbr="ARG")
    locality = DgrLocality.create(
        code="0061", name="PUERTO RICO", dgr_id=61, dgr_code=61,
        department_code=10, province_code=14, country=country,
    )
    AppParameter.create(key="f150.origin", value='{"locality_code": "0002"}')
    client = Client.create(name="Cliente F150", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12 km 8",
        locality=locality,
    )
    carrier = Carrier.create(
        name="Transporte F150", cuit="30777777770", codigo="0001",
        tipo="DIR", locality=locality, address="Ruta 12 km 8",
    )
    truck = Truck.create(
        domain="AB123CD", trailer_domain="AC456EF", carrier=carrier,
        chassis_type="1", trailer_type="1",
    )
    driver = Driver.create(
        name="Chofer F150",
        carrier=carrier,
        usual_truck=truck,
        cuit="20123456789",
        document="12345678",
        locality=locality,
        address="Posadas",
    )
    product = Product.create(
        codigo="ALM",
        name="Almidon F150",
        unit="KG",
        precio_neto_base=12.5,
        rh1="2",
        rh2="2",
        rh3="19",
        rh4="0",
        unidad_dgr="KG",
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
    # El legacy escribe entre la 4a clasificacion y la unidad una descripcion de
    # ancho fijo de 50 caracteres que deja vacia: el codigo del producto no va al F150.
    assert lines[1].endswith(f"@{'':<50}@KG@1,250@12.50@15,625.00@")
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


def test_recover_txt_copies_exact_bytes_without_second_batch(db, tmp_path):
    import hashlib

    remittance = _issued_remittance()
    service = F150BatchService("admin")
    original = tmp_path / "original.TXT"
    batch = service.generate([remittance], original)
    restored = tmp_path / "subfolder" / "copia.TXT"
    result = service.recover_txt(batch, restored)

    assert result == restored
    assert restored.read_bytes() == original.read_bytes()
    assert hashlib.sha256(restored.read_bytes()).hexdigest() == batch.sha256
    assert F150Batch.select().count() == 1
    assert F150BatchRemittance.select().count() == 1
    refreshed = F150Batch.get_by_id(batch.id)
    assert refreshed.file_path == batch.file_path
    assert refreshed.sha256 == batch.sha256
    assert AuditLog.select().where(AuditLog.action == "recuperar_txt").count() == 1
    with pytest.raises(FileExistsError):
        service.recover_txt(batch, restored)


def test_recover_txt_refuses_missing_or_tampered_original(db, tmp_path):
    remittance = _issued_remittance()
    service = F150BatchService("admin")
    original = tmp_path / "original.TXT"
    batch = service.generate([remittance], original)
    original.write_bytes(b"alterado")
    with pytest.raises(F150ValidationError, match="SHA-256"):
        service.recover_txt(batch, tmp_path / "copia.TXT")
    original.unlink()
    assert service.recover_txt(batch, tmp_path / "copia.TXT").read_bytes()
    assert (tmp_path / "copia.TXT").read_bytes() != b"alterado"


def test_regenerate_missing_file_matches_original_and_preserves_batch(db, tmp_path):
    remittance = _issued_remittance()
    service = F150BatchService("admin")
    original = tmp_path / "first.TXT"
    batch = service.generate([remittance], original)
    expected = original.read_bytes()
    original.unlink()
    recovered = service.recover_txt(batch, tmp_path / "second.TXT")
    assert recovered.read_bytes() == expected
    assert F150Batch.select().count() == 1
    assert F150BatchRemittance.select().count() == 1


def test_regenerate_missing_file_rejects_changed_data(db, tmp_path):
    remittance = _issued_remittance()
    service = F150BatchService("admin")
    original = tmp_path / "first.TXT"
    batch = service.generate([remittance], original)
    original.unlink()
    remittance.observations = "CAMBIO POSTERIOR"
    remittance.save()
    target = tmp_path / "second.TXT"
    with pytest.raises(F150ValidationError, match="no coincide"):
        service.recover_txt(batch, target)
    assert not target.exists()
    assert F150Batch.select().count() == 1
