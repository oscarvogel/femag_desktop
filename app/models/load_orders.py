from datetime import date

from peewee import CharField, DateField, FloatField, ForeignKeyField, IntegerField, TextField

from app.models.base import BaseModel
from app.models.masters import Carrier, Client, ClientAddress, Driver, PalletType, Product, Truck


class LoadOrder(BaseModel):
    STATUS_DRAFT = "Borrador"
    STATUS_PENDING = STATUS_DRAFT
    STATUS_ISSUED = "Emitida"
    STATUS_CLOSED = "Cerrada"
    STATUS_ANNULLED = "Anulada"
    ACTIVE_STATUSES = (STATUS_PENDING, STATUS_ISSUED)
    FINAL_STATUSES = (STATUS_CLOSED, STATUS_ANNULLED)

    order_number = IntegerField(unique=True)
    date = DateField(default=date.today)
    client = ForeignKeyField(Client, backref="load_orders")
    delivery_address = ForeignKeyField(ClientAddress, backref="load_orders")
    carrier = ForeignKeyField(Carrier, backref="load_orders")
    driver = ForeignKeyField(Driver, backref="load_orders")
    truck = ForeignKeyField(Truck, backref="load_orders")
    status = CharField(default=STATUS_PENDING)
    observations = TextField(null=True)
    created_by = CharField(null=True)
    updated_by = CharField(null=True)

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES


class LoadOrderProduct(BaseModel):
    order = ForeignKeyField(LoadOrder, backref="products", on_delete="CASCADE")
    product = ForeignKeyField(Product, backref="load_order_details")
    quantity = FloatField()
    unit = CharField()
    observations = TextField(null=True)


class LoadOrderPallet(BaseModel):
    order = ForeignKeyField(LoadOrder, backref="pallets", on_delete="CASCADE")
    pallet_type = ForeignKeyField(PalletType, backref="load_order_details")
    measure = CharField()
    weight = FloatField()
    quantity = IntegerField()
    observations = TextField(null=True)


class LoadOrderStatusHistory(BaseModel):
    order = ForeignKeyField(LoadOrder, backref="status_history", on_delete="CASCADE")
    old_status = CharField(null=True)
    new_status = CharField()
    user = CharField(null=True)
    observation = TextField(null=True)
