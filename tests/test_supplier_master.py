"""Tests del ABM de productores y de la reimportacion que no pisa datos (#963)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date
from decimal import Decimal

import pytest

from app.importers.femagfab import LegacySupplier

_QT_APP = None


def _app():
    global _QT_APP
    from PyQt5.QtWidgets import QApplication

    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def _user(username, profile):
    from app.services.auth_service import AuthService

    return AuthService().create_user(username, "clave", profile)


@pytest.fixture()
def seeded(db):
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    return db


class _Source:
    instance = "femagfab"

    def __init__(self, rows):
        self.rows = rows

    def fetch_suppliers(self):
        return list(self.rows)

    def supplier_source_key(self, code):
        return f"femagfab:femagfab:proveedo:{code}"


def _legacy(code, name):
    return LegacySupplier(code=code, name=name, locality="", phone="")


# ------------------------------------------------------------------ CUIT/DNI
@pytest.mark.parametrize(
    "value,expected",
    [
        ("20-12345678-6", "20123456786"),
        ("20123456786", "20123456786"),
        ("12.345.678", "12345678"),
        ("1234567", "1234567"),
        ("", None),
        (None, None),
    ],
)
def test_validate_tax_id_acepta_cuit_y_dni(value, expected):
    from app.services.supplier_master_service import validate_tax_id

    assert validate_tax_id(value) == expected


@pytest.mark.parametrize("value", ["20-12345678-5", "123456", "123456789", "abc"])
def test_validate_tax_id_rechaza_invalidos(value):
    from app.services.supplier_master_service import SupplierMasterError, validate_tax_id

    with pytest.raises(SupplierMasterError):
        validate_tax_id(value)


# ------------------------------------------------------------------ servicio
def test_crear_editar_y_auditar(seeded):
    from app.models.audit import AuditLog
    from app.services.supplier_master_service import SupplierMasterService

    service = SupplierMasterService("admin")
    supplier = service.create(name="  KLEM   JORGE ", locality="Oberá", tax_id="20-12345678-6")
    assert supplier.name == "KLEM JORGE"
    assert supplier.normalized_name == "KLEM JORGE"
    assert supplier.tax_id == "20123456786"

    edited = service.update(
        supplier,
        name="Klem Jorge Alberto",
        locality="Oberá",
        tax_id="20123456786",
        identity_verified=True,
    )
    assert edited.name == "Klem Jorge Alberto"
    # La clave del importador no cambia al editar el nombre.
    assert edited.normalized_name == "KLEM JORGE"
    assert edited.identity_verified
    acciones = [row.action for row in AuditLog.select().where(AuditLog.module == "Maestros")]
    assert acciones == ["crear", "modificar"]


def test_cuit_repetido_se_rechaza_con_el_nombre(seeded):
    from app.services.supplier_master_service import SupplierMasterError, SupplierMasterService

    service = SupplierMasterService("admin")
    service.create(name="KLEM JORGE", tax_id="20123456786")
    otro = service.create(name="OTRO")
    with pytest.raises(SupplierMasterError, match="KLEM JORGE"):
        service.update(otro, name="OTRO", tax_id="20-12345678-6")


def test_no_se_verifica_sin_cuit_ni_se_guarda_sin_nombre(seeded):
    from app.services.supplier_master_service import SupplierMasterError, SupplierMasterService

    service = SupplierMasterService("admin")
    with pytest.raises(SupplierMasterError, match="CUIT/DNI"):
        service.create(name="SIN DATOS", identity_verified=True)
    with pytest.raises(SupplierMasterError, match="nombre"):
        service.create(name="   ")


def test_baja_y_reactivacion_no_borran_nada(seeded):
    from app.models.suppliers import Supplier, SupplierDocument
    from app.services.supplier_master_service import SupplierMasterService

    service = SupplierMasterService("admin")
    supplier = service.create(name="KLEM JORGE")
    SupplierDocument.create(
        supplier=supplier, kind=SupplierDocument.KIND_TICKET, source_key="k1",
        source_code="1", issued_at=date(2026, 6, 1), amount=Decimal("100"),
        balance=Decimal("100"), source_hash="x",
    )
    service.set_active(supplier, False)
    assert not Supplier.get_by_id(supplier.id).active
    assert SupplierDocument.select().count() == 1
    service.set_active(supplier, True)
    assert Supplier.get_by_id(supplier.id).active


# ------------------------------------------------------------------ importador
def test_reimportar_no_pisa_lo_cargado_a_mano(seeded):
    from app.models.suppliers import Supplier
    from app.services.supplier_import_service import SupplierImportService
    from app.services.supplier_master_service import SupplierMasterService

    SupplierImportService(source=_Source([_legacy("0123", "KLEM JORGE")])).import_suppliers()
    supplier = Supplier.get()
    SupplierMasterService("admin").update(
        supplier, name="Klem Jorge Alberto", phone="3755-123456",
        tax_id="20123456786", identity_verified=True,
    )

    report = SupplierImportService(
        source=_Source([_legacy("0123", "KLEM JORGE")])
    ).import_suppliers()

    supplier = Supplier.get_by_id(supplier.id)
    assert report.created == 0
    assert supplier.name == "Klem Jorge Alberto"
    assert supplier.phone == "3755-123456"
    assert supplier.tax_id == "20123456786"
    assert supplier.identity_verified


def test_la_fusion_del_importador_no_borra_documentos_ni_pagos(seeded):
    """Antes `_merge` borraba en cascada al absorbido con sus documentos."""
    from app.models.suppliers import (
        Supplier,
        SupplierAccountMovement,
        SupplierDocument,
        SupplierPayment,
    )
    from app.services.supplier_import_service import SupplierImportService
    from app.services.supplier_ledger_service import AllocationRequest, SupplierLedgerService

    SupplierImportService(
        source=_Source([_legacy("0001", "PEREZ JUAN"), _legacy("0002", "GOMEZ ANA")])
    ).import_suppliers()
    gomez = Supplier.get(Supplier.normalized_name == "GOMEZ ANA")
    ticket = SupplierDocument.create(
        supplier=gomez, kind=SupplierDocument.KIND_TICKET, source_key="k1",
        source_code="1", issued_at=date(2026, 6, 1), amount=Decimal("1000"),
        balance=Decimal("1000"), source_hash="x",
    )
    SupplierLedgerService("admin").register_payment(
        supplier=gomez, amount=Decimal("100"), method="efectivo",
        allocations=[AllocationRequest(ticket, Decimal("100"))],
    )

    # El legacy renombra la ficha 0001 con el nombre de la otra persona.
    SupplierImportService(
        source=_Source([_legacy("0001", "GOMEZ ANA"), _legacy("0002", "GOMEZ ANA")])
    ).import_suppliers()

    assert Supplier.select().count() == 1
    survivor = Supplier.get()
    assert SupplierDocument.get_by_id(ticket.id).supplier_id == survivor.id
    assert SupplierPayment.get().supplier_id == survivor.id
    assert all(m.supplier_id == survivor.id for m in SupplierAccountMovement.select())
    assert sorted(survivor.legacy_code_list) == ["0001", "0002"]


def test_el_importador_no_fusiona_una_identidad_verificada(seeded):
    from app.models.suppliers import Supplier
    from app.services.supplier_import_service import SupplierImportService
    from app.services.supplier_master_service import SupplierMasterService

    SupplierImportService(
        source=_Source([_legacy("0001", "PEREZ JUAN"), _legacy("0002", "GOMEZ ANA")])
    ).import_suppliers()
    perez = Supplier.get(Supplier.normalized_name == "PEREZ JUAN")
    SupplierMasterService("admin").update(
        perez, name="PEREZ JUAN", tax_id="20123456786", identity_verified=True
    )
    SupplierImportService(
        source=_Source([_legacy("0001", "GOMEZ ANA"), _legacy("0002", "GOMEZ ANA")])
    ).import_suppliers()
    assert Supplier.select().count() == 2


# ------------------------------------------------------------------ pantalla
def _page(user):
    from app.ui.supplier_master import build_supplier_master_page

    _app()
    return build_supplier_master_page(user=user, current_user=user.username)


def test_pantalla_vacia_y_alta_desde_el_dialogo(seeded):
    from PyQt5.QtWidgets import QDialog

    admin = _user("admin_abm_prod", "Administrador")
    page = _page(admin)
    assert page.table.rowCount() == 0
    assert not page.empty_label.isHidden()

    def run(dialog):
        dialog.name_input.setText("CHER CRISTIAN ARIEL")
        dialog.tax_id_input.setText("20-12345678-6")
        dialog.locality_input.setText("Oberá")
        dialog._save()
        return dialog.result()

    page.dialog_runner = run
    page.open_new()
    assert page.table.rowCount() == 1
    assert page.table.item(0, 0).text() == "CHER CRISTIAN ARIEL"
    assert page.table.item(0, 4).text() == "20-12345678-6"
    assert page.empty_label.isHidden()
    assert QDialog.Accepted == 1


def test_el_dialogo_muestra_el_error_y_no_cierra(seeded):
    from app.ui.supplier_master import SupplierEntryDialog

    _app()
    dialog = SupplierEntryDialog(current_user="admin")
    dialog.name_input.setText("X")
    dialog.tax_id_input.setText("20-12345678-5")
    dialog._save()
    assert dialog.result() == 0
    assert "dígito verificador" in dialog.feedback.message


def test_busqueda_por_codigo_legacy_y_cuit(seeded):
    from app.services.supplier_import_service import SupplierImportService
    from app.services.supplier_master_service import SupplierMasterService

    SupplierImportService(
        source=_Source([_legacy("0656", "COOP NUEVA ARGENTINA"), _legacy("0123", "KLEM JORGE")])
    ).import_suppliers()
    from app.models.suppliers import Supplier

    SupplierMasterService("admin").update(
        Supplier.get(Supplier.normalized_name == "KLEM JORGE"),
        name="KLEM JORGE", tax_id="20123456786",
    )
    page = _page(_user("admin_busca", "Administrador"))
    page.search_input.setText("0656")
    assert page.table.rowCount() == 1
    assert page.table.item(0, 0).text() == "COOP NUEVA ARGENTINA"
    page.search_input.setText("20-12345678-6")
    assert page.table.rowCount() == 1
    assert page.table.item(0, 0).text() == "KLEM JORGE"


def test_dar_de_baja_desde_la_pantalla(seeded):
    from app.models.suppliers import Supplier
    from app.services.supplier_master_service import SupplierMasterService

    SupplierMasterService("admin").create(name="KLEM JORGE")
    page = _page(_user("admin_baja", "Administrador"))
    page.confirm = lambda _message: True
    page.toggle_active()
    assert not Supplier.get().active
    assert page.active_button.text() == "Reactivar"
    assert page.table.item(0, 6).text() == "Inactivo"


def test_ficha_con_fichas_unificadas_pide_verificar(seeded):
    from app.models.suppliers import Supplier
    from app.services.supplier_import_service import SupplierImportService
    from app.ui.supplier_master import SupplierDetailDialog

    SupplierImportService(
        source=_Source([_legacy("0656", "COOP NUEVA ARGENTINA"), _legacy("0999", "COOP  NUEVA ARGENTINA")])
    ).import_suppliers()
    _app()
    dialog = SupplierDetailDialog(supplier_id=Supplier.get().id)
    assert dialog.codes_table.rowCount() == 2
    assert "0 tickets y 0 pagarés" in dialog.summary_label.text()


def test_permisos_por_perfil_y_menu(seeded):
    from app.ui.menu import build_sidebar_tree_spec

    solo_consulta = _user("consulta_abm", "Solo consulta")
    page = _page(solo_consulta)
    assert not page.new_button.isEnabled()
    assert not page.edit_button.isEnabled()

    secretaria = _user("secretaria_abm", "Secretaría")
    page = _page(secretaria)
    assert page.new_button.isEnabled()

    principal = build_sidebar_tree_spec(secretaria).sections[0]
    maestros = next(item for item in principal.items if item.title == "Maestros")
    item = next(child for child in maestros.children if child.title == "Productores")
    assert item.route_key == "suppliers"
