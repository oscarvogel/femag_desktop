"""Reparto de una cantidad en dos partes de facturación (#585, PR 1).

Este primer PR solo deja el modelo preparado: la cantidad a facturar ahora en el
renglón, el momento de facturación en el presupuesto y la migración que reemplaza el
índice único legacy. La emisión de las dos partes llega en los PR siguientes.
"""
from datetime import date

import pytest
from peewee import IntegrityError, SqliteDatabase

from app.models.load_orders import BILLING_TIMINGS
from tests.conftest import _master_data


def _order_with_line(quantity=1200.0, cantidad_facturar_ahora=None):
    from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct

    data = _master_data()
    order = LoadOrder.create(
        order_number=1,
        date=date.today(),
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
    )
    destination = LoadOrderDestination.create(
        order=order,
        client=data["client"],
        delivery_address=data["address"],
        sequence=1,
    )
    line = LoadOrderProduct.create(
        order=order,
        destination=destination,
        product=data["product"],
        quantity=quantity,
        unit="bolsa",
        cantidad_facturar_ahora=cantidad_facturar_ahora,
    )
    return order, data["client"], line


# ------------------------------------------------------- reparto del renglón


def test_line_without_explicit_split_factures_everything_now(db):
    _order, _client, line = _order_with_line(quantity=1200.0)

    assert line.cantidad_facturar_ahora is None
    assert line.tiene_reparto_facturacion is False
    assert line.cantidad_facturacion_inmediata == 1200.0
    assert line.cantidad_facturacion_diferida == 0.0


def test_explicit_split_resolves_both_parts(db):
    _order, _client, line = _order_with_line(
        quantity=1200.0, cantidad_facturar_ahora=800.0
    )

    assert line.tiene_reparto_facturacion is True
    assert line.cantidad_facturacion_inmediata == 800.0
    assert line.cantidad_facturacion_diferida == 400.0
    # La cantidad total no se toca: logística y remito siguen viendo 1200.
    assert line.quantity == 1200.0
    assert line.cantidad_facturacion_inmediata + line.cantidad_facturacion_diferida == 1200.0


def test_fully_deferred_line_has_no_immediate_part(db):
    _order, _client, line = _order_with_line(quantity=1200.0, cantidad_facturar_ahora=0.0)

    assert line.tiene_reparto_facturacion is True
    assert line.cantidad_facturacion_inmediata == 0.0
    assert line.cantidad_facturacion_diferida == 1200.0


def test_deferred_quantity_never_goes_negative(db):
    _order, _client, line = _order_with_line(
        quantity=1200.0, cantidad_facturar_ahora=1500.0
    )

    # La validación de 0 <= x <= cantidad total corresponde a la UI y al servicio;
    # la propiedad no debe devolver un residuo negativo aunque llegue un dato malo.
    assert line.cantidad_facturacion_diferida == 0.0


# -------------------------------------------------- momento de facturación


def test_budget_defaults_to_immediate_timing(db):
    from app.models.budgets import Budget

    order, client, _line = _order_with_line()
    budget = Budget.create(
        budget_number=1,
        client=client,
        load_order=order,
        origin=Budget.ORIGIN_LOAD_ORDER,
    )

    assert budget.timing == Budget.TIMING_IMMEDIATE
    assert budget.timing_label == "Facturado ahora"


def test_deferred_budget_has_its_own_label(db):
    from app.models.budgets import Budget

    order, client, _line = _order_with_line()
    budget = Budget.create(
        budget_number=1,
        client=client,
        load_order=order,
        origin=Budget.ORIGIN_LOAD_ORDER,
        timing=Budget.TIMING_DEFERRED,
    )

    assert budget.timing == "deferred"
    assert budget.timing_label == "A facturar después"


def test_same_client_and_order_accepts_one_budget_per_timing(db):
    from app.models.budgets import Budget

    order, client, _line = _order_with_line()
    common = {
        "client": client,
        "load_order": order,
        "origin": Budget.ORIGIN_LOAD_ORDER,
    }

    immediate = Budget.create(budget_number=1, timing=Budget.TIMING_IMMEDIATE, **common)
    deferred = Budget.create(budget_number=2, timing=Budget.TIMING_DEFERRED, **common)

    assert immediate.id != deferred.id
    assert Budget.select().where(Budget.load_order == order).count() == 2


def test_still_rejects_two_budgets_with_the_same_timing(db):
    from app.models.budgets import Budget

    order, client, _line = _order_with_line()
    common = {
        "client": client,
        "load_order": order,
        "origin": Budget.ORIGIN_LOAD_ORDER,
        "timing": Budget.TIMING_IMMEDIATE,
    }
    Budget.create(budget_number=1, **common)

    with pytest.raises(IntegrityError):
        Budget.create(budget_number=2, **common)


def test_budget_status_tracks_each_timing(db):
    from app.models.budgets import Budget
    from app.models.load_orders import LoadOrderBudgetStatus

    order, client, _line = _order_with_line()

    for timing in BILLING_TIMINGS:
        LoadOrderBudgetStatus.create(
            order=order,
            client=client,
            timing=timing,
            status=LoadOrderBudgetStatus.STATUS_PENDING,
        )

    statuses = LoadOrderBudgetStatus.select().where(LoadOrderBudgetStatus.order == order)
    assert statuses.count() == 2
    assert {status.timing for status in statuses} == {
        Budget.TIMING_IMMEDIATE,
        Budget.TIMING_DEFERRED,
    }


def test_deferred_movement_type_is_distinct_from_the_historical_one():
    from app.models.accounting import ClientAccountMovement

    # La parte al contado reutiliza el tipo histórico para no tocar los movimientos
    # ya emitidos; la diferida necesita el suyo para distinguirse en el estado de
    # cuenta y en los informes de cobranza.
    assert ClientAccountMovement.TYPE_LOAD_ORDER_IMMEDIATE == "load_order_documental"
    assert ClientAccountMovement.TYPE_LOAD_ORDER_DEFERRED == "load_order_documental_deferred"
    assert (
        ClientAccountMovement.TYPE_LOAD_ORDER_DEFERRED
        != ClientAccountMovement.TYPE_LOAD_ORDER_IMMEDIATE
    )
    assert (
        ClientAccountMovement.TYPE_LOAD_ORDER_DEFERRED_REVERSAL
        != ClientAccountMovement.TYPE_LOAD_ORDER_IMMEDIATE_REVERSAL
    )


# ------------------------------------------------------------------ migración


def _legacy_budget_database():
    """Base con la tabla ``budget`` del esquema anterior a #585."""
    database = SqliteDatabase(":memory:")
    database.connect()
    database.execute_sql(
        """
        CREATE TABLE budget (
            id INTEGER NOT NULL PRIMARY KEY,
            budget_number INTEGER NOT NULL,
            client_id INTEGER NOT NULL,
            load_order_id INTEGER,
            origin VARCHAR(255) NOT NULL,
            issue_date DATE NOT NULL,
            status VARCHAR(255) NOT NULL,
            observations TEXT,
            net_amount DOUBLE NOT NULL,
            discount_amount DOUBLE NOT NULL,
            vat_amount DOUBLE NOT NULL,
            total_amount DOUBLE NOT NULL,
            created_by VARCHAR(255)
        )
        """
    )
    database.execute_sql(
        "INSERT INTO budget (budget_number, client_id, load_order_id, origin, issue_date,"
        " status, observations, net_amount, discount_amount, vat_amount, total_amount,"
        " created_by) VALUES (1, 1, 1, 'load_order', '2026-10-01', 'active', NULL,"
        " 0, 0, 0, 0, 'legacy')"
    )
    return database


def test_missing_timing_column_is_added_and_backfilled():
    from app.config.schema import _ensure_model_columns
    from app.models.budgets import Budget

    database = _legacy_budget_database()
    try:
        _ensure_model_columns(database, Budget)

        columns = {column.name for column in database.get_columns("budget")}
        assert "timing" in columns
        # El presupuesto legacy queda como parte facturada al contado.
        assert database.execute_sql("SELECT timing FROM budget").fetchone()[0] == "immediate"
    finally:
        database.close()


def test_legacy_unique_index_is_replaced_by_the_timing_index(db):
    from app.config.schema import ensure_runtime_schema, validate_runtime_schema

    legacy = "budget_load_order_client_origin"
    db.execute_sql(f"DROP INDEX IF EXISTS `{legacy}`")
    db.execute_sql("DROP INDEX IF EXISTS `budget_load_order_client_origin_timing`")
    db.execute_sql(
        f"CREATE UNIQUE INDEX `{legacy}` "
        "ON `budget` (`load_order_id`, `client_id`, `origin`)"
    )

    ensure_runtime_schema(db)

    unique_sets = {
        frozenset(index.columns) for index in db.get_indexes("budget") if index.unique
    }
    assert frozenset({"load_order_id", "client_id", "origin"}) not in unique_sets
    assert frozenset({"load_order_id", "client_id", "origin", "timing"}) in unique_sets
    validate_runtime_schema(db)


def test_migration_is_idempotent(db):
    from app.config.schema import ensure_runtime_schema, validate_runtime_schema

    ensure_runtime_schema(db)
    ensure_runtime_schema(db)

    validate_runtime_schema(db)
