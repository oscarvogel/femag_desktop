import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtGui import QColor, QImage, QPixmap
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.services.auth_service import AuthService
from app.services.permission_service import PermissionService
from app.ui.desktop_app import FemagDesktopWindow
from app.ui.login_window import LoginWindow


OUTPUT_DIR = Path("docs") / "screenshots" / "issue_190_branding"


def _capture(widget, target: Path) -> None:
    canvas = QPixmap(widget.size())
    canvas.fill(QColor("white"))
    widget.render(canvas)
    image = canvas.toImage().convertToFormat(QImage.Format_RGB32)
    if not image.save(str(target), "PNG"):
        raise RuntimeError(f"No se pudo guardar {target}")


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])

    login = LoginWindow(demo_mode=True)
    app.processEvents()
    login_target = OUTPUT_DIR / "login.png"
    _capture(login, login_target)
    login.close()

    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    PermissionService().seed_defaults()
    user = AuthService().create_user("captura_branding", "clave", "Administrador")
    window = FemagDesktopWindow(user=user, demo_mode=True)
    window.resize(1440, 900)
    app.processEvents()
    workspace_target = OUTPUT_DIR / "workspace.png"
    _capture(window, workspace_target)
    window.close()
    database.close()
    app.quit()
    return [login_target, workspace_target]


if __name__ == "__main__":
    for path in generate():
        print(path)
