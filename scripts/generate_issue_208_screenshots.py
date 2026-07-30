import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtCore import QCoreApplication, QEvent
from PyQt5.QtWidgets import QApplication

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.services.load_order_service import LoadOrderService
from app.ui.desktop_app import LoadOrderPalletDialog
from scripts.generate_ux_screenshots import (
    _capture,
    _masters,
    _service_destinations,
    _set_combo,
    _show_dialog,
)


OUTPUT_DIR = Path("docs") / "screenshots" / "issue_208_bulk_pallet_operations"


def _settle_layout(app: QApplication) -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    for _ in range(3):
        app.processEvents()


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables(ALL_MODELS)
    data = _masters()
    service = LoadOrderService(current_user="captura208")
    order = service.create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=_service_destinations(data),
        pallets=[],
    )
    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderPalletDialog(service, order)
    _show_dialog(dialog, app)

    dialog.pallet_widget.bulk_pallet_count_input.setValue(19)
    dialog.pallet_widget.add_pallet_button.click()
    _settle_layout(app)
    targets = [OUTPUT_DIR / "01_19_tarjetas_agregadas.png"]
    _capture(dialog, targets[-1])

    _set_combo(dialog.pallet_widget.destination_combo, data["address_a"].id)
    _set_combo(dialog.pallet_widget.product_combo, data["cement"].id)
    dialog.pallet_widget.bulk_start_input.setValue(1)
    dialog.pallet_widget.bulk_target_count_input.setValue(10)
    _settle_layout(app)
    targets.append(OUTPUT_DIR / "02_asignacion_masiva_previa.png")
    _capture(dialog, targets[-1])

    dialog.pallet_widget.bulk_assign_button.click()
    _settle_layout(app)
    targets.append(OUTPUT_DIR / "03_10_pallets_asignados.png")
    _capture(dialog, targets[-1])

    dialog.pallet_widget.clear_all_allocations()
    _settle_layout(app)
    targets.append(OUTPUT_DIR / "04_asignaciones_limpiadas.png")
    _capture(dialog, targets[-1])

    dialog.close()
    database.close()
    return targets


def main() -> int:
    for path in generate():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
