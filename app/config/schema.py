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

from app.models import ALL_MODELS


def ensure_runtime_schema(database) -> None:
    database.create_tables(ALL_MODELS, safe=True)
    for model in ALL_MODELS:
        _ensure_model_columns(database, model)


def _ensure_model_columns(database, model) -> None:
    table_name = model._meta.table_name
    existing_columns = {column.name for column in database.get_columns(table_name)}
    for field in model._meta.sorted_fields:
        if field.primary_key:
            continue
        column_name = field.column_name
        if column_name in existing_columns:
            continue
        database.execute_sql(
            f"ALTER TABLE `{_escape_identifier(table_name)}` "
            f"ADD COLUMN `{_escape_identifier(column_name)}` {_field_sql(field)} NULL"
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
