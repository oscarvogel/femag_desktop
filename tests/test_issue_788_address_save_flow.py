"""Regresión #788: domicilio creado en la carga + guardado de orden real."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from conftest import _master_data


def _dialog(app):
    from app.ui.desktop_app import LoadOrderEntryDialog
    from app.services.load_order_service import LoadOrderService
    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="issue788"), "issue788")
    app.processEvents()
    return dialog


def _select_transport(dialog, data, app):
    dialog.driver_combo.setCurrentIndex(dialog.driver_combo.findData(data["driver"].id))
    app.processEvents()
    dialog.truck_combo.setCurrentIndex(dialog.truck_combo.findData(data["truck"].id))
    app.processEvents()


@pytest.mark.parametrize("primary", [True, False])
def test_new_address_can_be_used_to_save_complete_order(db, monkeypatch, primary):
    from PyQt5.QtWidgets import QApplication, QMessageBox, QDialog, QLineEdit, QPushButton
    from app.models.load_orders import LoadOrder, LoadOrderDestination
    from app.models.masters import ClientAddress
    from app.ui.master_abm import ClientAddressEntryDialog

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_transport(dialog, data, app)
    dialog.client_combo.setCurrentIndex(dialog.client_combo.findData(data["client"].id))
    app.processEvents()
    dialog.address_combo.lineEdit().setText("Ruta 788")

    def ask(_parent, title, *_args):
        if title == "Nuevo lugar de entrega":
            return QMessageBox.Yes
        if title == "Domicilio principal":
            return QMessageBox.Yes if primary else QMessageBox.No
        raise AssertionError(title)

    monkeypatch.setattr(QMessageBox, "question", staticmethod(ask))

    def create_address(self):
        self.findChild(QLineEdit, "addressProvinceInput").setText("Misiones")
        self.findChild(QLineEdit, "addressCityInput").setText("Obera")
        self.findChild(QPushButton, "saveAddressButton").click()
        assert self.saved_record is not None
        return QDialog.Accepted

    monkeypatch.setattr(ClientAddressEntryDialog, "exec_", create_address)
    dialog.add_destination_button.click()
    app.processEvents()

    assert len(dialog.destinations) == 1
    address_id = dialog.destinations[0]["address_id"]
    assert ClientAddress.get_by_id(address_id).is_primary is primary
    dialog.destinations[0]["products"].append({
        "product_id": data["product"].id,
        "product_label": data["product"].name,
        "quantity": 10,
        "unit": "kg",
        "precio_neto_unitario": 0,
        "descuento_porcentaje": 0,
        "iva_porcentaje": 0,
        "total": 0,
    })
    dialog._render_destinations()
    assert dialog._save_blocking_reason() is None
    assert dialog.save_button.isEnabled()
    dialog.save_button.click()
    app.processEvents()

    assert dialog.created_order is not None, dialog.feedback.text()
    order = LoadOrder.get_by_id(dialog.created_order.id)
    dest = LoadOrderDestination.get(LoadOrderDestination.order == order)
    assert dest.delivery_address.id == address_id
    assert len(list(dest.products)) == 1
    assert dest.products[0].product.id == data["product"].id


def test_save_explains_invalid_new_address_without_dropping_draft(db):
    from PyQt5.QtWidgets import QApplication
    from app.models.masters import ClientAddress

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_transport(dialog, data, app)
    dialog.destinations = [{
        "client_id": data["client"].id,
        "client_label": data["client"].name,
        "address_id": data["address"].id,
        "address_label": "Ruta 12",
        "products": [{"product_id": data["product"].id, "quantity": 10}],
    }]
    address = ClientAddress.get_by_id(data["address"].id)
    address.active = False
    address.save()
    dialog._update_save_button_state()
    assert dialog.save_button.isEnabled()
    dialog.save_button.click()
    assert "ya no es válido" in dialog.feedback.text()
    assert dialog.created_order is None
    assert len(dialog.destinations) == 1


def test_save_without_destinations_explains_why_button_cannot_save(db):
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_transport(dialog, data, app)
    assert dialog.save_button.isEnabled()
    dialog.save_button.click()
    assert "Agregue al menos un cliente y destino" in dialog.feedback.text()
