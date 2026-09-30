import json
from decimal import Decimal

from peewee import CharField, DateTimeField, TextField

from app.models.base import BaseModel, utc_now


def _json_default(value):
    """Serializa lo que ``json`` no sabe.

    Los importes monetarios son ``Decimal`` desde la migración a DECIMAL. Al
    AuditLog van como **texto**, no como float: convertir a float reintroduciría
    justo la pérdida de precisión que la migración elimina, y el registro de
    auditoría tiene que ser exacto.
    """
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError(
        f"Object of type {type(value).__name__} is not JSON serializable"
    )


class JSONTextField(TextField):
    def db_value(self, value):
        if value is None or isinstance(value, str):
            return value
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, default=_json_default
        )

    def python_value(self, value):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)


class AuditLog(BaseModel):
    user = CharField(null=True)
    occurred_at = DateTimeField(default=utc_now)
    module = CharField()
    action = CharField()
    record_ref = CharField(null=True)
    old_value = JSONTextField(null=True)
    new_value = JSONTextField(null=True)
    observation = TextField(null=True)
    workstation = CharField(null=True)
