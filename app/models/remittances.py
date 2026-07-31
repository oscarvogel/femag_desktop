from datetime import date

from peewee import CharField, DateField, DecimalField, ForeignKeyField, TextField

from app.models.base import BaseModel
from app.models.load_orders import LoadOrder
from app.models.masters import Carrier, Client, ClientAddress, Driver, Product


class Remittance(BaseModel):
    STATUS_DRAFT = "Borrador"
    STATUS_ISSUED = "Emitido"
    STATUS_ANNULLED = "Anulado"
    STATUSES = (STATUS_DRAFT, STATUS_ISSUED, STATUS_ANNULLED)

    remittance_number = CharField(unique=True)
    date = DateField(default=date.today)
    status = CharField(default=STATUS_DRAFT)
    client = ForeignKeyField(Client, backref="remittances")
    delivery_address = ForeignKeyField(ClientAddress, backref="remittances")
    source_order = ForeignKeyField(LoadOrder, backref="remittances", null=True, on_delete="SET NULL")
    carrier = ForeignKeyField(Carrier, backref="remittances", null=True, on_delete="SET NULL")
    driver = ForeignKeyField(Driver, backref="remittances", null=True, on_delete="SET NULL")
    client_name = CharField()
    client_cuit = CharField(null=True)
    delivery_address_text = CharField()
    carrier_name = CharField(null=True)
    driver_name = CharField(null=True)
    observations = TextField(null=True)
    created_by = CharField(null=True)
    updated_by = CharField(null=True)
    issued_by = CharField(null=True)
    annulled_by = CharField(null=True)
    annulment_reason = TextField(null=True)


class RemittanceItem(BaseModel):
    remittance = ForeignKeyField(Remittance, backref="items", on_delete="CASCADE")
    product = ForeignKeyField(Product, backref="remittance_items")
    product_name = CharField()
    quantity = DecimalField(max_digits=14, decimal_places=3)
    unit = CharField()
    observations = TextField(null=True)
