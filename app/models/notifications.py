from peewee import CharField, DateTimeField, ForeignKeyField, IntegerField

from app.models.base import BaseModel
from app.models.security import User


class AvisoLectura(BaseModel):
    user = ForeignKeyField(User, backref="avisos_lectura", on_delete="CASCADE")
    tipo = CharField()  # e.g. "orden_sin_cierre", "deuda_vencida", "producto_revision"
    referencia_id = IntegerField(null=True)
    leido_at = DateTimeField(null=True)
    oculto_hasta = DateTimeField(null=True)

    class Meta:
        indexes = (
            (("user", "tipo", "referencia_id"), True),
        )
