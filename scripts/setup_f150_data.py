"""Deja la base lista para generar el F150.

Importa la referencia DGR, los maestros del legacy y configura el origen DGR,
en ese orden, y al final verifica que quedo todo en su lugar.

    python scripts/setup_f150_data.py --dbf-dir "C:\\...\\sistema\\contable\\data"

El origen sale del ``LOCORIGEN`` del ``param.dbf`` del legacy (la localidad
desde la que salen los remitos de la empresa) y se puede forzar con
``--locality-code``.

Es idempotente: correrlo dos veces no cambia el resultado.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.services.f150_setup_service import F150SetupService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepara la base para que el F150 se pueda generar."
    )
    parser.add_argument(
        "--dbf-dir",
        required=True,
        help="Carpeta con los DBF del legacy (paises, provincias, localidades, locdgr, "
        "clientes, transporte, chofer, productos, param).",
    )
    parser.add_argument(
        "--param",
        help="Ruta del param.dbf para leer el LOCORIGEN. Por defecto, param.dbf "
        "de la carpeta --dbf-dir.",
    )
    parser.add_argument(
        "--locality-code",
        help="Codigo de localidad del origen DGR. Por defecto, el LOCORIGEN del param.dbf.",
    )
    parser.add_argument("--encoding", default="cp1252", help="Encoding DBF legacy, por defecto cp1252")
    parser.add_argument("--source-system", default="legacy_dbf", help="Identificador del sistema origen")
    parser.add_argument("--skip-dgr", action="store_true", help="No importar la referencia DGR")
    parser.add_argument("--skip-masters", action="store_true", help="No importar los maestros")
    parser.add_argument("--skip-origin", action="store_true", help="No configurar el origen DGR")
    parser.add_argument("--json", action="store_true", help="Salida en JSON")
    args = parser.parse_args(argv)

    dbf_dir = Path(args.dbf_dir)
    if not dbf_dir.is_dir():
        parser.error(f"La carpeta no existe: {dbf_dir}")
    param_path = Path(args.param) if args.param else dbf_dir / "param.dbf"

    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)
    try:
        report = F150SetupService().run(
            dbf_dir=dbf_dir,
            param_path=param_path if param_path.exists() else None,
            locality_code=args.locality_code,
            encoding=args.encoding,
            source_system=args.source_system,
            import_dgr=not args.skip_dgr,
            import_masters=not args.skip_masters,
            configure_origin=not args.skip_origin,
        )
    finally:
        if not database.is_closed():
            database.close()

    if args.json:
        print(json.dumps(
            {
                "dgr": report.dgr,
                "masters": report.masters,
                "origin": report.origin.__dict__ if report.origin else None,
                "checks": list(report.checks),
                "warnings": list(report.warnings),
                "remittances_ready": report.remittances_ready,
                "remittances_blocked": [
                    {"remittance": numero, "issues": list(problemas)}
                    for numero, problemas in report.remittances_blocked
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ))
    else:
        if report.dgr:
            print("Referencia DGR importada:")
            _print_resumen(report.dgr)
        if report.masters:
            print("Maestros importados:")
            _print_resumen(report.masters)
        print()
        print("Verificacion:")
        for check in report.checks:
            print(f"   {check}")
        if report.warnings:
            print()
            print("Avisos:")
            for warning in report.warnings:
                print(f"   - {warning}")
        if report.remittances_blocked:
            print()
            print("Remitos que todavia no pueden generar F150:")
            for numero, problemas in report.remittances_blocked:
                print(f"   {numero}: {', '.join(problemas)}")

    return 0 if report.ok else 1


def _print_resumen(resumen: dict) -> None:
    """Muestra los contadores que importan, sin esconder los que no se llaman igual."""
    for entidad, valores in sorted(resumen.items()):
        if not isinstance(valores, dict):
            continue
        partes = [
            f"{contador} {valores[contador]}"
            for contador in ("created", "updated", "imported", "skipped")
            if valores.get(contador)
        ]
        errores = len(valores.get("errors") or [])
        avisos = len(valores.get("warnings") or [])
        if errores:
            partes.append(f"{errores} errores")
        if avisos:
            partes.append(f"{avisos} avisos")
        extras = [
            f"{nombre} {cantidad}"
            for nombre, cantidad in sorted(valores.items())
            if nombre not in
            ("created", "updated", "imported", "skipped", "errors", "warnings")
            and isinstance(cantidad, int)
            and cantidad
        ]
        partes.extend(extras)
        print(f"   {entidad}: {', '.join(partes) if partes else 'sin cambios'}")


if __name__ == "__main__":
    raise SystemExit(main())
