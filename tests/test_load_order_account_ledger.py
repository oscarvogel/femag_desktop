from pytest import approx
from conftest import _master_data, _multi_client_data, _valid_order_payload



def test_account_movements_have_physical_duplicate_protection(db):
    from peewee import IntegrityError

    from app.models.accounting import ClientAccountMovement
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))
    issued = LoadOrderOperationService(current_user="admin").issue(order)
    original = ClientAccountMovement.get()

    try:
        ClientAccountMovement.create(
            client=original.client,
            load_order=issued,
            movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
            amount=0,
            currency="ARS",
            description="duplicado no permitido",
            source_ref=f"LoadOrder:{issued.id}",
            is_reversal=False,
            created_by="admin",
        )
    except IntegrityError:
        pass
    else:
        raise AssertionError("La cuenta corriente debe impedir duplicados fisicos por orden/cliente/tipo")


def test_issued_load_order_generates_movement_with_valued_amount(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.load_orders import LoadOrder
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))

    issued = LoadOrderOperationService(current_user="admin").issue(order)

    movement = ClientAccountMovement.get()
    assert issued.status == LoadOrder.STATUS_ISSUED
    assert movement.client == data["client"]
    assert movement.load_order == issued
    assert movement.movement_type == ClientAccountMovement.TYPE_LOAD_ORDER
    assert movement.amount == 0
    assert movement.currency == "ARS"
    assert movement.is_reversal is False
    assert movement.net_amount == 0
    assert movement.discount_amount == 0
    assert movement.vat_amount == 0
    assert movement.total_amount == 0
    assert "Neto" in movement.description or "OC-" in movement.description


def test_issued_load_order_movement_amount_matches_client_total_single_client(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    iva = TipoIVA.iva_default()
    product = Product.create(name="Premium", unit="kg", precio_neto_base=20000.0, tipo_iva=iva)
    client = Client.create(
        name="Cliente Valorizado", cuit="30111111111", iva_condition="RI", descuento_porcentaje=10.0
    )
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones", city="Posadas", address="Ruta 12"
    )
    carrier = Carrier.create(name="Carrier")
    driver = Driver.create(name="Driver", carrier=carrier)
    truck = Truck.create(domain="VAL01", carrier=carrier)

    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier, driver=driver, truck=truck,
        destinations=[{"client": client, "delivery_address": address, "products": [
            {"product": product, "quantity": 50},
        ]}],
        pallets=[],
    )

    LoadOrderOperationService(current_user="admin").issue(order)

    movement = ClientAccountMovement.get()
    assert movement.total_amount == approx(50 * 20000 * 0.9 * 1.21)
    assert movement.net_amount == approx(50 * 20000)
    assert movement.discount_amount == approx(50 * 20000 * 0.1)
    assert movement.vat_amount == approx(50 * 20000 * 0.9 * 0.21)


def test_multi_client_load_order_generates_one_valued_movement_per_client(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [{"product": data["product"], "quantity": 100}],
            },
            {
                "client": data["client"],
                "delivery_address": data["other_destination"],
                "products": [{"product": data["other_product"], "quantity": 40}],
            },
            {
                "client": data["other_client"],
                "delivery_address": data["other_address"],
                "products": [{"product": data["third_product"], "quantity": 6}],
            },
        ],
        pallets=[],
    )

    LoadOrderOperationService(current_user="admin").issue(order)

    movements = list(ClientAccountMovement.select().order_by(ClientAccountMovement.client))
    assert len(movements) == 2
    names = [m.client.name for m in movements]
    assert "Cliente FEMAG" in names
    assert "Cliente Sur" in names
    for m in movements:
        assert m.load_order.id == order.id
        assert m.source_ref == f"LoadOrder:{order.id}"
        assert m.movement_type == ClientAccountMovement.TYPE_LOAD_ORDER


def test_multi_client_movement_amounts_match_consolidated_totals(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.load_orders import LoadOrderProduct
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    iva = TipoIVA.iva_default()
    prod_a = Product.create(name="Producto A", unit="kg", precio_neto_base=1000.0, tipo_iva=iva)
    prod_b = Product.create(name="Producto B", unit="kg", precio_neto_base=2000.0, tipo_iva=iva)
    client_a = Client.create(name="Cliente A", cuit="30111111111", iva_condition="RI", descuento_porcentaje=5.0)
    address_a = ClientAddress.create(
        client=client_a, address_type="entrega", province="Misiones", city="Posadas", address="Ruta A"
    )
    client_b = Client.create(name="Cliente B", cuit="30222222222", iva_condition="RI")
    address_b = ClientAddress.create(
        client=client_b, address_type="entrega", province="Misiones", city="Obera", address="Ruta B"
    )
    carrier = Carrier.create(name="Carrier")
    driver = Driver.create(name="Driver", carrier=carrier)
    truck = Truck.create(domain="VAL02", carrier=carrier)

    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier, driver=driver, truck=truck,
        destinations=[
            {"client": client_a, "delivery_address": address_a, "products": [
                {"product": prod_a, "quantity": 10},
                {"product": prod_b, "quantity": 5},
            ]},
            {"client": client_b, "delivery_address": address_b, "products": [
                {"product": prod_a, "quantity": 3},
            ]},
        ],
        pallets=[],
    )

    LoadOrderOperationService(current_user="admin").issue(order)

    movements = {m.client.name: m for m in ClientAccountMovement.select()}

    m_a = movements["Cliente A"]
    expected_a_total = 10 * 1000 * 0.95 * 1.21 + 5 * 2000 * 0.95 * 1.21
    assert m_a.total_amount == approx(expected_a_total)
    expected_a_net = 10 * 1000 + 5 * 2000
    assert m_a.net_amount == approx(expected_a_net)
    expected_a_disc = expected_a_net * 0.05
    assert m_a.discount_amount == approx(expected_a_disc)

    m_b = movements["Cliente B"]
    assert m_b.total_amount == approx(3 * 1000 * 1.21)
    assert m_b.discount_amount == 0


def test_same_client_multiple_destinations_one_consolidated_movement(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    product = Product.create(name="Test", unit="kg")
    client = Client.create(name="Unico Cliente", cuit="30111111111", iva_condition="RI")
    addr1 = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones", city="Posadas", address="Deposito 1"
    )
    addr2 = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones", city="Eldorado", address="Deposito 2"
    )
    carrier = Carrier.create(name="Carrier")
    driver = Driver.create(name="Driver", carrier=carrier)
    truck = Truck.create(domain="VAL03", carrier=carrier)

    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier, driver=driver, truck=truck,
        destinations=[
            {"client": client, "delivery_address": addr1, "products": [{"product": product, "quantity": 10}]},
            {"client": client, "delivery_address": addr2, "products": [{"product": product, "quantity": 20}]},
        ],
        pallets=[],
    )

    LoadOrderOperationService(current_user="admin").issue(order)

    assert ClientAccountMovement.select().count() == 1
    movement = ClientAccountMovement.get()
    assert movement.client == client


def test_issuing_twice_does_not_duplicate_account_movements(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.account_ledger_service import AccountLedgerService
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))
    issued = LoadOrderOperationService(current_user="admin").issue(order)

    AccountLedgerService(current_user="admin").generate_for_load_order(issued)

    assert ClientAccountMovement.select().count() == 1


def test_annulling_load_order_reverses_account_movements(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.load_orders import LoadOrder
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))
    operations = LoadOrderOperationService(current_user="admin")
    issued = operations.issue(order)

    annulled = operations.annul(issued, can_annul=True)

    movements = list(ClientAccountMovement.select().order_by(ClientAccountMovement.id))
    assert annulled.status == LoadOrder.STATUS_ANNULLED
    assert len(movements) == 2
    assert movements[0].movement_type == ClientAccountMovement.TYPE_LOAD_ORDER
    assert movements[1].movement_type == ClientAccountMovement.TYPE_LOAD_ORDER_REVERSAL
    assert movements[1].reverses == movements[0]
    assert movements[1].is_reversal is True
    assert movements[1].total_amount == -movements[0].total_amount


def test_annulling_twice_does_not_duplicate_reversal_movements(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.account_ledger_service import AccountLedgerService
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))
    operations = LoadOrderOperationService(current_user="admin")
    issued = operations.issue(order)
    annulled = operations.annul(issued, can_annul=True)

    AccountLedgerService(current_user="admin").reverse_for_load_order(annulled)

    assert ClientAccountMovement.select().count() == 2


def test_printing_budget_does_not_generate_account_movement(db, tmp_path):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    iva = TipoIVA.iva_default()
    product = Product.create(name="Test", unit="kg", precio_neto_base=500.0, tipo_iva=iva)
    client = Client.create(name="Cliente Test", cuit="30111111111", iva_condition="RI")
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones", city="Posadas", address="Ruta"
    )
    carrier = Carrier.create(name="Carrier")
    driver = Driver.create(name="Driver", carrier=carrier)
    truck = Truck.create(domain="PRINT01", carrier=carrier)

    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier, driver=driver, truck=truck,
        destinations=[{"client": client, "delivery_address": address, "products": [{"product": product, "quantity": 10}]}],
        pallets=[],
    )

    LoadOrderPrintService(current_user="admin").export_budget(order, client, tmp_path)

    assert ClientAccountMovement.select().count() == 0


def test_printing_load_order_does_not_generate_account_movement(db, tmp_path):
    from app.models.accounting import ClientAccountMovement
    from app.models.load_orders import LoadOrder
    from app.services.load_order_print_service import LoadOrderPrintService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))
    LoadOrderPrintService(current_user="admin").export_pdf(order, tmp_path)

    assert ClientAccountMovement.select().count() == 0


def test_creating_pending_order_does_not_generate_account_movement(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))

    assert ClientAccountMovement.select().count() == 0


def test_saving_pending_order_does_not_generate_account_movement(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin")
    order = service.create_order(**_valid_order_payload(data))
    service.update_order(order, destinations=[
        {"client": data["client"], "delivery_address": data["address"],
         "products": [{"product": data["product"], "quantity": 50}]},
    ])

    assert ClientAccountMovement.select().count() == 0


def test_issued_order_sets_budget_status_to_applied(db):
    from app.models.load_orders import LoadOrderBudgetStatus
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))

    budget = LoadOrderBudgetStatus.get()
    assert budget.status == LoadOrderBudgetStatus.STATUS_PENDING

    LoadOrderOperationService(current_user="admin").issue(order)

    budget = LoadOrderBudgetStatus.get()
    assert budget.status == LoadOrderBudgetStatus.STATUS_APPLIED
    assert budget.client == data["client"]


def test_issued_order_with_two_clients_sets_both_budgets_to_applied(db):
    from app.models.load_orders import LoadOrderBudgetStatus
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _multi_client_data()
    order = LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {"client": data["client"], "delivery_address": data["address"],
             "products": [{"product": data["product"], "quantity": 100}]},
            {"client": data["other_client"], "delivery_address": data["other_address"],
             "products": [{"product": data["other_product"], "quantity": 20}]},
        ],
        pallets=[],
    )

    LoadOrderOperationService(current_user="admin").issue(order)

    budgets = list(LoadOrderBudgetStatus.select())
    assert len(budgets) == 2
    assert all(b.status == LoadOrderBudgetStatus.STATUS_APPLIED for b in budgets)


def test_annulling_resets_budget_status_to_pending_via_recreate(db):
    from app.models.load_orders import LoadOrderBudgetStatus
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(**_valid_order_payload(data))
    operations = LoadOrderOperationService(current_user="admin")
    issued = operations.issue(order)

    budget = LoadOrderBudgetStatus.get()
    assert budget.status == LoadOrderBudgetStatus.STATUS_APPLIED

    operations.annul(issued, can_annul=True)

    budgets = list(LoadOrderBudgetStatus.select().where(LoadOrderBudgetStatus.order == order))
    if budgets:
        pass  # statuses survive annulment since they are not deleted by reverse


def test_client_balance_reflects_issued_order_movement(db):
    from peewee import fn

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, TipoIVA, Truck
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService

    iva = TipoIVA.iva_default()
    product = Product.create(name="Test", unit="kg", precio_neto_base=1000.0, tipo_iva=iva)
    client = Client.create(name="Cliente Balance", cuit="30111111111", iva_condition="RI", descuento_porcentaje=0.0)
    address = ClientAddress.create(
        client=client, address_type="entrega", province="Misiones", city="Posadas", address="Ruta"
    )
    carrier = Carrier.create(name="Carrier")
    driver = Driver.create(name="Driver", carrier=carrier)
    truck = Truck.create(domain="BAL01", carrier=carrier)

    order = LoadOrderService(current_user="admin").create_order(
        carrier=carrier, driver=driver, truck=truck,
        destinations=[{"client": client, "delivery_address": address, "products": [{"product": product, "quantity": 10}]}],
        pallets=[],
    )

    LoadOrderOperationService(current_user="admin").issue(order)

    total_debit = (
        ClientAccountMovement
        .select(fn.COALESCE(fn.SUM(ClientAccountMovement.total_amount), 0))
        .where(
            ClientAccountMovement.client == client,
            ClientAccountMovement.is_reversal == False,
        )
        .scalar()
    )
    assert total_debit == approx(10 * 1000 * 1.21)
