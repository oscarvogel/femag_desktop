import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.admin_target import (
    describe_admin_target,
    require_mysql_target,
    resolve_admin_target,
)
from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepara el esquema de la base FEMAG del puesto."
    )
    parser.add_argument(
        "--allow-sqlite",
        action="store_true",
        help=(
            "Permite preparar la SQLite de demo de un checkout. Sin esta opcion, "
            "si la configuracion resuelve a SQLite el script aborta."
        ),
    )
    args = parser.parse_args(argv)

    try:
        target = resolve_admin_target()
    except Exception as exc:
        print("No se pudo resolver la base destino. Revise la configuracion de conexion del puesto.", file=sys.stderr)
        return 1

    print(f"Base destino: {describe_admin_target(target)}")
    error = require_mysql_target(target, allow_sqlite=args.allow_sqlite)
    if error is not None:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    db = None
    try:
        db = initialize_runtime_database(target.settings)
        db.connect(reuse_if_open=True)
        ensure_runtime_schema(db)
    except Exception:
        print(
            "No se pudo preparar la base FEMAG. Revise la configuracion, "
            "los permisos administrativos y el estado del servidor MySQL.",
            file=sys.stderr,
        )
        return 1
    finally:
        if db is not None and not db.is_closed():
            db.close()
    print(
        "Base FEMAG preparada correctamente en "
        f"{describe_admin_target(target)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
