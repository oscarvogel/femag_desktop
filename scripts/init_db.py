from app.config.database import initialize_runtime_database
from app.models import ALL_MODELS
from app.services.migration_service import MigrationRunner
from app.services.permission_service import PermissionService


def main() -> int:
    db = initialize_runtime_database()
    db.connect(reuse_if_open=True)
    db.create_tables(ALL_MODELS, safe=True)
    MigrationRunner(db).run_pending()
    PermissionService().seed_defaults()
    print("Base FEMAG inicializada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
