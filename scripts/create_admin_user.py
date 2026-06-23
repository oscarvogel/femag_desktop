import argparse

from app.config.database import initialize_runtime_database
from app.models import ALL_MODELS
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("password")
    args = parser.parse_args()

    db = initialize_runtime_database()
    db.connect(reuse_if_open=True)
    db.create_tables(ALL_MODELS, safe=True)
    PermissionService().seed_defaults()
    AuthService().create_user(args.username, args.password, "Administrador")
    print(f"Usuario administrador creado: {args.username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
