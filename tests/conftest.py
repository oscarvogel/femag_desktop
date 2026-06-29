import pytest
from peewee import SqliteDatabase


TEST_DB = SqliteDatabase(":memory:")


@pytest.fixture()
def db():
    from app.config.database import bind_database
    from app.models import ALL_MODELS

    bind_database(TEST_DB)
    TEST_DB.connect(reuse_if_open=True)
    TEST_DB.create_tables(ALL_MODELS)
    yield TEST_DB
    TEST_DB.drop_tables(ALL_MODELS)
    TEST_DB.close()


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
