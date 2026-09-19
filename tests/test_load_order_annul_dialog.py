from PyQt5.QtWidgets import QApplication

from app.models.load_orders import LoadOrder
from app.services.load_order_service import LoadOrderService
from app.ui.load_order_annul_dialog import LoadOrderAnnulDialog
from conftest import _master_data, _valid_order_payload


def test_annul_dialog_requires_reason_and_returns_trimmed_text(db):
    app = QApplication.instance() or QApplication([])
    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))

    dialog = LoadOrderAnnulDialog(order)
    dialog.reason_input.setPlainText("   ")
    dialog._validate_and_accept()
    app.processEvents()

    assert dialog.result() != dialog.Accepted
    assert dialog.validation_label.text() == "Debe indicar el motivo de la anulación."

    dialog.reason_input.setPlainText("  Error de carga controlado  ")
    dialog._validate_and_accept()
    app.processEvents()

    assert dialog.result() == dialog.Accepted
    assert dialog.reason() == "Error de carga controlado"


def test_annul_dialog_shows_order_number(db):
    app = QApplication.instance() or QApplication([])
    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))

    dialog = LoadOrderAnnulDialog(order)
    app.processEvents()

    assert f"OC-{order.order_number:06d}" in dialog.windowTitle()
