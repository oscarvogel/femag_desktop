import json

from peewee import CharField, DateTimeField, TextField

from app.models.base import BaseModel, utc_now


class JSONTextField(TextField):
    def db_value(self, value):
        if value is None or isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

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
