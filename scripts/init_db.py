import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema


def main() -> int:
    db = None
    try:
        db = initialize_runtime_database()
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
    print("Base FEMAG preparada correctamente")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
