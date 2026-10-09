"""Golden master F150: el archivo generado debe coincidir byte a byte con la muestra.

Las muestras de ``tests/fixtures/f150/`` son copias anonimizadas de archivos
reales del sistema anterior: conservan estructura, cantidad de campos, anchos,
espacios, CRLF y codificacion CP1252, pero no contienen ningun CUIT, DNI,
domicilio ni patente real. La autoridad fiscal sigue siendo el archivo real
``F.150-05-10-2026B.TXT``, que se compara por fuera del repositorio con
``scripts/compare_f150_golden_master.py``.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.f150_encoder import (
    DETAIL_DESCRIPTION_WIDTH,
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


FIXTURES = Path(__file__).parent / "fixtures" / "f150"


def _location(values: dict) -> F150Location:
    return F150Location(**values)


def _remittance(values: dict) -> F150Remittance:
    destination = values["destination"]
    return F150Remittance(
        document_date=date.fromisoformat(values["document_date"]),
        point_of_sale=values["point_of_sale"],
        number=values["number"],
        origin=_location(values["origin"]),
        destination=F150Party(
            cuit=destination["cuit"],
            name=destination["name"],
            address=destination["address"],
            door_number=destination["door_number"],
            location=F150Location(
                **{k: v for k, v in destination["location"].items()},
                country_name=destination["country_name"],
            ),
        ),
        carrier=F150Carrier(
            cuit=values["carrier"]["cuit"],
            name=values["carrier"]["name"],
            carrier_type=values["carrier"]["carrier_type"],
            address=values["carrier"]["address"],
            code=values["carrier"]["code"],
            location=_location(values["carrier"]["location"]),
        ),
        vehicle=F150Vehicle(**values["vehicle"]),
        driver=F150Driver(
            **{k: v for k, v in values["driver"].items() if k != "location"},
            location=_location(values["driver"]["location"]),
        ),
        items=tuple(
            F150Item(
                category_1=item["category_1"],
                category_2=item["category_2"],
                category_3=item["category_3"],
                category_4=item["category_4"],
                item_code=item["item_code"],
                unit=item["unit"],
                quantity=Decimal(item["quantity"]),
                unit_price=Decimal(item["unit_price"]),
                total=Decimal(item["total"]),
                description=item["description"],
            )
            for item in values["items"]
        ),
        observations=values["observations"],
        document_type=values["document_type"],
        movement_type=values["movement_type"],
    )


def _load(name: str) -> tuple[bytes, list[F150Remittance]]:
    expected = (FIXTURES / f"{name}.TXT").read_bytes()
    values = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return expected, [_remittance(row) for row in values]


def _first_difference(expected: bytes, generated: bytes) -> str:
    """Primera diferencia con offset, linea, campo y valor, sin exponer datos."""
    limit = min(len(expected), len(generated))
    offset = limit
    for index in range(limit):
        if expected[index] != generated[index]:
            offset = index
            break
    line_number = expected[:offset].count(b"\r\n") + 1
    line_start = expected.rfind(b"\r\n", 0, offset) + 2
    line = expected[line_start : expected.find(b"\r\n", line_start)]
    token_number = expected[line_start:offset].count(b"@") + 1
    return (
        f"offset={offset} linea={line_number} campo={token_number} "
        f"esperado={expected[offset:offset + 12]!r} generado={generated[offset:offset + 12]!r} "
        f"longitud_esperada={len(expected)} longitud_generada={len(generated)} "
        f"linea_esperada_tokens={len(line.split(b'@'))}"
    )


def _reference_encode(values: list[dict]) -> bytes:
    """Formateador independiente del contrato F150.

    No usa ``F150Encoder``: arma los registros a mano siguiendo el contrato
    verificado en los archivos reales, para que el test detects que el
    codificador y el contrato esten de acuerdo y no que uno repita al otro.
    """
    lines = []
    for header_number, document in enumerate(values, start=1):
        destination = document["destination"]
        carrier = document["carrier"]
        driver = document["driver"]
        vehicle = document["vehicle"]
        stamp = date.fromisoformat(document["document_date"]).strftime("%d%m%Y")
        shown = date.fromisoformat(document["document_date"]).strftime("%d-%m-%Y")
        point_of_sale = document["point_of_sale"].zfill(4)
        dest = destination["location"]
        carrier_location = carrier["location"]
        driver_location = driver["location"]
        header = [
            f"C{header_number}F150{stamp}",
            "1",
            document["document_type"],
            point_of_sale,
            shown,
            document["movement_type"],
            document["origin"]["locality_code"],
            dest["locality_code"],
            dest["country_code"],
            dest["province_code"],
            carrier["carrier_type"],
            carrier["cuit"],
            carrier["name"],
            carrier["address"],
            carrier["code"],
            carrier_location["department_code"],
            carrier_location["department_name"],
            carrier_location["locality_code"],
            carrier_location["locality_name"],
            carrier_location["province_code"],
            carrier_location["country_code"],
            vehicle["chassis_type"],
            vehicle["chassis_plate"],
            vehicle["trailer_type"],
            vehicle["trailer_plate"],
            vehicle["plate_country_code"],
            document["observations"],
            driver["cuit"],
            driver["document_type"],
            driver["document_number"],
            driver["name"],
            driver["address"],
            driver["door_number"],
            driver_location["department_code"],
            driver_location["department_name"],
            driver_location["locality_code"],
            driver_location["locality_name"],
            driver_location["province_code"],
            driver_location["country_code"],
            destination["cuit"],
            destination["name"],
            destination["address"],
            destination["door_number"],
            dest["department_code"],
            dest["department_name"],
            dest["locality_code"],
            dest["locality_name"],
            dest["province_code"],
            dest["country_code"],
            destination["country_name"],
        ]
        lines.append("@".join(header))
        for item in document["items"]:
            quantity = Decimal(item["quantity"])
            detail = [
                f"D{header_number}F150{stamp}",
                "2",
                shown,
                document["document_type"],
                point_of_sale,
                document["number"].zfill(8),
                item["category_1"],
                item["category_2"],
                item["category_3"],
                item["category_4"],
                item["description"].ljust(50)[:50],
                item["unit"],
                f"{quantity.quantize(Decimal('1')):,}",
                f"{Decimal(item['unit_price']).quantize(Decimal('0.01')):,}",
                f"{Decimal(item['total']).quantize(Decimal('0.01')):,}",
                "",
            ]
            lines.append("@".join(detail))
    return "\r\n".join(lines).encode("cp1252")


@pytest.mark.parametrize("name", ["golden_master_5c_6d", "golden_master_2c_3d"])
def test_generated_file_matches_golden_master_byte_for_byte(name):
    expected, remittances = _load(name)
    generated = F150Encoder().encode(remittances).encode(F150Encoder.encoding)
    assert generated == expected, _first_difference(expected, generated)


@pytest.mark.parametrize("name", ["golden_master_5c_6d", "golden_master_2c_3d"])
def test_independent_reference_formatter_agrees_with_golden_master(name):
    """El contrato F150 reconstruido a mano debe dar los mismos bytes."""
    expected, _ = _load(name)
    values = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    generated = _reference_encode(values)
    assert generated == expected, _first_difference(expected, generated)


@pytest.mark.parametrize("name", ["golden_master_5c_6d", "golden_master_2c_3d"])
def test_golden_master_shape_is_the_production_contract(name):
    """5 C + 6 D y 2 C + 3 D: una cabecera por remito, varios D por cabecera."""
    expected, remittances = _load(name)
    lines = expected.decode("cp1252").split("\r\n")
    headers = [line for line in lines if line.startswith("C")]
    details = [line for line in lines if line.startswith("D")]
    assert len(headers) == len(remittances)
    assert len(details) == sum(len(remittance.items) for remittance in remittances)
    assert all(len(line.split("@")) == 50 for line in headers)
    assert not any(line.endswith("@") for line in headers)
    assert all(len(line.split("@")) == 16 for line in details)
    assert all(line.endswith("@") for line in details)
    # un remito con dos renglones, como en la muestra operativa
    assert max(len(remittance.items) for remittance in remittances) == 2
    # el campo de ancho fijo entre la 4a clasificacion y la unidad
    for line in details:
        fields = line.split("@")
        assert len(fields[10]) == DETAIL_DESCRIPTION_WIDTH == 50
        assert fields[10] == " " * DETAIL_DESCRIPTION_WIDTH
    # numeracion con ceros a la izquierda
    assert all(len(line.split("@")[3]) == 4 for line in headers)
    assert all(len(line.split("@")[5]) == 8 for line in details)


def test_golden_master_keeps_cp1252_special_characters():
    """El sample real usa CP1252: los caracteres altos se escriben sin sustituciones."""
    _, remittances = _load("golden_master_5c_6d")
    remittance = remittances[0]
    object.__setattr__(
        remittance.destination, "name", "INDUSTRIA ANÓNIMA Nº 1"
    )
    generated = F150Encoder().encode([remittance]).encode(F150Encoder.encoding)
    assert "INDUSTRIA ANÓNIMA Nº 1".encode("cp1252") in generated
    assert "INDUSTRIA AN".encode("cp1252") in generated


def test_encode_does_not_append_trailing_line_ending():
    expected, remittances = _load("golden_master_2c_3d")
    content = F150Encoder().encode(remittances)
    assert not content.endswith("\r\n")
    assert content.count("\r\n") == expected.count(b"\r\n")


def test_point_of_sale_and_number_are_zero_padded():
    _, remittances = _load("golden_master_2c_3d")
    remittance = remittances[0]
    object.__setattr__(remittance, "point_of_sale", "1")
    object.__setattr__(remittance, "number", "10875")
    line = F150Encoder().encode([remittance]).split("\r\n")[1]
    fields = line.split("@")
    assert fields[4] == "0001"
    assert fields[5] == "00010875"


@pytest.mark.parametrize(
    "point_of_sale,number",
    [
        ("1", "123456789"),
        ("abc", "1"),
        ("", "1"),
        ("1", ""),
        ("0001", "12a45"),
    ],
)
def test_encode_rejects_invalid_numbering(point_of_sale, number):
    _, remittances = _load("golden_master_2c_3d")
    remittance = remittances[0]
    object.__setattr__(remittance, "point_of_sale", point_of_sale)
    object.__setattr__(remittance, "number", number)
    with pytest.raises(F150ValidationError):
        F150Encoder().encode([remittance])


def test_encode_rejects_inconsistent_amounts():
    _, remittances = _load("golden_master_2c_3d")
    item = remittances[0].items[0]
    object.__setattr__(item, "total", item.total + Decimal("1000"))
    with pytest.raises(F150ValidationError, match="no coincide"):
        F150Encoder().encode([remittances[0]])


def test_encode_rejects_non_positive_quantity():
    _, remittances = _load("golden_master_2c_3d")
    item = remittances[0].items[0]
    object.__setattr__(item, "quantity", Decimal("0"))
    object.__setattr__(item, "total", Decimal("0"))
    with pytest.raises(F150ValidationError, match="cantidad"):
        F150Encoder().encode([remittances[0]])


def test_encode_rejects_duplicate_remittance():
    _, remittances = _load("golden_master_2c_3d")
    with pytest.raises(F150ValidationError, match="esta repetido"):
        F150Encoder().encode([remittances[0], remittances[0]])


def test_several_details_share_one_header():
    _, remittances = _load("golden_master_2c_3d")
    lines = F150Encoder().encode(remittances).split("\r\n")
    assert [line[:1] for line in lines] == ["C", "D", "C", "D", "D"]
    assert lines[1][:14] == "D1F15013042019"
    assert lines[3][:14] == lines[4][:14] == "D2F15013042019"


def test_write_refuses_to_overwrite_existing_file(tmp_path):
    _, remittances = _load("golden_master_2c_3d")
    output = tmp_path / "F150.TXT"
    F150Encoder().write(remittances, output)
    assert output.read_bytes() == _load("golden_master_2c_3d")[0]
    with pytest.raises(FileExistsError):
        F150Encoder().write(remittances, output)
