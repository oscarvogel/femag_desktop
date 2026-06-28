import pytest


def _master_data():
    from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck

    client = Client.create(name="Cliente FEMAG", cuit="30712345678", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12",
        is_primary=True,
    )
    carrier = Carrier.create(name="Transporte Norte", cuit="30777777770")
    driver = Driver.create(name="Juan Perez", carrier=carrier, document="123")
    truck = Truck.create(domain="AB123CD", carrier=carrier)
    product = Product.create(name="Fecula de mandioca", unit="kg")
    other_product = Product.create(name="Almidon", unit="bolsa")
    pallet = PalletType.create(type="Pallet comun", measure="1x1", weight=12.5)
    return {
        "client": client,
        "address": address,
        "carrier": carrier,
        "driver": driver,
        "truck": truck,
        "product": product,
        "other_product": other_product,
        "pallet": pallet,
    }


def _multi_client_data():
    from app.models.masters import Client, ClientAddress, Product

    data = _master_data()
    other_client = Client.create(name="Cliente Sur", cuit="30999999999", iva_condition="RI")
    other_address = ClientAddress.create(
        client=other_client,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Ruta 14",
    )
    other_destination = ClientAddress.create(
        client=data["client"],
        address_type="entrega",
        province="Misiones",
        city="Eldorado",
        address="Ruta 12 km 1540",
    )
    third_product = Product.create(name="Glucosa", unit="bidon")
    data.update(
        {
            "other_client": other_client,
            "other_address": other_address,
            "other_destination": other_destination,
            "third_product": third_product,
        }
    )
    return data


def _valid_order_payload(data):
    return {
        "client": data["client"],
        "delivery_address": data["address"],
        "carrier": data["carrier"],
        "driver": data["driver"],
        "truck": data["truck"],
        "products": [{"product": data["product"], "quantity": 100}],
        "pallets": [],
    }


def test_create_load_order_with_products_pallets_blocks_driver_and_audits(db):
    from app.models.audit import AuditLog
    from app.models.load_orders import LoadOrder, LoadOrderPallet, LoadOrderProduct
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    order = LoadOrderService(current_user="admin").create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[
            {"product": data["product"], "quantity": 1000, "observations": "Bolsas nuevas"},
            {"product": data["other_product"], "quantity": 25, "unit": "bolsa"},
        ],
        pallets=[
            {
                "pallet_type": data["pallet"],
                "measure": "1x1",
                "weight": 12.5,
                "quantity": 10,
                "observations": "Buenos",
            }
        ],
        observations="Carga urgente",
    )

    refreshed_driver = type(data["driver"]).get_by_id(data["driver"].id)

    assert order.order_number == 1
    assert order.status == LoadOrder.STATUS_PENDING
    assert order.created_by == "admin"
    assert refreshed_driver.available is False
    assert LoadOrder.select().count() == 1
    assert LoadOrderProduct.select().where(LoadOrderProduct.order == order).count() == 2
    assert LoadOrderPallet.select().where(LoadOrderPallet.order == order).count() == 1
    assert AuditLog.select().where(AuditLog.module == "Ordenes de carga").count() >= 2


def test_create_load_order_with_one_client_and_multiple_products_in_destination(db):
    from app.models.load_orders import LoadOrderDestination, LoadOrderProduct
    from app.services.load_order_service import LoadOrderService

    data = _master_data()

    order = LoadOrderService(current_user="admin").create_order(
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [
                    {"product": data["product"], "quantity": 1000},
                    {"product": data["other_product"], "quantity": 25, "unit": "bolsa"},
                ],
            }
        ],
        pallets=[],
    )

    destination = LoadOrderDestination.get(LoadOrderDestination.order == order)
    products = list(LoadOrderProduct.select().where(LoadOrderProduct.destination == destination))

    assert order.client is None
    assert order.delivery_address is None
    assert destination.client == data["client"]
    assert destination.delivery_address == data["address"]
    assert [item.product.name for item in products] == ["Fecula de mandioca", "Almidon"]


def test_create_load_order_with_multiple_clients_destinations_and_products(db):
    from app.models.load_orders import LoadOrderDestination, LoadOrderProduct
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
                "products": [{"product": data["product"], "quantity": 1000}],
            },
            {
                "client": data["other_client"],
                "delivery_address": data["other_address"],
                "products": [
                    {"product": data["other_product"], "quantity": 40},
                    {"product": data["third_product"], "quantity": 6},
                ],
            },
        ],
        pallets=[],
    )

    destinations = list(LoadOrderDestination.select().where(LoadOrderDestination.order == order))

    assert [destination.client.name for destination in destinations] == ["Cliente FEMAG", "Cliente Sur"]
    assert [destination.delivery_address.city for destination in destinations] == ["Posadas", "Obera"]
    assert LoadOrderProduct.select().where(LoadOrderProduct.order == order).count() == 3


def test_create_load_order_allows_same_client_with_multiple_delivery_places(db):
    from app.models.load_orders import LoadOrderDestination
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
                "products": [{"product": data["product"], "quantity": 1000}],
            },
            {
                "client": data["client"],
                "delivery_address": data["other_destination"],
                "products": [{"product": data["other_product"], "quantity": 40}],
            },
        ],
        pallets=[],
    )

    cities = [
        destination.delivery_address.city
        for destination in LoadOrderDestination.select().where(LoadOrderDestination.order == order)
    ]

    assert cities == ["Posadas", "Eldorado"]


def test_create_load_order_rejects_destination_without_products(db):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()

    with pytest.raises(ValueError, match="cliente.*producto"):
        LoadOrderService(current_user="admin").create_order(
            carrier=data["carrier"],
            driver=data["driver"],
            truck=data["truck"],
            destinations=[
                {
                    "client": data["client"],
                    "delivery_address": data["address"],
                    "products": [],
                }
            ],
            pallets=[],
        )


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("client", "cliente"),
        ("delivery_address", "lugar de entrega"),
        ("carrier", "transportista"),
        ("truck", "camion"),
        ("driver", "chofer"),
    ],
)
def test_create_load_order_requires_header_entities(db, field, message):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    payload = _valid_order_payload(data)
    payload[field] = None

    with pytest.raises(ValueError, match=message):
        LoadOrderService(current_user="admin").create_order(**payload)


def test_create_load_order_requires_products(db):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    payload = _valid_order_payload(data)
    payload["products"] = []

    with pytest.raises(ValueError, match="producto"):
        LoadOrderService(current_user="admin").create_order(**payload)


def test_create_load_order_rejects_address_from_another_client(db):
    from app.models.masters import Client, ClientAddress
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    other_client = Client.create(name="Otro cliente", cuit="30999999999", iva_condition="RI")
    other_address = ClientAddress.create(
        client=other_client,
        address_type="entrega",
        province="Misiones",
        city="Obera",
        address="Ruta 14",
    )
    payload = _valid_order_payload(data)
    payload["delivery_address"] = other_address

    with pytest.raises(ValueError, match="cliente"):
        LoadOrderService(current_user="admin").create_order(**payload)


def test_create_load_order_rejects_truck_from_another_carrier(db):
    from app.models.masters import Carrier, Truck
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    other_carrier = Carrier.create(name="Transporte Sur")
    other_truck = Truck.create(domain="ZZ999ZZ", carrier=other_carrier)
    payload = _valid_order_payload(data)
    payload["truck"] = other_truck

    with pytest.raises(ValueError, match="camion.*transportista"):
        LoadOrderService(current_user="admin").create_order(**payload)


def test_create_load_order_rejects_driver_from_another_carrier(db):
    from app.models.masters import Carrier, Driver
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    other_carrier = Carrier.create(name="Transporte Sur")
    other_driver = Driver.create(name="Pedro Gomez", carrier=other_carrier)
    payload = _valid_order_payload(data)
    payload["driver"] = other_driver

    with pytest.raises(ValueError, match="chofer.*transportista"):
        LoadOrderService(current_user="admin").create_order(**payload)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("client", "cliente.*inactivo"),
        ("address", "lugar de entrega.*inactivo"),
        ("carrier", "transportista.*inactivo"),
        ("driver", "chofer.*inactivo"),
        ("truck", "camion.*inactivo"),
    ],
)
def test_create_load_order_rejects_inactive_master_data(db, field, message):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    payload = _valid_order_payload(data)
    data[field].active = False
    data[field].save()

    with pytest.raises(ValueError, match=message):
        LoadOrderService(current_user="admin").create_order(**payload)


def test_create_load_order_rejects_inactive_product(db):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    payload = _valid_order_payload(data)
    data["product"].active = False
    data["product"].save()

    with pytest.raises(ValueError, match="producto.*inactivo"):
        LoadOrderService(current_user="admin").create_order(**payload)


def test_create_load_order_rejects_invalid_order_date(db):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    payload = _valid_order_payload(data)
    payload["order_date"] = "2026-06-28"

    with pytest.raises(ValueError, match="fecha"):
        LoadOrderService(current_user="admin").create_order(**payload)


def test_update_pending_order_rejects_invalid_order_date(db):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin")
    order = service.create_order(**_valid_order_payload(data))

    with pytest.raises(ValueError, match="fecha"):
        service.update_order(order, date="2026-06-28")


def test_update_pending_order_rejects_inactive_delivery_address(db):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin")
    order = service.create_order(**_valid_order_payload(data))

    data["address"].active = False
    data["address"].save()

    with pytest.raises(ValueError, match="lugar de entrega.*inactivo"):
        service.update_order(
            order,
            destinations=[
                {
                    "client": data["client"],
                    "delivery_address": data["address"],
                    "products": [{"product": data["product"], "quantity": 50}],
                }
            ],
        )


@pytest.mark.parametrize(
    "products",
    [
        [{"product": None, "quantity": 100}],
        [{"product": "inexistente", "quantity": 100}],
        [{"quantity": 100}],
    ],
)
def test_create_load_order_rejects_invalid_product_reference(db, products):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    payload = _valid_order_payload(data)
    payload["products"] = products

    with pytest.raises(ValueError, match="producto"):
        LoadOrderService(current_user="admin").create_order(**payload)


@pytest.mark.parametrize("quantity", [0, -1])
def test_create_load_order_rejects_invalid_product_quantity(db, quantity):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    payload = _valid_order_payload(data)
    payload["products"] = [{"product": data["product"], "quantity": quantity}]

    with pytest.raises(ValueError, match="cantidad"):
        LoadOrderService(current_user="admin").create_order(**payload)


@pytest.mark.parametrize("quantity", [0, -1])
def test_create_load_order_rejects_invalid_pallet_quantity(db, quantity):
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    payload = _valid_order_payload(data)
    payload["pallets"] = [{"pallet_type": data["pallet"], "quantity": quantity}]

    with pytest.raises(ValueError, match="pallet"):
        LoadOrderService(current_user="admin").create_order(**payload)


def test_list_orders_returns_created_orders_newest_first(db):
    from datetime import date

    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin")
    first = service.create_order(**_valid_order_payload(data), order_date=date(2026, 6, 20))
    service.change_status(first, first.STATUS_CLOSED)
    second = service.create_order(**_valid_order_payload(data), order_date=date(2026, 6, 21))

    assert service.list_orders() == [second, first]
    assert service.list_orders(status=first.STATUS_CLOSED) == [first]
    assert service.list_orders(client=data["client"]) == [second, first]


def test_update_order_rejects_direct_status_changes(db):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin")
    order = service.create_order(**_valid_order_payload(data))

    with pytest.raises(ValueError, match="estado"):
        service.update_order(order, status=LoadOrder.STATUS_ANNULLED)

    assert type(order).get_by_id(order.id).status == LoadOrder.STATUS_PENDING


def test_update_pending_order_replaces_destinations_and_products(db):
    from app.models.load_orders import LoadOrderDestination, LoadOrderProduct
    from app.models.masters import Client, ClientAddress
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    other_client = Client.create(name="Cliente Editado", cuit="30700008888", iva_condition="RI")
    other_address = ClientAddress.create(
        client=other_client,
        address_type="entrega",
        province="Misiones",
        city="Eldorado",
        address="Ruta editada",
    )
    service = LoadOrderService(current_user="admin")
    order = service.create_order(**_valid_order_payload(data))

    updated = service.update_order(
        order,
        destinations=[
            {
                "client": data["client"],
                "delivery_address": data["address"],
                "products": [{"product": data["product"], "quantity": 100}],
            },
            {
                "client": other_client,
                "delivery_address": other_address,
                "products": [{"product": data["other_product"], "quantity": 25}],
            },
        ],
    )

    destinations = list(LoadOrderDestination.select().where(LoadOrderDestination.order == updated))
    products = list(LoadOrderProduct.select().where(LoadOrderProduct.order == updated))

    assert updated.id == order.id
    assert [destination.client.name for destination in destinations] == ["Cliente FEMAG", "Cliente Editado"]
    assert [product.product.name for product in products] == ["Fecula de mandioca", "Almidon"]
    assert [product.quantity for product in products] == [100, 25]


def test_blocked_driver_cannot_be_reused_until_order_is_closed_or_annulled(db):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin")
    first = service.create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 100}],
        pallets=[],
    )

    with pytest.raises(ValueError, match="chofer.*bloqueado"):
        service.create_order(
            client=data["client"],
            delivery_address=data["address"],
            carrier=data["carrier"],
            driver=data["driver"],
            truck=data["truck"],
            products=[{"product": data["product"], "quantity": 50}],
            pallets=[],
        )

    service.change_status(first, LoadOrder.STATUS_CLOSED)
    assert type(data["driver"]).get_by_id(data["driver"].id).available is True

    second = service.create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 50}],
        pallets=[],
    )
    service.annul_order(second, can_annul=True, reason="Cliente cancela")

    assert type(data["driver"]).get_by_id(data["driver"].id).available is True


def test_change_active_order_to_blocked_driver_is_rejected(db):
    from app.models.masters import Driver
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    other_driver = Driver.create(name="Pedro Gomez", carrier=data["carrier"], available=False)
    service = LoadOrderService(current_user="admin")
    order = service.create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 100}],
        pallets=[],
    )

    with pytest.raises(ValueError, match="chofer.*bloqueado"):
        service.update_order(order, driver=other_driver)


def test_available_drivers_excludes_blocked_active_drivers(db):
    from app.models.masters import Driver
    from app.services.driver_availability_service import DriverAvailabilityService
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    free_driver = Driver.create(name="Chofer libre", carrier=data["carrier"])
    LoadOrderService(current_user="admin").create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 100}],
        pallets=[],
    )

    names = [driver.name for driver in DriverAvailabilityService().available_drivers()]

    assert free_driver.name in names
    assert data["driver"].name not in names


def test_reopening_closed_order_requires_driver_availability(db):
    from app.models.load_orders import LoadOrder
    from app.services.load_order_service import LoadOrderService

    data = _master_data()
    service = LoadOrderService(current_user="admin")
    first = service.create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 100}],
        pallets=[],
    )
    service.change_status(first, LoadOrder.STATUS_CLOSED)
    service.create_order(
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        products=[{"product": data["product"], "quantity": 50}],
        pallets=[],
    )

    with pytest.raises(ValueError, match="chofer.*bloqueado"):
        service.change_status(first, LoadOrder.STATUS_PENDING)
