import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import build_sqlite_database, bind_database
from app.config.schema import ensure_runtime_schema
from app.models.security import User
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService


def main() -> int:
    db_path = Path("femag_demo.sqlite3")
    if db_path.exists():
        db_path.unlink()
        print(f"Database eliminada: {db_path}")

    database = build_sqlite_database()
    bind_database(database)
    database.connect(reuse_if_open=True)
    ensure_runtime_schema(database)
    PermissionService().seed_defaults()

    if not User.get_or_none(User.username == "demo"):
        AuthService().create_user("demo", "demo", "Administrador")

    from app.ui.desktop_app import _seed_demo_masters
    _seed_demo_masters()

    print("Demo reset completado.")
    print("Usuario: demo")
    print("Clave: demo")
    print("Ejecutar: python -m app.main --demo-ui")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
