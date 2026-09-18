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
    location = F150Location(locality_code="0001", locality_name="Posadas", province_code="54", country_code="ARG")
    detail = items or (
        F150Item(
            category_1="01", category_2="02", category_3="03", category_4="04",
            item_code="ALM", unit="KG", quantity=Decimal("1250"),
            unit_price=Decimal("12.50"), total=Decimal("15625.00"),
        ),
    )
    return F150Remittance(
        document_date=date(2026, 8, 23),
        point_of_sale="0001",
        number=number,
        origin=location,
        destination=F150Party(cuit="30712345678", name="Cliente Demo", address="Ruta 12", location=location),
        carrier=F150Carrier(cuit="30777777770", name="Transporte Norte", location=location),
        vehicle=F150Vehicle(chassis_plate="AB123CD", trailer_plate="AC456EF"),
        driver=F150Driver(cuit="20123456789", name="Juan Perez", document_number="12345678", location=location),
        items=tuple(detail),
    )


def test_encode_generates_header_and_detail():
    content = F150Encoder().encode([_remittance()])
    lines = content.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("C1F15023082026@1@12@0001@23-08-2026@SAL@")
    assert lines[1].endswith("@ALM@KG@1,250@12.50@15,625.00@")
    assert content.endswith("\r\n")


def test_encode_rejects_duplicates():
    remittance = _remittance()
    with pytest.raises(F150ValidationError, match="esta repetido"):
        F150Encoder().encode([remittance, remittance])


def test_write_does_not_overwrite(tmp_path):
    output = tmp_path / F150Encoder.suggested_filename(date(2026, 8, 23))
    F150Encoder().write([_remittance()], output)
    with pytest.raises(FileExistsError):
        F150Encoder().write([_remittance()], output)


LEGACY_HEADER = (
    "C1F15001102018@1@12@0001@01-10-2018@SAL@0002@0001@ARG@01@DIR@"
    "20-23737702-9@VOGEL RICARDO ARNOLDO@P. MARTIN HAHN Y RUTA NAC 12@0004@"
    "0010@@0061@PUERTO RICO@14@ARG@1@GET683@1@KKV479@ARG@@20-30717891-6@DNI@"
    "30717891@BOSING SERGIO ANDRES@RUIZ DE MONTOYA@@0010@@0062@"
    "RUIZ DE MONTOYA@14@ARG@30-63634545-4@CATTER MEAT S.A@CORDOBA AV. 836@@"
    "0000@@0001@CAPITAL FEDERAL@01@ARG@ARGENTINA"
)
LEGACY_DETAIL = (
    "D1F15001102018@2@01-10-2018@12@0001@00003894@2@2@19@0@@U@900@700.00@"
    "630,000.00@"
)


def _legacy_like_remittance():
    dest_location = F150Location(
        locality_code="0001",
        locality_name="CAPITAL FEDERAL",
        department_code="0000",
        province_code="01",
        country_code="ARG",
        country_name="ARGENTINA",
    )
    return F150Remittance(
        document_date=date(2018, 10, 1),
        point_of_sale="0001",
        number="00003894",
        origin=F150Location(locality_code="0002"),
        destination=F150Party(
            cuit="30-63634545-4",
            name="CATTER MEAT S.A",
            address="CORDOBA AV. 836",
            location=dest_location,
        ),
        carrier=F150Carrier(
            cuit="20-23737702-9",
            name="VOGEL RICARDO ARNOLDO",
            address="P. MARTIN HAHN Y RUTA NAC 12",
            code="0004",
            carrier_type="DIR",
            location=F150Location(
                department_code="0010",
                locality_code="0061",
                locality_name="PUERTO RICO",
                province_code="14",
                country_code="ARG",
            ),
        ),
        vehicle=F150Vehicle(
            chassis_plate="GET683",
            trailer_plate="KKV479",
            chassis_type="1",
            trailer_type="1",
            plate_country_code="ARG",
        ),
        driver=F150Driver(
            cuit="20-30717891-6",
            name="BOSING SERGIO ANDRES",
            document_number="30717891",
            address="RUIZ DE MONTOYA",
            location=F150Location(
                department_code="0010",
                locality_code="0062",
                locality_name="RUIZ DE MONTOYA",
                province_code="14",
                country_code="ARG",
            ),
        ),
        items=(
            F150Item(
                category_1="2",
                category_2="2",
                category_3="19",
                category_4="0",
                item_code="",
                unit="U",
                quantity=Decimal("900"),
                unit_price=Decimal("700.00"),
                total=Decimal("630000.00"),
            ),
        ),
    )


def test_encode_header_matches_legacy_layout_byte_for_byte():
    """La C legacy tiene 49 campos y termina sin @ (ver f150.scx Imprimir1.Click)."""
    content = F150Encoder().encode([_legacy_like_remittance()])
    lines = content.splitlines()
    assert len(lines) == 2
    assert lines[0] == LEGACY_HEADER
    assert not lines[0].endswith("@")
    assert lines[1] == LEGACY_DETAIL
    assert content.endswith("\r\n")
