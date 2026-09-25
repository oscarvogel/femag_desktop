import pytest
from pytest import approx

from conftest import _complete_order_for_issue, _master_data


def _payload(data, *, cantidad_facturada=40):
    return {
        "carrier": data["carrier"],
        "driver": data["driver"],
        "truck": data["truck"],
        "destinations": [
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [
                    {
                        "product": data["product"],
                        "quantity": 100,
                        "cantidad_facturada": cantidad_facturada,
                        "precio_neto_unitario": 1000.0,
                        "descuento_porcentaje": 0.0,
                        "iva_porcentaje": 0.0,
                    }
                ],
            }
        ],
        "pallets": [],
    }


def test_issue_553_persists_billed_and_pending_quantity(db):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(**_payload(data))

    line = order.products.get()
    assert line.quantity == 100
    assert line.cantidad_facturada == 40
    assert line.quantity - line.cantidad_facturada == 60
    assert line.total == approx(100000.0)


def test_issue_553_defaults_to_all_billed_for_legacy_payload(db):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    payload = _payload(data)
    del payload["destinations"][0]["products"][0]["cantidad_facturada"]

    order = LoadOrderService(current_user="admin").create_order(**payload)

    line = order.products.get()
    assert line.cantidad_facturada == 100


@pytest.mark.parametrize("cantidad_facturada", [-1, 101])
def test_issue_553_rejects_invalid_billed_quantity(db, cantidad_facturada):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    with pytest.raises(ValueError, match="cantidad facturada"):
        LoadOrderService(current_user="admin").create_order(
            **_payload(data, cantidad_facturada=cantidad_facturada)
        )


def test_issue_553_budget_keeps_full_total_and_snapshots_split(db):
    from app.services.budget_print_service import BudgetPrintService
    from app.services.budget_service import BudgetService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(**_payload(data))
    budget = BudgetService(current_user="admin").ensure_for_load_order(order)[0]
    item = budget.items.get()

    assert budget.total_amount == approx(100000.0)
    assert item.quantity == 100
    assert item.cantidad_facturada == 40
    split = BudgetPrintService._billing_split_totals(budget)
    assert split["facturado"] == approx(40000.0)
    assert split["pendiente"] == approx(60000.0)
    assert split["total"] == approx(100000.0)


def test_issue_553_account_ledger_still_uses_full_order_total(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(**_payload(data))
    _complete_order_for_issue(order)
    LoadOrderOperationService(current_user="admin").issue(order)

    movement = ClientAccountMovement.get()
    assert movement.total_amount == approx(100000.0)
