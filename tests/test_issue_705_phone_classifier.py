"""Clasificador de teléfonos y edición rápida del teléfono (#705)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _user(username, profile_name="Administrador"):
    from app.models.security import User, UserProfile

    profile, _ = UserProfile.get_or_create(name=profile_name)
    return User.create(username=username, password_hash="x", profile=profile, active=True)


def _cliente(nombre="Cliente 705", cuit="30707000001", lista=1, phone=None):
    from app.models.masters import Client

    return Client.create(
        name=nombre,
        cuit=cuit,
        iva_condition="RI",
        phone=phone,
        lista_precios=lista,
    )


# --------------------------------------------------------------- clasificador


def test_celular_con_el_15_despues_del_area():
    from app.services.whatsapp_phone_classifier import clasificar_telefono

    clasificacion = clasificar_telefono("011 15 53088679")
    assert clasificacion.es_celular
    assert clasificacion.normalizado == "5491153088679"
    assert clasificacion.es_enviable


def test_celular_sin_separadores():
    from app.services.whatsapp_phone_classifier import clasificar_telefono

    assert clasificar_telefono("0111553088679").normalizado == "5491153088679"
    assert clasificar_telefono("011-1553088679").normalizado == "5491153088679"
    assert clasificar_telefono("011-15 5913 3141").normalizado == "5491159133141"


def test_celular_internacional():
    from app.services.whatsapp_phone_classifier import clasificar_telefono

    assert clasificar_telefono("+5491153088679").normalizado == "5491153088679"
    assert clasificar_telefono("+54 9 3416 51-0261").normalizado == "5493416510261"
    assert clasificar_telefono("+549 1151830594").normalizado == "5491151830594"


def test_celular_con_area_de_cuatro_digitos():
    from app.services.whatsapp_phone_classifier import clasificar_telefono

    assert clasificar_telefono("02293-15663324").normalizado == "5492293663324"
    assert clasificar_telefono("0221-154947551").normalizado == "5492214947551"


def test_celular_con_area_invalida_no_es_celular():
    """Un fijo con "15" de casualidad y un área que no existe no es un celular."""
    from app.services.whatsapp_phone_classifier import clasificar_telefono

    # 0341 572-3786 es un fijo de Rosario: el "15" está de casualidad y el área
    # de dos dígitos "34" no existe.
    clasificacion = clasificar_telefono("0341-5723786")
    assert not clasificacion.es_celular
    assert clasificacion.estado == "posible"


def test_fijo_con_guiones_no_es_dos_telefonos():
    from app.services.whatsapp_phone_classifier import clasificar_telefono

    clasificacion = clasificar_telefono("011-4441-2835")
    assert clasificacion.estado == "posible"
    assert not clasificacion.propuesta


def test_linea_fija_es_posible_y_no_se_manda_solo():
    """Un número local de 10 u 11 dígitos puede ser fijo o un celular sin el "15"."""
    from app.services.whatsapp_phone_classifier import clasificar_telefono, numero_enviable

    clasificacion = clasificar_telefono("011 3511 1221")
    assert clasificacion.estado == "posible"
    assert not clasificacion.es_enviable
    assert numero_enviable("011 3511 1221") == ""
    # El normalizado que se muestra es el que la app mandaría hoy.
    assert clasificacion.normalizado == "5491135111221"


def test_celular_sin_codigo_de_area():
    from app.services.whatsapp_phone_classifier import clasificar_telefono

    clasificacion = clasificar_telefono("1531234567")
    assert clasificacion.estado == "posible"
    assert "área" in clasificacion.motivo


def test_telefono_con_letras_es_invalido():
    from app.services.whatsapp_phone_classifier import clasificar_telefono

    clasificacion = clasificar_telefono("PEREYRA 011-4687-9199")
    assert clasificacion.estado == "invalido"
    assert clasificacion.tiene_problema


def test_dos_telefonos_en_el_mismo_campo():
    from app.services.whatsapp_phone_classifier import clasificar_telefono

    clasificacion = clasificar_telefono("01148975105//01157357632")
    assert clasificacion.estado == "invalido"
    assert clasificacion.propuesta == "01148975105"

    clasificacion = clasificar_telefono("3404 633133 - 3404 634132")
    assert clasificacion.estado == "invalido"
    assert clasificacion.propuesta


def test_telefono_vacio_o_muy_corto():
    from app.services.whatsapp_phone_classifier import clasificar_telefono

    assert clasificar_telefono("").estado == "vacio"
    assert clasificar_telefono(None).estado == "vacio"
    assert clasificar_telefono("123").estado == "invalido"


# --------------------------------------------------------- edición del teléfono


def test_set_phone_guarda_y_audita(db):
    from app.models.audit import AuditLog
    from app.models.masters import Client
    from app.services.client_service import ClientService

    cliente = _cliente(phone=None)
    ClientService("admin-705").set_phone(cliente, "011 15 53088679")

    assert Client.get_by_id(cliente.id).phone == "011 15 53088679"
    acciones = [
        row.action
        for row in AuditLog.select().where(AuditLog.record_ref == f"Client:{cliente.id}")
    ]
    assert "actualizar teléfono" in acciones


def test_set_phone_rechaza_basura(db):
    from app.services.client_service import ClientService

    cliente = _cliente(phone="011 15 53088679")
    try:
        ClientService("admin-705").set_phone(cliente, "PEREYRA 011-4687-9199")
    except ValueError as exc:
        assert "no es válido" in str(exc)
    else:
        raise AssertionError("tenía que rechazar el teléfono con letras")


def test_set_phone_acepta_una_linea_fija(db):
    from app.models.masters import Client
    from app.services.client_service import ClientService

    cliente = _cliente(phone=None)
    ClientService("admin-705").set_phone(cliente, "011 3511 1221")
    assert Client.get_by_id(cliente.id).phone == "011 3511 1221"


def test_set_phone_puede_borrar_el_telefono(db):
    from app.models.masters import Client
    from app.services.client_service import ClientService

    cliente = _cliente(phone="011 15 53088679")
    ClientService("admin-705").set_phone(cliente, "")
    assert Client.get_by_id(cliente.id).phone is None


def test_set_phone_sin_cambio_no_escribe_nada(db):
    from app.models.audit import AuditLog
    from app.models.masters import Client
    from app.services.client_service import ClientService

    cliente = _cliente(phone="011 15 53088679")
    ClientService("admin-705").set_phone(cliente, "011 15 53088679")
    assert AuditLog.select().where(AuditLog.record_ref == f"Client:{cliente.id}").count() == 0
    assert Client.get_by_id(cliente.id).phone == "011 15 53088679"


def test_set_phone_no_toca_la_lista_ni_el_resto(db):
    from app.models.masters import Client
    from app.services.client_service import ClientService

    cliente = _cliente(nombre="Con Lista", cuit="30707000002", lista=3, phone=None)
    ClientService("admin-705").set_phone(cliente, "011 15 53088679")

    guardado = Client.get_by_id(cliente.id)
    assert guardado.lista_precios == 3
    assert guardado.name == "Con Lista"
    assert guardado.cuit == "30707000002"
    assert guardado.iva_condition == "RI"


# --------------------------------------------------------------------- UI


def test_clientes_page_has_phone_button(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.services.permission_service import PermissionService
    from app.ui.master_abm import build_client_abm_page

    PermissionService().seed_defaults()
    app = QApplication.instance() or QApplication([])
    admin = _user("admin-telefono-705")
    page = build_client_abm_page(
        user=admin,
        current_user=admin.username,
        view_ledger_callback=lambda _client: None,
    )
    app.processEvents()

    button = page.findChild(QPushButton, "editClientPhoneButton")
    assert button is not None
    assert button.text() == "Teléfono"


def test_dialog_muestra_la_clasificacion_en_vivo(db):
    from PyQt5.QtWidgets import QApplication, QLabel

    from app.ui.client_phone_edit_dialog import ClientPhoneEditDialog

    app = QApplication.instance() or QApplication([])
    cliente = _cliente(phone="011 15 53088679")
    dialog = ClientPhoneEditDialog(client=cliente, current_user="admin-705")
    app.processEvents()

    etiqueta = dialog.findChild(QLabel, "clientPhoneClassificationLabel")
    assert "Celular" in etiqueta.text()

    dialog.phone_input.setText("011 3511 1221")
    app.processEvents()
    assert "Revisar" in etiqueta.text()

    dialog.phone_input.setText("PEREYRA 011-4687-9199")
    app.processEvents()
    assert "No válido" in etiqueta.text()
