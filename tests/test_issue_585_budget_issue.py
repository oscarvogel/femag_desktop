"""Emision de los dos presupuestos de un renglón partido (#585, PR 3).

Al emitir la orden se generan dos presupuestos por cliente: el de la parte
facturada al contado y el de la parte a facturar despues, cada uno con su
numero, su movimiento en cuenta corriente y su vencimiento. Este PR no cambia
la pantalla ni el envio.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tests.conftest import _master_data


def _order_with_split(db, *, cantidad=1200.0, cantidad_facturar_ahora=800.0, **client_kwargs):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    for key, value in client_kwargs.items():
        setattr(data["client"], key, value)
    data["client"].save()
    return LoadOrderService(current_user="issue585").create_order(
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
                        "descuento_porcentaje": 5.0,
                    }
                ],
            }
        ],
    ), data


def _budgets_by_timing(order, client):
    from app.models.budgets import Budget

    return {
        budget.timing: budget
        for budget in Budget.select().where(
            (Budget.load_order == order) & (Budget.client == client)
        )
    }


# ------------------------------------------------------- emision de presupuestos


def test_orden_sin_reparto_genera_un_solo_presupuesto(db):
    from app.services.budget_service import BudgetService

    order, data = _order_with_split(db, cantidad_facturar_ahora=1200.0)
    budgets = BudgetService(current_user="issue585").ensure_for_load_order(order)

    assert len(budgets) == 1
    line = order.products[0]
    assert budgets[0].total_amount == pytest.approx(line.total, abs=0.01)


def test_orden_con_reparto_genera_dos_presupuestos(db):
    from app.models.budgets import Budget
    from app.services.budget_service import BudgetService

    order, data = _order_with_split(db)
    budgets = BudgetService(current_user="issue585").ensure_for_load_order(order)

    assert len(budgets) == 2
    by_timing = _budgets_by_timing(order, data["client"])
    assert set(by_timing) == {Budget.TIMING_IMMEDIATE, Budget.TIMING_DEFERRED}
    # Cada parte tiene su propio numero.
    assert by_timing[Budget.TIMING_IMMEDIATE].budget_number != by_timing[
        Budget.TIMING_DEFERRED
    ].budget_number


def test_las_cantidades_de_cada_parte_son_las_del_reparto(db):
    from app.services.budget_service import BudgetService

    order, data = _order_with_split(db)
    BudgetService(current_user="issue585").ensure_for_load_order(order)
    by_timing = _budgets_by_timing(order, data["client"])

    assert by_timing["immediate"].items[0].quantity == pytest.approx(800.0)
    assert by_timing["deferred"].items[0].quantity == pytest.approx(400.0)


def test_los_dos_presupuestos_suman_exactamente_el_renglon(db):
    """El cruce que ningun guard cubre hoy.

    ``assert_monetary_integrity`` valida cada presupuesto por separado, asi que
    nada impide que el reparto de una parte se desvíe. Este test es el que
    garantiza que los dos documentos juntos dan el total del renglon, al centavo.
    """
    from app.services.budget_service import BudgetService

    order, data = _order_with_split(db)
    BudgetService(current_user="issue585").ensure_for_load_order(order)
    by_timing = _budgets_by_timing(order, data["client"])
    line = order.products[0]

    suma = sum(
        Decimal(str(budget.total_amount)) for budget in by_timing.values()
    )
    # Sin esto el test pasaria con dos presupuestos en cero, que es exactamente
    # el caso degenerado que hay que evitar.
    assert by_timing["immediate"].total_amount > 0
    assert by_timing["deferred"].total_amount > 0
    assert suma == Decimal(str(line.total))


def test_cada_presupuesto_conserva_su_propia_integridad(db):
    from app.services.budget_service import BudgetService

    order, data = _order_with_split(db)
    service = BudgetService(current_user="issue585")
    for budget in service.ensure_for_load_order(order):
        service.assert_monetary_integrity(budget)


def test_renglon_totalmente_diferido_no_genera_presupuesto_inmediato(db):
    from app.services.budget_service import BudgetService

    order, data = _order_with_split(db, cantidad_facturar_ahora=0.0)
    BudgetService(current_user="issue585").ensure_for_load_order(order)
    by_timing = _budgets_by_timing(order, data["client"])

    assert set(by_timing) == {"deferred"}
    assert by_timing["deferred"].items[0].quantity == pytest.approx(1200.0)


def test_reemitir_no_duplica_presupuestos(db):
    from app.services.budget_service import BudgetService

    order, data = _order_with_split(db)
    service = BudgetService(current_user="issue585")
    first = service.ensure_for_load_order(order)
    second = service.ensure_for_load_order(order)

    assert {b.id for b in first} == {b.id for b in second}


# ----------------------------------------------------------- cuenta corriente


def test_cuenta_corriente_registra_dos_movimientos(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.account_ledger_service import AccountLedgerService

    order, data = _order_with_split(db)
    AccountLedgerService(current_user="issue585").generate_for_load_order(order)

    movements = ClientAccountMovement.select().where(
        (ClientAccountMovement.load_order == order)
        & (ClientAccountMovement.is_reversal == False)  # noqa: E712
    )
    assert movements.count() == 2
    assert {m.movement_type for m in movements} == {
        ClientAccountMovement.TYPE_LOAD_ORDER_IMMEDIATE,
        ClientAccountMovement.TYPE_LOAD_ORDER_DEFERRED,
    }


def test_la_parte_facturada_hoy_vence_al_contado_y_la_diferida_a_plazo(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.account_ledger_service import AccountLedgerService

    order, data = _order_with_split(db, dias_plazo_pago=30)
    AccountLedgerService(current_user="issue585").generate_for_load_order(order)

    by_type = {
        m.movement_type: m
        for m in ClientAccountMovement.select().where(
            (ClientAccountMovement.load_order == order)
            & (ClientAccountMovement.is_reversal == False)  # noqa: E712
        )
    }
    inmediato = by_type[ClientAccountMovement.TYPE_LOAD_ORDER_IMMEDIATE]
    diferido = by_type[ClientAccountMovement.TYPE_LOAD_ORDER_DEFERRED]

    assert inmediato.due_date == order.date
    assert diferido.due_date == order.date + timedelta(days=30)


def test_los_movimientos_apuntan_a_su_presupuesto(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.account_ledger_service import AccountLedgerService

    order, data = _order_with_split(db)
    AccountLedgerService(current_user="issue585").generate_for_load_order(order)
    by_timing = _budgets_by_timing(order, data["client"])

    for movement in ClientAccountMovement.select().where(
        (ClientAccountMovement.load_order == order)
        & (ClientAccountMovement.is_reversal == False)  # noqa: E712
    ):
        esperado = (
            by_timing["immediate"]
            if movement.movement_type == ClientAccountMovement.TYPE_LOAD_ORDER_IMMEDIATE
            else by_timing["deferred"]
        )
        assert movement.budget_id == esperado.id
        assert movement.reference == esperado.display_number
        assert movement.source_ref == f"Budget:{esperado.id}"


def test_anular_la_orden_revierte_los_dos_movimientos(db):
    """La deuda diferida no puede quedar huerfana al anular."""
    from app.models.accounting import ClientAccountMovement
    from app.services.account_ledger_service import AccountLedgerService

    order, data = _order_with_split(db)
    service = AccountLedgerService(current_user="issue585")
    service.generate_for_load_order(order)

    reversals = service.reverse_for_load_order(order)

    assert len(reversals) == 2
    originales = {m.id for m in ClientAccountMovement.select().where(
        (ClientAccountMovement.load_order == order)
        & (ClientAccountMovement.is_reversal == False)  # noqa: E712
    )}
    assert {r.reverses_id for r in reversals} == originales
    for reversal in reversals:
        assert reversal.total_amount < 0


def test_orden_sin_reparto_genera_un_solo_movimiento(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.account_ledger_service import AccountLedgerService

    order, data = _order_with_split(db, cantidad_facturar_ahora=1200.0)
    AccountLedgerService(current_user="issue585").generate_for_load_order(order)

    assert ClientAccountMovement.select().where(
        (ClientAccountMovement.load_order == order)
        & (ClientAccountMovement.is_reversal == False)  # noqa: E712
    ).count() == 1
