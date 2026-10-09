"""Devoluciones que el operador asigna a una de las dos partes (#585, PR 5).

Una orden partida tiene dos presupuestos con deudas distintas y vencimientos
distintos. Cuando vuelve mercaderia, el operador indica de que parte sale, para
que el acredite caiga contra el presupuesto correcto y el reporte de cobranza
siga reflejando la realidad.
"""
from decimal import Decimal

import pytest

from tests.conftest import _complete_order_for_issue, _master_data

PRECIO = 1000.0
CANTIDAD = 50.0
HOY = 30.0
DESPUES = 20.0


def _orden_partida(db, *, hoy=HOY):
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
                        "quantity": CANTIDAD,
                        "cantidad_facturar_ahora": hoy,
                        "precio_neto_unitario": PRECIO,
                    }
                ],
            }
        ],
    )
    _complete_order_for_issue(order, current_user="issue585")
    LoadOrderOperationService(current_user="issue585").issue(order)
    return order, data


def _cerrar(order, data, devoluciones):
    from app.services.load_order_closure_service import LoadOrderClosureService

    return LoadOrderClosureService(current_user="issue585").close_order(
        order,
        returns=devoluciones,
        no_payment_reason="Sin cobro en este cierre",
    )


def test_se_puede_devolver_del_mismo_producto_de_las_dos_partes(db):
    """El indice historico era (cierre, producto) y no permitia dos lineas.

    Con el reparto, un mismo producto puede volver parte de lo facturado hoy y
    parte de lo que estaba diferido, en el mismo cierre.
    """
    order, data = _orden_partida(db)
    linea = order.products[0]

    cierre = _cerrar(
        order,
        data,
        [
            {
                "order_product": linea,
                "quantity": 5.0,
                "reason": "Envase danado (hoy)",
                "timing": "immediate",
            },
            {
                "order_product": linea,
                "quantity": 3.0,
                "reason": "Envase danado (diferido)",
                "timing": "deferred",
            },
        ],
    )

    from app.models.load_orders import LoadOrderReturnLine

    lineas = list(LoadOrderReturnLine.select().where(LoadOrderReturnLine.closure == cierre))
    assert len(lineas) == 2
    assert {linea.timing for linea in lineas} == {"immediate", "deferred"}


def test_el_credito_se_separa_por_presupuesto(db):
    order, data = _orden_partida(db)
    linea = order.products[0]

    from app.services.load_order_return_credit_service import LoadOrderReturnCreditService

    _cerrar(
        order,
        data,
        [
            {"order_product": linea, "quantity": 5.0, "reason": "Hoy", "timing": "immediate"},
            {"order_product": linea, "quantity": 3.0, "reason": "Diferido", "timing": "deferred"},
        ],
    )

    from app.models.accounting import ClientAccountMovement

    movimientos = list(
        ClientAccountMovement.select().where(
            (ClientAccountMovement.load_order == order)
            & (ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_RETURN_CREDIT)
        )
    )
    # Un movimiento por presupuesto, no uno por cliente.
    assert len(movimientos) == 2
    assert {abs(round(float(m.total_amount), 2)) for m in movimientos} == {
        5000.0 * 1.21,
        3000.0 * 1.21,
    }
    for movimiento in movimientos:
        # Cada credito apunta a su presupuesto.
        assert movimiento.budget_id is not None
        assert movimiento.budget.timing in {"immediate", "deferred"}


def test_no_se_puede_devolver_mas_que_la_parte_elegida(db):
    order, data = _orden_partida(db)
    linea = order.products[0]

    from app.services.load_order_closure_service import LoadOrderClosureError

    with pytest.raises(LoadOrderClosureError, match="facturada hoy"):
        _cerrar(
            order,
            data,
            [
                {
                    "order_product": linea,
                    "quantity": 40.0,
                    "reason": "Demasiado",
                    "timing": "immediate",
                }
            ],
        )


def test_el_limite_de_la_parte_diferida_es_el_suyo(db):
    order, data = _orden_partida(db)
    linea = order.products[0]

    from app.services.load_order_closure_service import LoadOrderClosureError

    with pytest.raises(LoadOrderClosureError, match="facturar despues"):
        _cerrar(
            order,
            data,
            [
                {
                    "order_product": linea,
                    "quantity": 25.0,
                    "reason": "Demasiado",
                    "timing": "deferred",
                }
            ],
        )


def test_orden_sin_reparto_va_siempre_a_la_parte_de_hoy(db):
    """Sin dos presupuestos no hay nada que elegir: la devolucion va a la de hoy."""
    order, data = _orden_partida(db, hoy=CANTIDAD)
    linea = order.products[0]

    from app.models.budgets import Budget
    from app.models.load_orders import LoadOrderReturnLine

    cierre = _cerrar(
        order,
        data,
        [{"order_product": linea, "quantity": 4.0, "reason": "Envase danado"}],
    )

    linea_devolucion = LoadOrderReturnLine.get(LoadOrderReturnLine.closure == cierre)
    assert linea_devolucion.timing == Budget.TIMING_IMMEDIATE
    deferred = Budget.get_or_none(
        (Budget.load_order == order) & (Budget.timing == Budget.TIMING_DEFERRED)
    )
    assert deferred is None


def test_el_credito_conserva_las_dos_deudas_al_anular_la_devolucion(db):
    order, data = _orden_partida(db)
    linea = order.products[0]

    from app.services.load_order_return_credit_service import LoadOrderReturnCreditService
    from app.services.load_order_closure_service import LoadOrderClosureService

    cierre = _cerrar(
        order,
        data,
        [{"order_product": linea, "quantity": 5.0, "reason": "Hoy", "timing": "immediate"}],
    )
    servicio = LoadOrderReturnCreditService(current_user="issue585")
    reversals = servicio.reverse_for_closure(cierre)

    assert len(reversals) == 1
    # El credito es negativo; su reversa lo restaura, o sea que es positiva.
    assert reversals[0].total_amount > 0
    assert reversals[0].total_amount == 6050.0
