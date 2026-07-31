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


class SchemaValidationError(RuntimeError):
    """Raised when a workstation finds an incomplete runtime schema."""


def validate_runtime_schema(database) -> None:
    """Validate required tables and columns without changing the database."""
    existing_tables, columns_by_table, indexes_by_table = _runtime_schema_snapshot(
        database
    )
    required_tables = {model._meta.table_name for model in ALL_MODELS}
    missing_tables = sorted(required_tables - existing_tables)
    if missing_tables:
        raise SchemaValidationError(
            "Faltan tablas requeridas: " + ", ".join(missing_tables)
        )

    missing_columns = []
    for model in ALL_MODELS:
        table_name = model._meta.table_name
        existing_columns = columns_by_table.get(table_name, set())
        required_columns = {field.column_name for field in model._meta.sorted_fields}
        missing = sorted(required_columns - existing_columns)
        if missing:
            missing_columns.append(f"{table_name}: {', '.join(missing)}")

    if missing_columns:
        raise SchemaValidationError(
            "Faltan columnas requeridas (" + "; ".join(missing_columns) + ")"
        )

    missing_indexes = []
    for model in ALL_MODELS:
        table_name = model._meta.table_name
        existing_indexes = indexes_by_table.get(table_name, [])
        for field_names, unique in model._meta.indexes:
            expected_columns = {
                model._meta.fields[field_name].column_name for field_name in field_names
            }
            if not any(
                index_columns == expected_columns and (not unique or index_unique)
                for index_columns, index_unique in existing_indexes
            ):
                missing_indexes.append(
                    f"{table_name}: {', '.join(sorted(expected_columns))}"
                )

    if missing_indexes:
        raise SchemaValidationError(
            "Faltan indices requeridos (" + "; ".join(missing_indexes) + ")"
        )


def _runtime_schema_snapshot(database):
    if database.__class__.__name__ == "MySQLDatabase":
        return _mysql_schema_snapshot(database)

    tables = set(database.get_tables())
    columns = {
        table_name: {column.name for column in database.get_columns(table_name)}
        for table_name in tables
    }
    indexes = {
        table_name: [
            (set(index.columns), index.unique)
            for index in database.get_indexes(table_name)
        ]
        for table_name in tables
    }
    return tables, columns, indexes


def _mysql_schema_snapshot(database):
    table_rows = database.execute_sql(
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = DATABASE()"
    ).fetchall()
    column_rows = database.execute_sql(
        "SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE()"
    ).fetchall()
    index_rows = database.execute_sql(
        "SELECT TABLE_NAME, INDEX_NAME, NON_UNIQUE, COLUMN_NAME "
        "FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA = DATABASE() "
        "ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX"
    ).fetchall()

    tables = {row[0] for row in table_rows}
    columns = {table_name: set() for table_name in tables}
    for table_name, column_name in column_rows:
        columns.setdefault(table_name, set()).add(column_name)

    grouped_indexes = {}
    for table_name, index_name, non_unique, column_name in index_rows:
        key = (table_name, index_name)
        grouped_indexes.setdefault(key, (set(), not bool(non_unique)))[0].add(
            column_name
        )

    indexes = {table_name: [] for table_name in tables}
    for (table_name, _index_name), index_data in grouped_indexes.items():
        indexes.setdefault(table_name, []).append(index_data)
    return tables, columns, indexes


def ensure_runtime_schema(database) -> None:
    database.create_tables(ALL_MODELS, safe=True)
    for model in ALL_MODELS:
        _ensure_model_columns(database, model)
    if hasattr(database, "atomic"):
        _backfill_product_classification(database)
        _normalize_legacy_pallet_rows(database)
        _consolidate_shared_client_addresses(database)
    if hasattr(database, "get_indexes"):
        _ensure_pallet_sequence_index(database)
    _ensure_sqlite_index_integrity(database)


def _backfill_product_classification(database) -> None:
    from app.models.masters import Product
    from app.services.product_classification_service import analyze_legacy_product

    with database.atomic():
        for product in Product.select().order_by(Product.id):
            inference = analyze_legacy_product(product.name)
            if product.classification_source != "manual":
                product.product_kind = inference.product_kind
                product.classification_source = "inferido"
            if product.weight_source != "manual":
                if product.weight_source is None and product.peso_unitario_kg and product.peso_unitario_kg > 0:
                    product.weight_source = "manual"
                else:
                    product.peso_unitario_kg = inference.peso_unitario_kg
                    product.weight_source = "inferido"
            product.review_required = (
                product.product_kind == "revisar"
                or (product.product_kind == "producto" and product.peso_unitario_kg <= 0)
            )
            product.save()


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
