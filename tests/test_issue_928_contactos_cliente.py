"""Telefono y WhatsApp dentro de Editar y de la ficha del cliente (#928).

El punto de entrada unico es el formulario del cliente. La grilla ya no tiene
los botones ``Telefono`` ni ``WhatsApp`` que agregaron #705 y #923.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _cliente(**kwargs):
    from app.models.masters import Client

    values = {
        "name": "Cliente 928",
        "cuit": "30928000001",
        "iva_condition": "RI",
    }
    values.update(kwargs)
    return Client.create(**values)


def _dialog(cliente):
    from app.ui.master_abm import ClientEntryDialog

    return ClientEntryDialog(current_user="admin928", record_id=cliente.id)


def test_editar_guarda_telefono_y_whatsapp_juntos(db):
    from PyQt5.QtWidgets import QPushButton

    from app.models.masters import Client

    app = _app()
    cliente = _cliente()
    dialog = _dialog(cliente)

    dialog.phone_input.setText("+54 9 376 4555000")
    dialog.whatsapp_input.setText("011 15 53088679")
    app.processEvents()
    dialog.findChild(QPushButton, "saveClientButton").click()
    app.processEvents()

    guardado = Client.get_by_id(cliente.id)
    assert guardado.phone == "+54 9 376 4555000"
    assert guardado.whatsapp_phone == "5491153088679"
    assert dialog.result() == dialog.Accepted


def test_editar_rechaza_un_whatsapp_dudoso_sin_guardar_nada(db):
    from PyQt5.QtWidgets import QPushButton

    from app.models.masters import Client

    app = _app()
    cliente = _cliente(phone="011 15 3764555")
    dialog = _dialog(cliente)

    dialog.phone_input.setText("011 15 3764999")
    dialog.whatsapp_input.setText("011 4441-2835")
    app.processEvents()
    dialog.findChild(QPushButton, "saveClientButton").click()
    app.processEvents()

    guardado = Client.get_by_id(cliente.id)
    assert guardado.phone == "011 15 3764555"
    assert guardado.whatsapp_phone is None
    assert dialog.result() != dialog.Accepted


def test_editar_muestra_el_whatsapp_guardado_y_permite_borrarlo(db):
    from PyQt5.QtWidgets import QPushButton

    from app.models.masters import Client

    app = _app()
    cliente = _cliente(whatsapp_phone="5491153088679")
    dialog = _dialog(cliente)

    assert dialog.whatsapp_input.text() == "+5491153088679"

    dialog.whatsapp_input.setText("")
    app.processEvents()
    dialog.findChild(QPushButton, "saveClientButton").click()
    app.processEvents()

    assert Client.get_by_id(cliente.id).whatsapp_phone is None


def test_editar_muestra_la_clasificacion_en_vivo(db):
    from PyQt5.QtWidgets import QLabel

    app = _app()
    dialog = _dialog(_cliente())

    dialog.phone_input.setText("011 15 53088679")
    dialog.whatsapp_input.setText("PEREYRA 011-4687-9199")
    app.processEvents()

    telefono = dialog.findChild(QLabel, "clientPhoneClassificationLabel")
    whatsapp = dialog.findChild(QLabel, "clientWhatsappClassificationLabel")
    assert "Celular" in telefono.text()
    assert "No válido" in whatsapp.text()


def test_la_ficha_muestra_el_whatsapp_dedicado(db):
    from PyQt5.QtWidgets import QLabel

    from app.ui.master_detail_dialogs import ClientDetailDialog

    app = _app()
    cliente = _cliente(whatsapp_phone="5491153088679")
    dialog = ClientDetailDialog(current_user="admin928", record_id=cliente.id)

    etiqueta = dialog.findChild(QLabel, "clientDetailWhatsappValue")
    assert etiqueta is not None
    assert etiqueta.text() == "+5491153088679"

    sin_numero = _cliente(name="Cliente 928 sin WA", cuit="30928000002")
    dialog = ClientDetailDialog(current_user="admin928", record_id=sin_numero.id)
    assert dialog.findChild(QLabel, "clientDetailWhatsappValue").text() == "Sin WhatsApp"


def test_la_grilla_ya_no_tiene_botones_de_telefono_ni_whatsapp(db):
    from PyQt5.QtWidgets import QPushButton

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.master_abm import build_client_abm_page

    PermissionService().seed_defaults()
    perfil, _ = UserProfile.get_or_create(name="Administrador")
    usuario = User.create(
        username="admin928", password_hash="x", profile=perfil, active=True
    )
    app = _app()
    page = build_client_abm_page(
        user=usuario,
        current_user=usuario.username,
        view_ledger_callback=lambda _client: None,
    )
    app.processEvents()

    assert page.findChild(QPushButton, "editClientPhoneButton") is None
    assert page.findChild(QPushButton, "editClientWhatsappButton") is None
