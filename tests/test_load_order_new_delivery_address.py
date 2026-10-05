"""Alta de lugar de entrega desde la orden de carga (#658).

El operador escribe un destino que todavia no existe. Antes de este issue el texto
se borraba al perder el foco (`commit_combo_text`) y solo quedaba
`Seleccione cliente y destino.`. Aca se pregunta siempre, y si dice que si, el
domicilio se crea asociado al cliente y el destino queda cargado en la misma orden.
"""

import os

from conftest import _master_data

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _dialog(app):
    from app.services.load_order_service import LoadOrderService
    from app.ui.desktop_app import LoadOrderEntryDialog

    dialog = LoadOrderEntryDialog(LoadOrderService(current_user="issue658"), "issue658")
    app.processEvents()
    return dialog


def _combos(dialog):
    from PyQt5.QtWidgets import QComboBox

    return (
        dialog.findChild(QComboBox, "loadOrderClientInput"),
        dialog.findChild(QComboBox, "loadOrderAddressInput"),
    )


def _select_client(app, dialog, client):
    client_combo, _address_combo = _combos(dialog)
    index = client_combo.findData(client.id)
    assert index >= 0
    client_combo.setCurrentIndex(index)
    app.processEvents()


def _add_destination_click(dialog):
    from PyQt5.QtWidgets import QPushButton

    dialog.findChild(QPushButton, "addLoadOrderClientButton").click()


def _type_destination(dialog, text):
    _client_combo, address_combo = _combos(dialog)
    address_combo.lineEdit().setText(text)
    return address_combo


def _complete_address_dialog(dialog, *, province, city):
    """Responde el formulario real: no se reemplaza el dialogo, se lo completa."""
    from PyQt5.QtWidgets import QLineEdit, QPushButton

    dialog.findChild(QLineEdit, "addressProvinceInput").setText(province)
    dialog.findChild(QLineEdit, "addressCityInput").setText(city)
    dialog.findChild(QPushButton, "saveAddressButton").click()


def test_typed_destination_is_not_wiped_when_it_leaves_the_field(db):
    """El texto escrito es el alta pendiente: no se borra como en `commit_combo_text`."""
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_client(app, dialog, data["client"])
    address_combo = _combos(dialog)[1]

    address_combo.lineEdit().setText("Ruta 21")
    address_combo.lineEdit().editingFinished.emit()
    app.processEvents()

    assert address_combo.lineEdit().text() == "Ruta 21"
    assert dialog._pending_destination_text() == "Ruta 21"


def test_matching_typed_destination_still_selects_the_existing_address(db):
    """El autocompletado no se rompe: el texto exacto sigue eligiendo el domicilio."""
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_client(app, dialog, data["client"])
    address_combo = _combos(dialog)[1]

    label = address_combo.itemText(address_combo.findData(data["address"].id))
    address_combo.lineEdit().setText(label)
    address_combo.lineEdit().editingFinished.emit()
    app.processEvents()

    assert address_combo.currentData() == data["address"].id


def test_typed_destination_asks_and_creates_the_address_for_the_client(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

    from app.models.masters import ClientAddress
    from app.ui.master_abm import ClientAddressEntryDialog

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_client(app, dialog, data["client"])
    address_combo = _type_destination(dialog, "Ruta 21")

    asked = []

    def fake_question(_parent, title, text, *_args):
        asked.append((title, text))
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", fake_question)

    def fake_exec(self):
        from PyQt5.QtWidgets import QLineEdit

        assert self.findChild(QLineEdit, "addressStreetInput").text() == "Ruta 21"
        assert self.findChild(QLineEdit, "addressCityInput").text() == ""
        _complete_address_dialog(self, province="Misiones", city="Obera")
        return QDialog.Accepted

    monkeypatch.setattr(ClientAddressEntryDialog, "exec_", fake_exec)

    _add_destination_click(dialog)
    app.processEvents()

    # Desde #665 se pregunta ademas por el domicilio principal cuando el cliente ya
    # tiene lugares de entrega cargados.
    assert [title for title, _text in asked] == [
        "Nuevo lugar de entrega",
        "Domicilio principal",
    ]
    assert "Ruta 21" in asked[0][1]
    assert data["client"].name in asked[0][1]

    created = ClientAddress.get(
        (ClientAddress.client == data["client"]) & (ClientAddress.address == "Ruta 21")
    )
    assert created.city == "Obera"
    assert created.province == "Misiones"
    assert created.address_type == "entrega"
    assert created.active is True

    assert len(dialog.destinations) == 1
    assert dialog.destinations[0]["address_id"] == created.id
    assert dialog.destinations[0]["client_id"] == data["client"].id
    assert address_combo.currentData() == created.id


def test_declining_the_offer_creates_nothing_and_adds_no_destination(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.models.masters import ClientAddress

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_client(app, dialog, data["client"])
    _type_destination(dialog, "Ruta 21")

    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.No)

    _add_destination_click(dialog)
    app.processEvents()

    assert ClientAddress.select().where(ClientAddress.address == "Ruta 21").count() == 0
    assert dialog.destinations == []
    assert "No se dio de alta el lugar de entrega" in dialog.feedback.text()


def test_cancelling_the_address_dialog_creates_nothing(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

    from app.models.masters import ClientAddress
    from app.ui.master_abm import ClientAddressEntryDialog

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_client(app, dialog, data["client"])
    _type_destination(dialog, "Ruta 21")

    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.Yes)
    monkeypatch.setattr(ClientAddressEntryDialog, "exec_", lambda self: QDialog.Rejected)

    _add_destination_click(dialog)
    app.processEvents()

    assert ClientAddress.select().where(ClientAddress.address == "Ruta 21").count() == 0
    assert dialog.destinations == []


def test_typed_destination_matching_an_existing_address_does_not_ask_to_create(db, monkeypatch):
    """El riesgo real de "siempre preguntar" es duplicar un domicilio que ya existe.

    El combo muestra `Cliente - Ruta 12, Posadas`, asi que escribir `Ruta 12` nunca
    coincide con la etiqueta. Sin esta comparacion se crearia un segundo domicilio.
    """
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.models.masters import ClientAddress

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_client(app, dialog, data["client"])
    address_combo = _type_destination(dialog, "ruta 12")

    def unexpected(*_args, **_kwargs):
        raise AssertionError("no se debe preguntar por un domicilio que ya existe")

    monkeypatch.setattr(QMessageBox, "question", unexpected)

    _add_destination_click(dialog)
    app.processEvents()

    assert ClientAddress.select().where(ClientAddress.client == data["client"]).count() == 1
    assert len(dialog.destinations) == 1
    assert dialog.destinations[0]["address_id"] == data["address"].id
    assert address_combo.currentData() == data["address"].id
    # La orden sigue su curso: el destino existentey lo que el operador quiso cargar.
    assert dialog.feedback.text().endswith("Cliente/destino agregado. Ahora agregue productos.")


def test_typed_city_selects_the_existing_address_in_that_city(db, monkeypatch):
    """Escribir la ciudad es la otra forma natural de elegir un lugar de entrega."""
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.models.masters import ClientAddress

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_client(app, dialog, data["client"])
    _type_destination(dialog, "Posadas")

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no debe preguntar")),
    )

    _add_destination_click(dialog)
    app.processEvents()

    assert ClientAddress.select().where(ClientAddress.client == data["client"]).count() == 1
    assert dialog.destinations[0]["address_id"] == data["address"].id


def test_typed_destination_of_another_client_is_not_reused(db, monkeypatch):
    """La comparacion es contra los domicilios del cliente, no contra los de todos."""
    from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

    from app.models.masters import Client, ClientAddress
    from app.ui.master_abm import ClientAddressEntryDialog

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    other_client = Client.create(name="Cliente Sur 658", cuit="30999999658", iva_condition="RI")
    ClientAddress.create(
        client=other_client,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Ruta 21",
    )
    dialog = _dialog(app)
    _select_client(app, dialog, data["client"])
    address_combo = _type_destination(dialog, "Ruta 21")

    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.Yes)

    def fake_exec(self):
        _complete_address_dialog(self, province="Misiones", city="Obera")
        return QDialog.Accepted

    monkeypatch.setattr(ClientAddressEntryDialog, "exec_", fake_exec)

    _add_destination_click(dialog)
    app.processEvents()

    created = ClientAddress.get(
        (ClientAddress.client == data["client"]) & (ClientAddress.address == "Ruta 21")
    )
    assert created.client.id == data["client"].id
    assert dialog.destinations[0]["address_id"] == created.id
    assert address_combo.currentData() == created.id


def test_without_a_client_no_offer_is_made(db, monkeypatch):
    """El domicilio siempre se crea asociado a un cliente: sin cliente no se pregunta."""
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.models.masters import ClientAddress

    app = QApplication.instance() or QApplication([])
    dialog = _dialog(app)
    _combos(dialog)[1].lineEdit().setText("Ruta 21")

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no debe preguntar")),
    )

    _add_destination_click(dialog)
    app.processEvents()

    assert ClientAddress.select().where(ClientAddress.address == "Ruta 21").count() == 0
    assert dialog.destinations == []
    assert "Seleccione cliente y destino" in dialog.feedback.text()


def test_empty_destination_keeps_the_plain_selection_warning(db, monkeypatch):
    """Con dos domicilios no hay auto-seleccion: sin texto no se pregunta nada."""
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.models.masters import ClientAddress

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    ClientAddress.create(
        client=data["client"],
        address_type="entrega",
        province="Misiones",
        city="Eldorado",
        address="Ruta 12 km 1540",
    )
    dialog = _dialog(app)
    _select_client(app, dialog, data["client"])
    _combos(dialog)[1].clearEditText()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no debe preguntar")),
    )

    _add_destination_click(dialog)
    app.processEvents()

    assert dialog.destinations == []
    assert "Seleccione cliente y destino" in dialog.feedback.text()


def test_single_address_stays_auto_selected_when_nothing_is_typed(db, monkeypatch):
    """Un solo domicilio se elige solo: es el comportamiento previo y no se pierde."""
    from PyQt5.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = _dialog(app)
    _select_client(app, dialog, data["client"])

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("no debe preguntar")),
    )

    _add_destination_click(dialog)
    app.processEvents()

    assert len(dialog.destinations) == 1
    assert dialog.destinations[0]["address_id"] == data["address"].id


def test_client_without_addresses_still_warns_and_allows_the_new_one(db, monkeypatch):
    """El aviso de "sin lugares de entrega" no se pierde: ahora hay salida."""
    from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

    from app.models.masters import Client, ClientAddress
    from app.ui.master_abm import ClientAddressEntryDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente Sin Destino 658", cuit="30700000658", iva_condition="RI")
    dialog = _dialog(app)
    _select_client(app, dialog, client)

    assert "no tiene lugares de entrega activos" in dialog.feedback.text()
    assert _combos(dialog)[1].count() == 1

    _type_destination(dialog, "Ruta 33")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.Yes)

    def fake_exec(self):
        _complete_address_dialog(self, province="Misiones", city="Garuhape")
        return QDialog.Accepted

    monkeypatch.setattr(ClientAddressEntryDialog, "exec_", fake_exec)

    _add_destination_click(dialog)
    app.processEvents()

    created = ClientAddress.get(ClientAddress.client == client)
    assert created.city == "Garuhape"
    assert len(dialog.destinations) == 1
    assert dialog.destinations[0]["address_id"] == created.id


def test_address_dialog_prefills_the_typed_destination_as_delivery(db):
    """El formulario de domicilio llega con la calle escrita y el tipo Entrega."""
    from PyQt5.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton

    from app.models.masters import ClientAddress
    from app.ui.master_abm import ClientAddressEntryDialog

    app = QApplication.instance() or QApplication([])
    data = _master_data()

    dialog = ClientAddressEntryDialog(
        current_user="issue658",
        client_id=data["client"].id,
        prefill_address="Ruta 21",
    )
    app.processEvents()

    assert dialog.findChild(QLineEdit, "addressStreetInput").text() == "Ruta 21"
    assert dialog.findChild(QComboBox, "addressTypeInput").currentData() == "entrega"

    _complete_address_dialog(dialog, province="Misiones", city="Obera")

    created = ClientAddress.get(ClientAddress.address == "Ruta 21")
    assert created.client.id == data["client"].id
    assert created.address_type == "entrega"


def test_address_dialog_without_prefill_leaves_the_street_empty(db):
    """El parametro es opcional: el ABM de domicilios se comporta igual que antes."""
    from PyQt5.QtWidgets import QApplication, QLineEdit

    from app.ui.master_abm import ClientAddressEntryDialog

    app = QApplication.instance() or QApplication([])
    data = _master_data()

    dialog = ClientAddressEntryDialog(current_user="issue658", client_id=data["client"].id)
    app.processEvents()

    assert dialog.findChild(QLineEdit, "addressStreetInput").text() == ""


def test_new_delivery_address_does_not_disturb_other_clients(db, monkeypatch):
    """La comparacion contra domicilios existentes mira solo al cliente elegido."""
    from app.ui.desktop_app import _find_client_delivery_address

    data = _master_data()

    assert _find_client_delivery_address(data["client"].id, "Ruta 12").id == data["address"].id
    assert _find_client_delivery_address(data["client"].id, "ruta  12").id == data["address"].id
    assert _find_client_delivery_address(data["client"].id, "Ruta 12, Posadas").id == data["address"].id
    assert _find_client_delivery_address(data["client"].id, "Ruta 21") is None
    assert _find_client_delivery_address(data["client"].id, "   ") is None


def test_inactive_address_is_not_offered_as_an_existing_destination(db):
    """Un domicilio dado de baja no se reactiva solo: se propone crearlo de nuevo."""
    from app.ui.desktop_app import _find_client_delivery_address

    data = _master_data()
    address = data["address"]
    address.active = False
    address.save()

    assert _find_client_delivery_address(data["client"].id, "Ruta 12") is None