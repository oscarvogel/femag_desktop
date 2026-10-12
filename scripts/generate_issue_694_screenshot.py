"""Captura el buscador del menu lateral en los dos temas (#694).

Los tests comprueban que el filtro deja las filas correctas. Eso no dice si el
operador lo entiende: si el aviso de "sin resultados" queda escondido, o si el
campo se come el logo en el tema oscuro, los tests siguen verdes. Estas capturas
son para mirar eso.

    python scripts/generate_issue_694_screenshot.py
"""

import argparse
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Sin esto, este PyQt5 no encuentra directorio de fuentes y las capturas salen
# sin texto (mismo motivo que en generate_theme_screenshots.py).
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtWidgets import QApplication, QFrame

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.security import User, UserProfile
from app.services.permission_service import PermissionService
from app.ui.desktop_app import FemagDesktopWindow
from app.ui.theme import Theme, save_theme, stylesheet_for


DEFAULT_OUTPUT = Path("docs") / "screenshots" / "issue_694_buscador_menu"

# (nombre del archivo, texto del buscador). El menu completo se captura con el
# campo vacio, que es como abre la app.
ESCENARIOS = (
    ("01_menu_completo", ""),
    ("02_filtro_grupo", "maestros"),
    ("03_filtro_hoja", "f150"),
    ("04_sin_resultados", "ventas managers"),
)


def _capture(widget, target: Path) -> None:
    widget.repaint()
    QApplication.processEvents()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not widget.grab().save(str(target)):
        raise RuntimeError(f"No se pudo guardar {target}")


def generate(output_dir: Path) -> list[Path]:
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")

    # La ventana arma su tema con `load_theme()`, que sale de
    # `default_config_dir()` -> `%LOCALAPPDATA%`. Hay que mover la variable
    # entera: si se guarda en un temporal y se lee del real, la ventana abre
    # siempre en claro y las dos capturas salen iguales sin que nada avise.
    os.environ["LOCALAPPDATA"] = str(Path(tempfile.mkdtemp()))

    targets: list[Path] = []
    for theme in (Theme.LIGHT, Theme.DARK):
        nombre = theme.value
        save_theme(theme)
        app.setStyleSheet(stylesheet_for(theme))

        user = User.create(username=f"buscador_{nombre}", password_hash="x", profile=profile)
        window = FemagDesktopWindow(user=user, demo_mode=True)
        window.resize(1440, 900)
        window.show()
        app.processEvents()

        if window.theme is not theme:
            raise RuntimeError(
                f"La ventana abrio en {window.theme} y se pidio {theme}: "
                "las capturas serian de otro tema."
            )

        sidebar = window.findChild(QFrame, "sidebarContainer")
        if sidebar is None:
            raise RuntimeError("No se encontro el contenedor del sidebar.")

        for nombre_archivo, consulta in ESCENARIOS:
            window.sidebar_search.setText(consulta)
            app.processEvents()
            target = output_dir / f"{nombre_archivo}_{nombre}.png"
            _capture(sidebar, target)
            targets.append(target)

        window.sidebar_search.clear()
        window.close()

    database.close()
    return targets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Captura evidencia visual del buscador del menu (#694)"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    for path in generate(args.output_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())