"""Envio separado de los dos presupuestos de una orden partida (#585, PR 4).

Con el reparto, una orden emite dos presupuestos por cliente. El envio tiene que
poder elegir cual se genera y se manda, sin obligar al operador a imprimir el
presupuesto de la parte que todavia no corresponde.
"""
import os
from pathlib import Path

import pytest
from PyQt5.QtWidgets import QApplication, QCheckBox, QDialog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.conftest import _complete_order_for_issue, _master_data  # noqa: E402


def _app():
    return QApplication.instance() or QApplication([])


def _issued_order(db, *, cantidad=1200.0, cantidad_facturar_ahora=800.0):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="issue585").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [
                    {
                        "product": data["product"],
                        "quantity": cantidad,
                        "cantidad_facturar_ahora": cantidad_facturar_ahora,
                        "precio_neto_unitario": 14200.0,
                    }
                ],
            }
        ],
    )
    service = LoadOrderOperationService(current_user="issue585")
    # Solo completa los pallets: no toca los destinos, asi que el reparto se conserva.
    _complete_order_for_issue(order)
    service.issue(order)
    return service, LoadOrder.get_by_id(order.id), data


# ------------------------------------------------------------------ servicio


def test_una_orden_partida_tiene_las_dos_partes_para_enviar(db):
    from app.models.budgets import Budget

    _service, order, _data = _issued_order(db)

    assert set(_service.budget_timings_for_order(order)) == {
        Budget.TIMING_IMMEDIATE,
        Budget.TIMING_DEFERRED,
    }


def test_una_orden_sin_reparto_tiene_una_sola_parte(db):
    from app.models.budgets import Budget

    _service, order, _data = _issued_order(db, cantidad_facturar_ahora=1200.0)

    assert _service.budget_timings_for_order(order) == [Budget.TIMING_IMMEDIATE]


def test_enviar_sin_filtro_genera_las_dos_partes(db, tmp_path):
    from app.models.budgets import Budget

    service, order, data = _issued_order(db)
    service.prints_dir = tmp_path

    paths = service.export_budgets(order)

    assert len(paths) == 2
    esperados = {
        f"presupuesto_{budget.budget_number:06d}.pdf"
        for budget in Budget.select().where(
            (Budget.load_order == order) & (Budget.client == data["client"])
        )
    }
    assert {p.name for p in paths} == esperados


def test_enviar_solo_la_parte_facturada_hoy(db, tmp_path):
    from app.models.budgets import Budget

    service, order, data = _issued_order(db)
    service.prints_dir = tmp_path

    paths = service.export_budgets(order, timing=Budget.TIMING_IMMEDIATE)

    inmediato = Budget.get(
        (Budget.load_order == order)
        & (Budget.client == data["client"])
        & (Budget.timing == Budget.TIMING_IMMEDIATE)
    )
    assert len(paths) == 1
    assert paths[0].name == f"presupuesto_{inmediato.budget_number:06d}.pdf"
    assert paths[0].read_bytes().startswith(b"%PDF")


def test_enviar_solo_la_parte_diferida(db, tmp_path):
    from app.models.budgets import Budget

    service, order, data = _issued_order(db)
    service.prints_dir = tmp_path

    paths = service.export_budgets(order, timing=Budget.TIMING_DEFERRED)

    diferido = Budget.get(
        (Budget.load_order == order)
        & (Budget.client == data["client"])
        & (Budget.timing == Budget.TIMING_DEFERRED)
    )
    assert len(paths) == 1
    assert paths[0].name == f"presupuesto_{diferido.budget_number:06d}.pdf"


def test_el_pdf_de_cada_parte_muestra_su_importe(db, tmp_path):
    """El documento de hoy y el de despues no pueden llevar el mismo total."""
    from app.models.budgets import Budget
    from tests.load_order_printing_cases import _pdf_text

    service, order, _data = _issued_order(db)
    service.prints_dir = tmp_path

    textos = {}
    for timing in (Budget.TIMING_IMMEDIATE, Budget.TIMING_DEFERRED):
        paths = service.export_budgets(order, timing=timing)
        assert len(paths) == 1
        textos[timing] = _pdf_text(paths[0])

    assert textos[Budget.TIMING_IMMEDIATE] != textos[Budget.TIMING_DEFERRED]


# ------------------------------------------------------------------------ UI


def test_el_dialogo_de_envio_trae_las_dos_partes_marcadas(db):
    from app.ui.load_order_workspace_restore_extension import _BudgetSendChoiceDialog

    app = _app()
    dialog = _BudgetSendChoiceDialog(123)
    dialog.show()
    app.processEvents()

    assert dialog.findChild(QCheckBox, "budgetSendInmediatoCheck").isChecked() is True
    assert dialog.findChild(QCheckBox, "budgetSendDiferidoCheck").isChecked() is True
    assert dialog.selected_timings() == ["immediate", "deferred"]


def test_el_dialogo_permite_desmarcar_una_parte(db):
    from app.ui.load_order_workspace_restore_extension import _BudgetSendChoiceDialog

    app = _app()
    dialog = _BudgetSendChoiceDialog(123)
    dialog.show()
    app.processEvents()
    dialog.findChild(QCheckBox, "budgetSendDiferidoCheck").setChecked(False)

    assert dialog.selected_timings() == ["immediate"]


def test_el_dialogo_no_acepta_dejar_sin_marcar_nada(db):
    from app.ui.load_order_workspace_restore_extension import _BudgetSendChoiceDialog

    app = _app()
    dialog = _BudgetSendChoiceDialog(123)
    dialog.show()
    app.processEvents()
    dialog.findChild(QCheckBox, "budgetSendInmediatoCheck").setChecked(False)
    dialog.findChild(QCheckBox, "budgetSendDiferidoCheck").setChecked(False)

    dialog.findChild(_BudgetSendChoiceDialog, "budgetSendConfirmButton")
    dialog._validate_and_accept()
    app.processEvents()

    # Sin nada marcado no se acepta: no se genera un presupuesto de mas.
    assert dialog.result() != QDialog.Accepted


def test_el_boton_consulta_las_partes_y_pasa_el_filtro():
    """El boton tiene que preguntar solo cuando hay dos partes que elegir."""
    fuente = Path(
        r"app/ui/load_order_workspace_restore_extension.py"
    ).read_text(encoding="utf-8")

    assert "budget_timings_for_order" in fuente
    assert "_BudgetSendChoiceDialog" in fuente
    assert "export_budgets(order, timing=timing)" in fuente
