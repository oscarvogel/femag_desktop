import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtWidgets import QApplication, QLineEdit

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import Carrier, Driver, Truck
from app.ui.transport_setup_extension import TransportSetupDialog
from scripts.generate_ux_screenshots import _capture


OUTPUT = (
    Path("docs")
    / "screenshots"
    / "issue_352_edit_trailer_domain"
    / "transport_setup_editable_trailer_domain.png"
)


def generate() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables(ALL_MODELS)

    carrier = Carrier.create(name="Transporte Demostración")
    truck = Truck.create(
        domain="AB123CD",
        trailer_domain="AC456EF",
        carrier=carrier,
    )
    driver = Driver.create(
        name="Chofer Demostración",
        document="30123456",
        carrier=carrier,
        usual_truck=truck,
    )

    app = QApplication.instance() or QApplication([])
    dialog = TransportSetupDialog(
        current_user="captura352",
        initial_carrier_id=carrier.id,
        initial_truck_id=truck.id,
        initial_driver_id=driver.id,
    )
    dialog.findChild(QLineEdit, "transportSetupTrailerDomainInput").setText("AC789GH")
    dialog.adjustSize()
    dialog.resize(730, dialog.sizeHint().height())
    dialog.show()
    app.processEvents()
    _capture(dialog, OUTPUT)
    dialog.close()
    database.close()
    return OUTPUT


if __name__ == "__main__":
    print(generate())
