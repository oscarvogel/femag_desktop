from datetime import date

from peewee import BooleanField, CharField, DateField, ForeignKeyField, IntegerField, TextField

from app.models.base import BaseModel
from app.models.masters import Carrier, Client, Driver, Product, Truck


class LoadOrder(BaseModel):
    STATUS_PENDING = "Pendiente"
    STATUS_ISSUED = "Emitida"
    STATUS_CLOSED = "Cerrada"
    STATUS_ANNULLED = "Anulada"
    ACTIVE_STATUSES = (STATUS_PENDING, STATUS_ISSUED)
    FINAL_STATUSES = (STATUS_CLOSED, STATUS_ANNULLED)

    order_number = IntegerField(unique=True)
    date = DateField(default=date.today)
    header_client = ForeignKeyField(Client, backref="load_orders", null=True)
    header_client_text = CharField(null=True)
    destination = CharField()
    carrier = ForeignKeyField(Carrier, backref="load_orders")
    driver = ForeignKeyField(Driver, backref="load_orders")
    truck = ForeignKeyField(Truck, backref="load_orders")
    vehicle_clean_and_suitable = BooleanField(default=True)
    status = CharField(default=STATUS_PENDING)
    observations = TextField(null=True)
    created_by = CharField(null=True)
    updated_by = CharField(null=True)

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES


class LoadOrderLine(BaseModel):
    order = ForeignKeyField(LoadOrder, backref="lines", on_delete="CASCADE")
    client = ForeignKeyField(Client, backref="load_order_lines", null=True)
    recipient_text = CharField(null=True)
    destination_text = CharField(null=True)
    product = ForeignKeyField(Product, backref="load_order_lines", null=True)
    product_detail = CharField(null=True)
    bags_25kg = IntegerField(default=0)
    bags_10kg = IntegerField(default=0)
    pack = IntegerField(default=0)
    pallet = IntegerField(default=0)
    lot_number = CharField(null=True)
    production_date = DateField(null=True)
    observations = TextField(null=True)


class LoadOrderStatusHistory(BaseModel):
    order = ForeignKeyField(LoadOrder, backref="status_history", on_delete="CASCADE")
    old_status = CharField(null=True)
    new_status = CharField()
    user = CharField(null=True)
    observation = TextField(null=True)
