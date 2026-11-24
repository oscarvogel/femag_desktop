"""Evidencia de #916 con datos descartables, sin abrir la base del puesto."""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtCore import QDate
from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS, SYNC_MODELS
from app.services.f150_batch_service import F150BatchService
from app.ui.f150 import F150Page
from app.ui.theme import Theme, stylesheet_for
from tests.test_f150_pendientes import _emitir
from tests.test_issue_790_f150_dgr import _admin


def main():
    app = QApplication([])
    # Workaround local documentado en #652: offscreen necesita fuentes cargadas.
    for name in ("segoeui.ttf", "segoeuib.ttf"):
        font = Path("C:/Windows/Fonts") / name
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    if not QFontDatabase().families():
        raise RuntimeError("Qt no tiene fuentes disponibles para capturas legibles (#652).")
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(stylesheet_for(Theme.DARK))
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables([*ALL_MODELS, *SYNC_MODELS])
    _admin("admin")
    output = Path(__file__).resolve().parents[1] / "docs/screenshots/issue_916"
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as folder:
        root = Path(folder)
        service = F150BatchService("admin", archive_dir=root / "archive")
        for number in range(1, 19):
            remittance = _emitir(
                database, f"Cliente demostracion {number}", f"{10000 + number:08d}",
                cuit=f"30-{70000000 + number:08d}-1",
            )
            service.generate([remittance], root / f"F150-{number:03d}.txt")
        _emitir(database, "Cliente listo para generar", "00010050", cuit="30-70000050-1")
        _emitir(database, "Cliente con dato pendiente", "00010051", cuit="30-70000051-1", carrier_address=None)
        page = F150Page(current_user="admin", output_dir=root)
        page.show()

        def capture(name):
            app.processEvents()
            if not page.grab().save(str(output / name)):
                raise RuntimeError(f"No se pudo guardar {name}")

        for width, height in ((1638, 969), (1366, 768)):
            page.resize(width, height)
            page.tabs.setCurrentIndex(1)
            capture(f"historial_{width}x{height}.png")
        page.tabs.setCurrentIndex(0)
        capture("pendientes_1366x768.png")
        page.tabs.setCurrentIndex(1)
        page.history_use_dates.setChecked(True)
        page.history_date_from.setDate(QDate(2099, 1, 1))
        page.history_date_to.setDate(QDate(2099, 12, 31))
        page._refresh_history()
        capture("historial_sin_resultados.png")
        page.close()
    database.close()
    print(output)


if __name__ == "__main__":
    main()
