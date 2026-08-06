import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from peewee import SqliteDatabase
from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication, QComboBox, QLabel, QListView, QVBoxLayout, QWidget

from app.config.database import bind_database
from app.models import ALL_MODELS
from app.models.masters import Client, Product
from app.ui.combo_autocomplete import enable_combo_autocomplete
from app.ui.customer_payment_dialog import ClientPaymentDialog
from app.ui.desktop_app import LoadOrderEntryDialog, LoadOrderProductDialog
from app.services.load_order_service import LoadOrderService


OUTPUT_DIR = Path("docs/screenshots/issue_218_combo_autocomplete")


def _capture_filtered_combo(combo: QComboBox, query: str, title: str, output: Path) -> None:
    preview = QWidget()
    preview.setObjectName("autocompleteEvidence")
    preview.setStyleSheet("#autocompleteEvidence { background: #f8fafc; } QLabel { color: #0f172a; font-weight: 700; }")
    layout = QVBoxLayout(preview)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.addWidget(QLabel(title))

    preview_combo = QComboBox()
    for index in range(combo.count()):
        preview_combo.addItem(combo.itemText(index), combo.itemData(index))
    enable_combo_autocomplete(preview_combo, placeholder=combo.lineEdit().placeholderText())
    preview_combo.lineEdit().blockSignals(True)
    preview_combo.setEditText(query)
    preview_combo.completer().setCompletionPrefix(query)
    layout.addWidget(preview_combo)

    results = QListView()
    results.setModel(preview_combo.completer().completionModel())
    results.setMinimumHeight(max(72, results.model().rowCount() * 28 + 8))
    layout.addWidget(results)
    preview.resize(560, 80 + results.minimumHeight())
    preview.show()
    QApplication.processEvents()
    image = preview.grab().toImage().convertToFormat(QImage.Format_RGB32)
    if not image.save(str(output), "PNG"):
        raise RuntimeError(f"No se pudo guardar {output}")
    preview.close()


def generate() -> list[Path]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    database = SqliteDatabase(":memory:")
    bind_database(database)
    database.connect()
    database.create_tables(ALL_MODELS)

    Client.create(name="Autoservicio Norte", cuit="30111111119", iva_condition="RI")
    Client.create(name="Distribuidora del Sur", cuit="30222222229", iva_condition="RI")
    Client.create(name="Mercado Central", cuit="30333333339", iva_condition="RI")
    Product.create(name="Yerba Mate Tradicional", unit="kg")
    Product.create(name="Yerba Mate Suave", unit="kg")
    Product.create(name="Te Negro en Saquitos", unit="u")

    load_order = LoadOrderEntryDialog(LoadOrderService(current_user="captura218"), "captura218")
    product = LoadOrderProductDialog()
    payment = ClientPaymentDialog(current_user="captura218")
    app.processEvents()

    captures = [
        (load_order.client_combo, "sur", "Cliente - busqueda parcial: sur", OUTPUT_DIR / "cliente.png"),
        (product.product_combo, "mate", "Producto - busqueda parcial: mate", OUTPUT_DIR / "producto.png"),
        (payment.method_combo, "fer", "Medio de pago - busqueda parcial: fer", OUTPUT_DIR / "medio_pago.png"),
    ]
    for combo, query, title, output in captures:
        _capture_filtered_combo(combo, query, title, output)

    load_order.close()
    product.close()
    payment.close()
    database.close()
    app.quit()
    return [capture[3] for capture in captures]


if __name__ == "__main__":
    for path in generate():
        print(path)
