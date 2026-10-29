"""Estado durable de FEMAG Sync (#804).

La fabrica es la fuente de verdad. Estas tablas guardan el mapeo de IDs
globales, la cola de salida, la cola de entrada, los cursores y los conflictos
que requieren revision. No reemplazan los modelos de negocio: los referencian.
"""

from __future__ import annotations

from datetime import datetime, timezone

from peewee import CharField, DateTimeField, IntegerField, TextField

from app.models.audit import JSONTextField
from app.models.base import BaseModel


def utc_now_naive():
    """UTC sin tzinfo: SQLite y MySQL devuelven los campos de sync igual."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SyncEntityMap(BaseModel):
    """UUID estable por entidad local, sin tocar los IDs autoincrementales."""

    ENTITY_ORDER = "order"
    ENTITY_ORDER_LINE = "order_line"
    ENTITY_CLIENT = "client"
    ENTITY_DESTINATION = "destination"
    ENTITY_PALLET = "pallet"

    entity_type = CharField()
    local_id = CharField(max_length=64)
    global_uid = CharField(max_length=36, unique=True)
    local_version = IntegerField(default=1)
    last_published_version = IntegerField(null=True)

    class Meta:
        indexes = ((("entity_type", "local_id"), True),)


class SyncOutbox(BaseModel):
    """Evento local pendiente de enviar a la nube."""

    STATUS_PENDING = "pending"
    STATUS_SENT = "sent"
    STATUS_DEAD_LETTER = "dead_letter"

    event_id = CharField(max_length=36, unique=True)
    event_type = CharField()
    aggregate_type = CharField()
    aggregate_id = CharField(max_length=36)
    aggregate_version = IntegerField(default=1)
    idempotency_key = CharField(max_length=200, unique=True)
    payload = JSONTextField()
    occurred_at = DateTimeField(default=utc_now_naive)
    status = CharField(default=STATUS_PENDING)
    attempts = IntegerField(default=0)
    next_attempt_at = DateTimeField(null=True)
    last_error = TextField(null=True)
    sent_at = DateTimeField(null=True)

    class Meta:
        indexes = ((("status", "next_attempt_at"), False),)


class SyncInbox(BaseModel):
    """Evento recibido de la nube, deduplicado por ``event_id``."""

    STATUS_PENDING = "pending"
    STATUS_APPLIED = "applied"
    STATUS_CONFLICT = "conflict"
    STATUS_REJECTED = "rejected"

    event_id = CharField(max_length=36, unique=True)
    event_type = CharField()
    origin = CharField(default="cloud")
    aggregate_type = CharField()
    aggregate_id = CharField(max_length=36)
    aggregate_version = IntegerField(default=1)
    cursor_value = IntegerField(default=0)
    payload = JSONTextField()
    occurred_at = DateTimeField(null=True)
    status = CharField(default=STATUS_PENDING)
    attempts = IntegerField(default=0)
    last_error = TextField(null=True)
    received_at = DateTimeField(default=utc_now_naive)
    applied_at = DateTimeField(null=True)

    class Meta:
        indexes = ((("status", "cursor_value"), False),)


class SyncCursor(BaseModel):
    """Ultimo cursor confirmado por stream (factory o cloud)."""

    STREAM_FACTORY = "factory"
    STREAM_CLOUD = "cloud"
    STREAM_FACTORY_SNAPSHOT = "factory_snapshot"

    stream = CharField(max_length=32, unique=True)
    cursor_value = IntegerField(default=0)
    last_synced_at = DateTimeField(null=True)
    last_error = TextField(null=True)


class SyncConflict(BaseModel):
    """Evento que no se pudo aplicar y queda para revision manual."""

    STATUS_OPEN = "open"
    STATUS_RESOLVED = "resolved"
    STATUS_IGNORED = "ignored"

    event_id = CharField(max_length=36, unique=True)
    event_type = CharField()
    aggregate_type = CharField()
    aggregate_id = CharField(max_length=36)
    payload = JSONTextField()
    reason = TextField()
    status = CharField(default=STATUS_OPEN)
    resolution = TextField(null=True)
    resolved_at = DateTimeField(null=True)
    resolved_by = CharField(null=True)

    class Meta:
        indexes = ((("status", "created_at"), False),)

class SyncProjection(BaseModel):
    """Copia de lectura que la nube guarda de un recurso de fabrica."""

    RESOURCE_ORDER = "order"

    resource_type = CharField()
    resource_uid = CharField(max_length=36)
    qr_token = CharField(max_length=64, null=True, unique=True)
    order_number = IntegerField(null=True)
    status = CharField(null=True)
    version = IntegerField(default=1)
    payload = JSONTextField()
    source_updated_at = DateTimeField(null=True)
    published_at = DateTimeField(default=utc_now_naive)
    cancelled_at = DateTimeField(null=True)

    class Meta:
        indexes = ((("resource_type", "resource_uid"), True),)
