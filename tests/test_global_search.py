from app.services.global_search_service import (
    global_search,
    search_carriers,
    search_clients,
    search_drivers,
    search_orders,
    search_trucks,
)


def test_search_orders_empty_query_returns_empty(db):
    assert search_orders("") == []


def test_search_clients_empty_query_returns_empty(db):
    assert search_clients("") == []


def test_global_search_returns_grouped_results(db):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService

    client = Client.create(name="Cliente ABC", cuit="30700000001", iva_condition="RI")
    ClientAddress.create(client=client, address_type="entrega", province="Misiones", city="Posadas", address="Ruta 12")
    carrier = Carrier.create(name="Transporte Rápido")
    driver = Driver.create(name="Carlos Gomez", carrier=carrier)
    truck = Truck.create(domain="AA111AA", carrier=carrier)
    product = Product.create(name="Fecula", unit="kg")
    LoadOrderService(current_user="admin").create_order(
        client=client, delivery_address=client.addresses.first(), carrier=carrier,
        driver=driver, truck=truck, products=[{"product": product, "quantity": 100}],
    )

    results = global_search("ABC")
    assert "ordenes" in results
    assert "clientes" in results


def test_search_clients_finds_by_name(db):
    from app.models.masters import Client

    Client.create(name="Cliente Test", cuit="30700000002", iva_condition="RI")
    results = search_clients("cliente")
    assert len(results) >= 1
    assert results[0]["type"] == "cliente"
    assert "Cliente Test" in results[0]["label"]


def test_search_clients_finds_by_cuit(db):
    from app.models.masters import Client

    Client.create(name="Cliente CUIT", cuit="30700000003", iva_condition="RI")
    results = search_clients("30700000003")
    assert len(results) >= 1
    assert results[0]["type"] == "cliente"


def test_search_orders_finds_by_carrier(db):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService

    carrier = Carrier.create(name="Transporte Rápido")
    client = Client.create(name="Cliente Test", cuit="30700000004", iva_condition="RI")
    ClientAddress.create(client=client, address_type="entrega", province="Misiones", city="Posadas", address="Ruta 12")
    driver = Driver.create(name="Juan Perez", carrier=carrier)
    truck = Truck.create(domain="BB222BB", carrier=carrier)
    product = Product.create(name="Fecula", unit="kg")
    LoadOrderService(current_user="admin").create_order(
        client=client, delivery_address=client.addresses.first(), carrier=carrier,
        driver=driver, truck=truck, products=[{"product": product, "quantity": 100}],
    )

    results = search_orders("Rápido")
    assert len(results) >= 1
    assert results[0]["type"] == "orden"


def test_search_orders_finds_by_driver(db):
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.services.load_order_service import LoadOrderService

    carrier = Carrier.create(name="Transporte Test")
    client = Client.create(name="Cliente Test", cuit="30700000005", iva_condition="RI")
    ClientAddress.create(client=client, address_type="entrega", province="Misiones", city="Posadas", address="Ruta 12")
    driver = Driver.create(name="Pedro Lopez", carrier=carrier)
    truck = Truck.create(domain="CC333CC", carrier=carrier)
    product = Product.create(name="Fecula", unit="kg")
    LoadOrderService(current_user="admin").create_order(
        client=client, delivery_address=client.addresses.first(), carrier=carrier,
        driver=driver, truck=truck, products=[{"product": product, "quantity": 100}],
    )

    results = search_orders("Lopez")
    assert len(results) >= 1


def test_global_search_no_match_returns_empty_groups(db):
    results = global_search("zzznoexiste999")
    assert results["ordenes"] == []
    assert results["clientes"] == []
    assert results["choferes"] == []
    assert results["transportistas"] == []
    assert results["camiones"] == []


def test_search_drivers_finds_by_name(db):
    from app.models.masters import Carrier, Driver

    carrier = Carrier.create(name="Transporte Test")
    Driver.create(name="Juan Perez", carrier=carrier)
    results = search_drivers("Juan")
    assert len(results) >= 1
    assert results[0]["type"] == "chofer"


def test_search_drivers_empty_query(db):
    assert search_drivers("") == []


def test_search_carriers_finds_by_name(db):
    from app.models.masters import Carrier

    Carrier.create(name="Transporte Rapido", cuit="30777777770")
    results = search_carriers("Rapido")
    assert len(results) >= 1
    assert results[0]["type"] == "transportista"


def test_search_carriers_empty_query(db):
    assert search_carriers("") == []


def test_search_trucks_finds_by_domain(db):
    from app.models.masters import Carrier, Truck

    carrier = Carrier.create(name="Transporte Test")
    Truck.create(domain="AB123CD", carrier=carrier)
    results = search_trucks("AB123")
    assert len(results) >= 1
    assert results[0]["type"] == "camion"


def test_search_trucks_empty_query(db):
    assert search_trucks("") == []
