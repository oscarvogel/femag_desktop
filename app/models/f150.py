from peewee import CharField, DateField, ForeignKeyField, IntegerField

from app.models.audit import JSONTextField
from app.models.base import BaseModel
from app.models.remittances import Remittance


class F150Batch(BaseModel):
    STATUS_GENERATED = "Generado"

    batch_number = CharField(unique=True)
    process_date = DateField()
    file_name = CharField()
    file_path = CharField()
    sha256 = CharField()
    remittance_count = IntegerField()
    detail_count = IntegerField()
    status = CharField(default=STATUS_GENERATED)
    created_by = CharField(null=True)


class F150BatchRemittance(BaseModel):
    batch = ForeignKeyField(F150Batch, backref="remittances", on_delete="CASCADE")
    remittance = ForeignKeyField(
        Remittance,
        backref="f150_inclusions",
        on_delete="RESTRICT",
        unique=True,
    )
    point_of_sale = CharField()
    physical_number = CharField()
    snapshot = JSONTextField()

    class Meta:
        indexes = (
            (("batch", "remittance"), True),
        )
