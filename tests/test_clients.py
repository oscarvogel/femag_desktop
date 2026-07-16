import pytest


def test_client_service_creates_client_addresses_and_audits(db):
    from app.models.audit import AuditLog
    from app.models.masters import ClientAddress
    from app.services.client_service import ClientService

    service = ClientService(current_user="admin")
    client = service.create_client(
        name="Cliente FEMAG",
        cuit="30712345678",
        iva_condition="Responsable Inscripto",
        phone="3764",
        email="cliente@example.com",
        contact="Maria",
    )
    fiscal = service.add_address(client, "fiscal", "Misiones", "Posadas", "Calle 1")
    delivery = service.add_address(
        client, "entrega", "Misiones", "Obera", "Ruta 14", is_primary=True
    )

    assert fiscal.address_type == "fiscal"
    assert delivery.is_primary is True
    assert ClientAddress.select().where(ClientAddress.client == client).count() == 2
    assert AuditLog.select().where(AuditLog.module == "Clientes").count() == 3


def test_client_address_rules_are_enforced(db):
    from app.services.client_service import ClientService

    service = ClientService(current_user="admin")
    client = service.create_client("Cliente", "30700000009", "RI")
    service.add_address(client, "fiscal", "Misiones", "Posadas", "Fiscal")

    with pytest.raises(ValueError, match="domicilio fiscal"):
        service.add_address(client, "fiscal", "Misiones", "Obera", "Otro")

    first = service.add_address(client, "entrega", "Misiones", "A", "A", is_primary=True)
    second = service.add_address(client, "entrega", "Misiones", "B", "B", is_primary=True)
    first_refreshed = type(first).get_by_id(first.id)

    assert first_refreshed.is_primary is False
    assert second.is_primary is True


def test_shared_address_type_has_fiscal_and_delivery_functions():
    from app.models.masters import (
        client_address_has_delivery_function,
        client_address_has_fiscal_function,
        client_address_type_label,
    )

    assert client_address_type_label("fiscal") == "Fiscal"
    assert client_address_type_label("entrega") == "Entrega"
    assert client_address_type_label("fiscal_entrega") == "Fiscal / Entrega"
    assert client_address_has_fiscal_function("fiscal_entrega") is True
    assert client_address_has_delivery_function("fiscal_entrega") is True
    assert client_address_has_delivery_function("fiscal") is False


def test_shared_address_conflicts_with_an_existing_fiscal_address(db):
    from app.services.client_service import ClientService

    service = ClientService(current_user="admin")
    client = service.create_client("Cliente Compartido", "30700000123", "RI")
    service.add_address(client, "fiscal", "Misiones", "Posadas", "Fiscal")

    with pytest.raises(ValueError, match="ya tiene un domicilio fiscal"):
        service.add_address(client, "fiscal_entrega", "Misiones", "Posadas", "Compartido")


def test_fiscal_address_conflicts_with_an_existing_shared_address(db):
    from app.services.client_service import ClientService

    service = ClientService(current_user="admin")
    client = service.create_client("Cliente Compartido", "30700000124", "RI")
    shared = service.add_address(client, "fiscal_entrega", "Misiones", "Posadas", "Compartido")

    assert shared.is_primary is True
    with pytest.raises(ValueError, match="ya tiene un domicilio fiscal"):
        service.add_address(client, "fiscal", "Misiones", "Posadas", "Fiscal")


def test_editing_delivery_to_shared_respects_fiscal_uniqueness(db):
    from app.services.client_service import ClientService

    service = ClientService(current_user="admin")
    client = service.create_client("Cliente Edición", "30700000125", "RI")
    service.add_address(client, "fiscal", "Misiones", "Posadas", "Fiscal")
    delivery = service.add_address(client, "entrega", "Misiones", "Obera", "Entrega")

    with pytest.raises(ValueError, match="ya tiene un domicilio fiscal"):
        service.update_address(
            delivery,
            client=client,
            address_type="fiscal_entrega",
            province="Misiones",
            city="Obera",
            address="Entrega",
            active=True,
        )


def test_consolidation_keeps_referenced_delivery_address_id(db):
    from app.models.load_orders import LoadOrder
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Truck
    from app.services.client_service import ClientService

    client = Client.create(name="Cliente Referenciado", cuit="30700000126", iva_condition="RI")
    values = dict(client=client, province="Misiones", city="Posadas", address="Ruta", is_primary=True)
    fiscal = ClientAddress.create(address_type="fiscal", **values)
    delivery = ClientAddress.create(address_type="entrega", **values)
    carrier = Carrier.create(name="Transporte Referenciado")
    driver = Driver.create(name="Chofer Referenciado", carrier=carrier)
    truck = Truck.create(domain="REF126", carrier=carrier)
    order = LoadOrder.create(
        order_number=126,
        client=client,
        delivery_address=delivery,
        carrier=carrier,
        driver=driver,
        truck=truck,
    )

    shared = ClientService.consolidate_identical_fiscal_delivery(client)

    assert shared.id == delivery.id
    assert shared.address_type == "fiscal_entrega"
    assert ClientAddress.get_by_id(order.delivery_address_id).id == delivery.id
    assert ClientAddress.get_or_none(ClientAddress.id == fiscal.id) is None


def test_consolidation_preserves_pair_when_both_addresses_are_referenced(db):
    from app.models.load_orders import LoadOrder
    from app.models.masters import Carrier, Client, ClientAddress, Driver, Truck
    from app.services.client_service import ClientService

    client = Client.create(name="Cliente Dos Referencias", cuit="30700000127", iva_condition="RI")
    values = dict(client=client, province="Misiones", city="Posadas", address="Ruta", is_primary=True)
    fiscal = ClientAddress.create(address_type="fiscal", **values)
    delivery = ClientAddress.create(address_type="entrega", **values)
    carrier = Carrier.create(name="Transporte Dos Referencias")
    driver = Driver.create(name="Chofer Dos Referencias", carrier=carrier)
    truck = Truck.create(domain="REF127", carrier=carrier)
    for number, address in ((127, fiscal), (128, delivery)):
        LoadOrder.create(
            order_number=number,
            client=client,
            delivery_address=address,
            carrier=carrier,
            driver=driver,
            truck=truck,
        )

    assert ClientService.consolidate_identical_fiscal_delivery(client) is None
    assert ClientAddress.select().where(ClientAddress.client == client).count() == 2
