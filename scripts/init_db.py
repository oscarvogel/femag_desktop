from app.config.database import initialize_runtime_database
from app.models import ALL_MODELS


def main() -> int:
    db = initialize_runtime_database()
    db.connect(reuse_if_open=True)
    db.create_tables(ALL_MODELS, safe=True)
    print("Base FEMAG inicializada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
