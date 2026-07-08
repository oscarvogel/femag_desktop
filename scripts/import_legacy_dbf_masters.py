import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.importers.legacy_dbf import LegacyDbfMasterImporter


ENTITIES = ("clients", "carriers", "drivers", "trucks", "products")


def build_paths_by_entity(args) -> dict[str, str]:
    return {entity: getattr(args, entity) for entity in ENTITIES if getattr(args, entity)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Importa maestros desde DBF legacy con trazabilidad e idempotencia."
    )
    parser.add_argument("--clients", help="Ruta DBF de clientes")
    parser.add_argument("--carriers", help="Ruta DBF de transportistas")
    parser.add_argument("--drivers", help="Ruta DBF de choferes")
    parser.add_argument("--trucks", help="Ruta DBF de camiones")
    parser.add_argument("--products", help="Ruta DBF de productos")
    parser.add_argument("--encoding", default="cp1252", help="Encoding DBF legacy, por defecto cp1252")
    parser.add_argument("--source-system", default="legacy_dbf", help="Identificador del sistema origen")
    args = parser.parse_args(argv)

    paths_by_entity = build_paths_by_entity(args)
    if not paths_by_entity:
        parser.error("Indicar al menos una fuente: --clients, --carriers, --drivers, --trucks o --products.")

    database = initialize_runtime_database()
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)
    try:
        summary = LegacyDbfMasterImporter().import_dbf_files(
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
