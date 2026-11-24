"""Tests de la pantalla "Cuenta corriente productores" (#941)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date
from decimal import Decimal

import pytest

CUTOFF = date(2026, 11, 20)


_QT_APP = None


def _app():
    # La referencia se guarda: si el QApplication se libera, el primer widget
    # que se cree aborta el proceso.
    global _QT_APP
    from PyQt5.QtWidgets import QApplication

    _QT_APP = QApplication.instance() or QApplication([])
    return _QT_APP


def _supplier(name, codes=()):
    from app.models.suppliers import Supplier, SupplierLegacyCode

    supplier = Supplier.create(name=name, normalized_name=name)
    for code in codes:
        SupplierLegacyCode.create(
            supplier=supplier, code=code, source_key=f"femagfab:proveedo:{code}", name=name
        )
    return supplier


def _document(supplier, kind, code, balance, issued=date(2026, 6, 1), inferred=False):
    from app.models.suppliers import SupplierDocument

    return SupplierDocument.create(
        supplier=supplier,
        kind=kind,
        source_key=f"femagfab:{kind}:{code}",
        source_code=code,
        issued_at=issued,
        date_inferred=inferred,
        amount=Decimal(balance),
        balance=Decimal(balance),
        source_hash="x",
    )


def _user(username, profile):
    from app.services.auth_service import AuthService

    return AuthService().create_user(username, "clave", profile)


@pytest.fixture()
def datos(db):
    from app.models.suppliers import SupplierDocument, SupplierDocumentExclusion
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()
    T, P = SupplierDocument.KIND_TICKET, SupplierDocument.KIND_PROMISSORY_NOTE
    coop = _supplier("COOP NUEVA ARGENTINA", ("0656", "0999"))
    klem = _supplier("KLEM JORGE", ("0123",))
    zelaya = _supplier("ZELAYA RAMON", ("0500",))
    docs = {
        "coop_t1": _document(coop, T, "000000044143", "300000.00", issued=date(2026, 5, 2)),
        "coop_t2": _document(coop, T, "000000044150", "100000.00", inferred=True),
        "coop_p": _document(coop, P, "0616", "50000.00"),
        "klem_t": _document(klem, T, "000000045000", "900000.00", issued=date(2026, 9, 1)),
        "zelaya_p": _document(zelaya, P, "0700", "20000.00"),
    }
    SupplierDocumentExclusion.create(
        kind=T, source_key="femagfab:movi:x", source_code="x", supplier_code="0656",
        amount=Decimal("1234.50"), reason=SupplierDocumentExclusion.REASON_NO_QUANTITY,
    )
    return {"coop": coop, "klem": klem, "zelaya": zelaya, **docs}


def test_la_posicion_separa_a_pagar_y_a_cobrar_y_ordena_por_neto(datos):
    from app.services.supplier_position_service import (
        SupplierPositionFilters,
        SupplierPositionService,
    )

    result = SupplierPositionService().position(SupplierPositionFilters())

    assert [row.name for row in result.rows] == ["KLEM JORGE", "COOP NUEVA ARGENTINA", "ZELAYA RAMON"]
    coop = result.rows[1]
    assert coop.codes == "0656, 0999"
    assert coop.payable == Decimal("400000.00")
    assert coop.receivable == Decimal("50000.00")
    assert coop.net == Decimal("350000.00")
    assert coop.oldest_date == date(2026, 5, 2)
    assert result.payable == Decimal("1300000.00")
    assert result.receivable == Decimal("70000.00")
    assert result.net == Decimal("1230000.00")
    assert (result.excluded_count, result.excluded_amount) == (1, Decimal("1234.50"))


def test_la_posicion_coincide_con_el_libro(datos):
    from app.services.supplier_ledger_service import AllocationRequest, SupplierLedgerService
    from app.services.supplier_position_service import (
        SupplierPositionFilters,
        SupplierPositionService,
    )

    ledger = SupplierLedgerService("admin")
    ledger.open_ledger_from_imports(cutoff=CUTOFF)
    ledger.register_payment(
        supplier=datos["coop"],
        amount=Decimal("100000"),
        method="efectivo",
        allocations=[AllocationRequest(datos["coop_t2"], Decimal("100000"))],
    )

    result = SupplierPositionService().position(SupplierPositionFilters())
    balances = ledger.balances()
    for row in result.rows:
        assert row.net == balances[row.supplier_id]
    # El ticket saldado deja de aparecer con "solo con saldo".
    codes = {doc.code for doc in SupplierPositionService().documents(SupplierPositionFilters())}
    assert "000000044150" not in codes


def test_filtros_por_tipo_fecha_y_productor(datos):
    from app.models.suppliers import SupplierDocument
    from app.services.supplier_position_service import (
        SupplierPositionFilters,
        SupplierPositionService,
    )

    service = SupplierPositionService()
    solo_pagares = service.position(SupplierPositionFilters(kind=SupplierDocument.KIND_PROMISSORY_NOTE))
    assert solo_pagares.payable == Decimal("0.00")
    assert solo_pagares.receivable == Decimal("70000.00")

    desde_agosto = service.position(SupplierPositionFilters(date_from=date(2026, 8, 1)))
    assert [row.name for row in desde_agosto.rows] == ["KLEM JORGE"]

    coop = service.position(SupplierPositionFilters(supplier_id=datos["coop"].id))
    assert [row.name for row in coop.rows] == ["COOP NUEVA ARGENTINA"]


def test_exporta_excel_y_pdf_con_totales_y_exclusiones(datos, tmp_path):
    from openpyxl import load_workbook

    from app.reports.supplier_position_export import (
        export_supplier_position_pdf,
        export_supplier_position_xlsx,
    )
    from app.services.supplier_position_service import (
        SupplierPositionFilters,
        SupplierPositionService,
    )

    service = SupplierPositionService()
    filters = SupplierPositionFilters()
    documents = service.documents(filters)
    result = service.position(filters, documents=documents)

    xlsx = export_supplier_position_xlsx(result, documents, tmp_path / "pos.xlsx")
    book = load_workbook(xlsx)
    hoja = book["Posicion"]
    filas = list(hoja.iter_rows(values_only=True))
    total = next(fila for fila in filas if fila and fila[0] == "Total")
    assert total[2:5] == (1300000.0, 70000.0, 1230000.0)
    exclusion = next(fila for fila in filas if fila and str(fila[0]).startswith("Excluido"))
    assert exclusion[2] == 1234.5
    assert book["Documentos"].max_row == len(documents) + 1

    pdf = export_supplier_position_pdf(result, documents, tmp_path / "pos.pdf")
    assert pdf.read_bytes().startswith(b"%PDF")


def test_la_pantalla_muestra_totales_detalle_y_exclusiones(datos):
    from app.ui.supplier_ledger import SupplierLedgerPage

    _app()
    admin = _user("admin_prod", "Administrador")
    page = SupplierLedgerPage(user=admin, current_username=admin.username)

    assert page.position_table.rowCount() == 3
    assert "1.230.000,00" in page.net_label.text()
    assert "1 documentos" in page.exclusion_label.text()
    # Arranca con el primer productor (mayor neto) y su detalle.
    assert page.detail_title.text() == "KLEM JORGE"
    assert page.document_table.rowCount() == 1
    assert page.register_button.isEnabled()

    page.supplier_combo.setCurrentIndex(page.supplier_combo.findData(datos["coop"].id))
    page.refresh()
    assert page.position_table.rowCount() == 1
    assert page.detail_title.text() == "COOP NUEVA ARGENTINA"
    assert page.document_table.rowCount() == 3
    fechas = [page.document_table.item(r, 2).text() for r in range(3)]
    assert any(texto.endswith("*") for texto in fechas)


def test_el_combo_de_productor_no_acepta_texto_libre(datos):
    from app.ui.supplier_ledger import SupplierLedgerPage

    _app()
    admin = _user("admin_combo", "Administrador")
    page = SupplierLedgerPage(user=admin, current_username=admin.username)
    combo = page.supplier_combo
    combo.setCurrentIndex(combo.findData(datos["klem"].id))
    combo.lineEdit().setText("CUALQUIER COSA")
    combo.commit_search_text()
    assert combo.currentData() in (None, datos["klem"].id)
    assert combo.currentText() != "CUALQUIER COSA"


def test_registrar_y_anular_un_pago_desde_la_pantalla(datos, monkeypatch):
    from PyQt5.QtWidgets import QDialog, QMessageBox

    from app.models.suppliers import SupplierPayment
    from app.ui.supplier_ledger import SupplierLedgerPage

    _app()
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail(a[2]))
    admin = _user("admin_pago", "Administrador")
    page = SupplierLedgerPage(user=admin, current_username=admin.username)
    page.supplier_combo.setCurrentIndex(page.supplier_combo.findData(datos["coop"].id))
    page.refresh()

    captured = {}

    def fake_dialog(name, tickets):
        dialog = page.__class__._make_payment_dialog(page, name, tickets)
        # Solo tickets: el pagare no se ofrece para imputar.
        assert [t.code for t in dialog.tickets] == ["000000044143", "000000044150"]
        dialog.set_allocation(0, 120000)
        dialog.set_allocation(1, 100000)
        dialog.exec_ = lambda: QDialog.Accepted
        captured["dialog"] = dialog
        return dialog

    monkeypatch.setattr(page, "_make_payment_dialog", fake_dialog)
    payment = page.register_payment()

    assert payment is not None
    assert Decimal(str(payment.amount)) == Decimal("220000.00")
    assert payment.idempotency_key == captured["dialog"].idempotency_key
    coop_row = page._result.rows[0]
    assert coop_row.payable == Decimal("180000.00")
    assert page.payment_table.rowCount() == 1

    page.payment_table.selectRow(0)
    assert page.annul_button.isEnabled()
    monkeypatch.setattr(page, "_ask_annulment_reason", lambda _p: "Cargado por error")
    page.annul_selected_payment()

    assert SupplierPayment.get_by_id(payment.id).status == SupplierPayment.STATUS_ANNULLED
    assert page._result.rows[0].payable == Decimal("400000.00")


def test_sin_permiso_los_botones_quedan_deshabilitados(datos):
    from app.services.supplier_ledger_service import can_annul_payments, can_register_payments
    from app.ui.supplier_ledger import SupplierLedgerPage

    _app()
    consulta = _user("solo_consulta", "Solo consulta")
    page = SupplierLedgerPage(user=consulta, current_username=consulta.username)

    assert not can_register_payments(consulta)
    assert not page.register_button.isEnabled()
    assert "permiso" in page.register_button.toolTip()
    assert not page.annul_button.isEnabled()

    administracion = _user("administracion", "Administración")
    assert can_register_payments(administracion)
    assert not can_annul_payments(administracion)


def test_la_anulacion_usa_el_permiso_del_menu(datos):
    from app.models.security import MenuItem, Permission
    from app.services.supplier_ledger_service import (
        AllocationRequest,
        SupplierLedgerService,
        can_annul_payments,
    )

    operador = _user("operador_anula", "Administración")
    item = MenuItem.get(MenuItem.title == "Cuenta corriente productores")
    Permission.update(allowed=True).where(
        Permission.profile == operador.profile,
        Permission.menu_item == item,
        Permission.action == "anular",
    ).execute()
    assert can_annul_payments(operador)

    ledger = SupplierLedgerService(operador.username)
    pago = ledger.register_payment(
        supplier=datos["klem"],
        amount=Decimal("1000"),
        method="cheque",
        allocations=[AllocationRequest(datos["klem_t"], Decimal("1000"))],
    )
    ledger.annul_payment(pago, authorized_by=operador, reason="Cheque rechazado")


def test_pantalla_vacia_sin_documentos(db):
    from app.services.permission_service import PermissionService
    from app.ui.supplier_ledger import SupplierLedgerPage

    _app()
    PermissionService().seed_defaults()
    admin = _user("admin_vacio", "Administrador")
    page = SupplierLedgerPage(user=admin, current_username=admin.username)

    assert page.position_table.rowCount() == 0
    assert "No hay documentos importados" in page.exclusion_label.text()
    assert not page.register_button.isEnabled()
    assert not page.export_excel_button.isEnabled()


def test_el_menu_de_produccion_ofrece_la_pantalla(db):
    from app.services.permission_service import PermissionService
    from app.ui.menu import build_sidebar_tree_spec

    PermissionService().seed_defaults()
    admin = _user("admin_menu_prod", "Administrador")
    principal = build_sidebar_tree_spec(admin).sections[0]
    produccion = next(item for item in principal.items if item.title == "Producción")
    item = next(child for child in produccion.children if child.title == "Cuenta corriente productores")
    assert item.route_key == "supplier_ledger"
    assert item.placeholder is False

    gerencia = _user("gerencia_menu_prod", "Gerencia")
    principal = build_sidebar_tree_spec(gerencia).sections[0]
    titles = [
        child.title
        for parent in principal.items
        for child in (parent.children or [])
    ]
    assert "Cuenta corriente productores" not in titles
