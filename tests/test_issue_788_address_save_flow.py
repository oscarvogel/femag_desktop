"""Regresión #788: alta de domicilio y guardado real de la orden de carga.

El incidente reportado fue: el domicilio se guardaba, pero Guardar orden no
respondía y no mostraba ningún motivo. La reproducción demuestra que el botón
quedaba deshabilitado en silencio cuando el borrador todavía no estaba completo
(por ejemplo, el destino recién creado aún no tenía productos). Acá se fija que
el operador siempre vea el motivo, que un error de base no pierda el borrador y
que el alta de domicilio sea atómica.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from conftest import _master_data, _multi_client_data, _valid_order_payload


def _dialog(app, order=None):
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    dialog = LoadOrderEntryDialog(
        LoadOrderService(current_user="issue788"), "issue788", order=order
    )
    app.processEvents()
    return dialog


def _select_transport(dialog, data, app):
    dialog.driver_combo.setCurrentIndex(dialog.driver_combo.findData(data["driver"].id))
    app.processEvents()
    dialog.truck_combo.setCurrentIndex(dialog.truck_combo.findData(data["truck"].id))
    app.processEvents()


def _select_client(dialog, app, client):
    dialog.client_combo.setCurrentIndex(dialog.client_combo.findData(client.id))
    app.processEvents()


def _add_existing_destination(dialog, app, client):
    _select_client(dialog, app, client)
    dialog.add_destination_button.click()
    app.processEvents()


def _add_new_destination(
    dialog,
    app,
    monkeypatch,
    *,
    client,
    typed,
    primary,
    province="Misiones",
    city="Obera",
):
    from PyQt5.QtWidgets import QDialog, QLineEdit, QMessageBox, QPushButton

    from app.ui.master_abm import ClientAddressEntryDialog

    _select_client(dialog, app, client)
    dialog.address_combo.lineEdit().setText(typed)

    def ask(_parent, title, *_args):
        if title == "Nuevo lugar de entrega":
            return QMessageBox.Yes
        if title == "Domicilio principal":
            return QMessageBox.Yes if primary else QMessageBox.No
        raise AssertionError(title)

    monkeypatch.setattr(QMessageBox, "question", staticmethod(ask))

    def complete_address(self):
        assert self.findChild(QLineEdit, "addressStreetInput").text() == typed
        self.findChild(QLineEdit, "addressProvinceInput").setText(province)
        self.findChild(QLineEdit, "addressCityInput").setText(city)
        self.findChild(QPushButton, "saveAddressButton").click()
        assert self.saved_record is not None
        return QDialog.Accepted

    monkeypatch.setattr(ClientAddressEntryDialog, "exec_", complete_address)
    dialog.add_destination_button.click()
    app.processEvents()


def _add_product(dialog, app, monkeypatch, product, quantity):
    from PyQt5.QtWidgets import QDialog

    from app.ui.desktop_app import LoadOrderProductDialog

    def complete_product(self):
        index = self.product_combo.findData(product.id)
        assert index >= 0
        self.product_combo.setCurrentIndex(index)
        self.quantity_input.setValue(quantity)
        self._accept_product()
        return QDialog.Accepted

    monkeypatch.setattr(LoadOrderProductDialog, "exec_", complete_product)
    dialog.add_product_button.click()
    app.processEvents()


def _persisted_order(dialog):
    from app.models.load_orders import LoadOrder

    assert dialog.created_order is not None, dialog.feedback.text()
    return LoadOrder.get_by_id(dialog.created_order.id)


def _assert_order_header(order, data):
    assert order.carrier.id == data["carrier"].id
    assert order.driver.id == data["driver"].id
    assert order.truck.id == data["truck"].id


def _primary_addresses(client):
    from app.models.masters import ClientAddress

    return list(
        ClientAddress.select().where(
            (ClientAddress.client == client)
            & (ClientAddress.active == True)  # noqa: E712
            & (ClientAddress.is_primary == True)  # noqa: E712
        )
    )


@pytest.mark.parametrize("primary", [True, False])
def test_new_address_can_be_used_to_save_complete_order(db, monkeypatch, primary):
    from PyQt5.QtWidgets import QApplication

    from app.models.load_orders import LoadOrderDestination, LoadOrderProduct
    from app.models.masters import ClientAddress

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_transport(dialog, data, app)
    _add_new_destination(
        dialog,
        app,
        monkeypatch,
        client=data["client"],
        typed="Ruta 788",
        primary=primary,
    )
    assert len(dialog.destinations) == 1
    assert dialog.destinations[0]["client_id"] == data["client"].id
    new_address_id = dialog.destinations[0]["address_id"]
    new_address = ClientAddress.get_by_id(new_address_id)
    assert new_address.client.id == data["client"].id
    assert new_address.active is True
    assert new_address.is_primary is primary

    _add_product(dialog, app, monkeypatch, data["product"], 10)
    assert dialog._save_blocking_reason() is None
    assert dialog.save_hint.text() == ""
    assert dialog.save_button.isEnabled() is True

    dialog.save_button.click()
    app.processEvents()

    order = _persisted_order(dialog)
    _assert_order_header(order, data)
    destinations = list(order.destinations.order_by())
    assert len(destinations) == 1
    assert destinations[0].client.id == data["client"].id
    assert destinations[0].delivery_address.id == new_address_id
    products = list(LoadOrderProduct.select().where(LoadOrderProduct.order == order))
    assert len(products) == 1
    assert products[0].product.id == data["product"].id
    assert products[0].quantity == pytest.approx(10)
    assert products[0].unit == data["product"].unit

    # El alta no duplicó el domicilio ni cambió el principal sin preguntar.
    addresses = list(
        ClientAddress.select().where(ClientAddress.client == data["client"]).order_by(ClientAddress.id)
    )
    assert [row.id for row in addresses].count(new_address_id) == 1
    primary_rows = _primary_addresses(data["client"])
    assert len(primary_rows) == 1
    if primary:
        assert primary_rows[0].id == new_address_id
    else:
        assert primary_rows[0].id == data["address"].id


def test_client_without_addresses_gets_the_new_one_as_primary_and_saves(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Client, ClientAddress

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    client = Client.create(name="Cliente Sin Destino 788", cuit="30700000788", iva_condition="RI")
    dialog = _dialog(app)
    _select_transport(dialog, data, app)
    _add_new_destination(
        dialog,
        app,
        monkeypatch,
        client=client,
        typed="Ruta 788",
        primary=True,
        city="Garuhape",
    )
    _add_product(dialog, app, monkeypatch, data["product"], 7)
    dialog.save_button.click()
    app.processEvents()

    order = _persisted_order(dialog)
    assert len(list(order.destinations)) == 1
    address = ClientAddress.get(ClientAddress.client == client)
    assert address.is_primary is True
    assert address.active is True
    assert len(_primary_addresses(client)) == 1


def test_multiple_clients_and_mixed_new_and_existing_addresses_save_once(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication

    from app.models.load_orders import LoadOrderProduct
    from app.models.masters import ClientAddress

    app = QApplication.instance() or QApplication([])
    data = _multi_client_data()
    dialog = _dialog(app)
    _select_transport(dialog, data, app)

    _add_new_destination(
        dialog,
        app,
        monkeypatch,
        client=data["client"],
        typed="Ruta 788",
        primary=False,
    )
    new_address_id = dialog.destinations[0]["address_id"]
    _add_product(dialog, app, monkeypatch, data["product"], 10)

    _add_existing_destination(dialog, app, data["other_client"])
    _add_product(dialog, app, monkeypatch, data["other_product"], 5)

    assert len(dialog.destinations) == 2
    assert dialog._save_blocking_reason() is None
    dialog.save_button.click()
    app.processEvents()

    order = _persisted_order(dialog)
    _assert_order_header(order, data)
    destinations = list(order.destinations.order_by())
    assert len(destinations) == 2
    by_client = {destination.client.id: destination for destination in destinations}
    assert by_client[data["client"].id].delivery_address.id == new_address_id
    assert by_client[data["other_client"].id].delivery_address.id == data["other_address"].id

    products = list(
        LoadOrderProduct.select().where(LoadOrderProduct.order == order).order_by(LoadOrderProduct.id)
    )
    assert len(products) == 2
    assert {line.product.id for line in products} == {
        data["product"].id,
        data["other_product"].id,
    }
    quantities = {line.product.id: line.quantity for line in products}
    assert quantities[data["product"].id] == pytest.approx(10)
    assert quantities[data["other_product"].id] == pytest.approx(5)

    # El cliente con domicilio nuevo conserva su principal anterior.
    assert len(_primary_addresses(data["client"])) == 1
    assert _primary_addresses(data["client"])[0].id == data["address"].id
    assert ClientAddress.select().where(
        (ClientAddress.client == data["client"])
        & (ClientAddress.address == "Ruta 788")
    ).count() == 1


def test_existing_address_control_still_saves_without_touching_masters(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import ClientAddress

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    before = list(ClientAddress.select().order_by(ClientAddress.id))
    dialog = _dialog(app)
    _select_transport(dialog, data, app)
    _add_existing_destination(dialog, app, data["client"])
    _add_product(dialog, app, monkeypatch, data["product"], 10)
    dialog.save_button.click()
    app.processEvents()

    order = _persisted_order(dialog)
    assert [destination.delivery_address.id for destination in order.destinations] == [
        data["address"].id
    ]
    after = list(ClientAddress.select().order_by(ClientAddress.id))
    assert [(row.id, row.is_primary, row.active) for row in after] == [
        (row.id, row.is_primary, row.active) for row in before
    ]


def test_new_address_without_products_explains_and_keeps_draft(db, monkeypatch):
    """El síntoma del incidente: Guardar no respondía y no decía nada.

    Este caso falla con el código previo, porque el botón quedaba deshabilitado
    sin mensaje. Con la corrección, el botón sigue accionable, el motivo queda
    visible y el clic lleva al paso de productos sin perder el borrador.
    """
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_transport(dialog, data, app)
    _add_new_destination(
        dialog,
        app,
        monkeypatch,
        client=data["client"],
        typed="Ruta 788",
        primary=False,
    )
    draft = [dict(destination) for destination in dialog.destinations]
    address_id = dialog.destinations[0]["address_id"]

    assert dialog.save_button.isEnabled() is True
    assert "producto" in dialog.save_hint.text().lower()
    assert dialog.save_button.toolTip().lower().find("producto") >= 0

    dialog.save_button.click()
    app.processEvents()

    assert dialog.created_order is None
    assert "producto" in dialog.feedback.message.lower()
    assert data["client"].name in dialog.feedback.message
    assert dialog.destinations == draft
    assert dialog.destinations[0]["address_id"] == address_id
    assert dialog.step_stack.currentIndex() == 2
    assert dialog.save_hint.isHidden() is False


def test_database_failure_keeps_draft_and_can_be_retried(db, monkeypatch):
    """Un error de base no puede mostrar un mensaje vacío ni perder la carga."""
    from PyQt5.QtWidgets import QApplication, QDialog

    from app.models.load_orders import LoadOrder
    from app.models.masters import ClientAddress

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_transport(dialog, data, app)
    _add_new_destination(
        dialog,
        app,
        monkeypatch,
        client=data["client"],
        typed="Ruta 788",
        primary=False,
    )
    _add_product(dialog, app, monkeypatch, data["product"], 10)
    draft = [dict(destination) for destination in dialog.destinations]
    address_id = dialog.destinations[0]["address_id"]

    real_create = dialog.service.create_order
    calls = {"count": 0}

    def flaky_create_order(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("")
        return real_create(**kwargs)

    monkeypatch.setattr(dialog.service, "create_order", flaky_create_order)

    dialog.save_button.click()
    app.processEvents()

    assert calls["count"] == 1
    assert dialog.created_order is None
    assert dialog.destinations == draft
    assert dialog.destinations[0]["address_id"] == address_id
    assert dialog.result() != QDialog.Accepted
    assert dialog.feedback.message.strip() != ""
    assert "No se pudo guardar la orden" in dialog.feedback.message
    assert LoadOrder.select().count() == 0
    assert ClientAddress.get_by_id(address_id) is not None

    dialog.save_button.click()
    app.processEvents()

    assert calls["count"] == 2
    order = _persisted_order(dialog)
    assert order.id is not None
    # El reintento usa el mismo domicilio: no duplica el maestro.
    assert ClientAddress.select().where(
        (ClientAddress.client == data["client"])
        & (ClientAddress.address == "Ruta 788")
    ).count() == 1


def test_address_creation_rolls_back_if_audit_fails(db):
    """Alta de domicilio atómica: si falla la auditoría, no queda a medias."""
    from app.models.masters import ClientAddress
    from app.services.client_service import ClientService

    data = _master_data()
    old_primary = ClientAddress.get_by_id(data["address"].id)
    assert old_primary.is_primary is True

    class FailingAudit:
        def record(self, **_kwargs):
            raise RuntimeError("auditoria caida")

    service = ClientService(current_user="issue788", audit_service=FailingAudit())

    with pytest.raises(RuntimeError, match="auditoria caida"):
        service.add_address(
            data["client"],
            "entrega",
            "Misiones",
            "Obera",
            "Ruta 788",
            is_primary=True,
        )

    assert ClientAddress.select().where(
        (ClientAddress.client == data["client"])
        & (ClientAddress.address == "Ruta 788")
    ).count() == 0
    old_primary = ClientAddress.get_by_id(data["address"].id)
    assert old_primary.is_primary is True, "el principal anterior se perdió"
    assert len(_primary_addresses(data["client"])) == 1


def test_new_address_can_be_added_while_editing_an_order_and_saved(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication

    from app.models.load_orders import LoadOrderProduct
    from app.models.masters import ClientAddress
    from app.services.load_order_service import LoadOrderService

    app = QApplication.instance() or QApplication([])
    data = _multi_client_data()
    service = LoadOrderService(current_user="issue788")
    order = service.create_order(**_valid_order_payload(data))
    dialog = _dialog(app, order=order)
    _select_transport(dialog, data, app)
    _add_new_destination(
        dialog,
        app,
        monkeypatch,
        client=data["other_client"],
        typed="Ruta 799",
        primary=False,
    )
    new_address_id = dialog.destinations[-1]["address_id"]
    _add_product(dialog, app, monkeypatch, data["other_product"], 8)
    dialog.save_button.click()
    app.processEvents()

    saved = _persisted_order(dialog)
    assert saved.id == order.id
    destinations = list(saved.destinations.order_by())
    assert len(destinations) == 2
    assert destinations[-1].delivery_address.id == new_address_id
    products = list(LoadOrderProduct.select().where(LoadOrderProduct.order == saved))
    assert any(
        line.product.id == data["other_product"].id and line.quantity == pytest.approx(8)
        for line in products
    )
    assert ClientAddress.select().where(
        (ClientAddress.client == data["other_client"])
        & (ClientAddress.address == "Ruta 799")
    ).count() == 1
