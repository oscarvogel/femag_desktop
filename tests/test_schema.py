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
    truck_columns = {column.name: column for column in db.get_columns("truck")}

    assert "carrier_id" in columns
    assert columns["carrier_id"].null is True
    assert "cuit" in columns
    assert "available" in columns
    assert columns["usual_truck_id"].null is True
    assert truck_columns["trailer_domain"].null is True
    assert truck_columns["carrier_id"].null is True
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


def test_runtime_schema_maps_decimal_fields_with_declared_precision():
    from app.config.schema import _field_sql
    from app.models.masters import Product

    assert _field_sql(Product.peso_unitario_kg) == "DECIMAL(12,3)"


def test_runtime_schema_expands_legacy_aggregated_pallet_rows(db):
    from app.config.schema import _normalize_legacy_pallet_rows
    from app.models.load_orders import LoadOrder, LoadOrderPallet
    from app.models.masters import Carrier, Driver, PalletType, Truck

    carrier = Carrier.create(name="Transporte migracion")
    driver = Driver.create(name="Chofer migracion", carrier=carrier)
    truck = Truck.create(domain="MIG123", carrier=carrier)
    pallet_type = PalletType.create(type="Legacy", measure="1x1", weight=0)
    order = LoadOrder.create(order_number=501, carrier=carrier, driver=driver, truck=truck)
    LoadOrderPallet.create(
        order=order,
        pallet_type=pallet_type,
        sequence=1,
        measure="1x1",
        weight=0,
        quantity=3,
    )

    _normalize_legacy_pallet_rows(db)

    rows = [
        (row.sequence, row.quantity)
        for row in LoadOrderPallet.select().where(LoadOrderPallet.order == order).order_by(LoadOrderPallet.sequence)
    ]
    assert rows == [(1, 1), (2, 1), (3, 1)]


def test_runtime_schema_resequences_multiple_legacy_pallet_rows(db):
    from app.config.schema import _ensure_pallet_sequence_index, _normalize_legacy_pallet_rows
    from app.models.load_orders import LoadOrder, LoadOrderPallet
    from app.models.masters import Carrier, Driver, Truck

    carrier = Carrier.create(name="Transporte migracion multiple")
    driver = Driver.create(name="Chofer migracion multiple", carrier=carrier)
    truck = Truck.create(domain="MIG456", carrier=carrier)
    order = LoadOrder.create(order_number=502, carrier=carrier, driver=driver, truck=truck)
    first = LoadOrderPallet.create(order=order, sequence=1, quantity=1)
    second = LoadOrderPallet.create(order=order, sequence=2, quantity=2)
    db.execute_sql("DROP INDEX `loadorderpallet_order_id_sequence`")
    db.execute_sql("UPDATE loadorderpallet SET sequence = 1 WHERE order_id = ?", (order.id,))

    _normalize_legacy_pallet_rows(db)
    _ensure_pallet_sequence_index(db)

    rows = list(
        LoadOrderPallet.select()
        .where(LoadOrderPallet.order == order)
        .order_by(LoadOrderPallet.sequence)
    )
    assert [row.sequence for row in rows] == [1, 2, 3]
    assert [row.quantity for row in rows] == [1, 1, 1]
    assert {first.id, second.id}.issubset({row.id for row in rows})
    assert any(index.unique for index in db.get_indexes("loadorderpallet"))


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
