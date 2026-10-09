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


def test_validate_runtime_schema_reports_schema_newer_than_the_app(db):
    """App vieja contra base migrada por otro build: dice "falta" y no es falta.

    Es el incidente real: el PR #623 cambio el indice de devoluciones de dos columnas
    a tres. El puesto con la version anterior declara (closure_id, order_product_id)
    y la base ya tiene ese mismo indice con `timing` agregado. Antes el mensaje decia
    "Faltan indices requeridos" y mandaba a correr `init_db.py`, que no lo arregla
    porque corre la misma migracion y deja el esquema igual.

    Aqui se reproduce la situacion al reves con un indice real: la base tiene el
    indice declarado MAS una columna de mas.
    """
    import pytest

    from app.config.schema import SchemaTooNewError, validate_runtime_schema

    declared = next(
        item
        for item in db.get_indexes("loadorderpallet")
        if item.unique and set(item.columns) == {"order_id", "sequence"}
    )
    db.execute_sql(f'DROP INDEX "{declared.name}"')
    db.execute_sql(
        'CREATE UNIQUE INDEX "loadorderpallet_newer_index" '
        'ON "loadorderpallet" ("order_id", "sequence", "pallet_type_id")'
    )

    try:
        with pytest.raises(SchemaTooNewError) as exc_info:
            validate_runtime_schema(db)

        message = str(exc_info.value)
        assert "mas nueva" in message
        assert "loadorderpallet" in message
        # Nombra las columnas que la base tiene de mas, para que se entienda el choque.
        assert "pallet_type_id" in message
        assert "Faltan indices requeridos" not in message
    finally:
        db.execute_sql('DROP INDEX "loadorderpallet_newer_index"')
        db.execute_sql(
            'CREATE UNIQUE INDEX "%s" ON "loadorderpallet" ("order_id", "sequence")'
            % declared.name
        )


def test_validate_runtime_schema_still_reports_a_truly_missing_index(db):
    """Un indice que no existe, sin equivalente mas nuevo en la base, sigue faltando."""
    import pytest

    from app.config.schema import (
        SchemaTooNewError,
        SchemaValidationError,
        validate_runtime_schema,
    )

    declared = next(
        item
        for item in db.get_indexes("loadorderpallet")
        if item.unique and set(item.columns) == {"order_id", "sequence"}
    )
    db.execute_sql(f'DROP INDEX "{declared.name}"')

    try:
        with pytest.raises(SchemaValidationError) as exc_info:
            validate_runtime_schema(db)

        assert not isinstance(exc_info.value, SchemaTooNewError)
        assert "Faltan indices requeridos" in str(exc_info.value)
        assert "loadorderpallet" in str(exc_info.value)
    finally:
        db.execute_sql(
            'CREATE UNIQUE INDEX "%s" ON "loadorderpallet" ("order_id", "sequence")'
            % declared.name
        )


def test_schema_too_new_error_is_a_schema_validation_error():
    """Los dos sitios que ya capturaban SchemaValidationError siguen funcionando."""
    from app.config.schema import SchemaTooNewError, SchemaValidationError

    assert issubclass(SchemaTooNewError, SchemaValidationError)


def test_startup_message_for_newer_schema_says_update_the_app(monkeypatch):
    """El mensaje de arranque no puede mandar a init_db.py en el caso de base nueva."""
    import pytest

    from app.ui.desktop_app import SchemaTooNewAtStartup, _prepare_database

    class _Closed:
        def connect(self, *args, **kwargs):
            pass

        def is_closed(self):
            return False

        def close(self):
            pass

    from app.config import schema as schema_module

    def _raise(_database):
        raise schema_module.SchemaTooNewError("loadorderreturnline: closure_id, order_product_id")

    monkeypatch.setattr(schema_module, "validate_runtime_schema", _raise)
    monkeypatch.setattr(
        "app.ui.desktop_app.validate_runtime_schema", _raise, raising=False
    )
    monkeypatch.setattr(
        "app.ui.desktop_app.initialize_runtime_database", lambda: _Closed()
    )

    with pytest.raises(SchemaTooNewAtStartup) as exc_info:
        _prepare_database(demo_mode=False)

    # Sigue siendo RuntimeError para que el arranque no cambie de rama.
    assert isinstance(exc_info.value, RuntimeError)
    message = str(exc_info.value)
    assert "actualizar la aplicacion" in message
    assert "init_db.py" not in message
    assert "fuera de servicio" in message


def test_outdated_workstation_opens_the_update_without_being_able_to_say_no(monkeypatch):
    """Un puesto atrasado se actualiza en el momento: no puede seguir trabajando."""
    from app.services.update_service import UpdateInfo
    from app.ui import desktop_app

    info = UpdateInfo(
        version="2099.01.01.00.00.00",
        download_url="https://example.invalid/FEMAG.exe",
        sha256="a" * 64,
    )
    calls = []

    def _raise(*_args, **_kwargs):
        raise desktop_app.SchemaTooNewAtStartup("base mas nueva")

    def _fake_show(window, update, mandatory=False):
        calls.append(("update", window, update.version, mandatory))
        return True

    def _should_not_run(error):
        calls.append(("explain", str(error)))

    monkeypatch.setattr(desktop_app, "_prepare_database", _raise)
    monkeypatch.setattr(desktop_app, "_explain_outdated_app", _should_not_run)
    monkeypatch.setattr(
        "app.services.update_service.fetch_update_info", lambda *a, **k: info
    )
    monkeypatch.setattr("app.ui.update_extension._show_update_dialog", _fake_show)

    assert desktop_app.run_desktop_app() == 1

    assert len(calls) == 1
    assert calls[0][0] == "update"
    # Sin ventana: todavia no hay login. Y mandatory: no puede decir que no.
    assert calls[0][1] is None
    assert calls[0][2] == "2099.01.01.00.00.00"
    assert calls[0][3] is True


def test_outdated_workstation_explains_when_there_is_no_published_update(monkeypatch):
    """Sin version publicada, avisa con el detalle para que alguien lo resuelva."""
    from app.ui import desktop_app

    calls = []

    def _raise(*_args, **_kwargs):
        raise desktop_app.SchemaTooNewAtStartup("base mas nueva")

    monkeypatch.setattr(desktop_app, "_prepare_database", _raise)
    monkeypatch.setattr(
        "app.services.update_service.fetch_update_info", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "app.ui.update_extension._show_update_dialog",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no hay update")),
    )
    monkeypatch.setattr(
        desktop_app, "_explain_outdated_app", lambda error: calls.append(str(error))
    )

    assert desktop_app.run_desktop_app() == 1
    assert len(calls) == 1
    assert "base mas nueva" in calls[0]


def test_explanation_copies_the_detail_and_does_not_ask_to_prepare_the_schema(monkeypatch):
    """Lo unico accionable sin actualizacion es copiar el detalle y avisar."""
    import pytest

    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.ui import desktop_app

    _qapp = QApplication.instance() or QApplication([])
    seen = {}

    class _Box:
        Critical = QMessageBox.Critical
        Ok = QMessageBox.Ok

        def __init__(self, *_args, **_kwargs):
            seen["box"] = self

        def setText(self, text):
            seen["text"] = text

        def setInformativeText(self, text):
            seen["info"] = text

        def setDetailedText(self, text):
            seen["detail"] = text

        def setTextInteractionFlags(self, *_args):
            pass

        def setStandardButtons(self, *_args):
            pass

        def exec_(self):
            return QMessageBox.Ok

    monkeypatch.setattr(desktop_app, "QMessageBox", _Box)

    desktop_app._explain_outdated_app(RuntimeError("loadorderreturnline: closure_id"))

    detail = seen["detail"]
    assert desktop_app.BUILD_VERSION in detail
    assert "loadorderreturnline" in detail
    assert "init_db.py" not in seen["text"] + seen["info"] + detail
    assert "No se debe preparar ni revertir el esquema" in seen["info"]
    assert _qapp.clipboard().text() == detail


def test_mandatory_update_dialog_never_offers_a_decline(monkeypatch):
    """Con mandatory no hay boton de "No": decir que no deja el puesto caido."""
    import pytest

    from PyQt5.QtWidgets import QApplication, QMessageBox

    from app.services.update_service import UpdateInfo
    from app.ui import update_extension

    _qapp = QApplication.instance() or QApplication([])
    info = UpdateInfo(
        version="2099.01.01.00.00.00",
        download_url="https://example.invalid/FEMAG.exe",
        sha256="a" * 64,
    )

    asked = []

    def _information(_parent, title, text, *_args):
        asked.append(("information", title, text))
        return QMessageBox.Ok

    def _question(*args, **kwargs):
        asked.append(("question", args[1] if len(args) > 1 else ""))
        return QMessageBox.No

    monkeypatch.setattr(update_extension.QMessageBox, "information", staticmethod(_information))
    monkeypatch.setattr(update_extension.QMessageBox, "question", staticmethod(_question))

    class _FakeSignal:
        def connect(self, *_args):
            pass

    class _FakeSignals:
        progress = _FakeSignal()
        failed = _FakeSignal()
        downloaded = _FakeSignal()

    class _FakeWorker:
        def __init__(self, *_args, **_kwargs):
            self.signals = _FakeSignals()

    # Corta antes de descargar: solo importa que no se pregunto.
    monkeypatch.setattr(update_extension, "_DownloadWorker", _FakeWorker)
    monkeypatch.setattr(update_extension.QProgressDialog, "show", lambda self: None)
    monkeypatch.setattr(update_extension.QThreadPool.globalInstance(), "start", lambda worker: None)

    update_extension._show_update_dialog(None, info, mandatory=True)

    assert asked
    assert all(kind == "information" for kind, *_rest in asked)
    assert any("no puede trabajar" in text for _kind, _title, text in asked)


def test_optional_update_dialog_still_asks_before_downloading(monkeypatch):
    """El chequeo periodico no cambia: ahi el operador puede decir que no."""
    from PyQt5.QtWidgets import QMessageBox

    from app.services.update_service import UpdateInfo
    from app.ui import update_extension

    info = UpdateInfo(
        version="2099.01.01.00.00.00",
        download_url="https://example.invalid/FEMAG.exe",
        sha256="a" * 64,
    )
    asked = []

    def _question(_parent, title, text, *_args):
        asked.append(text)
        return QMessageBox.No

    monkeypatch.setattr(update_extension.QMessageBox, "question", staticmethod(_question))

    assert update_extension._show_update_dialog(None, info) is False
    assert len(asked) == 1
    assert "¿Desea descargar el instalador ahora?" in asked[0]


def test_startup_message_for_incomplete_schema_still_says_init_db(monkeypatch):
    """El caso de base incompleta conserva la accion correcta: init_db.py."""
    import pytest

    from app.config import schema as schema_module
    from app.ui.desktop_app import _prepare_database

    class _Closed:
        def connect(self, *args, **kwargs):
            pass

        def is_closed(self):
            return False

        def close(self):
            pass

    def _raise(_database):
        raise schema_module.SchemaValidationError("Faltan tablas requeridas: client")

    monkeypatch.setattr("app.ui.desktop_app.initialize_runtime_database", lambda: _Closed())
    monkeypatch.setattr("app.ui.desktop_app.validate_runtime_schema", _raise, raising=False)

    with pytest.raises(RuntimeError) as exc_info:
        _prepare_database(demo_mode=False)

    message = str(exc_info.value)
    assert "init_db.py" in message
    assert "actualizar la aplicacion" not in message


def test_connection_dialog_does_not_offer_to_prepare_a_newer_schema(monkeypatch):
    """Base nueva no debe ofrecer "crear o actualizar tablas": no lo arregla."""
    import pytest

    from app.ui import connection_dialog

    class _Database:
        def connect(self):
            pass

        def close(self):
            pass

        def is_closed(self):
            return False

    def _raise(_database):
        raise connection_dialog.SchemaTooNewError("loadorderreturnline: closure_id")

    monkeypatch.setattr(connection_dialog, "build_mysql_database", lambda _settings: _Database())
    monkeypatch.setattr(connection_dialog, "validate_runtime_schema", _raise)

    connection = connection_dialog.RuntimeConnection(
        host="almanet-server",
        port=3306,
        database="femag_desktop",
        user="operador",
        password="clave",
    )

    with pytest.raises(RuntimeError) as exc_info:
        connection_dialog.test_runtime_connection(connection)

    assert not isinstance(exc_info.value, connection_dialog.RuntimeSchemaPreparationRequired)
    assert "actualizar la aplicacion" in str(exc_info.value)


def test_backfill_missing_column_default_uses_mysql_placeholder():
    from collections import namedtuple

    from app.config.schema import _ensure_model_columns
    from app.models.masters import Product

    Column = namedtuple("Column", "name null")

    class MySQLDatabase:
        param = "%s"

        def __init__(self):
            self.statements = []

        def get_columns(self, _table_name):
            return [
                Column(field.column_name, field.null)
                for field in Product._meta.sorted_fields
                if field.column_name != "review_required"
            ]

        def execute_sql(self, sql, params=None):
            if params is not None:
                sql % params
            self.statements.append((sql, params))

    database = MySQLDatabase()

    _ensure_model_columns(database, Product)

    assert (
        "UPDATE `product` SET `review_required` = %s "
        "WHERE `review_required` IS NULL",
        (1,),
    ) in database.statements


def test_backfill_repairs_existing_nullable_mysql_column_after_partial_migration():
    from collections import namedtuple

    from app.config.schema import _ensure_model_columns
    from app.models.masters import Product

    Column = namedtuple("Column", "name null")

    class MySQLDatabase:
        param = "%s"

        def __init__(self):
            self.statements = []

        def get_columns(self, _table_name):
            return [
                Column(
                    field.column_name,
                    True if field.column_name == "review_required" else field.null,
                )
                for field in Product._meta.sorted_fields
            ]

        def execute_sql(self, sql, params=None):
            self.statements.append((sql, params))

    database = MySQLDatabase()

    _ensure_model_columns(database, Product)

    assert (
        "UPDATE `product` SET `review_required` = %s "
        "WHERE `review_required` IS NULL",
        (1,),
    ) in database.statements


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
    assert db.execute_sql("SELECT available FROM driver WHERE id = 1").fetchone() == (1,)
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


def test_ensure_runtime_schema_adds_trailer_snapshot_to_legacy_remittance(db):
    from app.config.schema import ensure_runtime_schema

    db.execute_sql("ALTER TABLE remittance DROP COLUMN trailer_domain")

    ensure_runtime_schema(db)

    columns = {column.name: column for column in db.get_columns("remittance")}
    assert columns["trailer_domain"].null is True


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



def test_mysql_money_column_detects_integer_or_zero_scale_legacy_types():
    from collections import namedtuple

    from app.config.schema import _mysql_money_column_needs_fractional_fix

    Column = namedtuple("Column", "data_type")

    class MySQLDatabase:
        pass

    database = MySQLDatabase()

    assert _mysql_money_column_needs_fractional_fix(
        database, "clientaccountmovement", "total_amount", Column("int")
    )
    assert _mysql_money_column_needs_fractional_fix(
        database, "clientaccountmovement", "total_amount", Column("decimal(18,0)")
    )
    assert not _mysql_money_column_needs_fractional_fix(
        database, "clientaccountmovement", "total_amount", Column("decimal(18,2)")
    )
    assert not _mysql_money_column_needs_fractional_fix(
        database, "clientaccountmovement", "total_amount", Column("double")
    )


def test_repair_payment_movement_restores_cents_from_receipt(db):
    import pytest

    from app.config.schema import _repair_payment_movement_amounts
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.services.client_payment_service import ClientPaymentService

    client = Client.create(
        name="Cliente Centavos",
        cuit="30999999991",
        iva_condition="RI",
    )
    payment = ClientPaymentService(current_user="tesoreria").register_payment(
        client=client,
        amount=898220.62,
        method="retenciones_percepciones",
    )
    movement = ClientAccountMovement.get(
        ClientAccountMovement.payment == payment,
        ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_PAYMENT,
    )
    movement.amount = -898221.0
    movement.net_amount = -898221.0
    movement.total_amount = -898221.0
    movement.save()

    _repair_payment_movement_amounts(db)

    movement = ClientAccountMovement.get_by_id(movement.id)
    assert movement.amount == pytest.approx(-898220.62)
    assert movement.net_amount == pytest.approx(-898220.62)
    assert movement.total_amount == pytest.approx(-898220.62)
