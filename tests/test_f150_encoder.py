from datetime import date
from decimal import Decimal

import pytest

from app.services.f150_encoder import (
    F150Carrier,
    F150Driver,
    F150Encoder,
    F150Item,
    F150Location,
    F150Party,
    F150Remittance,
    F150ValidationError,
    F150Vehicle,
)


def _remittance(*, number="00001068", items=None):
    origin = F150Location(
        locality_code="0001",
        locality_name="Posadas",
        province_code="54",
        country_code="ARG",
    )
    destination_location = F150Location(
        locality_code="0020",
        locality_name="Obera",
        department_code="0013",
        department_name="Obera",
        province_code="54",
        country_code="ARG",
        country_name="Argentina",
        postal_code="3360",
    )
    carrier_location = F150Location(
        locality_code="0001",
        locality_name="Posadas",
        department_code="0001",
        department_name="Capital",
        province_code="54",
        country_code="ARG",
    )
    detail = items or (
        F150Item(
            category_1="01",
            category_2="02",
            category_3="03",
            category_4="04",
            item_code="ALM",
            unit="KG",
            quantity=Decimal("1250"),
            unit_price=Decimal("12.50"),
            total=Decimal("15625.00"),
        ),
    )
    return F150Remittance(
        document_date=date(2026, 8, 23),
        point_of_sale="0001",
        number=number,
        origin=origin,
        destination=F150Party(
            cuit="30712345678",
            name="Cliente Demo FEMAG",
            address="Ruta 12 km 8",
            location=destination_location,
        ),
        carrier=F150Carrier(
            cuit="30777777770",
            name="Transporte Norte",
            carrier_type="01",
            address="Av. Uruguay 100",
            code="0007",
            location=carrier_location,
        ),
        vehicle=F150Vehicle(
            chassis_plate="AB123CD",
            trailer_plate="AC456EF",
            chassis_type="1",
            trailer_type="1",
            plate_country_code="ARG",
        ),
        driver=F150Driver(
            cuit="20123456789",
            name="Juan Perez",
            document_number="12345678",
            address="Calle 1",
            location=carrier_location,
        ),
        items=tuple(detail),
        observations="Entrega zafra 2026",
    )


def test_encode_uses_legacy_header_and_detail_records():
    content = F150Encoder().encode([_remittance()])

    lines = content.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("C1F15023082026@1@12@0001@23-08-2026@SAL@")
    assert "@30777777770@Transporte Norte@Av. Uruguay 100@0007@" in lines[0]
    assert lines[0].endswith("@ARG@Argentina@")
    assert lines[1] == (
        "D1F15023082026@2@23-08-2026@12@0001@00001068@01@02@03@04@"
        "ALM@KG@1,250@12.50@15,625.00@"
    )
    assert content.endswith("\r\n")


def test_encode_sanitizes_delimiter_and_line_breaks():
    remittance = _remittance()
    remittance = F150Remittance(
        **{**remittance.__dict__, "observations": "Carga@urgente\r\nControlada"}
    )

    header = F150Encoder().encode([remittance]).splitlines()[0]

    assert "Carga urgente  Controlada" in header


def test_encode_rejects_duplicate_remittances():
    remittance = _remittance()

    with pytest.raises(F150ValidationError, match="esta repetido"):
        F150Encoder().encode([remittance, remittance])


def test_encode_rejects_inconsistent_item_total():
    bad_item = F150Item(
        category_1="01",
        category_2="02",
        category_3="03",
        category_4="04",
        item_code="ALM",
        unit="KG",
        quantity=Decimal("2"),
        unit_price=Decimal("10"),
        total=Decimal("19"),
    )

    with pytest.raises(F150ValidationError, match="no coincide"):
        F150Encoder().encode([_remittance(items=(bad_item,))])


def test_write_uses_cp1252_and_does_not_overwrite(tmp_path):
    output = tmp_path / F150Encoder.suggested_filename(date(2026, 8, 23))
    remittance = _remittance()
    remittance = F150Remittance(
        **{**remittance.__dict__, "observations": "Camion verificado - Jose"}
    )

    written = F150Encoder().write([remittance], output)

    assert written == output
    assert b"Camion verificado - Jose" in output.read_bytes()
    with pytest.raises(FileExistsError):
        F150Encoder().write([remittance], output)
