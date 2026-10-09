"""El presupuesto no puede quedar viejo con la mercaderia anterior (#585).

Reproduce el caso reportado en produccion: se genera el presupuesto con la orden
sin reparto, despues se carga el reparto y se vuelve a generar. El documento ya
emitido se devolvia sin verificar, asi que una parte conservaba la cantidad
anterior y la nueva tomaba el residuo: los dos documentos juntos sumaban mas que
la mercaderia que sale del camion.
"""
from decimal import Decimal

import pytest

from tests.conftest import _complete_order_for_issue, _master_data

PRECIO = 29453.0
CANTIDAD = 50.0
HOY = 30.0
DESPUES = 20.0


def _orden(db):
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
                        "precio_neto_unitario": PRECIO,
                    }
                ],
            }
        ],
    )
    return order, data


def _cargar_reparto(order, data, hoy):
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
                        "quantity": CANTIDAD,
                        "cantidad_facturar_ahora": hoy,
                        "precio_neto_unitario": PRECIO,
                    }
                ],
            }
        ],
    )


def test_presupuesto_generado_antes_del_reparto_se_rehace(db):
    """El caso exacto del mostrador.

    Primero se genera el presupuesto con la orden entera. Despues se carga el
    reparto 30/20 y se genera de nuevo: la parte de hoy tiene que quedar en 30 y
    la diferida en 20, no 50 y 20.
    """
    from app.models.budgets import Budget
    from app.services.budget_service import BudgetService

    order, data = _orden(db)
    service = BudgetService(current_user="issue585")

    # Sin reparto: un solo presupuesto con la cantidad completa.
    service.ensure_for_load_order(order)
    budget_inicial = Budget.get(
        (Budget.load_order == order) & (Budget.timing == Budget.TIMING_IMMEDIATE)
    )
    numero = budget_inicial.budget_number
    assert budget_inicial.items[0].quantity == pytest.approx(50.0)

    _cargar_reparto(order, data, HOY)
    service.ensure_for_load_order(order)

    by_timing = {
        budget.timing: budget
        for budget in Budget.select().where(Budget.load_order == order)
    }
    assert set(by_timing) == {Budget.TIMING_IMMEDIATE, Budget.TIMING_DEFERRED}
    assert by_timing[Budget.TIMING_IMMEDIATE].items[0].quantity == pytest.approx(HOY)
    assert by_timing[Budget.TIMING_DEFERRED].items[0].quantity == pytest.approx(DESPUES)

    # Lo unico que no puede pasar: que los dos documentos sumen mas que el camion.
    suma = sum(float(budget.items[0].quantity) for budget in by_timing.values())
    assert suma == pytest.approx(CANTIDAD)


def test_rehacer_el_presupuesto_conserva_el_numero(db):
    from app.models.budgets import Budget
    from app.services.budget_service import BudgetService

    order, data = _orden(db)
    service = BudgetService(current_user="issue585")
    service.ensure_for_load_order(order)
    numero = Budget.get(
        (Budget.load_order == order) & (Budget.timing == Budget.TIMING_IMMEDIATE)
    ).budget_number

    _cargar_reparto(order, data, HOY)
    service.ensure_for_load_order(order)

    rehecho = Budget.get(
        (Budget.load_order == order) & (Budget.timing == Budget.TIMING_IMMEDIATE)
    )
    assert rehecho.budget_number == numero
    assert rehecho.status == Budget.STATUS_ACTIVE


def test_sin_reparto_se_genera_un_solo_presupuesto_con_el_total(db):
    from app.models.budgets import Budget
    from app.services.budget_service import BudgetService

    order, _data = _orden(db)
    BudgetService(current_user="issue585").ensure_for_load_order(order)

    budgets = list(Budget.select().where(Budget.load_order == order))
    assert len(budgets) == 1
    assert budgets[0].items[0].quantity == pytest.approx(CANTIDAD)
    # El total sale de los renglones del propio presupuesto.
    assert budgets[0].total_amount == pytest.approx(
        sum(float(item.total) for item in budgets[0].items)
    )


def test_cargar_y_quitar_el_reparto_no_deja_una_parte_vacia(db):
    """Si se saca el reparto, la parte diferida se anula en vez de quedar vacia."""
    from app.models.budgets import Budget
    from app.services.budget_service import BudgetService
    from app.services.load_order_service import LoadOrderService

    order, data = _orden(db)
    service = BudgetService(current_user="issue585")
    _cargar_reparto(order, data, HOY)
    service.ensure_for_load_order(order)

    # Se saca el reparto: la orden vuelve a facturarse entera.
    LoadOrderService(current_user="issue585").update_order(
        order,
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [
                    {
                        "product": data["product"],
                        "quantity": CANTIDAD,
                        "precio_neto_unitario": PRECIO,
                    }
                ],
            }
        ],
    )
    service.ensure_for_load_order(order)

    diferido = Budget.get_or_none(
        (Budget.load_order == order) & (Budget.timing == Budget.TIMING_DEFERRED)
    )
    assert diferido is not None
    assert diferido.status == Budget.STATUS_ANNULLED
    inmediato = Budget.get(
        (Budget.load_order == order) & (Budget.timing == Budget.TIMING_IMMEDIATE)
    )
    assert inmediato.items[0].quantity == pytest.approx(CANTIDAD)
    suma_items = sum(
        Decimal(str(item.total)) for item in inmediato.items
    )
    assert Decimal(str(inmediato.total_amount)) == suma_items


def test_orden_emitida_no_deja_presupuesto_desactualizado(db):
    """Con la orden emitida no se toca el documento: se corta con un error claro.

    Preferimos fallar a devolver importes que no son los de la mercaderia.
    """
    from app.models.budgets import Budget, BudgetItem
    from app.models.load_orders import LoadOrder
    from app.services.budget_service import BudgetService
    from app.services.load_order_operation_service import LoadOrderOperationService

    order, data = _orden(db)
    _complete_order_for_issue(order, current_user="issue585")
    emitted = LoadOrderOperationService(current_user="issue585").issue(order)
    emitted = LoadOrder.get_by_id(emitted.id)

    # Con la orden emitida el documento ya no se puede tocar. Se falsea el
    # detalle para simular un presupuesto desactualizado y se verifica que el
    # sistema corte en vez de devolver importes que no son los de la mercaderia.
    budget = Budget.get(
        (Budget.load_order == emitted) & (Budget.timing == Budget.TIMING_IMMEDIATE)
    )
    item = budget.items[0]
    item.quantity = 999.0
    item.total = 999.0 * PRECIO
    item.save(only=[BudgetItem.quantity, BudgetItem.total])

    with pytest.raises(ValueError, match="no coincide con la mercaderia"):
        BudgetService(current_user="issue585").ensure_for_load_order_client(
            emitted, data["client"], timing=Budget.TIMING_IMMEDIATE
        )
