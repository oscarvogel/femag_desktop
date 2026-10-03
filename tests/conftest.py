import pytest
from peewee import SqliteDatabase


TEST_DB = SqliteDatabase(":memory:")


@pytest.fixture(autouse=True)
def _isolate_femag_env(monkeypatch, tmp_path):
    """Aisla ``FEMAG_*`` del entorno real para que los tests sean deterministas.

    ``app.config.settings.load_settings`` hace ``load_dotenv(env_file, override=True)``
    con el archivo apuntado por ``FEMAG_ENV_FILE`` (o ``.env`` del CWD si no está).
    Los tests que cargan sus valores vía archivo .env (p. ej. ``test_config.py``)
    terminan escribiendo ``FEMAG_SQLITE_PATH`` / ``FEMAG_DEMO`` en ``os.environ``,
    pero ``monkeypatch`` solo rastrea lo que se setea explícitamente con
    ``monkeypatch.setenv`` — no lo que ``load_dotenv`` deja como side-effect.
    Eso filtra vars entre tests y rompe determinismo.

    Esta fixture autouse, por defecto, apunta ``FEMAG_ENV_FILE`` a un archivo
    inexistente (en el ``tmp_path`` del test) y limpia las ``FEMAG_*`` típicas.
    Los tests que necesitan un archivo real o vars específicas las setean con
    ``monkeypatch.setenv`` dentro de su cuerpo; ``monkeypatch`` restaura todo
    al terminar.
    """
    non_existent_env = tmp_path / "missing.env"
    monkeypatch.setenv("FEMAG_ENV_FILE", str(non_existent_env))
    for var in (
        "FEMAG_DB_ENGINE",
        "FEMAG_SQLITE_PATH",
        "FEMAG_SECURE_CONFIG",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


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


def _complete_order_for_issue(order, current_user="admin"):
    from app.services.load_order_service import LoadOrderService

    allocations = []
    for line in order.products:
        product = line.product
        if product.peso_unitario_kg == 0:
            product.peso_unitario_kg = 1
            product.save()
        allocations.append(
            {
                "client": line.destination.client,
                "delivery_address": line.destination.delivery_address,
                "product": product,
                "quantity": line.quantity,
            }
        )
    LoadOrderService(current_user=current_user).update_order(
        order,
        pallets=[{"sequence": 1, "pallet_type": None, "allocations": allocations}],
    )
    return order
