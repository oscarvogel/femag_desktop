"""Compara un archivo F150 generado contra una muestra real, fuera del repositorio.

El golden master real (``F.150-05-10-2026B.TXT``) contiene CUIT, DNI y
domicilios, asi que no se versiona. Este script lo compara en la maquina del
operador sin copiar sus datos a ningun lado y sin imprimir PII: reporta solo
posicion, tipo de registro, numero de campo y una huella de los valores.

Uso:

    python scripts/compare_f150_golden_master.py "C:\\ruta\\F.150-05-10-2026B.TXT"

    python scripts/compare_f150_golden_master.py --generate "C:\\ruta\\F150-generado.TXT" \\
        --master "C:\\ruta\\F.150-05-10-2026B.TXT"

Sin argumentos compara la muestra contra si misma para describir el contrato.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.f150_encoder import F150Encoder  # noqa: E402


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()[:12]


def redact(value: str) -> str:
    """Huella estable del valor: permite comparar sin exponer el dato."""
    text = value.strip()
    if not text:
        return "<vacio>"
    if len(text) <= 3:
        return f"<{len(text)} car>"
    return f"<{len(text)} car sha={digest(text.encode('utf-8', 'replace'))}>"


def describe(path: Path) -> None:
    raw = read_bytes(path)
    try:
        text = raw.decode(F150Encoder.encoding)
    except UnicodeDecodeError:
        print("ERROR: el archivo no decodifica como CP1252.")
        raise SystemExit(2) from None
    print(f"archivo            : {path.name}")
    print(f"bytes              : {len(raw)}")
    print(f"sha256             : {digest(raw)}")
    print(f"termina con CRLF   : {text.endswith(chr(13) + chr(10))}")
    print(f"usa CRLF           : {chr(13) + chr(10) in text}")
    print(f"caracteres > 0x7F  : {sorted({hex(ord(c)) for c in text if ord(c) > 126})}")
    lines = [line for line in text.rstrip("\r\n").split("\r\n") if line]
    headers = [line for line in lines if line.startswith("C")]
    details = [line for line in lines if line.startswith("D")]
    print(f"registros C / D    : {len(headers)} / {len(details)}")
    print(f"tokens por C       : {sorted({len(l.split('@')) for l in headers})}")
    print(f"tokens por D       : {sorted({len(l.split('@')) for l in details})}")
    print(f"C con @ final      : {sorted({l.endswith('@') for l in headers})}")
    print(f"D con @ final      : {sorted({l.endswith('@') for l in details})}")
    widths = {len(line.split('@')[10]) for line in details}
    blanks = {line.split('@')[10] for line in details}
    print(f"ancho campo descr. : {sorted(widths)}  todo-espacios={blanks == {' ' * 50}}")
    print(f"ancho punto venta  : {sorted({len(l.split('@')[3]) for l in headers})}")
    print(f"ancho nro remito   : {sorted({len(l.split('@')[5]) for l in details})}")
    units = {line.split("@")[11] for line in details}
    print(f"unidades           : {sorted(units)}")
    print()


def compare(expected_path: Path, actual_path: Path) -> int:
    expected = read_bytes(expected_path)
    actual = read_bytes(actual_path)
    print(f"esperado: {expected_path.name} ({len(expected)} bytes, {digest(expected)})")
    print(f"generado: {actual_path.name} ({len(actual)} bytes, {digest(actual)})")
    if expected == actual:
        print("RESULTADO: identico byte a byte.")
        return 0

    limit = min(len(expected), len(actual))
    offset = limit
    for index in range(limit):
        if expected[index] != actual[index]:
            offset = index
            break
    line_number = expected[:offset].count(b"\r\n") + 1
    line_start = expected.rfind(b"\r\n", 0, offset) + 2
    line_end = expected.find(b"\r\n", line_start)
    expected_line = expected[line_start : line_end if line_end > 0 else len(expected)]
    other_start = actual.rfind(b"\r\n", 0, offset) + 2
    other_end = actual.find(b"\r\n", other_start)
    actual_line = actual[other_start : other_end if other_end > 0 else len(actual)]
    field = expected_line[: offset - line_start].count(b"@") + 1
    expected_fields = expected_line.split(b"@")
    actual_fields = actual_line.split(b"@")
    same_kind = field < len(expected_fields) and field < len(actual_fields)
    print(f"primera diferencia : offset={offset} linea={line_number} campo={field}")
    if same_kind:
        print(f"  tipo registro    : {expected_fields[field - 1][:1].decode('ascii', 'replace')}")
        print(f"  valor esperado   : {redact(expected_fields[field - 1].decode('cp1252', 'replace'))}")
        print(f"  valor generado   : {redact(actual_fields[field - 1].decode('cp1252', 'replace'))}")
    print(f"  tokens esperados : {len(expected_fields)} / generados {len(actual_fields)}")
    print(f"  fin de archivo   : esperado={expected[-6:]!r} generado={actual[-6:]!r}")
    print(f"  longitud         : esperada={len(expected)} generada={len(actual)}")
    print()
    print("Diferencias por linea:")
    expected_lines = expected.rstrip(b"\r\n").split(b"\r\n")
    actual_lines = actual.rstrip(b"\r\n").split(b"\r\n")
    if len(expected_lines) != len(actual_lines):
        print(f"  cantidad de lineas: {len(expected_lines)} vs {len(actual_lines)}")
    shown = 0
    for number, (left, right) in enumerate(zip(expected_lines, actual_lines), start=1):
        if left == right:
            continue
        left_fields = left.split(b"@")
        right_fields = right.split(b"@")
        if len(left_fields) != len(right_fields):
            print(f"  linea {number}: {len(left_fields)} tokens vs {len(right_fields)}")
        for position, (a, b) in enumerate(zip(left_fields, right_fields), start=1):
            if a != b:
                print(
                    f"  linea {number} campo {position}: "
                    f"{redact(a.decode('cp1252', 'replace'))} vs "
                    f"{redact(b.decode('cp1252', 'replace'))}"
                )
        shown += 1
        if shown >= 20:
            print("  ...")
            break
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", nargs="?", help="muestra real F.150-...TXT")
    parser.add_argument("--master", dest="master_opt", help="muestra real")
    parser.add_argument("--generate", dest="generate", help="archivo generado")
    args = parser.parse_args()

    master = Path(args.master_opt or args.master) if (args.master_opt or args.master) else None
    if master is None:
        parser.error("falta la ruta de la muestra real")

    if args.generate:
        return compare(master, Path(args.generate))
    describe(master)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
