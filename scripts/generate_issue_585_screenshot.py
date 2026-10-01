"""Evidencia visual del reparto de cantidades en la orden de carga (#585)."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtWidgets import QApplication, QComboBox, QDialog, QDoubleSpinBox, QTableWidget

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
from app.services.load_order_service import LoadOrderService
from app.ui.desktop_app import LoadOrderEntryDialog, LoadOrderProductDialog
from scripts.generate_ux_screenshots import _capture

OUTPUT_DIR = Path("docs/screenshots/issue_585_reparto_cantidades")
STEP_REVISAR = 3


def _combo(dialog, object_name, value):
    combo = dialog.findChild(QComboBox, object_name)
    index = combo.findData(value)
    if index < 0:
        raise RuntimeError(f"No se encontro {object_name} con valor {value}")
    combo.setCurrentIndex(index)
    return combo


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)
    app = QApplication.instance() or QApplication([])
    try:
        carrier = Carrier.create(name="Transporte Norte", cuit="30777777770")
        driver = Driver.create(name="Juan Perez", carrier=carrier, document="123")
        truck = Truck.create(domain="AB123CD", carrier=carrier)
        client = Client.create(
            name="Alimentos Guarani",
            cuit="30700000585",
            iva_condition="RI",
            dias_plaza_pago=30,
            descuento_porcentaje=0,
        )
        address = ClientAddress.create(
            client=client,
            address_type="entrega",
            province="Misiones",
            city="Posadas",
            address="Ruta 12 km 1540",
            is_primary=True,
        )
        product = Product.create(
            name="Almidon de mandioca 25 kg",
            unit="bolsa",
            precio_neto_base=14200.0,
            peso_unitario_kg=25.0,
        )

        # 1. El dialogo real con el reparto cargado: es la evidencia principal.
        dialogo = LoadOrderProductDialog(client=client)
        dialogo.show()
        app.processEvents()
        _combo_dialog = dialogo.findChild(QComboBox, "productDialogProductInput")
        _combo_dialog.setCurrentIndex(_combo_dialog.findData(product.id))
        dialogo.findChild(QDoubleSpinBox, "productDialogQuantityInput").setValue(1200.0)
        dialogo.findChild(
            QDoubleSpinBox, "productDialogCantidadFacturarDespuesInput"
        ).setValue(400.0)
        app.processEvents()
        dialog_target = OUTPUT_DIR / "producto_reparto_cantidades.png"
        _capture(dialogo, dialog_target)
        dialogo.close()

        # 2. La grilla de productos y la de revisar con las dos columnas.
        entry = LoadOrderEntryDialog(LoadOrderService(current_user="issue585"), "issue585")
        entry.resize(1400, 900)
        entry.show()
        app.processEvents()

        _combo(entry, "loadOrderDriverInput", driver.id)
        _combo(entry, "loadOrderTruckInput", truck.id)
        _combo(entry, "loadOrderClientInput", client.id)
        _combo(entry, "loadOrderAddressInput", address.id)
        app.processEvents()
        entry.findChild(QTableWidget, "loadOrderDestinationDraftTable")

        from PyQt5.QtWidgets import QPushButton

        entry.findChild(QPushButton, "addLoadOrderClientButton").click()
        app.processEvents()
        entry.findChild(QTableWidget, "loadOrderDestinationDraftTable").setCurrentCell(0, 0)
        app.processEvents()

        original_exec = LoadOrderProductDialog.exec_

        def accept_product(self):
            self.product = {
                "product_id": product.id,
                "product_label": product.name,
                "quantity": 1200.0,
                "cantidad_facturar_ahora": 800.0,
                "unit": product.unit,
                "precio_neto_unitario": 14200.0,
                "descuento_porcentaje": 0.0,
                "iva_porcentaje": 21.0,
                "neto_subtotal": 1200.0 * 14200.0,
                "descuento_importe": 0.0,
                "neto_gravado": 1200.0 * 14200.0,
                "iva_importe": 1200.0 * 14200.0 * 0.21,
                "total": 1200.0 * 14200.0 * 1.21,
            }
            return QDialog.Accepted

        LoadOrderProductDialog.exec_ = accept_product
        try:
            entry.findChild(QPushButton, "addLoadOrderProductButton").click()
        finally:
            LoadOrderProductDialog.exec_ = original_exec
        app.processEvents()

        productos_target = OUTPUT_DIR / "orden_productos_reparto.png"
        _capture(entry, productos_target)

        entry.step_stack.setCurrentIndex(STEP_REVISAR)
        app.processEvents()
        revisar_target = OUTPUT_DIR / "orden_revisar_reparto.png"
        _capture(entry, revisar_target)
        entry.close()
        return [dialog_target, productos_target, revisar_target]
    finally:
        database.close()


if __name__ == "__main__":
    for path in generate():
        print(path)
