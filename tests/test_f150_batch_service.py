from datetime import date
from decimal import Decimal

import pytest

from app.models.audit import AuditLog
from app.models.dgr import DgrCountry, DgrLocality
from app.models.f150 import F150Batch, F150BatchRemittance
from app.models.load_orders import LoadOrderDestination, LoadOrderProduct
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
from app.models.remittances import Remittance
from app.models.system import AppParameter
from app.services.f150_batch_service import F150BatchService
from app.services.f150_encoder import F150ValidationError
from app.services.remittance_service import RemittanceService
from tests.f150_support import attach_frozen_prices


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
        tipo="DIR", locality=locality,
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
    # El precio fiscal sale del renglon de la orden, no del maestro.
    attach_frozen_prices(remittance, {product.id: Decimal("12.50")})
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
    assert lines[1].endswith(f"@0@{' ' * 50}@KG@1,250@12.50@15,625.00@")
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


def test_price_comes_from_the_operation_not_the_master(db, tmp_path):
    """El importe sale del precio congelado de la orden aunque el maestro cambie."""
    remittance = _issued_remittance()
    product = list(remittance.items)[0].product
    product.precio_neto_base = 999.0
    product.save()

    output = tmp_path / "f150-precio-operacion.TXT"
    F150BatchService("admin").generate([remittance], output)

    detail = output.read_bytes().decode("cp1252").splitlines()[1]
    assert detail.endswith("@1,250@12.50@15,625.00@")
    inclusion = F150BatchRemittance.get()
    assert inclusion.snapshot["items"][0]["unit_price"] == "12.50"


def test_generation_is_blocked_without_frozen_price(db, tmp_path):
    """Sin precio historico congelado no se emite: no se inventa ni el maestro."""
    remittance = _issued_remittance()
    remittance.source_order = None
    remittance.save(only=[Remittance.source_order])

    issues = F150BatchService.validation_issues(remittance)
    assert any("sin precio historico congelado" in issue for issue in issues)
    with pytest.raises(F150ValidationError, match="sin precio historico congelado"):
        F150BatchService("admin").generate([remittance], tmp_path / "bloqueado.TXT")
    assert not (tmp_path / "bloqueado.TXT").exists()
    assert F150Batch.select().count() == 0


def test_generation_is_blocked_when_frozen_price_is_zero(db, tmp_path):
    remittance = _issued_remittance()
    order = remittance.source_order
    for line in order.products:
        line.precio_neto_unitario = 0.0
        line.save()

    issues = F150BatchService.validation_issues(remittance)
    assert any("sin precio historico congelado" in issue for issue in issues)
    with pytest.raises(F150ValidationError, match="sin precio historico congelado"):
        F150BatchService("admin").generate([remittance], tmp_path / "cero.TXT")


def test_generation_is_blocked_when_frozen_price_is_ambiguous(db, tmp_path):
    """Dos renglones de la orden con precios distintos para el mismo producto."""
    remittance = _issued_remittance()
    order = remittance.source_order
    line = list(order.products)[0]
    LoadOrderProduct.create(
        order=order,
        destination=line.destination,
        product=line.product,
        quantity=1.0,
        unit=line.unit,
        precio_neto_unitario=88.0,
    )
    issues = F150BatchService.validation_issues(remittance)
    assert any("sin precio historico congelado" in issue for issue in issues)
    with pytest.raises(F150ValidationError, match="sin precio historico congelado"):
        F150BatchService("admin").generate([remittance], tmp_path / "ambiguo.TXT")


def test_generation_is_blocked_when_order_destination_does_not_match(db, tmp_path):
    """El precio de otro destino de la misma orden no alcanza."""
    remittance = _issued_remittance()
    order = remittance.source_order
    other = ClientAddress.create(
        client=remittance.client,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Ruta 12 km 20",
    )
    for line in list(order.products):
        line.destination = LoadOrderDestination.create(
            order=order, client=remittance.client, delivery_address=other
        )
        line.save()

    issues = F150BatchService.validation_issues(remittance)
    assert any("sin precio historico congelado" in issue for issue in issues)
    with pytest.raises(F150ValidationError, match="sin precio historico congelado"):
        F150BatchService("admin").generate([remittance], tmp_path / "otro.TXT")
