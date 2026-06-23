import argparse

from app.config.database import initialize_runtime_database
from app.models import ALL_MODELS
from app.services.backup_service import BackupService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default="admin")
    args = parser.parse_args()

    db = initialize_runtime_database()
    db.connect(reuse_if_open=True)
    db.create_tables(ALL_MODELS, safe=True)
    result = BackupService().run_manual_backup(user=args.user)
    print(f"{result.status}: {result.file_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
