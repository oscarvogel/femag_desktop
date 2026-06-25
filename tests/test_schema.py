from peewee import SqliteDatabase


def test_ensure_runtime_schema_adds_missing_columns_to_existing_tables():
    from app.config.database import bind_database
    from app.config.schema import ensure_runtime_schema

    db = SqliteDatabase(":memory:")
    bind_database(db)
    db.connect(reuse_if_open=True)
    db.execute_sql(
        """
        CREATE TABLE driver (
            id INTEGER PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )

    ensure_runtime_schema(db)

    column_names = {column.name for column in db.get_columns("driver")}

    assert "carrier_id" in column_names
    assert "available" in column_names


def test_ensure_runtime_schema_relaxes_nullable_columns_for_mysql_tables():
    from collections import namedtuple

    from app.config.schema import ensure_runtime_schema

    Column = namedtuple("Column", "name null")

    class MySQLDatabase:
        def __init__(self):
            self.sql = []

        def create_tables(self, models, safe=True):
            return None

        def get_columns(self, table_name):
            if table_name == "loadorder":
                return [
                    Column("order_number", False),
                    Column("date", False),
                    Column("client_id", False),
                    Column("delivery_address_id", False),
                    Column("carrier_id", False),
                    Column("driver_id", False),
                    Column("truck_id", False),
                    Column("status", False),
                    Column("observations", True),
                    Column("created_by", True),
                    Column("updated_by", True),
                    Column("created_at", False),
                    Column("updated_at", False),
                ]
            return [Column(field.column_name, field.null) for field in _model_by_table(table_name)._meta.sorted_fields]

        def execute_sql(self, sql):
            self.sql.append(sql)

    database = MySQLDatabase()

    ensure_runtime_schema(database)

    assert (
        "ALTER TABLE `loadorder` MODIFY COLUMN `client_id` INTEGER NULL"
        in database.sql
    )
    assert (
        "ALTER TABLE `loadorder` MODIFY COLUMN `delivery_address_id` INTEGER NULL"
        in database.sql
    )


def _model_by_table(table_name):
    from app.models import ALL_MODELS

    return next(model for model in ALL_MODELS if model._meta.table_name == table_name)
