from datetime import date

from peewee import CharField, DateField, FloatField, ForeignKeyField, TextField

from app.models.base import BaseModel
from app.models.masters import Client


class ClientPayment(BaseModel):
    METHOD_CASH = "efectivo"
    METHOD_TRANSFER = "transferencia"
    METHOD_CHECK = "cheque"
    METHODS = (METHOD_CASH, METHOD_TRANSFER, METHOD_CHECK)

    receipt_number = CharField(unique=True)
    client = ForeignKeyField(Client, backref="payments")
    payment_date = DateField(default=date.today)
    amount = FloatField()
    method = CharField()
    reference = CharField(null=True)
    observations = TextField(null=True)
    created_by = CharField(null=True)
