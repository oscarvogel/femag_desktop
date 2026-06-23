from peewee import CharField, DateTimeField, IntegerField, TextField

from app.models.base import BaseModel, utc_now


class AppParameter(BaseModel):
    key = CharField(unique=True)
    value = TextField(null=True)


class NumberSequence(BaseModel):
    name = CharField(unique=True)
    current_number = IntegerField(default=0)


class ImportBatch(BaseModel):
    source_system = CharField()
    status = CharField(default="pending")
    started_at = DateTimeField(default=utc_now)
    finished_at = DateTimeField(null=True)
    summary = TextField(null=True)


class BackupLog(BaseModel):
    started_at = DateTimeField(default=utc_now)
    finished_at = DateTimeField(null=True)
    status = CharField()
    file_path = CharField(null=True)
    message = TextField(null=True)
