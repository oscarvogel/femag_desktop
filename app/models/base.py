from datetime import datetime, timezone

from peewee import DateTimeField, Model

from app.config.database import database_proxy


def utc_now():
    return datetime.now(timezone.utc)


class BaseModel(Model):
    created_at = DateTimeField(default=utc_now)
    updated_at = DateTimeField(default=utc_now)

    class Meta:
        database = database_proxy

    def save(self, *args, **kwargs):
        self.updated_at = utc_now()
        return super().save(*args, **kwargs)
