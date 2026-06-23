from peewee import BooleanField, CharField, FloatField, ForeignKeyField, TextField

from app.models.base import BaseModel


class Client(BaseModel):
    name = CharField()
    cuit = CharField(unique=True)
    iva_condition = CharField()
    phone = CharField(null=True)
    email = CharField(null=True)
    contact = CharField(null=True)
    active = BooleanField(default=True)


class ClientAddress(BaseModel):
    client = ForeignKeyField(Client, backref="addresses")
    address_type = CharField()
    province = CharField()
    city = CharField()
    address = CharField()
    is_primary = BooleanField(default=False)
    observations = TextField(null=True)


class Product(BaseModel):
    name = CharField(unique=True)
    unit = CharField()
    active = BooleanField(default=True)


class Driver(BaseModel):
    name = CharField(unique=True)
    document = CharField(null=True)
    phone = CharField(null=True)
    active = BooleanField(default=True)
    available = BooleanField(default=True)


class Carrier(BaseModel):
    name = CharField(unique=True)
    cuit = CharField(null=True)
    phone = CharField(null=True)
    active = BooleanField(default=True)


class Truck(BaseModel):
    domain = CharField(unique=True)
    carrier = ForeignKeyField(Carrier, backref="trucks", null=True)
    active = BooleanField(default=True)


class PalletType(BaseModel):
    type = CharField(unique=True)
    measure = CharField()
    weight = FloatField()
    active = BooleanField(default=True)


class OperationalService(BaseModel):
    name = CharField(unique=True)
    active = BooleanField(default=True)
