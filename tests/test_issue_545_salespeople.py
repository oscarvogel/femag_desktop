import pytest


def _set_combo_data(combo, value):
    index = combo.findData(value)
    assert index >= 0
    combo.setCurrentIndex(index)


def test_salesperson_master_and_client_assignment(db):
    from app.models.masters import Client, Salesperson
    from app.services.client_service import ClientService
    from app.services.master_service import MasterService

    master = MasterService("issue545")
    luis = master.create_salesperson(
        "Luis",
        phone="+5493764000001",
        observations="Cartera norte",
    )
    pedro = master.create_salesperson("Pedro")

    client = ClientService("issue545").create_client(
        "Cliente vendedor 545",
        "30700000545",
        "RI",
        salesperson=luis,
    )

    assert client.salesperson == luis
    assert luis.active is True
    assert Salesperson.select().count() == 2

    ClientService("issue545").set_salesperson(client, pedro)
    client = Client.get_by_id(client.id)
    assert client.salesperson == pedro

    ClientService("issue545").set_salesperson(client, None)
    assert Client.get_by_id(client.id).salesperson_id is None


def test_inactive_salesperson_cannot_be_assigned_to_new_client(db):
    from app.models.masters import Salesperson
    from app.services.client_service import ClientService

    inactive = Salesperson.create(name="Vendedor inactivo 545", active=False)

    with pytest.raises(ValueError, match="inactivo"):
        ClientService("issue545").create_client(
            "Cliente bloqueado 545",
            "30700010545",
            "RI",
            salesperson=inactive,
        )


def test_salesperson_options_only_offer_active_and_preserve_current_inactive(db):
    from app.models.masters import Salesperson
    from app.ui.master_abm import _salesperson_options

    active = Salesperson.create(name="Luis activo 545")
    inactive = Salesperson.create(name="Pedro inactivo 545", active=False)

    new_options = dict(_salesperson_options())
    assert active.id in new_options
    assert inactive.id not in new_options

    edit_options = dict(_salesperson_options(include_id=inactive.id))
    assert active.id in edit_options
    assert inactive.id in edit_options
    assert "Inactivo" in edit_options[inactive.id]


def test_client_rows_filter_by_salesperson_and_unassigned(db):
    from app.models.masters import Client, Salesperson
    from app.ui.master_abm import _client_rows

    luis = Salesperson.create(name="Luis filtro 545")
    pedro = Salesperson.create(name="Pedro filtro 545")
    Client.create(
        name="Cliente Luis 545",
        cuit="30700030545",
        iva_condition="RI",
        salesperson=luis,
    )
    Client.create(
        name="Cliente Pedro 545",
        cuit="30700040545",
        iva_condition="RI",
        salesperson=pedro,
    )
    Client.create(
        name="Cliente sin vendedor 545",
        cuit="30700050545",
        iva_condition="RI",
    )

    luis_rows = _client_rows(luis.id)
    assert [row[1] for row in luis_rows] == ["Cliente Luis 545"]
    assert luis_rows[0][3] == "Luis filtro 545"

    unassigned_rows = _client_rows("unassigned")
    assert [row[1] for row in unassigned_rows] == ["Cliente sin vendedor 545"]
    assert unassigned_rows[0][3] == "Sin asignar"


def test_salesperson_master_is_registered_in_ui_and_permissions(db):
    from app.services.permission_service import MENU
    from app.services.menu_service import REAL_MODULES
    from app.ui.master_abm import master_abm_configs

    assert "Vendedores" in MENU["Maestros"]
    assert REAL_MODULES["Vendedores"] == "salespeople"
    config = master_abm_configs()["salespeople"]
    assert config.title == "Vendedores"
    assert config.columns == ["Nombre", "Teléfono", "Estado"]


def test_runtime_schema_restores_salesperson_index_idempotently(db):
    from app.config.schema import ensure_runtime_schema, validate_runtime_schema

    salesperson_indexes = [
        index
        for index in db.get_indexes("client")
        if set(index.columns) == {"salesperson_id"}
    ]
    assert salesperson_indexes

    for index in salesperson_indexes:
        db.execute_sql(f'DROP INDEX "{index.name}"')

    ensure_runtime_schema(db)
    ensure_runtime_schema(db)
    validate_runtime_schema(db)

    columns = {column.name for column in db.get_columns("client")}
    assert "salesperson_id" in columns
    assert any(
        set(index.columns) == {"salesperson_id"}
        for index in db.get_indexes("client")
    )


def test_runtime_schema_adds_nullable_salesperson_column_to_legacy_client():
    from collections import namedtuple

    from app.config.schema import _ensure_model_columns
    from app.models.masters import Client

    Column = namedtuple("Column", "name null")

    class MySQLDatabase:
        def __init__(self):
            self.sql = []

        def get_columns(self, _table_name):
            return [
                Column(field.column_name, field.null)
                for field in Client._meta.sorted_fields
                if field.column_name != "salesperson_id"
            ]

        def execute_sql(self, sql, params=None):
            self.sql.append((sql, params))

    database = MySQLDatabase()

    _ensure_model_columns(database, Client)

    assert (
        "ALTER TABLE `client` ADD COLUMN `salesperson_id` INTEGER NULL",
        None,
    ) in database.sql
