from peewee import (
    BooleanField,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
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
    if hasattr(database, "atomic"):
        _normalize_legacy_pallet_rows(database)
        _consolidate_shared_client_addresses(database)
    if hasattr(database, "get_indexes"):
        _ensure_pallet_sequence_index(database)
    _ensure_sqlite_index_integrity(database)


def _consolidate_shared_client_addresses(database) -> None:
    from app.models.masters import Client
    from app.services.client_service import ClientService

    with database.atomic():
        for client in Client.select().order_by(Client.id):
            ClientService.consolidate_identical_fiscal_delivery(client)


def _ensure_sqlite_index_integrity(database) -> None:
    if database.__class__.__name__ != "SqliteDatabase":
        return
    issues = [row[0] for row in database.execute_sql("PRAGMA integrity_check").fetchall()]
    if issues == ["ok"]:
        return
    if issues and all("index" in issue.lower() for issue in issues):
        database.execute_sql("REINDEX")
        issues = [row[0] for row in database.execute_sql("PRAGMA integrity_check").fetchall()]
        if issues == ["ok"]:
            return
    summary = "; ".join(issues[:3])
    raise RuntimeError(f"La base SQLite no supera integrity_check: {summary}")


def _ensure_pallet_sequence_index(database) -> None:
    table_name = "loadorderpallet"
    if any(
        index.unique and set(index.columns) == {"order_id", "sequence"}
        for index in database.get_indexes(table_name)
    ):
        return
    database.execute_sql(
        "CREATE UNIQUE INDEX `loadorderpallet_order_id_sequence` "
        "ON `loadorderpallet` (`order_id`, `sequence`)"
    )


def _normalize_legacy_pallet_rows(database) -> None:
    from app.models.load_orders import LoadOrderPallet

    order_ids = [
        row.order_id
        for row in LoadOrderPallet.select(LoadOrderPallet.order).distinct()
    ]
    if not order_ids:
        return
    with database.atomic():
        for order_id in order_ids:
            rows = list(
                LoadOrderPallet.select()
                .where(LoadOrderPallet.order == order_id)
                .order_by(LoadOrderPallet.id)
            )
            expanded_rows = []
            for temporary_sequence, row in enumerate(rows, start=1):
                original_quantity = max(int(row.quantity or 1), 1)
                row.sequence = -temporary_sequence
                row.quantity = 1
                row.save()
                expanded_rows.append(row)
                for _ in range(1, original_quantity):
                    expanded_rows.append(
                        LoadOrderPallet.create(
                            order=order_id,
                            pallet_type=row.pallet_type,
                            sequence=-(len(rows) + len(expanded_rows)),
                            measure=row.measure,
                            weight=row.weight,
                            quantity=1,
                            observations=row.observations,
                        )
                    )
            for sequence, row in enumerate(expanded_rows, start=1):
                row.sequence = sequence
                row.save()


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
    if isinstance(field, DecimalField):
        return f"DECIMAL({field.max_digits},{field.decimal_places})"
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
