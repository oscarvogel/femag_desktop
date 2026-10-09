"""Clientes sin CUIT en la importacion legacy (#686).

El legacy completa el CUIT con ceros y guiones cuando el cliente no lo tiene.
Como ``Client.cuit`` era unico y no admitia NULL, varias filas distintas caian
en el mismo valor y el importador resolvia todas al mismo registro: un cliente
se pisaba sobre otro y la importacion terminaba en
``Duplicate entry '00000000000' for key 'client.client_cuit'``.

Las filas de abajo son literales de ``clientes.dbf`` (663 filas, legacy de
FEMAG). Los casos estan extraidos del archivo real, no inventados: si el
problema se arregla en el parser pero no en la identidad, estos tests lo toman.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.importers.legacy_dbf import LegacyDbfMasterImporter
from app.models.masters import Client

# QApplication vive en una referencia del modulo a proposito: si queda solo en
# una variable local, el recolector lo libera cuando el test termina y Qt se
# termina usando despues de destruido. Ahi el proceso muere sin traceback.
_QT_APP = None


# CODIGO / CUIT / nombre tomados de clientes.dbf
CLIENT_SIN_CUIT_A = {"CODIGO": "0694", "NOMBRE": "CAREL HUE", "CUIT": "00-00000000-0"}
CLIENT_SIN_CUIT_B = {"CODIGO": "0695", "NOMBRE": "EXPRESO DEL PARQUE FAVA ANDRES",
                     "CUIT": "00-00000000-0"}
CLIENT_SIN_CUIT_C = {"CODIGO": "0696", "NOMBRE": "BAREIRO JAVIER", "CUIT": "00-00000000-0"}
CLIENT_SIN_CUIT_D = {"CODIGO": "0697", "NOMBRE": "PINTO CLAUDIO", "CUIT": "00-00000000-0"}
CLIENT_SIN_CUIT_E = {"CODIGO": "0057", "NOMBRE": "CACERES RAMON", "CUIT": "  -        -0"}
CLIENT_SIN_CUIT_F = {"CODIGO": "0058", "NOMBRE": "RUIZ ELVIO RAMON", "CUIT": "  -        -0"}

# CUIT real repetido en clientes.dbf
CLIENT_CUIT_REPETIDO_A = {"CODIGO": "0100", "NOMBRE": "TRANSPORTE SUR",
                           "CUIT": "30-69329993-0"}
CLIENT_CUIT_REPETIDO_B = {"CODIGO": "0101", "NOMBRE": "TRANSPORTES DEL LITORAL",
                          "CUIT": "30-69329993-0"}

CLIENT_CON_CUIT = {"CODIGO": "0200", "NOMBRE": "CLIENTE CON CUIT", "CUIT": "30-12345678-4"}

# Para el caso de adopción: el CUIT que ya existe cargado a mano en FEMAG
CLIENT_CON_CUIT_CAREL = {"CODIGO": "0694", "NOMBRE": "CAREL HUE", "CUIT": "30-71111111-8"}


def _import_clients(rows, source_system="legacy_dbf"):
    return LegacyDbfMasterImporter().import_rows(
        {"clients": rows}, source_system=source_system
    )


def test_clean_cuit_trata_el_relleno_como_ausente():
    importer = LegacyDbfMasterImporter()
    assert importer._clean_cuit("00-00000000-0") is None
    assert importer._clean_cuit("  -        -0") is None
    assert importer._clean_cuit("") is None
    assert importer._clean_cuit("0") is None
    # Un CUIT real se conserva, sin separadores
    assert importer._clean_cuit("30-12345678-4") == "30123456784"


def test_clientes_sin_cuit_no_se_pisan_entre_si(db):
    """Las seis filas de relleno del legacy tienen que quedar en seis clientes."""
    rows = [
        CLIENT_SIN_CUIT_A,
        CLIENT_SIN_CUIT_B,
        CLIENT_SIN_CUIT_C,
        CLIENT_SIN_CUIT_D,
        CLIENT_SIN_CUIT_E,
        CLIENT_SIN_CUIT_F,
    ]
    summary = _import_clients(rows)

    assert summary["clients"]["created"] == 6
    assert Client.select().count() == 6
    # Y cada uno con su propio CODIGO del legacy
    source_ids = sorted(
        Client.select(Client.source_id).order_by(Client.source_id).scalars()
    )
    assert source_ids == ["0057", "0058", "0694", "0695", "0696", "0697"]


def test_el_cuit_de_relleno_no_se_persiste(db):
    _import_clients([CLIENT_SIN_CUIT_A, CLIENT_SIN_CUIT_B])
    assert Client.select().where(Client.cuit.is_null(False)).count() == 0


def test_la_importacion_no_aborta_con_clientes_sin_cuit(db):
    """El caso que reproducia el 1062: CUIT repetido y columna unica."""
    summary = _import_clients([CLIENT_CON_CUIT, CLIENT_SIN_CUIT_A])
    assert summary["clients"]["errors"] == []
    assert Client.get(Client.source_id == "0694").name == "CAREL HUE"
    assert Client.get(Client.source_id == "0200").cuit == "30123456784"


def test_importar_dos_veces_no_duplica_clientes(db):
    rows = [CLIENT_CON_CUIT, CLIENT_SIN_CUIT_A, CLIENT_SIN_CUIT_B]
    _import_clients(rows)
    second = _import_clients(rows)

    assert second["clients"]["created"] == 0
    assert second["clients"]["updated"] == 3
    assert Client.select().count() == 3


def test_cuit_real_repetido_se_avisa_y_no_rompe_la_importacion(db):
    """El legacy trae CUITs reales repetidos; el indice unico sigue protegiendo.

    El comportamiento es el previo: la segunda fila se adopta sobre la primera.
    Lo que no puede pasar es que la importacion aborte, y el operador tiene que
    enterarse por el resumen de que una fila absorbio a la otra.
    """
    summary = _import_clients([CLIENT_CUIT_REPETIDO_A, CLIENT_CUIT_REPETIDO_B])

    assert summary["clients"]["errors"] == []
    assert summary["clients"]["created"] == 1
    assert summary["clients"]["updated"] == 1
    warnings = summary["clients"]["warnings"]
    assert [w["code"] for w in warnings] == ["client_cuit_shared_by_two_rows"]
    assert Client.select().count() == 1
    assert Client.get().cuit == "30693299930"
    # Queda la última fila leída, que es lo que el comportamiento previo hacía
    assert Client.get().name == "TRANSPORTES DEL LITORAL"


def test_adoptar_un_cliente_sin_trazanza_no_avisa(db):
    """Un cliente cargado a mano en FEMAG se adopta en silencio: es lo esperado."""
    Client.create(name="Cliente FEMAG", cuit="30711111118", iva_condition="RI")
    summary = _import_clients([CLIENT_CON_CUIT_CAREL])

    assert summary["clients"]["updated"] == 1
    assert summary["clients"]["warnings"] == []
    assert Client.select().count() == 1
    assert Client.get().source_id == "0694"


def test_reimportar_el_mismo_lote_no_avisa_nada(db):
    """Una segunda pasada limpia tiene que ser silenciosa.

    El aviso de CUIT compartido es para cuando dos filas del legacy se pisan.
    Reimportar el mismo lote no pisa nada, asi que no debe ensuciar el resumen
    que el operador lee para decidir si importar.
    """
    rows = [CLIENT_CON_CUIT, CLIENT_SIN_CUIT_A, CLIENT_SIN_CUIT_B]
    first = _import_clients(rows)
    assert first["clients"]["warnings"] == []

    second = _import_clients(rows)
    assert second["clients"]["errors"] == []
    assert second["clients"]["warnings"] == []
    assert second["clients"]["created"] == 0
    assert second["clients"]["updated"] == 3
    assert Client.select().count() == 3


def test_actualizar_por_source_id_cambia_el_ormino_mismo_cliente(db):
    """La identidad es el CODIGO del legacy, no el CUIT."""
    _import_clients([{"CODIGO": "0697", "NOMBRE": "PINTO CLAUDIO", "CUIT": "00-00000000-0"}])
    _import_clients([{"CODIGO": "0697", "NOMBRE": "PINTO CLAUDIO ACTUALIZADO",
                      "CUIT": "00-00000000-0"}])

    assert Client.select().count() == 1
    assert Client.get(Client.source_id == "0697").name == "PINTO CLAUDIO ACTUALIZADO"


def test_el_cliente_actualiza_su_propio_cuit(db):
    _import_clients([{"CODIGO": "0200", "NOMBRE": "CLIENTE CON CUIT", "CUIT": "30-12345678-4"}])
    _import_clients([{"CODIGO": "0200", "NOMBRE": "CLIENTE CON CUIT", "CUIT": "30-87654321-9"}])

    assert Client.select().count() == 1
    assert Client.get(Client.source_id == "0200").cuit == "30876543219"


def test_el_abm_de_clientes_abre_un_cliente_sin_cuit(db):
    """Leer un cliente sin CUIT no puede reventar el formulario.

    ``Client.cuit`` pasa a admitir NULL, asi que los ABM tienen que aguantar el
    caso: ``setText(None)`` es TypeError en PyQt5 y el operador se queda sin
    poder abrir ni editar ese cliente.
    """
    from PyQt5.QtWidgets import QApplication, QLineEdit

    from app.ui.master_abm import ClientEntryDialog

    # QApplication se queda en una variable del modulo: si el collectedor lo
    # libera, Qt se usa despues de destruido y el proceso muere sin traceback.
    global _QT_APP
    if _QT_APP is None:
        _QT_APP = QApplication.instance() or QApplication([])

    _import_clients([CLIENT_SIN_CUIT_D])
    client = Client.get(Client.source_id == "0697")
    assert client.cuit is None

    dialog = ClientEntryDialog(current_user="issue686", record_id=client.id)
    assert dialog.findChild(QLineEdit, "clientCuitInput").text() == ""
    assert dialog.findChild(QLineEdit, "clientNameInput").text() == "PINTO CLAUDIO"