import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import datetime
from decimal import Decimal

from app.importers.femagfab import LegacyReceipt
from app.services.raw_material_receipt_import_service import (
    RawMaterialReceiptImportService, ReceiptPreview,
)


def receipt(payable="10000", yield_average="25.00", legacy="0", comp="123"):
    return LegacyReceipt(
        comp=comp, received_at=datetime(2026, 9, 28, 10, 0),
        supplier_code="0001", supplier_name="Proveedor", product_code="01",
        product_name="Mandioca", gross_kg=Decimal("20000"), tare_kg=Decimal("10000"),
        net_kg=Decimal("10000"), payable_kg=Decimal(payable),
        earth_discount_pct=Decimal("0"), cepa_discount_pct=Decimal("0"),
        yield_1=Decimal("25"), yield_2=Decimal("25"), yield_3=Decimal("25"),
        yield_average=Decimal(yield_average), legacy_starch_kg=Decimal(legacy),
    )


def test_theoretical_starch_does_not_trust_legacy_fecula():
    row = receipt(legacy="0")
    assert row.theoretical_starch_kg == Decimal("2500.00")


def test_hash_changes_when_productive_source_changes():
    before = receipt(yield_average="25.00")
    after = receipt(yield_average="24.50")
    assert before.source_hash != after.source_hash


def test_weighted_yield_uses_payable_kilos():
    rows = [receipt(payable="10000", yield_average="20"), receipt(payable="30000", yield_average="30")]
    totals = RawMaterialReceiptImportService.totals(rows)
    assert totals.tickets == 2
    assert totals.payable_kg == Decimal("40000")
    assert totals.theoretical_starch_kg == Decimal("11000.00")
    assert totals.weighted_yield == Decimal("27.5")


class _PreviewServiceStub:
    """Reusa los totales reales pero evita tocar femagfab o la base FEMAG."""

    NEW = RawMaterialReceiptImportService.NEW
    UNCHANGED = RawMaterialReceiptImportService.UNCHANGED
    MODIFIED = RawMaterialReceiptImportService.MODIFIED
    totals = staticmethod(RawMaterialReceiptImportService.totals)

    def __init__(self, rows, status):
        self.rows = rows
        self.status = status
        self.imported = []

    def preview(self, day):
        previews = [
            ReceiptPreview(
                row=row,
                source_key=f"femagfab:femagfab:movi:{row.comp}",
                status=self.status,
            )
            for row in self.rows
        ]
        return previews, self.totals(self.rows)

    def import_new(self, previews):
        pending = [preview for preview in previews if preview.status == self.NEW]
        self.imported.extend(pending)
        return len(pending)


def _imported_day():
    """Los 8 tickets del 28/09/2026, ya importados en la corrida real."""
    return [receipt(legacy="9999.00", comp=str(1000 + index)) for index in range(8)]


def test_production_menu_group_exposes_receipt_import_route(db):
    from app.services.auth_service import AuthService
    from app.services.permission_service import PermissionService
    from app.ui.menu import build_sidebar_tree_spec

    PermissionService().seed_defaults()
    user = AuthService().create_user("admin_receipt_menu", "clave", "Administrador")

    principal = build_sidebar_tree_spec(user).sections[0]
    titles = [item.title for item in principal.items]
    produccion = next(item for item in principal.items if item.title == "Producción")

    assert [child.title for child in produccion.children] == ["Recepciones de materia prima"]
    child = produccion.children[0]
    assert child.route_key == "raw_material_receipts"
    assert child.placeholder is False
    # La pantalla debe quedar dentro del bloque propio de Producción, sin romper
    # la cadena Operaciones -> Informes -> Maestros -> Cuenta corriente.
    assert titles.index("Producción") < titles.index("Operaciones")
    assert titles.index("Cuenta corriente") == titles.index("Maestros") + 1


def test_sidebar_navigates_to_receipt_import_page(db):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QListWidget

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow
    from app.ui.raw_material_receipt_import import RawMaterialReceiptImportPage

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_receipt_nav", password_hash="x", profile=profile)
    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    nav = window.findChild(QListWidget, "sidebar")
    rows = {
        nav.item(row).text().strip(): nav.item(row).data(Qt.UserRole)
        for row in range(nav.count())
    }
    assert rows.get("Producción") == "group:Producción"

    window._navigate_to_route("raw_material_receipts")
    app.processEvents()

    rows = {
        nav.item(row).text().strip(): nav.item(row).data(Qt.UserRole)
        for row in range(nav.count())
    }
    assert rows.get("Recepciones de materia prima") == "raw_material_receipts"
    assert window._current_route == "raw_material_receipts"
    assert isinstance(window.stack.currentWidget(), RawMaterialReceiptImportPage)


def test_already_imported_day_shows_sin_cambios_and_disables_import(db):
    from PyQt5.QtCore import QDate
    from PyQt5.QtWidgets import QApplication

    from app.ui.raw_material_receipt_import import RawMaterialReceiptImportPage

    app = QApplication.instance() or QApplication([])
    service = _PreviewServiceStub(_imported_day(), RawMaterialReceiptImportService.UNCHANGED)
    page = RawMaterialReceiptImportPage(service=service)
    page.day.setDate(QDate(2026, 9, 28))
    app.processEvents()

    page.refresh()
    app.processEvents()

    assert page.table.rowCount() == 8
    assert page.table.item(0, 0).text() == "1000"
    assert page.table.item(0, 7).text() == "Sin cambios"
    assert all(
        page.table.item(row, 7).text() == "Sin cambios" for row in range(page.table.rowCount())
    )
    # La fécula teórica nunca se toma del FECULA legacy del origen.
    assert page.table.item(0, 5).text() == "2,500.00"
    assert page.table.item(0, 6).text() == "9,999.00"
    assert page.import_button.isEnabled() is False

    summary = page.summary_label.text()
    assert "8 ticket(s)" in summary
    assert "80,000.00 kg liquidables" in summary
    assert "rinde ponderado 25.00 %" in summary
    assert "20,000.00 kg de fécula teórica" in summary

    page.import_new()
    assert service.imported == []


def test_pending_tickets_enable_import_action(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.raw_material_receipt_import import RawMaterialReceiptImportPage

    app = QApplication.instance() or QApplication([])
    service = _PreviewServiceStub(_imported_day(), RawMaterialReceiptImportService.NEW)
    page = RawMaterialReceiptImportPage(service=service)
    app.processEvents()

    page.refresh()
    app.processEvents()

    assert page.table.item(0, 7).text() == "Nuevo"
    assert page.import_button.isEnabled() is True
    assert "8 ticket(s) sin importar" in page.summary_label.text()

    page.import_new()
    assert len(service.imported) == 8
