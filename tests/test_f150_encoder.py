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
