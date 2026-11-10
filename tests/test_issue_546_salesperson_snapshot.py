"""#546 - snapshot historico del vendedor en ordenes y presupuestos."""

from conftest import _master_data, _valid_order_payload

from app.models.budgets import Budget
from app.models.masters import Client, Product, Salesperson
from app.services.budget_service import BudgetService
from app.services.load_order_service import LoadOrderService


def _assign(client: Client, salesperson: Salesperson) -> None:
    client.salesperson = salesperson
    client.save()


def test_order_destination_snapshots_salesperson_on_creation(db):
    seller = Salesperson.create(name="Vendedor Orden 546")
    data = _master_data()
    _assign(data["client"], seller)

    order = LoadOrderService(current_user="admin").create_order(
        **_valid_order_payload(data)
    )

    destination = order.destinations.get()
    assert destination.salesperson_id == seller.id


def test_order_destination_keeps_snapshot_after_client_reassignment_and_edit(db):
    seller_a = Salesperson.create(name="Vendedor A 546")
    seller_b = Salesperson.create(name="Vendedor B 546")
    data = _master_data()
    _assign(data["client"], seller_a)

    service = LoadOrderService(current_user="admin")
    order = service.create_order(**_valid_order_payload(data))

    _assign(data["client"], seller_b)
    service.update_order(
        order,
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [{"product": data["product"], "quantity": 100}],
            }
        ],
    )

    destination = order.destinations.get()
    assert destination.salesperson_id == seller_a.id


def test_order_destination_is_null_when_client_has_no_salesperson(db):
    data = _master_data()

    order = LoadOrderService(current_user="admin").create_order(
        **_valid_order_payload(data)
    )

    assert order.destinations.get().salesperson_id is None


def test_manual_budget_snapshots_current_salesperson(db):
    seller = Salesperson.create(name="Vendedor Presupuesto 546")
    client = Client.create(
        name="Cliente Presupuesto 546",
        cuit="30700090546",
        iva_condition="RI",
        salesperson=seller,
    )
    product = Product.create(name="Producto Presupuesto 546", unit="bolsa")

    budget = BudgetService(current_user="admin").create_manual(
        client=client,
        items=[{"product": product, "quantity": 1, "unit": "bolsa", "unit_price": 100}],
    )

    assert budget.salesperson_id == seller.id


def test_order_budget_uses_order_snapshot_not_current_client_salesperson(db):
    seller_a = Salesperson.create(name="Vendedor OC A 546")
    seller_b = Salesperson.create(name="Vendedor OC B 546")
    data = _master_data()
    _assign(data["client"], seller_a)
    order = LoadOrderService(current_user="admin").create_order(
        **_valid_order_payload(data)
    )

    _assign(data["client"], seller_b)
    budget = BudgetService(current_user="admin").ensure_for_load_order_client(
        order, data["client"]
    )

    assert budget is not None
    assert budget.salesperson_id == seller_a.id
    assert Budget.get_by_id(budget.id).salesperson_id == seller_a.id
