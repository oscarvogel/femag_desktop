"""Registro de la version por puesto (#664) y la pregunta del domicilio principal (#665)."""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# --- #664: que version corre en cada puesto -------------------------------------


def test_records_the_running_version_per_workstation(db):
    from app.services.audit_service import AuditService

    AuditService().record_workstation_version("2099.01.01.00.00.00", workstation="PC-PRUEBA")

    rows = list(
        db.get_model("AuditLog") if False else _rows(db, "PC-PRUEBA")
    )
    assert len(rows) == 1
    assert rows[0].new_value == {"version": "2099.01.01.00.00.00"}


def _rows(db, workstation):
    from app.models.audit import AuditLog

    return list(
        AuditLog.select().where(
            (AuditLog.action == "version de puesto") & (AuditLog.workstation == workstation)
        )
    )


def test_does_not_insert_one_row_per_startup(db):
    """Un insert por arranque seria ruido: la fila del puesto se actualiza."""
    from app.services.audit_service import AuditService

    service = AuditService()
    for version in ("2099.01.01.00.00.00", "2099.01.02.00.00.00", "2099.01.03.00.00.00"):
        service.record_workstation_version(version, workstation="PC-PRUEBA")

    rows = _rows(db, "PC-PRUEBA")
    assert len(rows) == 1
    assert rows[0].new_value == {"version": "2099.01.03.00.00.00"}


def test_keeps_one_row_per_workstation(db):
    """Cada equipo tiene su fila: el inventario es por puesto, no global."""
    from app.services.audit_service import AuditService

    service = AuditService()
    service.record_workstation_version("2099.01.01.00.00.00", workstation="PC-A")
    service.record_workstation_version("2099.01.02.00.00.00", workstation="PC-B")

    assert len(_rows(db, "PC-A")) == 1
    assert len(_rows(db, "PC-B")) == 1
    assert _rows(db, "PC-B")[0].new_value == {"version": "2099.01.02.00.00.00"}


def test_registration_failure_never_breaks_startup(monkeypatch):
    """Registrar la version no puede ser un motivo mas de que el puesto no abra."""
    from app.ui import desktop_app

    monkeypatch.setattr(
        desktop_app.AuditService,
        "record_workstation_version",
        lambda self, version: (_ for _ in ()).throw(RuntimeError("base caida")),
    )

    # No debe levantar: la excepcion se come adentro.
    desktop_app._record_workstation_version()


def test_records_the_version_in_the_running_build(db, monkeypatch):
    """El valor registrado es el de la app que esta corriendo, no uno fijo."""
    from app.build_version import BUILD_VERSION
    from app.ui import desktop_app

    desktop_app._record_workstation_version()

    from app.models.audit import AuditLog

    row = (
        AuditLog.select()
        .where(AuditLog.action == "version de puesto")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None
    assert row.new_value == {"version": BUILD_VERSION}


# --- #665: el operador decide si el destino nuevo es el principal ----------------


def _master_data():
    from tests.conftest import _master_data as master

    return master()


def test_asks_the_operator_when_the_client_already_has_delivery_addresses(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    data = _master_data()
    client = data["client"]

    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderEntryDialog(_service(), "issue665")
    app.processEvents()

    asked = []

    def fake_question(_parent, title, text, *_args):
        asked.append((title, text))
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))

    assert dialog._ask_primary_delivery_address(client) is False
    assert len(asked) == 1
    assert "principal" in asked[0][0].lower()
    assert client.name in asked[0][1]


def test_new_address_becomes_primary_only_if_the_operator_says_yes(db, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderEntryDialog(_service(), "issue665")
    app.processEvents()

    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *_a, **_k: QMessageBox.Yes)
    )

    assert dialog._ask_primary_delivery_address(_master_data()["client"]) is True


def test_client_without_delivery_addresses_makes_it_primary_without_asking(db, monkeypatch):
    """Sin ningun domicilio previo no hay a quien sacarle el principal."""
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.models.masters import Client
    from app.ui.desktop_app import LoadOrderEntryDialog

    app = QApplication.instance() or QApplication([])
    dialog = LoadOrderEntryDialog(_service(), "issue665")
    app.processEvents()

    nuevo = Client.create(name="Cliente Sin Destino 665", cuit="30700000665", iva_condition="RI")

    def unexpected(*_args, **_kwargs):
        raise AssertionError("no hay que preguntar si el cliente no tiene domicilios")

    monkeypatch.setattr(QMessageBox, "question", staticmethod(unexpected))

    assert dialog._ask_primary_delivery_address(nuevo) is True


def test_the_answer_reaches_the_address_creation(db, monkeypatch):
    """La respuesta del operador es la que define `is_primary` del domicilio nuevo."""
    from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

    from app.models.masters import ClientAddress
    from app.ui.desktop_app import LoadOrderEntryDialog
    from app.ui.master_abm import ClientAddressEntryDialog

    app = QApplication.instance() or QApplication([])
    data = _master_data()
    dialog = LoadOrderEntryDialog(_service(), "issue665")
    app.processEvents()

    client_combo = dialog.findChild(_QComboBox(), "loadOrderClientInput")
    client_combo.setCurrentIndex(client_combo.findData(data["client"].id))
    app.processEvents()

    address_combo = dialog.findChild(_QComboBox(), "loadOrderAddressInput")
    address_combo.lineEdit().setText("Ruta 77")

    def answer_by_title(_parent, title, _text, *_args):
        # Da de alta el destino, pero NO lo deja como domicilio principal.
        if title == "Nuevo lugar de entrega":
            return QMessageBox.Yes
        if title == "Domicilio principal":
            return QMessageBox.No
        raise AssertionError("pregunta inesperada: " + str(title))

    monkeypatch.setattr(QMessageBox, "question", staticmethod(answer_by_title))

    def fake_exec(self):
        dialog.findChild(_QLineEdit(), "addressProvinceInput").setText("Misiones")
        dialog.findChild(_QLineEdit(), "addressCityInput").setText("Obera")
        dialog.findChild(_QPushButton(), "saveAddressButton").click()
        return QDialog.Accepted

    monkeypatch.setattr(ClientAddressEntryDialog, "exec_", fake_exec)

    dialog.findChild(_QPushButton(), "addLoadOrderClientButton").click()
    app.processEvents()

    nuevo = ClientAddress.get(
        (ClientAddress.client == data["client"]) & (ClientAddress.address == "Ruta 77")
    )
    assert nuevo.city == "Obera"
    # El operador dijo que no: el domicilio previo sigue siendo el principal.
    assert nuevo.is_primary is False
    assert data["address"].is_primary is True


def test_abm_keeps_its_own_rule_when_the_caller_does_not_decide(db):
    """Sin override, el alta manual del ABM sigue haciendo el domicilio principal.

    La regla vive en el dialogo, no en `ClientService.add_address` (cuyo default es
    False), asi que se prueba por el dialogo real y no por el servicio.
    """
    from PyQt5.QtWidgets import QApplication, QDialog

    from app.models.masters import Client, ClientAddress
    from app.ui.master_abm import ClientAddressEntryDialog

    app = QApplication.instance() or QApplication([])
    client = Client.create(name="Cliente ABM 665", cuit="30700000666", iva_condition="RI")

    dialog = ClientAddressEntryDialog(current_user="issue665", client_id=client.id)
    app.processEvents()
    assert dialog.is_primary is None

    dialog.findChild(_QLineEdit(), "addressStreetInput").setText("Ruta 88")
    dialog.findChild(_QLineEdit(), "addressProvinceInput").setText("Misiones")
    dialog.findChild(_QLineEdit(), "addressCityInput").setText("Obera")
    dialog.findChild(_QPushButton(), "saveAddressButton").click()
    app.processEvents()

    created = ClientAddress.get(ClientAddress.client == client)
    assert created.is_primary is True


def _service():
    from app.services.load_order_service import LoadOrderService

    return LoadOrderService(current_user="issue665")


def _QComboBox():
    from PyQt5.QtWidgets import QComboBox

    return QComboBox


def _QLineEdit():
    from PyQt5.QtWidgets import QLineEdit

    return QLineEdit


def _QPushButton():
    from PyQt5.QtWidgets import QPushButton

    return QPushButton