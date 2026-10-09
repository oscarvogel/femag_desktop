"""Modificar un articulo con presupuestos ya generados (#585).

El presupuesto se rehace solo mientras la orden se puede editar. Acu se cubre el
recorrido completo: generar con una mercaderia, modificar el articulo, guardar y
volver a generar. Es el caso que reporto el operador, donde el documento se
quedaba con la mercaderia anterior.
"""
from decimal import Decimal

import pytest

from tests.conftest import _master_data

PRECIO = 29453.0


def _crear_orden(cantidad, cantidad_hoy=None, precio=PRECIO):
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
                        "cantidad_facturar_ahora": cantidad_hoy,
                        "precio_neto_unitario": precio,
                    }
                ],
            }
        ],
    )
    return order, data


def _modificar(order, data, cantidad, cantidad_hoy=None, precio=PRECIO):
    from app.services.load_order_service import LoadOrderService

    LoadOrderService(current_user="issue585").update_order(
        order,
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [
                    {
                        "product": data["product"],
                        "quantity": cantidad,
                        "cantidad_facturar_ahora": cantidad_hoy,
                        "precio_neto_unitario": precio,
                    }
                ],
            }
        ],
    )


def _presupuesto_inmediato(order):
    from app.models.budgets import Budget

    return Budget.get(
        (Budget.load_order == order) & (Budget.timing == Budget.TIMING_IMMEDIATE)
    )


def test_modificar_la_cantidad_rehace_el_presupuesto(db):
    from app.services.budget_service import BudgetService

    order, data = _crear_orden(50.0)
    service = BudgetService(current_user="issue585")
    service.ensure_for_load_order(order)
    assert _presupuesto_inmediato(order).items[0].quantity == pytest.approx(50.0)

    _modificar(order, data, 30.0)
    service.ensure_for_load_order(order)

    budget = _presupuesto_inmediato(order)
    assert budget.items[0].quantity == pytest.approx(30.0)
    assert budget.total_amount == pytest.approx(
        sum(float(item.total) for item in budget.items)
    )


def test_modificar_el_precio_rehace_el_presupuesto(db):
    from app.services.budget_service import BudgetService

    order, data = _crear_orden(50.0)
    service = BudgetService(current_user="issue585")
    service.ensure_for_load_order(order)
    total_inicial = _presupuesto_inmediato(order).total_amount

    _modificar(order, data, 50.0, precio=30000.0)
    service.ensure_for_load_order(order)

    budget = _presupuesto_inmediato(order)
    assert budget.total_amount != pytest.approx(total_inicial)
    assert budget.total_amount == pytest.approx(
        sum(float(item.total) for item in budget.items)
    )


def test_agregar_el_reparto_rehace_las_das_partes(db):
    """El caso del mostrador: se genera sin reparto y despues se reparte."""
    from app.models.budgets import Budget
    from app.services.budget_service import BudgetService

    order, data = _crear_orden(50.0)
    service = BudgetService(current_user="issue585")
    service.ensure_for_load_order(order)
    numero = _presupuesto_inmediato(order).budget_number

    _modificar(order, data, 50.0, cantidad_hoy=30.0)
    service.ensure_for_load_order(order)

    by_timing = {
        budget.timing: budget
        for budget in Budget.select().where(Budget.load_order == order)
    }
    assert by_timing["immediate"].items[0].quantity == pytest.approx(30.0)
    assert by_timing["deferred"].items[0].quantity == pytest.approx(20.0)
    suma = sum(float(b.items[0].quantity) for b in by_timing.values())
    assert suma == pytest.approx(50.0)
    # El numero del presupuesto rehecho no se consume: no queda un hueco.
    assert by_timing["immediate"].budget_number == numero


def test_cargar_un_renglon_nuevo_tambien_entra_al_presupuesto(db):
    from app.models.masters import Product
    from app.services.budget_service import BudgetService

    order, data = _crear_orden(50.0)
    service = BudgetService(current_user="issue585")
    service.ensure_for_load_order(order)
    otro = Product.create(name="Otro articulo", unit="unidad", precio_neto_base=1000.0)

    from app.services.load_order_service import LoadOrderService

    LoadOrderService(current_user="issue585").update_order(
        order,
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [
                    {
                        "product": data["product"],
                        "quantity": 50.0,
                        "precio_neto_unitario": PRECIO,
                    },
                    {"product": otro, "quantity": 7.0, "precio_neto_unitario": 1000.0},
                ],
            }
        ],
    )
    service.ensure_for_load_order(order)

    budget = _presupuesto_inmediato(order)
    cantidades = sorted(float(item.quantity) for item in budget.items)
    assert cantidades == [7.0, 50.0]
    assert budget.total_amount == pytest.approx(
        sum(float(item.total) for item in budget.items)
    )


def test_sin_tocar_la_orden_el_presupuesto_no_cambia(db):
    """Sin cambios en la orden el documento tiene que quedar igual."""
    from app.services.budget_service import BudgetService

    order, _data = _crear_orden(50.0)
    service = BudgetService(current_user="issue585")
    service.ensure_for_load_order(order)
    antes = Decimal(str(_presupuesto_inmediato(order).total_amount))

    service.ensure_for_load_order(order)

    assert Decimal(str(_presupuesto_inmediato(order).total_amount)) == antes
