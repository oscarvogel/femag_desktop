"""
Captura de la seccion de cobranzas del dashboard con la base real (#952).

Corre la pantalla contra un MariaDB con el dump de produccion importado, para
dejar evidencia de como quedan las tarjetas con la exposicion por cliente.

    python scripts/generate_issue_952_screenshot.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
os.environ["FEMAG_SECURE_CONFIG"] = "0"
os.environ["FEMAG_DB_ENGINE"] = "mysql"
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "3307")
os.environ.setdefault("DB_NAME", "femag_desktop")
os.environ.setdefault("DB_USER", "root")
os.environ.setdefault("DB_PASSWORD", "root")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt5.QtWidgets import QApplication  # noqa: E402

from app.config.database import build_mysql_database, database_proxy  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from app.services.permission_service import PermissionService  # noqa: E402
from app.ui.desktop_app import FemagDesktopWindow  # noqa: E402
from scripts.generate_ux_screenshots import _capture  # noqa: E402


OUTPUT_DIR = Path("docs") / "screenshots" / "issue_952_cobranzas"


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = build_mysql_database()
    database_proxy.initialize(database)
    database.connect(reuse_if_open=True)

    app = QApplication.instance() or QApplication([])
    try:
        PermissionService().seed_defaults()
        username = "captura952"
        admin = AuthService().authenticate(username, "secreto")
        if admin is None:
            admin = AuthService().create_user(username, "secreto", "Administrador")

        window = FemagDesktopWindow(user=admin, demo_mode=False)
        window.resize(1600, 950)
        window._navigate_to_route("dashboard")
        window.show()
        app.processEvents()

        target = OUTPUT_DIR / "dashboard_cobranzas_exposicion_neta.png"
        _capture(window, target)
        window.close()
        return [target]
    finally:
        database.close()


if __name__ == "__main__":
    for path in generate():
        print(path)
