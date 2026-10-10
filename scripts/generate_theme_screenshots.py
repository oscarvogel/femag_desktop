"""Captura el dashboard, la pagina de ordenes y un dialogo en los dos temas.

Es la validacion visual del tema oscuro (#120). El paso 1 dejo la paleta
construida pero nadie la miro: estas capturas son para eso. Si un color quedo
mal, se ve en el PNG, no en un assert.

    python scripts/generate_theme_screenshots.py
"""

import argparse
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Sin esto, este PyQt5 no encuentra directorio de fuentes y las capturas salen
# sin texto: se puede revisar la superficie pero no el contraste del texto, que
# es justo lo que hay que mirar en un tema oscuro.
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import (
    Carrier,
    Client,
    ClientAddress,
    Driver,
    Product,
    Truck,
)
from app.models.security import User, UserProfile
from app.services.load_order_service import LoadOrderService
from app.services.permission_service import PermissionService
from app.ui.desktop_app import FemagDesktopWindow, LoadOrderEntryDialog
from app.ui.theme import Theme, save_theme, stylesheet_for


DEFAULT_OUTPUT = Path("docs") / "screenshots" / "issue_120_tema"


def _masters():
    carrier = Carrier.create(name="Transporte Tema")
    driver = Driver.create(name="Chofer Tema", carrier=carrier)
    truck = Truck.create(domain="TEM01", carrier=carrier)
    client = Client.create(name="Ferreteria Tema", cuit="30700001781", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Deposito Central",
    )
    product = Product.create(name="Cemento 25 kg", unit="bolsa", peso_unitario_kg=Decimal("25.000"))
    return locals()


def _capture(widget, target: Path) -> None:
    widget.repaint()
    from PyQt5.QtWidgets import QApplication

    QApplication.processEvents()
    target.parent.mkdir(parents=True, exist_ok=True)
    pixmap = widget.grab()
    if not pixmap.save(str(target)):
        raise RuntimeError(f"No se pudo guardar {target}")


def generate(output_dir: Path) -> list[Path]:
    from PyQt5.QtWidgets import QApplication

    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables(ALL_MODELS)
    data = _masters()
    service = LoadOrderService(current_user="tema_captura")
    app = QApplication.instance() or QApplication([])

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    targets: list[Path] = []

    # La ventana arma su tema con `load_theme()`, que sale de
    # `default_config_dir()` -> `%LOCALAPPDATA%`. Hay que mover esa variable,
    # no solo pasar un directorio a `save_theme`: si se guarda en un temporal
    # y se lee del real, la ventana abre siempre en claro y las dos capturas
    # salen iguales sin que nada avise. Por eso, ademas, se verifica abajo que
    # la ventana quedo en el tema pedido.
    config_dir = Path(tempfile.mkdtemp())
    os.environ["LOCALAPPDATA"] = str(config_dir)

    for theme in (Theme.LIGHT, Theme.DARK):
        nombre = theme.value
        save_theme(theme)
        app.setStyleSheet(stylesheet_for(theme))

        user = User.create(username=f"tema_{nombre}", password_hash="x", profile=profile)
        window = FemagDesktopWindow(user=user, demo_mode=True)
        window.resize(1440, 900)
        window.show()
        app.processEvents()

        if window.theme is not theme:
            raise RuntimeError(
                f"La ventana abrio en {window.theme} y se pidio {theme}: "
                "las capturas serian de otro tema."
            )
        _capture(window, output_dir / f"01_dashboard_{nombre}.png")
        targets.append(output_dir / f"01_dashboard_{nombre}.png")

        window._navigate_to_route("load_orders")
        app.processEvents()
        _capture(window, output_dir / f"02_ordenes_{nombre}.png")
        targets.append(output_dir / f"02_ordenes_{nombre}.png")
        window.close()

        dialog = LoadOrderEntryDialog(service, "tema_captura")
        dialog.resize(1180, 700)
        dialog.show()
        app.processEvents()
        _capture(dialog, output_dir / f"03_dialogo_orden_{nombre}.png")
        targets.append(output_dir / f"03_dialogo_orden_{nombre}.png")
        dialog.close()

    database.close()
    return targets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Captura evidencia visual del tema oscuro (#120)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    for path in generate(args.output_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())