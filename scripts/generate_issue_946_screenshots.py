"""Genera la evidencia visual del issue #946.

Captura los dos formularios que le faltaban a Cristina la celda de Localidad DGR
y la de Domicilio fiscal (Rentas), con datos cargados, para ver que la pantalla
no se pisa y que los campos se leen.

Uso:
    .\\.venv\\Scripts\\python.exe scripts\\generate_issue_946_screenshots.py
"""

import argparse
import json
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtGui import QColor, QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QPushButton

from app.config.database import bind_database
from app.importers.dgr_reference import DgrReferenceImporter
from app.models import ALL_MODELS
from app.models.dgr import DgrLocality
from app.models.masters import (
    Carrier,
    Client,
    ClientAddress,
    Driver,
    Product,
    Truck,
)
from app.models.security import User, UserProfile
from app.models.system import AppParameter
from app.services.remittance_service import RemittanceService
from app.ui.f150 import F150Page
from app.ui.master_abm import CarrierEntryDialog, DriverEntryDialog

DEFAULT_OUTPUT = Path("docs") / "screenshots" / "issue_946"

DGR_ROWS = {
    "paises": [{"IDPAIS": 200, "NOMBRE": "ARGENTINA", "ABR": "ARG"}],
    "provincias": [{"CODIGO": 14, "DESCRIPCIO": "MISIONES"}],
    "locdgr": [
        {"IDLOCALIDA": 61, "CODIGODGR": 61, "PROVINCIA": 14, "DPTO": 10,
         "DESCRIPCIO": "PUERTO RICO"}
    ],
    "localidades": [
        {"CODIGO": "2457", "LOCALIDAD": "PUERTO RICO", "CODIGODGR": 61,
         "PAISDGR": 200, "PROVDGR": 14, "DEPA": 10, "PROVINCIA": "MISIONES"}
    ],
}


def _capture(widget, target: Path) -> None:
    """Captura el widget y verifica que no salgan regiones negras."""
    canvas = QPixmap(widget.size())
    canvas.fill(QColor("white"))
    widget.render(canvas)
    image = canvas.toImage().convertToFormat(QImage.Format_RGB32)
    pixels = [
        image.pixelColor(x, y)
        for x in range(0, image.width(), 10)
        for y in range(0, image.height(), 10)
    ]
    black = sum(
        color.red() < 8 and color.green() < 8 and color.blue() < 8 for color in pixels
    )
    if black > len(pixels) // 5:
        raise RuntimeError(f"La captura contiene regiones negras anormales: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(target), "PNG"):
        raise RuntimeError(f"No se pudo guardar {target}")


def _masters():
    DgrReferenceImporter().import_rows(DGR_ROWS)
    locality = DgrLocality.get(DgrLocality.code == "2457")
    carrier = Carrier.create(
        name="FERREYRA JUAN CARLOS",
        cuit="20-23737702-9",
        phone="0341-1234567",
        tipo="DIR",
        codigo="0004",
        locality=locality,
        address="L. N. ALEM",
        fiscal_address="AV. ALEM 1250 - ROSARIO",
    )
    truck = Truck.create(
        domain="UKJ233", trailer_domain="BMF190", carrier=carrier,
        chassis_type="1", trailer_type="1",
    )
    driver = Driver.create(
        name="GIMENEZ JORGE ARIEL",
        carrier=carrier,
        usual_truck=truck,
        document="23-22840465-9",
        locality=locality,
        address="L. N. ALEM",
        fiscal_address="AV. ALEM 1250 - ROSARIO",
    )
    return carrier, driver


def _remito_sin_localidad(locality, carrier, driver):
    """Remito emitido cuyo chofer no tiene localidad DGR ni domicilio fiscal.

    Es el caso que reporto Cristina: el F150 lo rechaza y el operador tiene que
    ver, en la propia pantalla, que le falta el dato y de quien es.
    """
    AppParameter.get_or_create(
        key="f150.origin", defaults={"value": json.dumps({"locality_code": "2457"})}
    )
    profile = UserProfile.get_or_create(name="Administrador")[0]
    User.get_or_create(
        username="admin",
        defaults={"password_hash": "x", "profile": profile, "active": True},
    )
    # El chofer queda como lo报告中 Cristina en la ficha: con domicilio pero
    # sin localidad DGR asignada.
    driver.locality = None
    driver.fiscal_address = None
    driver.save()
    client = Client.create(name="Ferreteria Avenida", cuit="30-63634545-4", iva_condition="RI")
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones",
        city="Puerto Rico", address="Ruta 12 km 8", locality=locality,
    )
    truck = driver.usual_truck
    product = Product.create(
        codigo="G-300", name="Almidon", unit="bolsa", precio_neto_base=18600.0,
        rh1="2", rh2="2", rh3="19", rh4="0", unidad_dgr="U",
    )
    service = RemittanceService("admin")
    draft = service.create_manual(
        client=client, delivery_address=address, carrier=carrier, truck=truck,
        driver=driver, physical_point_of_sale="0001", physical_number="946",
        remittance_date=date(2026, 11, 23),
        items=[{"product": product, "quantity": Decimal("500")}],
    )
    return service.issue(draft)


def generate(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect(reuse_if_open=True)
    database.create_tables(ALL_MODELS)
    carrier, driver = _masters()
    app = QApplication.instance() or QApplication([])

    targets = []

    driver_dialog = DriverEntryDialog(current_user="admin", record_id=driver.id)
    driver_dialog.show()
    app.processEvents()
    target = output_dir / "01_chofer_editar_localidad_y_domicilio_fiscal.png"
    _capture(driver_dialog, target)
    targets.append(target)
    driver_dialog.close()

    carrier_dialog = CarrierEntryDialog(current_user="admin", record_id=carrier.id)
    carrier_dialog.show()
    app.processEvents()
    target = output_dir / "02_transportista_editar_localidad_y_domicilio_fiscal.png"
    _capture(carrier_dialog, target)
    targets.append(target)
    carrier_dialog.close()

    _remito_sin_localidad(DgrLocality.get(DgrLocality.code == "2457"), carrier, driver)

    page = F150Page(current_user="admin", output_dir=output_dir)
    page.show()
    for width, height in ((1638, 969), (1366, 768)):
        page.resize(width, height)
        app.processEvents()
        target = output_dir / f"03_f150_pendientes_{width}x{height}.png"
        _capture(page, target)
        targets.append(target)
    page.close()

    database.close()
    return targets


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Capturas del issue #946")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    for path in generate(args.output_dir):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
