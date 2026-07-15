from decimal import Decimal

import pytest
from peewee import IntegrityError


def test_base_models_create_expected_records(db):
    from app.models.masters import Client, Product
    from app.models.security import User, UserProfile

    profile = UserProfile.create(name="Administrador")
    user = User.create(username="admin", password_hash="hash", profile=profile)
    client = Client.create(name="FEMAG", cuit="30700000001", iva_condition="RI")
    product = Product.create(name="Fecula de mandioca", unit="kg")

    assert user.profile.name == "Administrador"
    assert client.active is True
    assert product.active is True


def test_unique_business_keys_are_enforced(db):
    from app.models.masters import Carrier, Client, Truck

    Client.create(name="Cliente A", cuit="30111111110", iva_condition="RI")
    carrier = Carrier.create(name="Transporte Norte")
    Truck.create(domain="AA123BB", carrier=carrier)

    with pytest.raises(IntegrityError):
        Client.create(name="Duplicado", cuit="30111111110", iva_condition="RI")
    with pytest.raises(IntegrityError):
        Truck.create(domain="AA123BB", carrier=carrier)


def test_product_weight_defaults_to_zero(db):
    from app.models.masters import Product

    product = Product.create(name="Articulo sin peso", unit="unidad")

    assert product.peso_unitario_kg == Decimal("0.000")


def test_pallet_allocation_snapshots_weight_and_calculates_kg(db):
    from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderPallet, LoadOrderPalletAllocation
    from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck

    client = Client.create(name="Cliente peso", cuit="30700000009", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12",
    )
    carrier = Carrier.create(name="Transporte peso")
    driver = Driver.create(name="Chofer peso", carrier=carrier)
    truck = Truck.create(domain="KG123AA", carrier=carrier)
    product = Product.create(
        name="Bolsa 25,5 kg",
        unit="bolsa",
        peso_unitario_kg=Decimal("25.500"),
    )
    pallet_type = PalletType.create(type="Pallet prueba", measure="1x1", weight=0)
    order = LoadOrder.create(order_number=99, carrier=carrier, driver=driver, truck=truck)
    destination = LoadOrderDestination.create(order=order, client=client, delivery_address=address)
    pallet = LoadOrderPallet.create(
        order=order,
        pallet_type=pallet_type,
        sequence=1,
        measure="1x1",
        weight=0,
        quantity=1,
    )

    allocation = LoadOrderPalletAllocation.create(
        pallet=pallet,
        destination=destination,
        product=product,
        quantity=Decimal("12.000"),
        peso_unitario_kg=product.peso_unitario_kg,
    )

    assert allocation.kilos == Decimal("306.000")
    assert pallet.kilos == Decimal("306.000")
