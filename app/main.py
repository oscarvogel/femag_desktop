import argparse
import os
from pathlib import Path

from peewee import SqliteDatabase

from app.config.database import bind_database
from app.config.logging_config import configure_logging
from app.config.settings import load_settings
from app.models import ALL_MODELS


def smoke_check() -> str:
    load_settings()
    configure_logging()
    from app.models import ALL_MODELS
    from app.ui.dashboard import future_module_message
    from app.ui.framework import get_ui_framework

    assert ALL_MODELS
    assert future_module_message()
    assert get_ui_framework().name == "pyqt5libs"
    return "FEMAG smoke OK"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="femag-desktop")
    parser.add_argument("--smoke", action="store_true", help="Validate imports/config without opening UI")
    parser.add_argument("--demo", action="store_true", help="Open FEMAG with a local demo database")
    parser.add_argument("--demo-db", default="data/femag_demo.sqlite3", help="SQLite path used by --demo")
    parser.add_argument("--no-show", action="store_true", help="Initialize demo UI without showing windows")
    args = parser.parse_args(argv)
    if args.smoke:
        print(smoke_check())
        return 0
    if args.demo:
        return run_demo_app(Path(args.demo_db), no_show=args.no_show)

    print("FEMAG Desktop UI requires a workstation session.")
    return 0


def run_demo_app(db_path: Path, *, no_show: bool = False) -> int:
    if no_show:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(db_path)
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables(ALL_MODELS, safe=True)

    from scripts.seed_demo_data import seed_demo_data

    seed_demo_data()

    from PyQt5.QtWidgets import QApplication

    from app.ui.login_window import LoginWindow
    from app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    if no_show:
        MainWindow(user=_demo_user())
        print("FEMAG demo UI OK")
        return 0

    login = LoginWindow()
    login.show()
    login.raise_()
    login.activateWindow()
    if login.exec_() != LoginWindow.Accepted:
        return 0
    window = MainWindow(user=login.user)
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec_()


def _demo_user():
    from app.models.security import User

    return User.get(User.username == "secretaria")


if __name__ == "__main__":
    raise SystemExit(main())
