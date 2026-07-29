from datetime import date

from peewee import CharField, DateField, DateTimeField, FloatField, ForeignKeyField, TextField

from app.models.base import BaseModel
from app.models.masters import Client


class ClientPayment(BaseModel):
    METHOD_CASH = "efectivo"
    METHOD_TRANSFER = "transferencia"
    METHOD_CHECK = "cheque"
    METHOD_OTHER = "otros"
    METHODS = (METHOD_CASH, METHOD_TRANSFER, METHOD_CHECK, METHOD_OTHER)

    STATUS_ACTIVE = "activo"
    STATUS_ANNULLED = "anulado"
    STATUSES = (STATUS_ACTIVE, STATUS_ANNULLED)

    receipt_number = CharField(unique=True)
    client = ForeignKeyField(Client, backref="payments")
    payment_date = DateField(default=date.today)
    amount = FloatField()
    method = CharField()
    reference = CharField(null=True)
    observations = TextField(null=True)
    created_by = CharField(null=True)
    status = CharField(default=STATUS_ACTIVE)
    annulled_at = DateTimeField(null=True)
    annulled_by = CharField(null=True)
    annulment_reason = TextField(null=True)
