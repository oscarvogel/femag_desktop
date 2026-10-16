"""Control permanente: re-codifica el corpus F150 real y lo compara byte a byte.

El corpus del sistema anterior trae CUIT, DNI y domicilios, asi que **no se
versiona**: vive en la maquina del operador y este script lo recorre sin copiar
sus datos a ningun lado. Los valores que difieren se reportan solo como huella,
nunca como texto.

Que el codificador reconstruya los archivos reales byte a byte es lo que
sostiene el contrato fiscal del formato. El golden master anonimizado de
``tests/fixtures/f150/`` cubre el mismo contrato en CI, sin datos personales.

Uso:

    python scripts/verify_f150_corpus.py "C:\\ruta\\con\\los\\F150*.TXT"
    python scripts/verify_f150_corpus.py "C:\\contable\\F150-20190708.TXT"

Devuelve 0 si todos los archivos se reproducen identicos.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.f150_encoder import (  # noqa: E402
    F150Carrier, F150Driver, F150Encoder, F150Item, F150Location,
    F150Party, F150Remittance, F150Vehicle,
)

DEFAULT_CORPUS = r"C:\Programacion\dante\contable\F150*.TXT"


def redact(value: str) -> str:
    """Huella estable: permite comparar sin exponer el dato."""
    text = value.strip()
    if not text:
        return "<vacio>"
    if len(text) <= 3:
        return f"<{len(text)} car>"
    return f"<{len(text)} car sha={hashlib.sha256(text.encode('utf-8', 'replace')).hexdigest()[:8]}>"


def dec(value: str) -> str:
    return value.strip()


def num(value: str) -> Decimal:
    return Decimal(value.replace(",", ""))


def block(dept, dept_name, loc, loc_name, prov, country, country_name="") -> F150Location:
    return F150Location(
        department_code=dept, department_name=dept_name, locality_code=loc,
        locality_name=loc_name, province_code=prov, country_code=country,
        country_name=country_name,
    )


def parse(path: Path) -> list[F150Remittance]:
    """Vuelve el archivo real a snapshots, campo por campo, sin suponer nada."""
    text = path.read_bytes().decode(F150Encoder.encoding).rstrip("\r\n")
    lines = [line for line in text.split("\r\n") if line]
    headers = []
    for line in lines:
        r = line.split("@")
        if r[0][0] == "C":
            headers.append(
                {
                    "date": datetime.strptime(r[4], "%d-%m-%Y").date(),
                    "pos": r[3], "doc_type": r[2], "movement": r[5],
                    "observations": dec(r[26]),
                    "origin": F150Location(locality_code=dec(r[6])),
                    "destination": F150Party(
                        cuit=dec(r[39]), name=dec(r[40]), address=dec(r[41]),
                        door_number=dec(r[42]),
                        location=block(dec(r[43]), dec(r[44]), dec(r[45]),
                                       dec(r[46]), dec(r[47]), dec(r[48]), dec(r[49])),
                    ),
                    "carrier": F150Carrier(
                        cuit=dec(r[11]), name=dec(r[12]), carrier_type=dec(r[10]),
                        address=dec(r[13]), code=dec(r[14]),
                        location=block(dec(r[15]), dec(r[16]), dec(r[17]),
                                       dec(r[18]), dec(r[19]), dec(r[20])),
                    ),
                    "vehicle": F150Vehicle(
                        chassis_type=dec(r[21]), chassis_plate=dec(r[22]),
                        trailer_type=dec(r[23]), trailer_plate=dec(r[24]),
                        plate_country_code=dec(r[25]),
                    ),
                    "driver": F150Driver(
                        cuit=dec(r[27]), document_type=dec(r[28]),
                        document_number=dec(r[29]), name=dec(r[30]),
                        address=dec(r[31]), door_number=dec(r[32]),
                        location=block(dec(r[33]), dec(r[34]), dec(r[35]),
                                       dec(r[36]), dec(r[37]), dec(r[38])),
                    ),
                    "number": None, "items": [],
                }
            )
            continue
        current = headers[-1]
        current["number"] = r[5]
        current["items"].append(
            F150Item(
                category_1=dec(r[6]), category_2=dec(r[7]), category_3=dec(r[8]),
                category_4=dec(r[9]), item_code="", unit=dec(r[11]),
                quantity=num(r[12]), unit_price=num(r[13]), total=num(r[14]),
                description=r[10],
            )
        )
    return [
        F150Remittance(
            document_date=h["date"], point_of_sale=h["pos"], number=h["number"],
            origin=h["origin"], destination=h["destination"], carrier=h["carrier"],
            vehicle=h["vehicle"], driver=h["driver"], items=tuple(h["items"]),
            observations=h["observations"], document_type=h["doc_type"],
            movement_type=h["movement"],
        )
        for h in headers
    ]


def compare(expected: bytes, generated: bytes) -> str:
    limit = min(len(expected), len(generated))
    offset = limit
    for index in range(limit):
        if expected[index] != generated[index]:
            offset = index
            break
    line_number = expected[:offset].count(b"\r\n") + 1
    line_start = expected.rfind(b"\r\n", 0, offset) + 2
    end = expected.find(b"\r\n", line_start)
    expected_line = expected[line_start : end if end > 0 else len(expected)]
    other_start = generated.rfind(b"\r\n", 0, offset) + 2
    other_end = generated.find(b"\r\n", other_start)
    generated_line = generated[other_start : other_end if other_end > 0 else len(generated)]
    field = expected_line[: offset - line_start].count(b"@") + 1
    parts = []
    if field <= len(expected_line.split(b"@")) and field <= len(generated_line.split(b"@")):
        a = expected_line.split(b"@")[field - 1]
        b = generated_line.split(b"@")[field - 1]
        parts.append(f"esperado={redact(a.decode('cp1252', 'replace'))}")
        parts.append(f"generado={redact(b.decode('cp1252', 'replace'))}")
    return (
        f"linea={line_number} campo={field} offset={offset} "
        f"tokens={len(expected_line.split(b'@'))}/{len(generated_line.split(b'@'))} "
        f"bytes={len(expected)}/{len(generated)} " + " ".join(parts)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="archivos o patrones del corpus")
    parser.add_argument("--limit", type=int, default=0, help="muestra solo los primeros N")
    args = parser.parse_args()

    patterns = args.paths or [DEFAULT_CORPUS]
    files: list[Path] = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            files.extend(Path(match) for match in matches)
        else:
            files.append(Path(pattern))
    files = sorted({f for f in files if f.exists()})
    if not files:
        print("No se encontraron archivos F150 para verificar.")
        return 2

    encoder = F150Encoder()
    ok = 0
    failures = []
    for path in files:
        raw = path.read_bytes()
        try:
            generated = encoder.encode(parse(path)).encode(encoder.encoding)
        except (InvalidOperation, IndexError, ValueError, UnicodeDecodeError) as exc:
            failures.append((path.name, f"no se pudo reconstruir: {type(exc).__name__}"))
            continue
        if generated == raw:
            ok += 1
        else:
            failures.append((path.name, compare(raw, generated)))

    print(f"archivos verificados : {len(files)}")
    print(f"identicos byte a byte: {ok}")
    print(f"con diferencias      : {len(failures)}")
    shown = failures if not args.limit else failures[: args.limit]
    for name, detail in shown:
        print(f"  [difiere] {name}: {detail}")
    if len(shown) < len(failures):
        print(f"  ... y {len(failures) - len(shown)} mas")
    if failures:
        print()
        print("El contrato del formato cambio: revisar app/services/f150_encoder.py")
        print("antes de tocar nada. No ajustes a ojo contra un archivo real.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
