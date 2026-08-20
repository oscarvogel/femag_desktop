from peewee import BooleanField, CharField, DateField, FloatField, ForeignKeyField, TextField

from app.models.base import BaseModel
from app.models.load_orders import LoadOrder
from app.models.masters import Client
from app.models.payments import ClientPayment


class ClientAccountMovement(BaseModel):
    TYPE_OPENING_BALANCE = "opening_balance"
    TYPE_LOAD_ORDER = "load_order_documental"
    TYPE_LOAD_ORDER_REVERSAL = "load_order_documental_reversal"
    TYPE_PAYMENT = "payment"
    TYPE_PAYMENT_REVERSAL = "payment_reversal"
    TYPE_MANUAL_DEBIT = "manual_debit"
    TYPE_MANUAL_DEBIT_REVERSAL = "manual_debit_reversal"
    TYPE_MANUAL_CREDIT = "manual_credit"
    TYPE_MANUAL_CREDIT_REVERSAL = "manual_credit_reversal"
    TYPE_RETURN_CREDIT = "return_credit"
    TYPE_RETURN_CREDIT_REVERSAL = "return_credit_reversal"

    client = ForeignKeyField(Client, backref="account_movements")
    load_order = ForeignKeyField(LoadOrder, backref="account_movements", null=True)
    payment = ForeignKeyField(ClientPayment, backref="account_movements", null=True)
    movement_type = CharField()
    amount = FloatField(default=0)
    net_amount = FloatField(default=0)
    discount_amount = FloatField(default=0)
    vat_amount = FloatField(default=0)
    total_amount = FloatField(default=0)
    currency = CharField(default="ARS")
    movement_date = DateField(null=True)
    due_date = DateField(null=True)
    description = TextField()
    observations = TextField(null=True)
    source_ref = CharField()
    reference = CharField(null=True)
    is_reversal = BooleanField(default=False)
    reverses = ForeignKeyField("self", backref="reversal_movements", null=True)
    created_by = CharField(null=True)

    class Meta:
        indexes = ((("source_ref", "client", "movement_type", "is_reversal"), True),)
