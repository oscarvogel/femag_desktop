import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtWidgets import QApplication, QTableWidget

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.security import User, UserProfile
from app.services.load_order_operation_service import LoadOrderOperationService
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService
from app.ui.desktop_app import FemagDesktopWindow
from scripts.generate_ux_screenshots import (
    _capture,
    _masters,
    _pallet_payload,
    _service_destinations,
)


DEFAULT_OUTPUT = Path("docs") / "screenshots" / "issue_162_reprint" / "reprint_action.png"


def generate(target: Path, pdf_dir: Path | None = None) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables(ALL_MODELS)
    try:
        data = _masters()
        PermissionService().seed_defaults()
        profile = UserProfile.get(UserProfile.name == "Administrador")
        user = User.create(username="captura162_admin", password_hash="x", profile=profile)
        service = LoadOrderService(current_user=user.username)
        order = service.create_order(
            carrier=data["carrier"],
            driver=data["driver"],
            truck=data["truck"],
            destinations=_service_destinations(data),
            pallets=_pallet_payload(data),
        )
        app = QApplication.instance() or QApplication([])
        with TemporaryDirectory(prefix="femag-issue-162-") as prints_dir:
            LoadOrderOperationService(
                current_user=user.username,
                prints_dir=prints_dir,
            ).print_order(order)
            if pdf_dir is not None:
                pdf_dir.mkdir(parents=True, exist_ok=True)
                LoadOrderOperationService(
                    current_user=user.username,
                    prints_dir=pdf_dir,
                ).reprint_order(order, can_reprint=True)
            window = FemagDesktopWindow(user=user, demo_mode=True)
            window.resize(1440, 900)
            window._navigate_to_route("load_orders")
            window.show()
            app.processEvents()
            table = window.findChild(QTableWidget, "loadOrdersTable")
            table.setCurrentCell(0, 0)
            app.processEvents()
            _capture(window, target)
            window.close()
        return target
    finally:
        database.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Genera evidencia visual del issue #162")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        help="Opcional: genera también un PDF de reimpresión para validación visual",
    )
    args = parser.parse_args(argv)
    print(generate(args.output, args.pdf_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
