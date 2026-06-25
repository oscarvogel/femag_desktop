import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema


def main() -> int:
    db = initialize_runtime_database()
    db.connect(reuse_if_open=True)
    ensure_runtime_schema(db)
    print("Base FEMAG inicializada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
