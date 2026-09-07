import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.importers.dgr_reference import DgrReferenceImporter


def build_paths_by_entity(args) -> dict[str, str]:
    return {
        entity: getattr(args, entity)
        for entity in ("paises", "provincias", "localidades", "locdgr")
        if getattr(args, entity)
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Importa tablas de referencia DGR desde DBF legacy (idempotente)."
    )
    parser.add_argument("--paises", help="Ruta DBF de países")
    parser.add_argument("--provincias", help="Ruta DBF de provincias")
    parser.add_argument("--localidades", help="Ruta DBF de localidades")
    parser.add_argument("--locdgr", help="Ruta DBF de códigos DGR")
    parser.add_argument("--encoding", default="cp1252", help="Encoding DBF legacy, por defecto cp1252")
    parser.add_argument("--source-system", default="legacy_dbf", help="Identificador del sistema origen")
    args = parser.parse_args(argv)

    paths_by_entity = build_paths_by_entity(args)
    if not paths_by_entity:
        parser.error("Indicar al menos una fuente: --paises, --provincias, --localidades o --locdgr.")

    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)
    try:
        summary = DgrReferenceImporter().import_dbf_files(
            paths_by_entity,
            source_system=args.source_system,
            encoding=args.encoding,
        )
    finally:
        if not database.is_closed():
            database.close()

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
