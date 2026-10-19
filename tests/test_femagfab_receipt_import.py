import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

from app.importers.femagfab import LegacyReceipt
from app.services.raw_material_receipt_import_service import (
    RawMaterialReceiptImportService, ReceiptPreview,
)

# Hash calculado con el importer de origin/main (antes de #722). Si este valor
# cambia, todas las importaciones ya hechas -- septiembre y octubre -- aparecen
# como "modificado en origen" y piden conciliacion manual.
GOLDEN_HASH_MEASURED = "08f6cb77013006b5ee97760447e9fd2368d8955a64487ed38655f16d7d17e072"


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


def test_fetch_range_covers_the_whole_last_day(monkeypatch):
    from app.importers.femagfab import FemagFabSource

    source = FemagFabSource(host="host", database="femagfab", user="user", password="")
    captured = {}

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params):
            captured["params"] = params

        def fetchall(self):
            return []

    class _Connection:
        def cursor(self):
            return _Cursor()

        def close(self):
            pass

    monkeypatch.setattr(source, "_connect", lambda: _Connection())
    rows = source.fetch_range(date(2026, 1, 1), date(2026, 1, 31))

    assert rows == []
    assert captured["params"] == (datetime(2026, 1, 1), datetime(2026, 2, 1))


def test_theoretical_starch_does_not_trust_legacy_fecula():
    row = receipt(legacy="0")
    assert row.theoretical_starch_kg == Decimal("2500.00")


def test_hash_changes_when_productive_source_changes():
    before = receipt(yield_average="25.00")
    after = receipt(yield_average="24.50")
    assert before.source_hash != after.source_hash


def test_el_hash_de_un_ticket_medido_no_cambio():
    """El hash tiene que seguir siendo el de antes de #722.

    Las importaciones de septiembre y octubre ya estan hechas con el hash
    anterior. Si este valor cambia, todas esas tickets aparecen como
    "modificado en origen" y el sistema pide conciliacion manual.
    """
    assert receipt().source_hash == GOLDEN_HASH_MEASURED


def test_el_hash_no_depende_del_rinde_estimado():
    """Cambiar el parametro no puede invalidar lo ya importado.

    El hash cubre el contenido del legacy y nada mas. El rinde estimado es
    un dato derivado de la planta: si entrara en el hash, mover el parametro
    volveria "modificado" todo lo importado.
    """
    con_2233 = replace(receipt(yield_average="0"), applied_yield_pct=Decimal("22.33"))
    con_30 = replace(receipt(yield_average="0"), applied_yield_pct=Decimal("30"))

    assert con_2233.source_hash == con_30.source_hash
    assert con_2233.source_hash != receipt().source_hash


def test_el_payload_conserva_el_rinde_de_origen():
    """El payload es la foto del legacy: el PROMEDIO tal como vino."""
    fila = replace(receipt(yield_average="0"), applied_yield_pct=Decimal("22.33"))

    assert fila.payload()["yield_average"] == "0"
    assert fila.payload()["theoretical_starch_kg"] == "0.00"
    assert fila.theoretical_starch_kg == Decimal("2233.00")


def test_preview_range_classifies_tickets_in_bulk(db):
    from app.models.production import RawMaterialReceipt

    rows = [receipt(comp="1"), receipt(comp="2"), receipt(comp="3")]
    source = _SourceStub(rows)
    service = RawMaterialReceiptImportService(source=source)

    def stored(row, source_hash):
        return RawMaterialReceipt.create(
            source_key=source.source_key(row.comp), source_comp=row.comp,
            source_hash=source_hash, received_at=row.received_at,
            supplier_code=row.supplier_code, product_code=row.product_code,
            gross_kg=row.gross_kg, tare_kg=row.tare_kg, net_kg=row.net_kg,
            payable_kg=row.payable_kg, yield_average=row.yield_average,
            theoretical_starch_kg=row.theoretical_starch_kg, source_payload="{}",
        )

    stored(rows[0], rows[0].source_hash)
    stored(rows[1], "hash-viejo")

    phases = []
    previews, _ = service.preview_range(
        date(2026, 9, 1), date(2026, 9, 28), progress=lambda *args: phases.append(args)
    )

    assert [preview.status for preview in previews] == [
        RawMaterialReceiptImportService.UNCHANGED,
        RawMaterialReceiptImportService.MODIFIED,
        RawMaterialReceiptImportService.NEW,
    ]
    assert phases[0] == ("consulta", 0, 0)
    assert phases[-1] == ("revision", 3, 3)


class _SourceStub:
    instance = "femagfab"

    def __init__(self, rows):
        self.rows = rows

    def source_key(self, comp):
        return f"femagfab:femagfab:movi:{comp}"

    def fetch_range(self, start, end):
        return self.rows


def test_weighted_yield_uses_payable_kilos():
    rows = [receipt(payable="10000", yield_average="20"), receipt(payable="30000", yield_average="30")]
    totals = RawMaterialReceiptImportService.totals(rows)
    assert totals.tickets == 2
    assert totals.payable_kg == Decimal("40000")
    assert totals.theoretical_starch_kg == Decimal("11000.00")
    assert totals.weighted_yield == Decimal("27.5")


def test_una_carga_sin_rinde_entra_con_el_rinde_estimado(db):
    """Lo que pidio la planta: la carga entra, con un rinde estimado."""
    from app.services.estimated_yield_service import EstimatedYieldService

    assert EstimatedYieldService.estimated_yield_pct() == Decimal("22.33")

    service = RawMaterialReceiptImportService(source=_SourceStub([receipt(yield_average="0")]))
    previews, totals = service.preview_range(date(2026, 9, 1), date(2026, 9, 28))

    fila = previews[0].row
    assert fila.is_estimated_yield is True
    assert fila.effective_yield_pct == Decimal("22.33")
    assert fila.theoretical_starch_kg == Decimal("2233.00")
    assert totals.estimated_tickets == 1
    assert totals.estimated_payable_kg == Decimal("10000")
    assert totals.estimated_starch_kg == Decimal("2233.00")
    assert totals.measured_tickets == 0
    assert totals.weighted_yield == Decimal("0")


def test_una_carga_con_rinde_conserva_el_suyo(db):
    service = RawMaterialReceiptImportService(source=_SourceStub([receipt(yield_average="25.00")]))
    previews, totals = service.preview_range(date(2026, 9, 1), date(2026, 9, 28))

    fila = previews[0].row
    assert fila.is_estimated_yield is False
    assert fila.effective_yield_pct == Decimal("25.00")
    assert fila.theoretical_starch_kg == Decimal("2500.00")
    assert totals.estimated_tickets == 0
    assert totals.measured_tickets == 1


def test_el_rinde_estimado_es_configurable(db):
    from app.services.estimated_yield_service import EstimatedYieldService

    EstimatedYieldService.set_estimated_yield_pct("23.50")
    assert EstimatedYieldService.estimated_yield_pct() == Decimal("23.50")

    service = RawMaterialReceiptImportService(source=_SourceStub([receipt(yield_average="0")]))
    previews, totals = service.preview_range(date(2026, 9, 1), date(2026, 9, 28))

    assert previews[0].row.effective_yield_pct == Decimal("23.50")
    assert totals.estimated_yield_pct == Decimal("23.50")


def test_el_rinde_ponderado_sale_solo_de_los_tickets_medidos(db):
    """Un ticket sin rinde no puede hundir el rendimiento del rango."""
    rows = [
        receipt(comp="1", payable="10000", yield_average="20"),
        receipt(comp="2", payable="30000", yield_average="0"),
    ]
    service = RawMaterialReceiptImportService(source=_SourceStub(rows))
    _, totals = service.preview_range(date(2026, 9, 1), date(2026, 9, 28))

    assert totals.tickets == 2
    assert totals.measured_tickets == 1
    assert totals.measured_payable_kg == Decimal("10000")
    assert totals.estimated_tickets == 1
    assert totals.estimated_payable_kg == Decimal("30000")
    # 20 %, no 7,5 %: el ticket sin rinde no pesa en el promedio.
    assert totals.weighted_yield == Decimal("20")
    # 10000 x 20 % + 30000 x 22,33 %
    assert totals.theoretical_starch_kg == Decimal("8699.00")


def test_la_importacion_guarda_de_donde_salio_el_rinde(db):
    from app.models.production import (
        RawMaterialReceipt, YIELD_SOURCE_ESTIMATED, YIELD_SOURCE_MEASURED,
    )

    rows = [receipt(comp="1"), receipt(comp="2", yield_average="0")]
    service = RawMaterialReceiptImportService(source=_SourceStub(rows))
    previews, _ = service.preview_range(date(2026, 9, 1), date(2026, 9, 28))

    assert service.import_new(previews) == 2

    medido = RawMaterialReceipt.get(RawMaterialReceipt.source_comp == "1")
    estimado = RawMaterialReceipt.get(RawMaterialReceipt.source_comp == "2")
    assert medido.yield_source == YIELD_SOURCE_MEASURED
    assert medido.estimated_yield_pct is None
    assert medido.is_estimated_yield is False
    assert estimado.yield_source == YIELD_SOURCE_ESTIMATED
    assert estimado.estimated_yield_pct == Decimal("22.33")
    assert estimado.is_estimated_yield is True
    assert estimado.theoretical_starch_kg == Decimal("2233.00")


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
        self.ranges = []
        self.phases = []

    def preview(self, day):
        return self.preview_range(day, day)

    def preview_range(self, start, end, progress=None):
        self.ranges.append((start, end))
        if progress:
            progress("consulta", 0, 0)
        previews = [
            ReceiptPreview(
                row=row,
                source_key=f"femagfab:femagfab:movi:{row.comp}",
                status=self.status,
            )
            for row in self.rows
        ]
        if progress:
            for index, _ in enumerate(previews, start=1):
                self.phases.append(("revision", index, len(previews)))
                progress("revision", index, len(previews))
        return previews, self.totals(self.rows)

    def import_new(self, previews, progress=None):
        pending = [preview for preview in previews if preview.status == self.NEW]
        for index, _ in enumerate(pending, start=1):
            if progress:
                self.phases.append(("importacion", index, len(pending)))
                progress("importacion", index, len(pending))
        self.imported.extend(pending)
        return len(pending)


def _wait_for(app, page, timeout=5.0):
    import time

    deadline = time.time() + timeout
    while page._busy and time.time() < deadline:
        app.processEvents()
    app.processEvents()
    assert page._busy is False, "la consulta/importacion no termino a tiempo"


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

    assert [child.title for child in produccion.children] == [
        "Recepciones de materia prima",
        "Partes de producción",
        "Contraste de producción",
        "Inventario inicial",
        "Conteo físico",
    ]
    child = produccion.children[0]
    assert child.route_key == "raw_material_receipts"
    assert child.placeholder is False
    contraste = produccion.children[2]
    assert contraste.route_key == "production_contrast"
    assert contraste.placeholder is False
    inventario = produccion.children[3]
    assert inventario.route_key == "stock_initial_inventory"
    assert inventario.placeholder is False
    conteo = produccion.children[4]
    assert conteo.route_key == "stock_count"
    assert conteo.placeholder is False
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
    page.start_day.setDate(QDate(2026, 9, 28))
    page.end_day.setDate(QDate(2026, 9, 28))
    app.processEvents()

    page.refresh()
    _wait_for(app, page)

    assert page.table.rowCount() == 8
    assert page.table.item(0, 0).text() == "1000"
    assert page.table.item(0, 8).text() == "Sin cambios"
    assert all(
        page.table.item(row, 8).text() == "Sin cambios" for row in range(page.table.rowCount())
    )
    # La fécula teórica nunca se toma del FECULA legacy del origen.
    assert page.table.item(0, 6).text() == "2,500.00"
    assert page.table.item(0, 7).text() == "9,999.00"
    # Este ticket tiene rinde medido, asi que el origen dice "Medido".
    assert page.table.item(0, 4).text() == "25.00 %"
    assert page.table.item(0, 5).text() == "Medido"
    assert page.import_button.isEnabled() is False

    summary = page.summary_label.text()
    assert "8 ticket(s)" in summary
    assert "80,000.00 kg liquidables" in summary
    assert "rinde ponderado 25.00 %" in summary
    assert "20,000.00 kg de fécula teórica" in summary

    page.import_new()
    app.processEvents()
    assert service.imported == []


def test_pending_tickets_enable_import_action(db):
    from PyQt5.QtWidgets import QApplication

    from app.ui.raw_material_receipt_import import RawMaterialReceiptImportPage

    app = QApplication.instance() or QApplication([])
    service = _PreviewServiceStub(_imported_day(), RawMaterialReceiptImportService.NEW)
    page = RawMaterialReceiptImportPage(service=service)
    app.processEvents()

    page.refresh()
    _wait_for(app, page)

    assert page.table.item(0, 8).text() == "Nuevo"
    assert page.import_button.isEnabled() is True
    assert "8 ticket(s) sin importar" in page.summary_label.text()

    page.import_new()
    _wait_for(app, page)
    assert len(service.imported) == 8
    assert page.import_button.isEnabled() is False
    assert service.phases[-1][0] == "importacion"


def test_consulta_uses_inclusive_range_and_shows_progress(db):
    from PyQt5.QtCore import QDate
    from PyQt5.QtWidgets import QApplication

    from app.ui.raw_material_receipt_import import RawMaterialReceiptImportPage

    app = QApplication.instance() or QApplication([])
    service = _PreviewServiceStub(_imported_day(), RawMaterialReceiptImportService.UNCHANGED)
    page = RawMaterialReceiptImportPage(service=service)
    page.start_day.setDate(QDate(2026, 9, 1))
    page.end_day.setDate(QDate(2026, 9, 28))
    app.processEvents()

    page.refresh()
    _wait_for(app, page)

    assert service.ranges == [(date(2026, 9, 1), date(2026, 9, 28))]
    assert ("revision", 8, 8) in service.phases
    assert "entre el 01/09/2026 y el 28/09/2026" in page.feedback.message
    assert page.progress.isVisible() is False


def test_la_pantalla_muestra_el_rinde_estimado(db):
    """La carga sin rinde se ve con el valor estimado y marcada como tal."""
    from dataclasses import replace

    from PyQt5.QtWidgets import QApplication

    from app.ui.raw_material_receipt_import import RawMaterialReceiptImportPage

    app = QApplication.instance() or QApplication([])
    fila = replace(receipt(yield_average="0"), applied_yield_pct=Decimal("22.33"))
    service = _PreviewServiceStub([fila], RawMaterialReceiptImportService.NEW)
    page = RawMaterialReceiptImportPage(service=service)
    app.processEvents()

    page.refresh()
    _wait_for(app, page)

    assert page.table.item(0, 4).text() == "22.33 %"
    assert page.table.item(0, 5).text() == "Estimado"
    assert page.table.item(0, 6).text() == "2,233.00"
    resumen = page.summary_label.text()
    assert "1 ticket(s) sin rinde medido" in resumen
    assert "10,000.00 kg con rinde estimado" in resumen
    # Sin rindes medidos no hay rendimiento ponderado que mostrar.
    assert "ningún ticket con rinde medido" in resumen


def test_el_campo_de_rinde_estimado_se_guarda_al_consultar(db):
    from PyQt5.QtWidgets import QApplication

    from app.services.estimated_yield_service import EstimatedYieldService
    from app.ui.raw_material_receipt_import import RawMaterialReceiptImportPage

    app = QApplication.instance() or QApplication([])
    service = _PreviewServiceStub(_imported_day(), RawMaterialReceiptImportService.UNCHANGED)
    page = RawMaterialReceiptImportPage(service=service)
    app.processEvents()

    assert page.estimated_yield.value() == 22.33

    page.estimated_yield.setValue(23.75)
    page.refresh()
    _wait_for(app, page)

    assert EstimatedYieldService.estimated_yield_pct() == Decimal("23.75")


def test_invalid_range_is_rejected_without_querying(db):
    from PyQt5.QtCore import QDate
    from PyQt5.QtWidgets import QApplication

    from app.ui.raw_material_receipt_import import RawMaterialReceiptImportPage

    app = QApplication.instance() or QApplication([])
    service = _PreviewServiceStub(_imported_day(), RawMaterialReceiptImportService.NEW)
    page = RawMaterialReceiptImportPage(service=service)
    page.start_day.setDate(QDate(2026, 9, 28))
    page.end_day.setDate(QDate(2026, 9, 1))
    app.processEvents()

    page.refresh()
    app.processEvents()

    assert service.ranges == []
    assert "posterior" in page.feedback.message.lower()
