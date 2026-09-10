from __future__ import annotations

from peewee import CharField, DateTimeField, ForeignKeyField, IntegerField, TextField

from app.models.base import BaseModel
from app.models.security import User


class WhatsAppEnvio(BaseModel):
    """Auditoría funcional de envíos de documentos por WhatsApp."""

    tipo_documento = CharField(max_length=80)
    documento_id = CharField(max_length=120)
    destinatario = CharField(max_length=40)
    external_ref = CharField(max_length=300, unique=True)
    message_id = CharField(max_length=120, null=True, index=True)
    provider_message_id = CharField(max_length=180, null=True)
    estado = CharField(max_length=40, default="preparing", index=True)
    caption = TextField(null=True)
    nombre_archivo = CharField(max_length=255)
    mime_type = CharField(max_length=120, default="application/pdf")
    error = TextField(null=True)
    accepted_at = DateTimeField(null=True)
    delivered_at = DateTimeField(null=True)
    read_at = DateTimeField(null=True)
    failed_at = DateTimeField(null=True)
    usuario = ForeignKeyField(User, backref="whatsapp_envios", null=True)

    class Meta:
        table_name = "whatsapp_envios"
        indexes = (
            (("tipo_documento", "documento_id"), False),
            (("destinatario", "created_at"), False),
        )
