from datetime import date

from peewee import (
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    FloatField,
    ForeignKeyField,
    TextField,
)

from app.models.base import BaseModel
from app.models.load_orders import LoadOrderClosure
from app.models.masters import Client


class PaymentMethod(BaseModel):
    code = CharField(unique=True)
    name = CharField()
    active = BooleanField(default=True)
    sort_order = FloatField(default=0)


class ClientPayment(BaseModel):
    # Constantes legacy conservadas para compatibilidad con integraciones/tests existentes.
    METHOD_CASH = "efectivo"
    METHOD_TRANSFER = "transferencia"
    METHOD_CHECK = "cheque"
    METHOD_RETENTION = "retenciones_percepciones"
    METHOD_HOLISTOR = "holistor"
    METHOD_OTHER = "otros"
    METHODS = (
        METHOD_CASH,
        METHOD_TRANSFER,
        METHOD_CHECK,
        METHOD_RETENTION,
        METHOD_HOLISTOR,
        METHOD_OTHER,
    )

    STATUS_ACTIVE = "activo"
    STATUS_ANNULLED = "anulado"
    STATUSES = (STATUS_ACTIVE, STATUS_ANNULLED)

    receipt_number = CharField(unique=True)
    client = ForeignKeyField(Client, backref="payments")
    closure = ForeignKeyField(LoadOrderClosure, backref="payments", null=True)
    payment_date = DateField(default=date.today)
    amount = FloatField()
    # Campos legacy: se mantienen para pagos históricos y compatibilidad.
    # En pagos compuestos guardan el primer medio y su referencia cuando corresponde.
    method = CharField()
    reference = CharField(null=True)
    observations = TextField(null=True)
    created_by = CharField(null=True)
    status = CharField(default=STATUS_ACTIVE)
    annulled_at = DateTimeField(null=True)
    annulled_by = CharField(null=True)
    annulment_reason = TextField(null=True)


class ClientPaymentDetail(BaseModel):
    payment = ForeignKeyField(ClientPayment, backref="details", on_delete="CASCADE")
    payment_method = ForeignKeyField(PaymentMethod, backref="payment_details")
    amount = FloatField()
    reference = CharField(null=True)
    observations = TextField(null=True)
    sequence = FloatField(default=1)

    class Meta:
        indexes = ((('payment', 'sequence'), True),)
