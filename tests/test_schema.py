from peewee import SqliteDatabase


def test_mysql_runtime_schema_snapshot_uses_three_batched_queries():
    from app.config.schema import _runtime_schema_snapshot

    queries = []

    class Cursor:
        def __init__(self, rows):
            self.rows = rows

        def fetchall(self):
            return self.rows

    class MySQLDatabase:
        def execute_sql(self, sql):
            queries.append(sql)
            if "INFORMATION_SCHEMA.TABLES" in sql:
                return Cursor([("client",)])
            if "INFORMATION_SCHEMA.COLUMNS" in sql:
                return Cursor([("client", "id"), ("client", "name")])
            if "INFORMATION_SCHEMA.STATISTICS" in sql:
                return Cursor(
                    [
                        ("client", "client_name", 0, "name"),
                    ]
                )
            raise AssertionError(f"Consulta inesperada: {sql}")

    tables, columns, indexes = _runtime_schema_snapshot(MySQLDatabase())

    assert len(queries) == 3
    assert tables == {"client"}
    assert columns == {"client": {"id", "name"}}
    assert indexes == {"client": [({"name"}, True)]}


def test_validate_runtime_schema_accepts_complete_schema_without_writes(db):
    from app.config.schema import validate_runtime_schema

    statements = []
    db.connection().set_trace_callback(statements.append)
    try:
        validate_runtime_schema(db)
    finally:
        db.connection().set_trace_callback(None)

    mutating_prefixes = (
        "CREATE",
        "ALTER",
        "DROP",
        "INSERT",
        "UPDATE",
        "DELETE",
        "REPLACE",
    )
    assert not [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(mutating_prefixes)
    ]


def test_validate_runtime_schema_reports_missing_tables():
    import pytest

    from app.config.schema import SchemaValidationError, validate_runtime_schema

    database = SqliteDatabase(":memory:")
    database.connect()
    try:
        with pytest.raises(SchemaValidationError, match="Faltan tablas requeridas"):
            validate_runtime_schema(database)
    finally:
        database.close()


def test_validate_runtime_schema_reports_missing_columns(db):
    import pytest

    from app.config.schema import SchemaValidationError, validate_runtime_schema

    db.execute_sql("ALTER TABLE client RENAME TO client_complete")
    db.execute_sql("CREATE TABLE client (id INTEGER PRIMARY KEY)")
    try:
        with pytest.raises(SchemaValidationError, match="client") as exc_info:
            validate_runtime_schema(db)
        assert "name" in str(exc_info.value)
    finally:
        db.execute_sql("DROP TABLE client")
        db.execute_sql("ALTER TABLE client_complete RENAME TO client")


def test_validate_runtime_schema_reports_missing_indexes(db):
    import pytest

    from app.config.schema import SchemaValidationError, validate_runtime_schema

    index = next(
        item
        for item in db.get_indexes("loadorderpallet")
        if item.unique and set(item.columns) == {"order_id", "sequence"}
    )
    db.execute_sql(f'DROP INDEX "{index.name}"')

    with pytest.raises(SchemaValidationError, match="Faltan indices requeridos") as exc_info:
        validate_runtime_schema(db)

    assert "loadorderpallet" in str(exc_info.value)


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
    assert db.execute_sql("PRAGMA integrity_check").fetchall() == [("ok",)]
    db.execute_sql(
        "INSERT INTO driver (id, name, carrier_id, usual_truck_id) VALUES (2, 'Chofer nuevo', 1, 1)"
    )
    assert db.execute_sql("SELECT name FROM driver WHERE id = 2").fetchone() == ("Chofer nuevo",)


def test_driver_schema_allows_null_carrier_and_cuit(db):
    columns = {column.name: column for column in db.get_columns("driver")}

    assert columns["carrier_id"].null is True
    assert columns["cuit"].null is True


def test_payment_schema_includes_annulment_tracking_columns(db):
    columns = {column.name for column in db.get_columns("clientpayment")}

    assert {
        "closure_id",
        "status",
        "annulled_at",
        "annulled_by",
        "annulment_reason",
    }.issubset(columns)


def test_account_movement_schema_includes_manual_adjustment_fields(db):
    columns = {column.name for column in db.get_columns("clientaccountmovement")}

    assert {"movement_date", "reference", "observations"}.issubset(columns)


def test_runtime_schema_adds_manual_adjustment_fields_to_legacy_account_movements(db):
    from app.config.schema import ensure_runtime_schema, validate_runtime_schema

    db.execute_sql("ALTER TABLE clientaccountmovement DROP COLUMN movement_date")
    db.execute_sql("ALTER TABLE clientaccountmovement DROP COLUMN reference")
    db.execute_sql("ALTER TABLE clientaccountmovement DROP COLUMN observations")

    ensure_runtime_schema(db)
    validate_runtime_schema(db)

    columns = {column.name for column in db.get_columns("clientaccountmovement")}
    assert {"movement_date", "reference", "observations"}.issubset(columns)


def test_runtime_schema_creates_load_order_closure_table_and_active_index(db):
    from app.config.schema import ensure_runtime_schema, validate_runtime_schema
    from app.models.load_orders import LoadOrderClosure

    db.drop_tables([LoadOrderClosure])

    ensure_runtime_schema(db)
    validate_runtime_schema(db)

    columns = {column.name for column in db.get_columns("loadorderclosure")}
    assert {
        "order_id",
        "status",
        "active_marker",
        "closed_at",
        "closed_by",
        "observations",
        "no_payment_reason",
        "reopened_at",
        "reopened_by",
        "reopen_reason",
    }.issubset(columns)
    assert any(
        index.unique and set(index.columns) == {"order_id", "active_marker"}
        for index in db.get_indexes("loadorderclosure")
    )


def test_runtime_schema_migrates_account_movement_index_for_multiple_closure_payments(db):
    from app.config.schema import ensure_runtime_schema, validate_runtime_schema

    legacy_columns = {"load_order_id", "client_id", "movement_type", "is_reversal"}
    expected_columns = {"source_ref", "client_id", "movement_type", "is_reversal"}
    for index in db.get_indexes("clientaccountmovement"):
        if index.unique and set(index.columns) == expected_columns:
            db.execute_sql(f"DROP INDEX `{index.name}`")
    db.execute_sql(
        "CREATE UNIQUE INDEX legacy_account_movement_order_client_type "
        "ON clientaccountmovement (load_order_id, client_id, movement_type, is_reversal)"
    )

    ensure_runtime_schema(db)
    validate_runtime_schema(db)

    indexes = db.get_indexes("clientaccountmovement")
    assert not any(index.unique and set(index.columns) == legacy_columns for index in indexes)
    assert any(index.unique and set(index.columns) == expected_columns for index in indexes)


def test_runtime_schema_backfills_active_status_for_legacy_payments(db):
    from app.config.schema import ensure_runtime_schema
    from app.models.masters import Client
    from app.services.client_payment_service import ClientPaymentService

    client = Client.create(
        name="Cliente Pago Legacy",
        cuit="30700000999",
        iva_condition="RI",
    )
    payment = ClientPaymentService(current_user="admin").register_payment(
        client=client,
        amount=100,
    )
    db.execute_sql("ALTER TABLE clientpayment DROP COLUMN status")

    ensure_runtime_schema(db)

    status = db.execute_sql(
        "SELECT status FROM clientpayment WHERE id = ?",
        (payment.id,),
    ).fetchone()[0]
    assert status == "activo"


def test_runtime_schema_consolidates_identical_fiscal_and_delivery_addresses(db):
    from app.config.schema import ensure_runtime_schema
    from app.models.masters import Client, ClientAddress

    client = Client.create(name="Cliente Migración", cuit="30700000444", iva_condition="RI")
    values = dict(
        client=client,
        province="Sin especificar",
        city="Posadas",
        address="Ruta 12",
        observations="Código postal: 3300",
        is_primary=True,
    )
    ClientAddress.create(address_type="fiscal", **values)
    ClientAddress.create(address_type="entrega", **values)

    ensure_runtime_schema(db)

    assert ClientAddress.select().where(ClientAddress.client == client).count() == 1
    assert ClientAddress.get(ClientAddress.client == client).address_type == "fiscal_entrega"


def test_runtime_schema_maps_decimal_fields_with_declared_precision():
    from app.config.schema import _field_sql
    from app.models.masters import Product

    assert _field_sql(Product.peso_unitario_kg) == "DECIMAL(12,3)"


def test_runtime_schema_backfills_product_classification_and_preserves_positive_weight(db):
    from decimal import Decimal
    from app.config.schema import ensure_runtime_schema
    from app.models.masters import Product

    inferred = Product.create(name="PACK 10 UNIDADES X 1 KG", unit="unidad")
    manual_weight = Product.create(name="FECULA X 25 KG", unit="kg", peso_unitario_kg=Decimal("12.000"))

    ensure_runtime_schema(db)
    ensure_runtime_schema(db)

    inferred = Product.get_by_id(inferred.id)
    manual_weight = Product.get_by_id(manual_weight.id)
    assert (inferred.product_kind, inferred.peso_unitario_kg, inferred.classification_source, inferred.weight_source) == (
        "producto", Decimal("10.000"), "inferido", "inferido"
    )
    assert manual_weight.peso_unitario_kg == Decimal("12.000")
    assert manual_weight.weight_source == "manual"


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
