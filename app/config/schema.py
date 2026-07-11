from peewee import (
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    FloatField,
    ForeignKeyField,
    IntegerField,
    TextField,
)
from playhouse.migrate import SqliteMigrator, migrate

from app.models import ALL_MODELS


def ensure_runtime_schema(database) -> None:
    database.create_tables(ALL_MODELS, safe=True)
    for model in ALL_MODELS:
        _ensure_model_columns(database, model)


def _ensure_model_columns(database, model) -> None:
    table_name = model._meta.table_name
    existing_columns = {column.name: column for column in database.get_columns(table_name)}
    for field in model._meta.sorted_fields:
        if field.primary_key:
            continue
        column_name = field.column_name
        existing_column = existing_columns.get(column_name)
        if existing_column is None:
            database.execute_sql(
                f"ALTER TABLE `{_escape_identifier(table_name)}` "
                f"ADD COLUMN `{_escape_identifier(column_name)}` {_field_sql(field)} NULL"
            )
            _backfill_column_default(database, table_name, column_name, field)
            continue
        if field.null and existing_column.null is False:
            if _supports_modify_column(database):
                database.execute_sql(
                    f"ALTER TABLE `{_escape_identifier(table_name)}` "
                    f"MODIFY COLUMN `{_escape_identifier(column_name)}` {_field_sql(field)} NULL"
                )
            elif database.__class__.__name__ == "SqliteDatabase":
                _sqlite_drop_not_null(database, table_name, column_name)


def _backfill_column_default(database, table_name: str, column_name: str, field) -> None:
    default = field.default
    if default is not None and not callable(default):
        database.execute_sql(
            f"UPDATE `{_escape_identifier(table_name)}` "
            f"SET `{_escape_identifier(column_name)}` = ? "
            f"WHERE `{_escape_identifier(column_name)}` IS NULL",
            (int(default) if isinstance(default, bool) else default,),
        )


def _field_sql(field) -> str:
    if isinstance(field, ForeignKeyField):
        return "INTEGER"
    if isinstance(field, CharField):
        return f"VARCHAR({field.max_length or 255})"
    if isinstance(field, TextField):
        return "TEXT"
    if isinstance(field, BooleanField):
        return "BOOL"
    if isinstance(field, DateTimeField):
        return "DATETIME"
    if isinstance(field, DateField):
        return "DATE"
    if isinstance(field, FloatField):
        return "DOUBLE"
    if isinstance(field, IntegerField):
        return "INTEGER"
    return "TEXT"


def _escape_identifier(value: str) -> str:
    return value.replace("`", "``")


def _supports_modify_column(database) -> bool:
    return database.__class__.__name__ == "MySQLDatabase"


def _sqlite_drop_not_null(database, table_name: str, column_name: str) -> None:
    foreign_keys_were_enabled = bool(database.execute_sql("PRAGMA foreign_keys").fetchone()[0])
    if foreign_keys_were_enabled:
        database.execute_sql("PRAGMA foreign_keys = OFF")
    try:
        migrate(SqliteMigrator(database).drop_not_null(table_name, column_name))
    finally:
        if foreign_keys_were_enabled:
            database.execute_sql("PRAGMA foreign_keys = ON")
