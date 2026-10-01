"""El movimiento diferido tiene que verse en todos los consumidores (#585).

Al agregar el tipo de movimiento de la parte diferida, los consumidores que
filtraban por el tipo historico dejaron de verla. Estos tests fijan que la parte
a facturar despues cuente en cada uno.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tests.conftest import _complete_order_for_issue, _master_data

PLAZO_CLIENTE = 30


def _orden_partida(db):
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    data["client"].dias_plazo_pago = PLAZO_CLIENTE
    data["client"].save()
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
                        "quantity": 1200.0,
                        "cantidad_facturar_ahora": 800.0,
                        "precio_neto_unitario": 14200.0,
                    }
                ],
            }
        ],
    )
    _complete_order_for_issue(order, current_user="issue585")
    service = LoadOrderOperationService(current_user="issue585")
    return service.issue(order), data


def test_pagar_solo_lo_de_hoy_deja_la_orden_parcial(db):
    """La regresion que encontro el ensayo de despacho.

    Antes solo se suma el movimiento del tipo historico, asi que la parte
    diferida no contaba como deuda y la orden se reportaba cobrada con un tercio
    del total todavia impago.
    """
    from app.models.budgets import Budget
    from app.models.payments import ClientPayment
    from app.services.load_order_closure_service import (
        LoadOrderClosureError,
        LoadOrderClosureService,
    )

    order, data = _orden_partida(db)
    budgets = {
        budget.timing: budget
        for budget in Budget.select().where(Budget.load_order == order)
    }
    servicio = LoadOrderClosureService(current_user="issue585")
    cierre = servicio.close_order(
        order,
        payments=[
            {
                "client": data["client"],
                "amount": budgets["immediate"].total_amount,
                "method": ClientPayment.METHOD_TRANSFER,
                "reference": "TRANSFER-1",
            }
        ],
    )

    resumen = servicio.payment_summary(cierre)[0]
    assert resumen["total"] == pytest.approx(
        budgets["immediate"].total_amount + budgets["deferred"].total_amount
    )
    assert resumen["balance"] > 0
    assert resumen["status"] == LoadOrderClosureService.PAYMENT_STATUS_PARTIAL
    assert servicio.payment_status(cierre) == LoadOrderClosureService.PAYMENT_STATUS_PARTIAL


def test_pagar_las_dos_partes_deja_la_orden_cobrada(db):
    from app.models.budgets import Budget
    from app.models.payments import ClientPayment
    from app.services.load_order_closure_service import LoadOrderClosureService

    order, data = _orden_partida(db)
    budgets = list(Budget.select().where(Budget.load_order == order))
    servicio = LoadOrderClosureService(current_user="issue585")
    cierre = servicio.close_order(
        order,
        payments=[
            {
                "client": data["client"],
                "amount": sum(b.total_amount for b in budgets),
                "method": ClientPayment.METHOD_TRANSFER,
            }
        ],
    )

    assert servicio.payment_status(cierre) == LoadOrderClosureService.PAYMENT_STATUS_PAID


def test_el_informe_de_cobranza_incluye_la_parte_diferida(db):
    from app.models.accounting import ClientAccountMovement
    from app.reports.collection_due_report import CollectionDueFilters
    from app.reports.collection_due_report import CollectionDueReportService

    order, _data = _orden_partida(db)
    inicio = order.date - timedelta(days=1)
    fin = order.date + timedelta(days=PLAZO_CLIENTE + 1)

    report = CollectionDueReportService().report(
        CollectionDueFilters(due_from=inicio, due_to=fin),
        today=order.date,
    )

    # La parte de hoy vence al contado y la diferida a plazo: dos filas distintas.
    assert len(report.rows) == 2
    vencimientos = sorted(row["due_date"] for row in report.rows)
    assert vencimientos == [
        order.date,
        order.date + timedelta(days=PLAZO_CLIENTE),
    ]
    # La que vence a plazo es la parte diferida, la que queda para cobrar despues.
    diferida = max(report.rows, key=lambda row: row["due_date"])
    assert diferida["delta_days"] == PLAZO_CLIENTE


def test_el_limite_de_credito_ve_la_parte_diferida(db):
    """Una orden totalmente diferida igual es deuda del cliente."""
    from app.services.load_order_service import LoadOrderService
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.client_credit_service import ClientCreditService

    data = _master_data()
    data["client"].dias_plazo_pago = PLAZO_CLIENTE
    data["client"].save()
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
                        "quantity": 500.0,
                        "cantidad_facturar_ahora": 0.0,
                        "precio_neto_unitario": 1000.0,
                    }
                ],
            }
        ],
    )
    _complete_order_for_issue(order, current_user="issue585")
    LoadOrderOperationService(current_user="issue585").issue(order)

    pendientes = ClientCreditService._dispatch_balances(data["client"])
    order_ids = {row["order"].id for row in pendientes}
    assert order.id in order_ids


def test_el_estado_de_cuenta_etiqueta_la_parte_diferida(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.account_statement_print_service import _movement_type_label

    order, _data = _orden_partida(db)
    diferido = ClientAccountMovement.get(
        (ClientAccountMovement.load_order == order)
        & (ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_LOAD_ORDER_DEFERRED)
    )
    etiqueta = _movement_type_label(diferido)

    # No puede caer en la etiqueta generica "Movimiento": se pierde de que se trata.
    assert etiqueta != "Movimiento"
    assert "despu" in etiqueta.lower()
