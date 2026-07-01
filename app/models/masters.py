from peewee import BooleanField, CharField, FloatField, ForeignKeyField, IntegerField, TextField

from app.models.base import BaseModel


class TipoIVA(BaseModel):
    nombre = CharField(unique=True)
    porcentaje = FloatField()
    activo = BooleanField(default=True)

    @classmethod
    def iva_default(cls) -> "TipoIVA":
        return cls.get_or_create(nombre="IVA 21%", defaults={"porcentaje": 21.0, "activo": True})[0]


class Client(BaseModel):
    name = CharField()
    cuit = CharField(unique=True)
    iva_condition = CharField()
    phone = CharField(null=True)
    email = CharField(null=True)
    contact = CharField(null=True)
    active = BooleanField(default=True)
    descuento_porcentaje = FloatField(default=0.0)
    lista_precios = IntegerField(default=1)


class ClientAddress(BaseModel):
    client = ForeignKeyField(Client, backref="addresses")
    address_type = CharField()
    province = CharField()
    city = CharField()
    address = CharField()
    is_primary = BooleanField(default=False)
    observations = TextField(null=True)
    active = BooleanField(default=True)


class Product(BaseModel):
    name = CharField(unique=True)
    unit = CharField()
    active = BooleanField(default=True)
    precio_neto_base = FloatField(default=0.0)
    precio_lista_1 = FloatField(default=0.0)
    precio_lista_2 = FloatField(default=0.0)
    precio_lista_3 = FloatField(default=0.0)
    precio_lista_4 = FloatField(default=0.0)
    tipo_iva = ForeignKeyField(TipoIVA, backref="products", null=True)


class Carrier(BaseModel):
    name = CharField(unique=True)
    cuit = CharField(null=True)
    phone = CharField(null=True)
    active = BooleanField(default=True)


class Driver(BaseModel):
    name = CharField(unique=True)
    carrier = ForeignKeyField(Carrier, backref="drivers")
    document = CharField(null=True)
    phone = CharField(null=True)
    active = BooleanField(default=True)
    available = BooleanField(default=True)


class Truck(BaseModel):
    domain = CharField(unique=True)
    carrier = ForeignKeyField(Carrier, backref="trucks")
    active = BooleanField(default=True)


class PalletType(BaseModel):
    type = CharField(unique=True)
    measure = CharField()
    weight = FloatField()
    active = BooleanField(default=True)


class OperationalService(BaseModel):
    name = CharField(unique=True)
    active = BooleanField(default=True)
