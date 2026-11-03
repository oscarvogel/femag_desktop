from peewee import CharField, DateField, ForeignKeyField, TextField

from app.models.base import BaseModel
from app.models.masters import Client


class ClientAgendaEntry(BaseModel):
    client = ForeignKeyField(Client, backref="agenda_entries", on_delete="RESTRICT")
    occurred_on = DateField(index=True)
    text = TextField()
    author = CharField()
