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
