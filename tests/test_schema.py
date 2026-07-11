from peewee import SqliteDatabase


def test_ensure_runtime_schema_adds_missing_columns_to_existing_tables():
    from app.config.database import bind_database
    from app.config.schema import ensure_runtime_schema

    db = SqliteDatabase(":memory:", pragmas={"foreign_keys": 1})
    bind_database(db)
    db.connect(reuse_if_open=True)
    db.execute_sql(
        """
        CREATE TABLE carrier (
            id INTEGER PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    db.execute_sql(
        """
        CREATE TABLE driver (
            id INTEGER PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE,
            carrier_id INTEGER NOT NULL REFERENCES carrier(id),
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    db.execute_sql(
        """
        CREATE TABLE truck (
            id INTEGER PRIMARY KEY,
            domain VARCHAR(255) NOT NULL UNIQUE,
            carrier_id INTEGER NOT NULL REFERENCES carrier(id),
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    db.execute_sql(
        """
        CREATE TABLE loadorder (
            id INTEGER PRIMARY KEY,
            order_number INTEGER NOT NULL UNIQUE,
            date DATE NOT NULL,
            carrier_id INTEGER NOT NULL REFERENCES carrier(id),
            driver_id INTEGER NOT NULL REFERENCES driver(id),
            truck_id INTEGER NOT NULL REFERENCES truck(id),
            status VARCHAR(255) NOT NULL,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    )
    db.execute_sql("INSERT INTO carrier (id, name) VALUES (1, 'Transporte existente')")
    db.execute_sql("INSERT INTO driver (id, name, carrier_id) VALUES (1, 'Chofer existente', 1)")
    db.execute_sql("INSERT INTO truck (id, domain, carrier_id) VALUES (1, 'ABC123', 1)")
    db.execute_sql(
        """
        INSERT INTO loadorder (id, order_number, date, carrier_id, driver_id, truck_id, status)
        VALUES (1, 1, '2026-07-11', 1, 1, 1, 'Pendiente')
        """
    )

    ensure_runtime_schema(db)

    columns = {column.name: column for column in db.get_columns("driver")}

    assert "carrier_id" in columns
    assert columns["carrier_id"].null is True
    assert "cuit" in columns
    assert "available" in columns
    assert db.execute_sql("SELECT name, carrier_id FROM driver WHERE id = 1").fetchone() == (
        "Chofer existente",
        1,
    )
    assert any(index.unique for index in db.get_indexes("driver"))
    assert any(foreign_key.column == "carrier_id" for foreign_key in db.get_foreign_keys("driver"))
    assert db.execute_sql("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.execute_sql("PRAGMA foreign_key_check").fetchall() == []


def test_driver_schema_allows_null_carrier_and_cuit(db):
    columns = {column.name: column for column in db.get_columns("driver")}

    assert columns["carrier_id"].null is True
    assert columns["cuit"].null is True


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
