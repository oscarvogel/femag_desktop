import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.models.security import User
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("password")
    args = parser.parse_args()

    db = initialize_runtime_database()
    db.connect(reuse_if_open=True)
    ensure_runtime_schema(db)
    PermissionService().seed_defaults()
    auth = AuthService()
    if User.select().exists():
        auth.create_user(args.username, args.password, "Administrador")
    else:
        auth.create_initial_admin(args.username, args.password)
    print(f"Usuario administrador creado: {args.username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
