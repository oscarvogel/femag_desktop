from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from importlib import import_module
from pkgutil import iter_modules

from peewee import CharField, DateTimeField, Model

from app.config.database import database_proxy
import app.migrations


Migration = tuple[str, Callable]


class SchemaMigration(Model):
    migration_id = CharField(unique=True)
    applied_at = DateTimeField(default=lambda: datetime.now(timezone.utc))

    class Meta:
        database = database_proxy
        table_name = "schema_migrations"


class MigrationRunner:
    def __init__(self, db, migrations: list[Migration] | None = None):
        self.db = db
        self.migrations = migrations if migrations is not None else self._discover_migrations()

    def run_pending(self) -> list[str]:
        self.db.create_tables([SchemaMigration], safe=True)
        applied = {row.migration_id for row in SchemaMigration.select()}
        applied_now = []
        for migration_id, migrate in self.migrations:
            if migration_id in applied:
                continue
            migrate(self.db)
            SchemaMigration.create(migration_id=migration_id)
            applied_now.append(migration_id)
        return applied_now

    def _discover_migrations(self) -> list[Migration]:
        discovered = []
        for module_info in iter_modules(app.migrations.__path__):
            if not module_info.name[0].isdigit():
                continue
            module = import_module(f"app.migrations.{module_info.name}")
            discovered.append((module.MIGRATION_ID, module.migrate))
        return sorted(discovered, key=lambda item: item[0])
