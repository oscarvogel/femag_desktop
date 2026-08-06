from __future__ import annotations

import os
import sys
from pathlib import Path

from app.main import main


def configure_production_runtime() -> Path:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    runtime_dir = local_app_data / "FEMAG Desktop"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "outputs").mkdir(exist_ok=True)
    (runtime_dir / "backups").mkdir(exist_ok=True)
    os.chdir(runtime_dir)
    os.environ["APP_ENV"] = "production"
    os.environ["FEMAG_DB_ENGINE"] = "mysql"
    os.environ["FEMAG_SECURE_CONFIG"] = "1"
    os.environ["BACKUP_DIR"] = str(runtime_dir / "backups")
    return runtime_dir


def run() -> int:
    configure_production_runtime()
    args = sys.argv[1:] or ["--ui"]
    return main(args)


if __name__ == "__main__":
    raise SystemExit(run())
