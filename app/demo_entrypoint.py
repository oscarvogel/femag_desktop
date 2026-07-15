from __future__ import annotations

import os
import sys
from pathlib import Path

from app.main import main


def _install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def configure_standalone_demo() -> Path:
    install_dir = _install_dir()
    data_dir = install_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (install_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (install_dir / "backups").mkdir(parents=True, exist_ok=True)

    os.chdir(install_dir)
    os.environ["APP_ENV"] = "demo"
    os.environ["FEMAG_DB_ENGINE"] = "sqlite"
    os.environ["FEMAG_SQLITE_PATH"] = str(data_dir / "femag_demo.sqlite3")
    os.environ["FEMAG_DEMO"] = "1"
    os.environ["BACKUP_DIR"] = str(install_dir / "backups")
    return install_dir


def run() -> int:
    configure_standalone_demo()
    args = sys.argv[1:] or ["--demo-ui"]
    return main(args)


if __name__ == "__main__":
    raise SystemExit(run())
