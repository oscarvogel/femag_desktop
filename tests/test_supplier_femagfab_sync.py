"""Tests de la importacion de productores desde femagfab en la pantalla (#957)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime
from decimal import Decimal

import pytest

from app.importers.femagfab import (
    LegacySupplier,
    LegacySupplierPromissoryNote,
    LegacySupplierTicket,
)

_QT_APP = None


def _app():
    global _QT_APP
    from PyQt5.QtWidgets import QApplication

    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


class _FakeSource:
    instance = "femagfab"
    configured = True

    def __init__(self, *, fail=False):
        self.fail = fail

    def fetch_suppliers(self):
        if self.fail:
            raise ConnectionError("Can't connect to MySQL server")
        return [
            LegacySupplier(code="0656", name="COOP NUEVA ARGENTINA", locality="", phone=""),
            LegacySupplier(code="0999", name="COOP  NUEVA ARGENTINA", locality="", phone=""),
            LegacySupplier(code="0123", name="KLEM JORGE", locality="", phone=""),
        ]

    def fetch_supplier_tickets(self):
        def ticket(comp, supplier, kg, price):
            payable, precio = Decimal(kg), Decimal(price)
            return LegacySupplierTicket(
                comp=comp,
                received_at=datetime(2026, 6, 2, 10, 0),
                supplier_code=supplier,
                product_code="01",
                payable_kg=payable,
                price_per_ton=precio,
                legacy_balance=payable * precio / Decimal("1000"),
            )

        return [
            ticket("000000044143", "0656", "1574", "190000"),
            ticket("000000044150", "0999", "1000", "200000"),
            ticket("000000045000", "0123", "500", "180000"),
            # Sin kilos: queda excluido con su motivo.
            LegacySupplierTicket(
                comp="000000045001",
                received_at=datetime(2026, 6, 3, 9, 0),
                supplier_code="0123",
                product_code="01",
                payable_kg=Decimal("0"),
                price_per_ton=Decimal("0"),
                legacy_balance=Decimal("12345"),
            ),
        ]

    def fetch_supplier_promissory_notes(self):
        return [
            LegacySupplierPromissoryNote(
                code="0616",
                supplier_code="0656",
                issued_on="2026-04-28",
                amount=Decimal("8000000"),
                balance=Decimal("5700000"),
                concept="",
            )
        ]

    def supplier_source_key(self, code):
        return f"femagfab:femagfab:proveedo:{code}"

    def document_source_key(self, kind, code):
        return f"femagfab:femagfab:{kind}:{code}"


def _user(username, profile):
    from app.services.auth_service import AuthService

    return AuthService().create_user(username, "clave", profile)


@pytest.fixture()
def admin(db):
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    return _user("admin_sync", "Administrador")


def test_importa_maestro_documentos_y_abre_el_libro(admin):
    from app.models.audit import AuditLog
    from app.models.suppliers import Supplier, SupplierAccountMovement, SupplierDocument
    from app.services.supplier_femagfab_sync_service import FemagFabSupplierSyncService
    from app.services.supplier_position_service import (
        SupplierPositionFilters,
        SupplierPositionService,
    )

    result = FemagFabSupplierSyncService(source=_FakeSource()).run(user=admin)

    assert Supplier.select().count() == 2  # las dos fichas de la cooperativa son una persona
    assert SupplierDocument.select().count() == 4
    assert result.documents.excluded_count == 1
    assert result.openings_created == 4
    assert SupplierAccountMovement.select().count() == 4
    position = SupplierPositionService().position(SupplierPositionFilters())
    assert position.payable == Decimal("589060.00")
    assert position.receivable == Decimal("5700000.00")
    assert AuditLog.select().where(AuditLog.action == "importar_femagfab").count() == 1
    assert "Excluidos por falta de datos: 1 por $ 12.345,00." in result.summary_lines()


def test_repetir_la_importacion_no_duplica_nada(admin):
    from app.models.suppliers import (
        Supplier,
        SupplierAccountMovement,
        SupplierDocument,
        SupplierDocumentExclusion,
    )
    from app.services.supplier_femagfab_sync_service import FemagFabSupplierSyncService

    service = FemagFabSupplierSyncService(source=_FakeSource())
    service.run(user=admin)
    second = service.run(user=admin)

    assert second.documents.imported == 0
    assert second.documents.already_imported == 4
    assert second.openings_created == 0
    assert Supplier.select().count() == 2
    assert SupplierDocument.select().count() == 4
    assert SupplierDocumentExclusion.select().count() == 1
    assert SupplierAccountMovement.select().count() == 4


def test_un_pago_registrado_no_se_pisa_al_reimportar(admin):
    from app.models.suppliers import SupplierDocument
    from app.services.supplier_femagfab_sync_service import FemagFabSupplierSyncService
    from app.services.supplier_ledger_service import AllocationRequest, SupplierLedgerService

    service = FemagFabSupplierSyncService(source=_FakeSource())
    service.run(user=admin)
    ticket = SupplierDocument.get(SupplierDocument.source_code == "000000045000")
    ledger = SupplierLedgerService(admin.username)
    ledger.register_payment(
        supplier=ticket.supplier,
        amount=Decimal("1000"),
        method="efectivo",
        allocations=[AllocationRequest(ticket, Decimal("1000"))],
    )
    service.run(user=admin)

    assert ledger.document_pending(SupplierDocument.get_by_id(ticket.id)) == Decimal("89000.00")


def test_sin_permiso_no_importa(admin):
    from app.models.suppliers import Supplier
    from app.services.supplier_femagfab_sync_service import (
        FemagFabSupplierSyncService,
        can_import_from_femagfab,
    )

    administracion = _user("administracion_sync", "Administración")
    assert not can_import_from_femagfab(administracion)
    with pytest.raises(PermissionError):
        FemagFabSupplierSyncService(source=_FakeSource()).run(user=administracion)
    assert Supplier.select().count() == 0


def test_error_de_conexion_y_falta_de_configuracion(admin):
    from app.services.supplier_femagfab_sync_service import (
        FemagFabSupplierSyncService,
        SupplierSyncError,
    )

    with pytest.raises(SupplierSyncError, match="No se pudo leer femagfab"):
        FemagFabSupplierSyncService(source=_FakeSource(fail=True)).run(user=admin)

    source = _FakeSource()
    source.configured = False
    with pytest.raises(SupplierSyncError, match="no está configurada"):
        FemagFabSupplierSyncService(source=source).run(user=admin)


def test_el_boton_de_la_pantalla_importa_y_refresca(admin, monkeypatch):
    from PyQt5.QtWidgets import QMessageBox

    from app.services.supplier_femagfab_sync_service import FemagFabSupplierSyncService
    from app.ui.supplier_ledger import SupplierLedgerPage

    _app()
    shown = {}
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.setdefault("info", a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail(a[2]))
    page = SupplierLedgerPage(user=admin, current_username=admin.username)
    assert page.position_table.rowCount() == 0
    assert page.import_button.isEnabled()

    monkeypatch.setattr(page, "_confirm_import", lambda: True)
    monkeypatch.setattr(
        page, "_make_sync_service", lambda: FemagFabSupplierSyncService(source=_FakeSource())
    )
    page.import_from_femagfab()

    assert page.position_table.rowCount() == 2
    assert "Productores:" in shown["info"]


def test_cancelar_la_confirmacion_no_importa(admin, monkeypatch):
    from app.models.suppliers import Supplier
    from app.ui.supplier_ledger import SupplierLedgerPage

    _app()
    page = SupplierLedgerPage(user=admin, current_username=admin.username)
    monkeypatch.setattr(page, "_confirm_import", lambda: False)
    monkeypatch.setattr(page, "_make_sync_service", lambda: pytest.fail("no debia importar"))
    assert page.import_from_femagfab() is None
    assert Supplier.select().count() == 0


def test_el_error_se_muestra_sin_romper_la_pantalla(admin, monkeypatch):
    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.services.supplier_femagfab_sync_service import FemagFabSupplierSyncService
    from app.ui.supplier_ledger import SupplierLedgerPage

    _app()
    shown = {}
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.setdefault("warn", a[2]))
    page = SupplierLedgerPage(user=admin, current_username=admin.username)
    monkeypatch.setattr(page, "_confirm_import", lambda: True)
    monkeypatch.setattr(
        page, "_make_sync_service", lambda: FemagFabSupplierSyncService(source=_FakeSource(fail=True))
    )
    assert page.import_from_femagfab() is None
    assert "No se pudo leer femagfab" in shown["warn"]
    assert QApplication.overrideCursor() is None


def test_el_boton_queda_deshabilitado_sin_permiso(admin):
    from app.ui.supplier_ledger import SupplierLedgerPage

    _app()
    secretaria = _user("secretaria_sync", "Secretaría")
    page = SupplierLedgerPage(user=secretaria, current_username=secretaria.username)
    assert not page.import_button.isEnabled()
    assert "permiso" in page.import_button.toolTip()
