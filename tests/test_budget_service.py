from pytest import approx

from app.models.accounting import ClientAccountMovement
from app.models.budgets import Budget, BudgetItem
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
from app.services.account_ledger_service import AccountLedgerService
from app.services.budget_print_service import BudgetPrintService
from app.services.budget_service import BudgetService
from app.services.ledger_query_service import client_balance
from app.services.load_order_service import LoadOrderService


def _make_multi_client_order():
    iva = TipoIVA.iva_default()
    product_a = Product.create(
        name="Fecula presupuesto A",
        unit="bolsa",
        precio_neto_base=1000.0,
        tipo_iva=iva,
    )
    product_b = Product.create(
        name="Fecula presupuesto B",
        unit="bolsa",
        precio_neto_base=2000.0,
        tipo_iva=iva,
    )
    client_a = Client.create(
        name="Cliente Presupuesto A",
        cuit="30711111111",
        iva_condition="RI",
    )
    client_b = Client.create(
        name="Cliente Presupuesto B",
        cuit="30722222222",
        iva_condition="RI",
    )
    address_a = ClientAddress.create(
        client=client_a,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Destino A",
    )
    address_b = ClientAddress.create(
        client=client_b,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Destino B",
    )
    carrier = Carrier.create(name="Transportista presupuestos")
    driver = Driver.create(name="Chofer presupuestos", carrier=carrier)
    truck = Truck.create(domain="PRES01", carrier=carrier)
    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client_a,
                "delivery_address": address_a,
                "products": [{"product": product_a, "quantity": 10}],
            },
            {
                "client": client_b,
                "delivery_address": address_b,
                "products": [{"product": product_b, "quantity": 5}],
            },
        ],
        pallets=[],
    )
    return order, client_a, client_b, product_a, product_b


def test_load_order_creates_one_persistent_numbered_budget_per_client(db):
    order, client_a, client_b, product_a, product_b = _make_multi_client_order()
    service = BudgetService(current_user="admin")

    first = service.ensure_for_load_order(order)
    second = service.ensure_for_load_order(order)

    assert len(first) == 2
    assert [budget.id for budget in second] == [budget.id for budget in first]
    assert Budget.select().count() == 2
    assert {budget.budget_number for budget in first} == {1, 2}
    assert all(budget.origin == Budget.ORIGIN_LOAD_ORDER for budget in first)
    assert all(budget.load_order == order for budget in first)
    assert all(budget.load_order_reference == f"OC-{order.order_number:06d}" for budget in first)

    budget_a = Budget.get(Budget.client == client_a)
    budget_b = Budget.get(Budget.client == client_b)
    assert [item.product for item in budget_a.items] == [product_a]
    assert [item.product for item in budget_b.items] == [product_b]
    assert budget_a.total_amount == approx(10 * 1000 * 1.21)
    assert budget_b.total_amount == approx(5 * 2000 * 1.21)


def test_load_order_account_movements_reference_each_client_budget_without_duplicates(db):
    order, client_a, client_b, _product_a, _product_b = _make_multi_client_order()
    service = AccountLedgerService(current_user="admin")

    first = service.generate_for_load_order(order)
    second = service.generate_for_load_order(order)

    assert len(first) == 2
    assert len(second) == 2
    assert ClientAccountMovement.select().count() == 2
    for client in (client_a, client_b):
        movement = ClientAccountMovement.get(ClientAccountMovement.client == client)
        budget = Budget.get(Budget.client == client)
        assert movement.budget == budget
        assert movement.reference == budget.display_number
        assert movement.source_ref == f"Budget:{budget.id}"
        assert movement.total_amount == approx(budget.total_amount)
        assert client_balance(client) == approx(budget.total_amount)


def test_manual_budget_creates_debt_and_annulment_reverses_it(db):
    product = Product.create(name="Producto presupuesto manual", unit="bolsa")
    client = Client.create(
        name="Cliente Presupuesto Manual",
        cuit="30733333333",
        iva_condition="RI",
        dias_plazo_pago=15,
    )
    service = BudgetService(current_user="admin")

    budget = service.create_manual(
        client=client,
        items=[
            {
                "product": product,
                "quantity": 3,
                "unit": "bolsa",
                "unit_price": 1000,
                "discount_percentage": 10,
                "vat_percentage": 21,
            }
        ],
        observations="Caso especial",
    )

    expected_total = (3 * 1000 * 0.90) * 1.21
    assert budget.origin == Budget.ORIGIN_MANUAL
    assert budget.load_order_id is None
    assert budget.total_amount == approx(expected_total)
    assert BudgetItem.select().where(BudgetItem.budget == budget).count() == 1
    assert client_balance(client) == approx(expected_total)

    movement = ClientAccountMovement.get(ClientAccountMovement.budget == budget)
    assert movement.movement_type == ClientAccountMovement.TYPE_BUDGET_MANUAL
    assert movement.reference == budget.display_number
    assert movement.total_amount == approx(expected_total)

    service.annul_manual(budget)
    service.annul_manual(budget)
    budget = Budget.get_by_id(budget.id)
    assert budget.status == Budget.STATUS_ANNULLED
    assert client_balance(client) == approx(0)
    assert (
        ClientAccountMovement.select()
        .where(ClientAccountMovement.budget == budget)
        .count()
        == 2
    )


def test_budget_prints_individual_files_and_bundle(db, tmp_path):
    order, _client_a, _client_b, _product_a, _product_b = _make_multi_client_order()
    service = BudgetPrintService(current_user="admin")

    individual = service.export_for_load_order(order, tmp_path)
    bundle = service.export_bundle_for_load_order(order, tmp_path)

    assert len(individual) == 2
    assert all(path.exists() and path.stat().st_size > 0 for path in individual)
    assert {path.name for path in individual} == {
        "presupuesto_000001.pdf",
        "presupuesto_000002.pdf",
    }
    assert bundle.exists()
    assert bundle.name == f"presupuestos_OC-{order.order_number:06d}.pdf"
    assert bundle.stat().st_size > 0
    assert Budget.select().count() == 2
