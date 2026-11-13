"""Numero de WhatsApp dedicado para clientes y vendedores (#923)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_cliente_tiene_campo_whatsapp_phone(db):
    from app.models.masters import Client

    cliente = Client.create(name="Cliente 923", cuit="30923000001", iva_condition="RI")
    assert cliente.whatsapp_phone is None


def test_vendedor_tiene_campo_whatsapp_phone(db):
    from app.models.masters import Salesperson

    vendedor = Salesperson.create(name="Vendedor 923")
    assert vendedor.whatsapp_phone is None


def test_el_esquema_existente_gana_la_columna(db):
    """La columna tiene que aparecer sola en una base que ya existe (#923).

    Las tablas quedan con la forma que tenian antes del cambio: las mismas
    filas, pero sin la columna ``whatsapp_phone``. Como la tabla ya existe,
    ``ensure_runtime_schema`` no puede resolverlo por ``CREATE TABLE``
    (``create_tables(safe=True)`` no toca una tabla que ya esta): la unica
    ruta que queda es ``ALTER TABLE ... ADD COLUMN``, que es la que corre en
    la base real cuando la app nueva se abre contra la base vieja.
    """
    from app.config.schema import ensure_runtime_schema
    from app.models.masters import Client, Salesperson

    cliente = Client.create(
        name="Cliente Legacy 923",
        cuit="30923000009",
        iva_condition="RI",
        phone="3511550002",
    )
    vendedor = Salesperson.create(name="Vendedor Legacy 923", phone="3511550001")

    # La base queda como estaba antes del cambio.
    db.execute_sql("ALTER TABLE `client` DROP COLUMN `whatsapp_phone`")
    db.execute_sql("ALTER TABLE `salesperson` DROP COLUMN `whatsapp_phone`")

    columnas_client = [columna.name for columna in db.get_columns("client")]
    columnas_salesperson = [columna.name for columna in db.get_columns("salesperson")]
    assert "whatsapp_phone" not in columnas_client
    assert "whatsapp_phone" not in columnas_salesperson

    ensure_runtime_schema(db)

    # ALTER TABLE agrega la columna al final de la tabla. Si la tabla se
    # recreara, el orden seria el de declaracion del modelo y estas listas no
    # darian igual.
    assert [
        columna.name for columna in db.get_columns("client")
    ] == columnas_client + ["whatsapp_phone"]
    assert [
        columna.name for columna in db.get_columns("salesperson")
    ] == columnas_salesperson + ["whatsapp_phone"]

    # Las filas que ya estaban siguen ahi: la columna es adicional, no pisa
    # el ``phone`` que el cliente y el vendedor ya tenian.
    cliente = Client.get_by_id(cliente.id)
    vendedor = Salesperson.get_by_id(vendedor.id)
    assert cliente.phone == "3511550002"
    assert vendedor.phone == "3511550001"

    # Y las filas viejas quedan sin numero de WhatsApp: no se inventa un valor.
    assert cliente.whatsapp_phone is None
    assert vendedor.whatsapp_phone is None


# ------------------------------------------------------------------ resolver


def test_el_whatsapp_dedicado_manda_sobre_el_telefono():
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_DEDICADO,
        resolver_contacto,
    )

    contacto = resolver_contacto(
        whatsapp_phone="+5491153088679", phone="011 4441-2835"
    )
    assert contacto.enviable
    assert contacto.numero == "5491153088679"
    assert contacto.origen == ORIGEN_DEDICADO


def test_sin_whatsapp_dedicado_cae_al_telefono_si_es_celular():
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_TELEFONO,
        resolver_contacto,
    )

    contacto = resolver_contacto(whatsapp_phone="", phone="011 15 53088679")
    assert contacto.enviable
    assert contacto.numero == "5491153088679"
    assert contacto.origen == ORIGEN_TELEFONO


def test_un_telefono_dudoso_no_es_destino():
    from app.services.whatsapp_contact_resolver import resolver_contacto

    contacto = resolver_contacto(whatsapp_phone="", phone="011 4441-2835")
    assert not contacto.enviable
    assert contacto.numero == ""
    assert "dudoso" in contacto.mensaje


def test_un_whatsapp_cargado_que_no_es_celular_no_cae_al_telefono():
    """Si el operador cargo un WhatsApp roto, no se manda a otro numero."""
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_DEDICADO,
        resolver_contacto,
    )

    contacto = resolver_contacto(
        whatsapp_phone="011 4441-2835", phone="011 15 53088679"
    )
    assert not contacto.enviable
    assert contacto.origen == ORIGEN_DEDICADO


def test_sin_telefono_no_hay_destino():
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_NINGUNO,
        resolver_contacto,
    )

    contacto = resolver_contacto(whatsapp_phone="", phone="")
    assert not contacto.enviable
    assert contacto.origen == ORIGEN_NINGUNO


def test_con_el_flag_apagado_se_ignora_el_campo_nuevo():
    from app.services.whatsapp_contact_resolver import (
        ORIGEN_TELEFONO,
        resolver_contacto,
    )

    contacto = resolver_contacto(
        whatsapp_phone="+5491153088679",
        phone="011 15 53088679",
        preferir_dedicado=False,
    )
    assert contacto.numero == "5491153088679"
    assert contacto.origen == ORIGEN_TELEFONO


def test_el_mensaje_es_el_mismo_que_el_de_hoy():
    """El texto de error no cambia: el operador ve lo mismo que siempre."""
    from app.services.account_statement_share_service import normalize_whatsapp_phone
    from app.services.whatsapp_contact_resolver import resolver_contacto

    # El caso valido entra tambien: cuando el numero se puede mandar, el
    # mensaje es "" (no hay error que mostrar). El centinela es "" y no None
    # porque el resolver devuelve "" en el caso enviable.
    for numero in ("011 4441-2835", "01148975105//01157357632", "", "011 15 53088679"):
        try:
            normalize_whatsapp_phone(numero)
            esperado = ""
        except ValueError as exc:
            esperado = str(exc)
        contacto = resolver_contacto(whatsapp_phone="", phone=numero)
        assert contacto.mensaje == esperado


# ------------------------------------------------------------------ servicio


def _usuario(nombre="admin923"):
    from app.models.security import User, UserProfile

    perfil, _ = UserProfile.get_or_create(name="Administrador")
    return User.create(username=nombre, password_hash="x", profile=perfil, active=True)


def test_guarda_el_whatsapp_normalizado(db):
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(name="Cliente WS", cuit="30923000002", iva_condition="RI")
    WhatsAppContactService("admin923").set_client_whatsapp_phone(
        cliente, "011 15 53088679"
    )
    assert cliente.whatsapp_phone == "5491153088679"


def test_no_toca_el_telefono(db):
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(
        name="Cliente WS2", cuit="30923000003", iva_condition="RI", phone="011 4441-2835"
    )
    WhatsAppContactService("admin923").set_client_whatsapp_phone(
        cliente, "+5491153088679"
    )
    assert cliente.phone == "011 4441-2835"


def test_rechaza_un_telefono_dudoso(db):
    import pytest

    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(name="Cliente WS3", cuit="30923000004", iva_condition="RI")
    with pytest.raises(ValueError):
        WhatsAppContactService("admin923").set_client_whatsapp_phone(
            cliente, "011 4441-2835"
        )
    assert cliente.whatsapp_phone is None


def test_rechaza_un_numero_invalido(db):
    import pytest

    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(name="Cliente WS4", cuit="30923000005", iva_condition="RI")
    with pytest.raises(ValueError):
        WhatsAppContactService("admin923").set_client_whatsapp_phone(
            cliente, "01148975105//01157357632"
        )


def test_audita_el_cambio(db):
    from app.models.audit import AuditLog
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    usuario = _usuario("admin923")
    cliente = Client.create(name="Cliente WS5", cuit="30923000006", iva_condition="RI")
    WhatsAppContactService("admin923").set_client_whatsapp_phone(
        cliente, "+5491153088679"
    )
    registro = (
        AuditLog.select()
        .where(AuditLog.record_ref == f"Client:{cliente.id}")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert registro is not None
    assert registro.action == "actualizar WhatsApp"
    assert registro.user_id == usuario.id


def test_si_no_cambia_no_escribe_ni_audita(db):
    from app.models.audit import AuditLog
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(name="Cliente WS6", cuit="30923000007", iva_condition="RI")
    servicio = WhatsAppContactService("admin923")
    servicio.set_client_whatsapp_phone(cliente, "+5491153088679")
    antes = AuditLog.select().where(AuditLog.record_ref == f"Client:{cliente.id}").count()
    servicio.set_client_whatsapp_phone(cliente, "011 15 53088679")
    despues = AuditLog.select().where(AuditLog.record_ref == f"Client:{cliente.id}").count()
    assert antes == despues


def test_guarda_el_whatsapp_del_vendedor(db):
    from app.models.masters import Salesperson
    from app.services.whatsapp_contact_service import WhatsAppContactService

    vendedor = Salesperson.create(name="Vendedor WS", phone="2236800402")
    WhatsAppContactService("admin923").set_salesperson_whatsapp_phone(
        vendedor, "+5491153088679"
    )
    assert vendedor.whatsapp_phone == "5491153088679"
    assert vendedor.phone == "2236800402"


def test_un_numero_vacio_borra_el_whatsapp(db):
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(
        name="Cliente WS7", cuit="30923000028", iva_condition="RI", whatsapp_phone="5491153088679"
    )
    WhatsAppContactService("admin923").set_client_whatsapp_phone(cliente, "")
    assert cliente.whatsapp_phone is None


# ------------------------------------------------------- correccion 1: mensaje


def test_el_mensaje_de_dos_telefonos_no_manda_a_cargar_el_15(db):
    """Con dos telefonos en el campo, el "15" no es el consejo (#923).

    El consejo tiene que decir que hacer: cargar el "15" no arregla un campo
    con dos numeros.
    """
    import pytest

    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(name="Cliente WS8", cuit="30923000029", iva_condition="RI")
    with pytest.raises(ValueError) as exc:
        WhatsAppContactService("admin923").set_client_whatsapp_phone(
            cliente, "01148975105//01157357632"
        )
    mensaje = str(exc.value)
    assert "15" not in mensaje
    assert "un solo numero" in mensaje


def test_el_mensaje_del_numero_sin_el_9_dice_que_agregue_el_9(db):
    """Un internacional sin el 9 se arregla con el 9, no con el "15" (#923)."""
    import pytest

    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(name="Cliente WS9", cuit="30923000030", iva_condition="RI")
    with pytest.raises(ValueError) as exc:
        WhatsAppContactService("admin923").set_client_whatsapp_phone(
            cliente, "+54 11 53088679"
        )
    mensaje = str(exc.value)
    assert "internacional" in mensaje
    assert "con el 9" in mensaje


# --------------------------------------------- correccion 2: None es un error


def test_un_none_no_borra_el_whatsapp(db):
    """``None`` es un error del que lo llama, no un borrado (#923)."""
    import pytest

    from app.models.audit import AuditLog
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(
        name="Cliente WS10", cuit="30923000031", iva_condition="RI", whatsapp_phone="5491153088679"
    )
    with pytest.raises(ValueError):
        WhatsAppContactService("admin923").set_client_whatsapp_phone(cliente, None)

    # El numero que estaba cargado sigue cargado: no se borro por error.
    assert Client.get_by_id(cliente.id).whatsapp_phone == "5491153088679"
    assert (
        AuditLog.select().where(AuditLog.record_ref == f"Client:{cliente.id}").count() == 0
    )


# --------------------------------------- correccion 3: renormalizar lo guardado


def test_un_valor_guardado_con_espacios_se_renormaliza(db):
    """Un valor con espacios se corrige y queda auditado el antes real (#923)."""
    from app.models.audit import AuditLog
    from app.models.masters import Client
    from app.services.whatsapp_contact_service import WhatsAppContactService

    cliente = Client.create(
        name="Cliente WS11",
        cuit="30923000032",
        iva_condition="RI",
        whatsapp_phone=" 5491153088679 ",
    )
    WhatsAppContactService("admin923").set_client_whatsapp_phone(
        cliente, "011 15 53088679"
    )

    assert cliente.whatsapp_phone == "5491153088679"
    assert Client.get_by_id(cliente.id).whatsapp_phone == "5491153088679"

    registro = (
        AuditLog.select()
        .where(AuditLog.record_ref == f"Client:{cliente.id}")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert registro is not None
    assert registro.old_value == {"whatsapp_phone": " 5491153088679 "}
    assert registro.new_value == {"whatsapp_phone": "5491153088679"}


# -------------------------------------------------------------------- flag


def _sin_env_real(monkeypatch, tmp_path):
    """Apunta ``FEMAG_ENV_FILE`` a un archivo inexistente (#923).

    Asi el test no depende de la fixture autouse de ``conftest.py``: si esa
    fixture cambia, el ``.env`` real del developer tampoco puede encender el
    flag. Es el mismo patron que usa ``tests/test_config.py``.
    """
    monkeypatch.setenv("FEMAG_ENV_FILE", str(tmp_path / "missing.env"))


def test_el_flag_esta_apagado_por_default(monkeypatch, tmp_path):
    from app.config.settings import load_settings

    _sin_env_real(monkeypatch, tmp_path)
    monkeypatch.delenv("FEMAG_WHATSAPP_DEDICADO", raising=False)
    assert load_settings().whatsapp_contact_dedicado is False


def test_el_flag_se_enciende_con_la_variable(monkeypatch, tmp_path):
    from app.config.settings import load_settings

    _sin_env_real(monkeypatch, tmp_path)
    monkeypatch.setenv("FEMAG_WHATSAPP_DEDICADO", "1")
    assert load_settings().whatsapp_contact_dedicado is True


@pytest.mark.parametrize(
    "valor",
    ["1", "true", "yes", "si", "sí", "on"],
)
def test_el_flag_enciende_con_cualquier_valor_aceptado(monkeypatch, tmp_path, valor):
    """El contrato del flag acepta todos los valores truthy declarados (#923).

    No se prueba el helper ``_flag_enabled`` en general: lo que importa es que
    este flag se encienda con cualquiera de las formas que el administrador
    puede escribir en el ``.env`` del puesto.
    """
    from app.config.settings import load_settings

    _sin_env_real(monkeypatch, tmp_path)
    monkeypatch.setenv("FEMAG_WHATSAPP_DEDICADO", valor)
    assert load_settings().whatsapp_contact_dedicado is True


@pytest.mark.parametrize("valor", ["0", "false", "no", ""])
def test_el_flag_queda_apagado_con_un_valor_no_aceptado(monkeypatch, tmp_path, valor):
    """Los valores que no son truthy dejan el flag apagado (#923)."""
    from app.config.settings import load_settings

    _sin_env_real(monkeypatch, tmp_path)
    monkeypatch.setenv("FEMAG_WHATSAPP_DEDICADO", valor)
    assert load_settings().whatsapp_contact_dedicado is False


# ----------------------------------------------------------------- interfaz


@pytest.fixture(scope="module")
def app():
    """La app de Qt para poder instanciar los dialogos (#923).

    Se crea una sola vez por modulo y se mantiene viva: si se perdiera al
    terminar cada test, el dialogo del test siguiente encontraria widgets
    destruidos.
    """
    from PyQt5.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_el_dialogo_guarda_el_whatsapp(db, app):
    from app.models.masters import Client
    from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog

    cliente = Client.create(name="Cliente Dialogo", cuit="30923000008", iva_condition="RI")
    dialogo = ClientWhatsappEditDialog(client=cliente, current_user="admin923")
    dialogo.whatsapp_input.setText("011 15 53088679")
    dialogo._guardar()
    assert cliente.whatsapp_phone == "5491153088679"


def test_el_dialogo_no_guarda_un_numero_dudoso(db, app):
    from PyQt5.QtWidgets import QDialog

    from app.models.masters import Client
    from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog

    cliente = Client.create(name="Cliente Dialogo2", cuit="30923000009", iva_condition="RI")
    dialogo = ClientWhatsappEditDialog(client=cliente, current_user="admin923")
    dialogo.whatsapp_input.setText("011 4441-2835")
    dialogo._guardar()
    assert cliente.whatsapp_phone is None

    # El operador recibe el motivo: el mensaje del servicio dice que hacer.
    assert "no se puede usar para WhatsApp" in dialogo.feedback.message
    assert "Cargue el celular con el 15" in dialogo.feedback.message
    # Y el dialogo sigue abierto: no se guardo nada.
    assert dialogo.result() != QDialog.Accepted


def test_el_dialogo_muestra_el_estado_de_la_clasificacion(db, app):
    from app.models.masters import Client
    from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog

    cliente = Client.create(name="Cliente Dialogo3", cuit="30923000010", iva_condition="RI")
    dialogo = ClientWhatsappEditDialog(client=cliente, current_user="admin923")
    dialogo.whatsapp_input.setText("011 15 53088679")
    assert "Celular" in dialogo.classification_label.text()
    dialogo.whatsapp_input.setText("011 4441-2835")
    assert "Revisar" in dialogo.classification_label.text()


def test_el_dialogo_reabre_un_cliente_con_whatsapp(db, app):
    """Un WhatsApp ya guardado se tiene que poder reabrir y guardar (#923).

    El valor guardado es el normalizado sin "+" ("5491153088679"). Si el
    dialogo lo precarga tal cual, el clasificador no lo reconoce (solo
    entiende el formato internacional si el texto empieza con "+"), el label
    dice "No valido" y "Guardar" falla. Precargando la forma internacional,
    el numero se ve como celular y guardar no cambia nada.
    """
    from PyQt5.QtWidgets import QDialog

    from app.models.audit import AuditLog
    from app.models.masters import Client
    from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog

    cliente = Client.create(
        name="Cliente Reabierto",
        cuit="30923000033",
        iva_condition="RI",
        whatsapp_phone="5491153088679",
    )
    dialogo = ClientWhatsappEditDialog(client=cliente, current_user="admin923")

    assert "Celular" in dialogo.classification_label.text()

    dialogo._guardar()

    # El dialogo cierra y el valor guardado sigue siendo el mismo.
    assert dialogo.result() == QDialog.Accepted
    assert cliente.whatsapp_phone == "5491153088679"
    assert Client.get_by_id(cliente.id).whatsapp_phone == "5491153088679"
    # Como el valor no cambio, no hay nada que auditar.
    assert (
        AuditLog.select().where(AuditLog.record_ref == f"Client:{cliente.id}").count() == 0
    )


def test_el_dialogo_vacio_borra_el_whatsapp(db, app):
    """Un numero vacio borra el WhatsApp: no es un error (#923)."""
    from app.models.masters import Client
    from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog

    cliente = Client.create(
        name="Cliente Borrado",
        cuit="30923000034",
        iva_condition="RI",
        whatsapp_phone="5491153088679",
    )
    dialogo = ClientWhatsappEditDialog(client=cliente, current_user="admin923")
    dialogo.whatsapp_input.setText("")
    dialogo._guardar()

    assert cliente.whatsapp_phone is None
    assert Client.get_by_id(cliente.id).whatsapp_phone is None


def test_el_dialogo_no_toca_el_telefono_general(db, app):
    """El ``phone`` del cliente no se toca ni al guardar ni al borrar (#923)."""
    from app.models.masters import Client
    from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog

    cliente = Client.create(
        name="Cliente Telefono",
        cuit="30923000035",
        iva_condition="RI",
        phone="011 4441-2835",
        whatsapp_phone="5491153088679",
    )

    dialogo = ClientWhatsappEditDialog(client=cliente, current_user="admin923")
    dialogo.whatsapp_input.setText("011 15 59133141")
    dialogo._guardar()
    assert cliente.whatsapp_phone == "5491159133141"
    assert cliente.phone == "011 4441-2835"

    dialogo = ClientWhatsappEditDialog(client=cliente, current_user="admin923")
    dialogo.whatsapp_input.setText("")
    dialogo._guardar()
    assert cliente.whatsapp_phone is None
    assert cliente.phone == "011 4441-2835"
    assert Client.get_by_id(cliente.id).phone == "011 4441-2835"


def test_el_dialogo_audita_el_cambio(db, app):
    """Todo cambio real escribe la fila de auditoria (#923)."""
    from app.models.audit import AuditLog
    from app.models.masters import Client
    from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog

    usuario = _usuario("admin923")
    cliente = Client.create(
        name="Cliente Auditoria",
        cuit="30923000036",
        iva_condition="RI",
        whatsapp_phone="5491153088679",
    )

    # Un cambio real: guardar un celular distinto.
    dialogo = ClientWhatsappEditDialog(client=cliente, current_user="admin923")
    dialogo.whatsapp_input.setText("011 15 59133141")
    dialogo._guardar()
    # Y un borrado: tambien es un cambio real.
    dialogo = ClientWhatsappEditDialog(client=cliente, current_user="admin923")
    dialogo.whatsapp_input.setText("")
    dialogo._guardar()

    filas = list(
        AuditLog.select().where(AuditLog.record_ref == f"Client:{cliente.id}")
    )
    assert len(filas) == 2
    assert {fila.action for fila in filas} == {"actualizar WhatsApp"}
    assert {fila.user_id for fila in filas} == {usuario.id}


# ------------------------------------------------------- grilla de clientes


def test_la_grilla_de_clientes_muestra_el_whatsapp(db):
    from app.models.masters import Client
    from app.ui.master_abm import master_abm_configs

    cliente = Client.create(
        name="Cliente Grilla",
        cuit="30923000011",
        iva_condition="RI",
        whatsapp_phone="5491153088679",
    )
    config = master_abm_configs()["clients"]
    assert "WhatsApp" in config.columns
    filas = config.rows_fn()
    fila = [f for f in filas if f[0] == cliente.id][0]

    # La fila arranca con el id, que no es una columna visible: los valores
    # que se pintan en la grilla son ``fila[1:]`` y van en el orden de
    # ``config.columns``.
    visibles = fila[1:]
    assert dict(zip(config.columns, visibles))["WhatsApp"] == "5491153088679"
    assert fila[config.columns.index("WhatsApp") + 1] == "5491153088679"


def _pagina_de_clientes(app, usuario):
    """Arma la pantalla real de Clientes, como la que ve el operador."""
    from app.ui.master_abm import build_client_abm_page

    pagina = build_client_abm_page(
        user=usuario,
        current_user=usuario.username,
        view_ledger_callback=lambda _client: None,
    )
    app.processEvents()
    return pagina


def test_el_boton_de_whatsapp_abre_el_dialogo_del_cliente(db, app):
    """El boton tiene que abrir el dialogo de verdad (#923).

    Un boton visible sin accion real no cierra el PR: por eso el test abre el
    dialogo de verdad y mira que sea el del cliente seleccionado.
    """
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QPushButton

    from app.models.masters import Client
    from app.services.permission_service import PermissionService
    from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog

    PermissionService().seed_defaults()
    usuario = _usuario("admin923-boton")
    cliente = Client.create(name="Cliente Boton", cuit="30923000037", iva_condition="RI")
    pagina = _pagina_de_clientes(app, usuario)

    boton = pagina.findChild(QPushButton, "editClientWhatsappButton")
    assert boton is not None
    assert boton.text() == "WhatsApp"
    assert boton.toolTip() == (
        "Carga el numero de WhatsApp del cliente. Solo se aceptan celulares: "
        "el telefono general queda aparte."
    )

    errores = []

    def revisar() -> None:
        dialogo = app.activeModalWidget()
        try:
            assert isinstance(dialogo, ClientWhatsappEditDialog)
            assert dialogo.client.id == cliente.id
        except BaseException as exc:  # noqa: BLE001 - el error se re-lanza abajo
            errores.append(exc)
        finally:
            if dialogo is not None:
                dialogo.reject()

    QTimer.singleShot(0, revisar)
    boton.click()
    app.processEvents()

    if errores:
        raise errores[0]


def test_el_boton_de_whatsapp_sin_cliente_seleccionado_no_abre_nada(db, app):
    """Sin cliente elegido el boton avisa, no abre el dialogo (#923)."""
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QPushButton

    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    usuario = _usuario("admin923-sin-cliente")
    pagina = _pagina_de_clientes(app, usuario)

    boton = pagina.findChild(QPushButton, "editClientWhatsappButton")
    assert boton is not None

    errores = []

    def revisar() -> None:
        dialogo = app.activeModalWidget()
        if dialogo is not None:
            errores.append(AssertionError("Se abrio el dialogo sin cliente elegido"))
            dialogo.reject()

    QTimer.singleShot(0, revisar)
    boton.click()
    app.processEvents()

    if errores:
        raise errores[0]

    # El aviso vive suelto en la app (no esta en el layout de la pagina),
    # asi que se busca por objectName entre los widgets vivos.
    from app.ui.form_feedback import FormFeedback

    mensajes = [
        widget.message
        for widget in app.allWidgets()
        if isinstance(widget, FormFeedback)
        and widget.objectName() == "clientAbmFeedback"
    ]
    assert any(
        "Seleccione un cliente para cargarle el WhatsApp." in mensaje
        for mensaje in mensajes
    ), f"El boton no aviso que falta elegir un cliente: {mensajes}"


# ----------------------------------------------------------------- vendedores


def test_actualizar_vendedor_no_borra_el_whatsapp_si_no_se_pasa(db):
    """Un llamador que no conoce el campo no puede vaciarlo por accidente."""
    from app.models.masters import Salesperson
    from app.services.master_service import MasterService

    vendedor = Salesperson.create(name="Vendedor Master", whatsapp_phone="5491153088679")
    MasterService("admin923").update_salesperson(vendedor, "Vendedor Master")
    assert vendedor.whatsapp_phone == "5491153088679"


def test_actualizar_vendedor_guarda_el_whatsapp(db):
    from app.models.masters import Salesperson
    from app.services.master_service import MasterService

    vendedor = Salesperson.create(name="Vendedor Master2")
    MasterService("admin923").update_salesperson(
        vendedor, "Vendedor Master2", whatsapp_phone="011 15 53088679"
    )
    assert vendedor.whatsapp_phone == "5491153088679"


def test_crear_vendedor_rechaza_un_whatsapp_dudoso(db):
    from app.services.master_service import MasterService

    with pytest.raises(ValueError):
        MasterService("admin923").create_salesperson(
            "Vendedor Mal", whatsapp_phone="011 4441-2835"
        )


def test_la_grilla_de_vendedores_muestra_el_whatsapp(db):
    from app.models.masters import Salesperson
    from app.ui.master_abm import master_abm_configs

    vendedor = Salesperson.create(name="Vendedor Grilla", whatsapp_phone="5491153088679")
    config = master_abm_configs()["salespeople"]
    assert "WhatsApp" in config.columns
    filas = config.rows_fn()
    fila = [f for f in filas if f[0] == vendedor.id][0]

    # La fila arranca con el id, que no es una columna visible: los valores que
    # se pintan en la grilla son ``fila[1:]``.
    visibles = fila[1:]
    assert dict(zip(config.columns, visibles))["WhatsApp"] == "5491153088679"
    assert fila[config.columns.index("WhatsApp") + 1] == "5491153088679"


def test_el_dialogo_del_vendedor_reabre_un_whatsapp_guardado(db, app):
    """Un vendedor con WhatsApp guardado se tiene que poder reabrir y guardar.

    Lo que se guarda es el normalizado **sin** "+" ("5491153088679"). Si el
    dialogo lo precarga tal cual, el clasificador no lo reconoce (solo entiende
    el formato internacional si el texto empieza con "+") y guardar falla: el
    vendedor no se puede editar. Precargando la forma internacional, guardar no
    cambia nada.
    """
    from PyQt5.QtWidgets import QDialog, QLineEdit, QPushButton

    from app.models.masters import Salesperson
    from app.ui.master_abm import SalespersonEntryDialog

    vendedor = Salesperson.create(
        name="Vendedor Reabierto", whatsapp_phone="5491153088679"
    )
    dialogo = SalespersonEntryDialog(current_user="admin923", record_id=vendedor.id)

    campo = dialogo.findChild(QLineEdit, "salespersonWhatsappInput")
    assert campo is not None
    assert campo.text() == "+5491153088679"

    dialogo.findChild(QPushButton, "saveSalespersonButton").click()

    # El dialogo acepto: se pudo guardar.
    assert dialogo.result() == QDialog.Accepted
    # Y el valor guardado sigue siendo el mismo, sin el "+".
    assert Salesperson.get_by_id(vendedor.id).whatsapp_phone == "5491153088679"


def test_el_dialogo_del_vendedor_no_guarda_un_numero_dudoso(db, app):
    """Un numero dudoso no se guarda y el dialogo sigue abierto (#923)."""
    from PyQt5.QtWidgets import QDialog, QLineEdit, QPushButton

    from app.models.masters import Salesperson
    from app.ui.master_abm import SalespersonEntryDialog

    vendedor = Salesperson.create(name="Vendedor Dudoso")
    dialogo = SalespersonEntryDialog(current_user="admin923", record_id=vendedor.id)

    dialogo.findChild(QLineEdit, "salespersonWhatsappInput").setText("011 4441-2835")
    dialogo.findChild(QPushButton, "saveSalespersonButton").click()

    assert dialogo.result() != QDialog.Accepted
    assert Salesperson.get_by_id(vendedor.id).whatsapp_phone is None
    assert "no se puede usar para WhatsApp" in dialogo.feedback.message


def test_el_dialogo_del_vendedor_borra_el_whatsapp_si_se_vacia(db, app):
    """Un campo vacio borra el WhatsApp: no es un error (#923)."""
    from PyQt5.QtWidgets import QLineEdit, QPushButton

    from app.models.masters import Salesperson
    from app.ui.master_abm import SalespersonEntryDialog

    vendedor = Salesperson.create(
        name="Vendedor Borrado", whatsapp_phone="5491153088679"
    )
    dialogo = SalespersonEntryDialog(current_user="admin923", record_id=vendedor.id)

    dialogo.findChild(QLineEdit, "salespersonWhatsappInput").setText("")
    dialogo.findChild(QPushButton, "saveSalespersonButton").click()

    assert Salesperson.get_by_id(vendedor.id).whatsapp_phone is None


# ------------------------------------------- correccion 1: auditoria del campo


def test_el_cambio_de_whatsapp_del_vendedor_se_audita(db):
    """El WhatsApp se audita con su propia accion (#923).

    El cambio de un campo que tiene un solo proposito no se esconde dentro de
    la edicion del maestro: se audita con ``action="actualizar WhatsApp"`` y
    ``record_ref="Salesperson:<id>"``, como el del cliente.
    """
    from app.models.audit import AuditLog
    from app.models.masters import Salesperson
    from app.services.master_service import MasterService

    vendedor = Salesperson.create(
        name="Vendedor Auditoria", whatsapp_phone="5491153088679"
    )
    MasterService("admin923").update_salesperson(
        vendedor, "Vendedor Auditoria", whatsapp_phone="011 15 59133141"
    )

    fila = (
        AuditLog.select()
        .where(
            (AuditLog.record_ref == f"Salesperson:{vendedor.id}")
            & (AuditLog.action == "actualizar WhatsApp")
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert fila is not None
    assert fila.old_value == {"whatsapp_phone": "5491153088679"}
    assert fila.new_value == {"whatsapp_phone": "5491159133141"}


def test_la_edicion_del_vendedor_se_audita_tambien_como_modificar(db):
    """La auditoria del maestro no se pierde (#923)."""
    from app.models.audit import AuditLog
    from app.models.masters import Salesperson
    from app.services.master_service import MasterService

    vendedor = Salesperson.create(name="Vendedor Maestro")
    MasterService("admin923").update_salesperson(
        vendedor, "Vendedor Maestro Renombrado", whatsapp_phone="011 15 59133141"
    )

    fila = (
        AuditLog.select()
        .where(
            (AuditLog.record_ref == f"Salesperson:{vendedor.id}")
            & (AuditLog.action == "modificar")
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert fila is not None
    assert fila.new_value["name"] == "Vendedor Maestro Renombrado"


def test_el_alta_del_vendedor_no_audita_el_whatsapp_como_actualizacion(db):
    """En el alta, la creacion del maestro ya cubre el WhatsApp (#923)."""
    from app.models.audit import AuditLog
    from app.services.master_service import MasterService

    MasterService("admin923").create_salesperson(
        "Vendedor Alta", whatsapp_phone="011 15 59133141"
    )

    assert (
        AuditLog.select().where(AuditLog.action == "actualizar WhatsApp").count() == 0
    )


def test_el_cambio_de_whatsapp_no_rompe_el_resto_de_la_edicion(db):
    """Los demas campos del vendedor se siguen guardando bien (#923)."""
    from app.models.masters import Salesperson
    from app.services.master_service import MasterService

    vendedor = Salesperson.create(name="Vendedor Resto", phone="011 4441-2835")
    MasterService("admin923").update_salesperson(
        vendedor,
        "Vendedor Renombrado",
        phone="011 4441-2836",
        email="nuevo@example.com",
        whatsapp_phone="011 15 59133141",
    )

    guardado = Salesperson.get_by_id(vendedor.id)
    assert guardado.name == "Vendedor Renombrado"
    assert guardado.phone == "011 4441-2836"
    assert guardado.email == "nuevo@example.com"
    assert guardado.whatsapp_phone == "5491159133141"
    # La fila se actualizó: el ``updated_at`` no es el de la creación.
    assert guardado.updated_at is not None
    assert guardado.updated_at != vendedor.updated_at


# ------------------------------------- correccion 2: None explicito es error


def test_un_none_explicito_no_borra_el_whatsapp_del_vendedor(db):
    """``None`` explicito es un error, no un borrado (#923).

    El centinela existe para distinguir "no lo paso" de "lo paso vacio": un
    ``None`` explicito viene de un llamador que se equivoco, y no puede
    vaciar un numero que estaba cargado.
    """
    from app.models.masters import Salesperson
    from app.services.master_service import MasterService

    vendedor = Salesperson.create(
        name="Vendedor None", whatsapp_phone="5491153088679"
    )
    with pytest.raises(ValueError):
        MasterService("admin923").update_salesperson(
            vendedor, "Vendedor None", whatsapp_phone=None
        )

    # El numero que estaba cargado sigue cargado.
    assert Salesperson.get_by_id(vendedor.id).whatsapp_phone == "5491153088679"


def test_el_alta_sin_whatsapp_no_es_un_error(db):
    """En el alta, ``None`` es el default: vendedor sin WhatsApp (#923)."""
    from app.services.master_service import MasterService

    vendedor = MasterService("admin923").create_salesperson("Vendedor Sin Ws")
    assert vendedor.whatsapp_phone is None


def test_los_dos_dialogos_precargan_el_whatsapp_igual(db, app):
    """Cliente y vendedor precargan el numero guardado de la misma forma (#923).

    El pre-fill vive en un solo helper compartido: si el dialogo del cliente
    tuviera su propia copia, cambiar la forma de precargar podria hacer que
    uno de los dos mostrara el numero de otra manera.
    """
    from PyQt5.QtWidgets import QLineEdit

    from app.models.masters import Client, Salesperson
    from app.ui import client_whatsapp_edit_dialog
    from app.ui.client_whatsapp_edit_dialog import ClientWhatsappEditDialog
    from app.ui.master_abm import SalespersonEntryDialog

    # No hay dos copias del pre-fill: el dialogo del cliente usa el helper
    # compartido del modulo de piezas.
    assert not hasattr(client_whatsapp_edit_dialog, "_prefill")

    cliente = Client.create(
        name="Cliente Prefill",
        cuit="30923000038",
        iva_condition="RI",
        whatsapp_phone="5491153088679",
    )
    vendedor = Salesperson.create(
        name="Vendedor Prefill", whatsapp_phone="5491153088679"
    )

    dialogo_cliente = ClientWhatsappEditDialog(client=cliente, current_user="admin923")
    dialogo_vendedor = SalespersonEntryDialog(
        current_user="admin923", record_id=vendedor.id
    )

    campo_cliente = dialogo_cliente.findChild(QLineEdit, "clientWhatsappInput")
    campo_vendedor = dialogo_vendedor.findChild(QLineEdit, "salespersonWhatsappInput")
    assert campo_cliente is not None
    assert campo_vendedor is not None
    assert campo_cliente.text() == campo_vendedor.text() == "+5491153088679"
