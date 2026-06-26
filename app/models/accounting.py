from peewee import BooleanField, CharField, FloatField, ForeignKeyField, TextField

from app.models.base import BaseModel
from app.models.load_orders import LoadOrder
from app.models.masters import Client


class ClientAccountMovement(BaseModel):
    TYPE_LOAD_ORDER = "load_order_documental"
    TYPE_LOAD_ORDER_REVERSAL = "load_order_documental_reversal"

    client = ForeignKeyField(Client, backref="account_movements")
    load_order = ForeignKeyField(LoadOrder, backref="account_movements")
    movement_type = CharField()
    amount = FloatField(default=0)
    currency = CharField(default="ARS")
    description = TextField()
    source_ref = CharField()
    is_reversal = BooleanField(default=False)
    reverses = ForeignKeyField("self", backref="reversal_movements", null=True)
    created_by = CharField(null=True)

    class Meta:
        indexes = ((("load_order", "client", "movement_type", "is_reversal"), True),)
