import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.database import initialize_runtime_database
from app.config.schema import ensure_runtime_schema
from app.services.backup_service import BackupService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default="admin")
    args = parser.parse_args()

    db = initialize_runtime_database()
    db.connect(reuse_if_open=True)
    ensure_runtime_schema(db)
    result = BackupService().run_manual_backup(user=args.user)
    print(f"{result.status}: {result.file_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
