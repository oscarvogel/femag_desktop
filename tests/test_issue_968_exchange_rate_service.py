"""#968: cotizaciones historicas inmutables, versionadas y con Decimal."""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pymysql
import pytest
from peewee import MySQLDatabase

from app.config.database import bind_database, database_proxy
from app.config.schema import (
    SchemaValidationError,
    ensure_runtime_schema,
    validate_runtime_schema,
)
from app.models import ALL_MODELS, SYNC_MODELS
from app.models.audit import AuditLog
from app.models.exchange_rates import ExchangeRate
from app.models.masters import Client
from app.services.audit_service import AuditService
from app.services.exchange_rate_service import (
    ExchangeRateAmbiguousSource,
    ExchangeRateNotFound,
    ExchangeRateService,
    InvalidExchangeRate,
)
from app.services.money import quantize_money

DAY = date(2026, 11, 27)
PREVIOUS_DAY = date(2026, 11, 26)
FETCHED = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def _register(service: ExchangeRateService, **overrides):
    values = {
        "base_currency": "USD",
        "quote_currency": "ARS",
        "effective_date": DAY,
        "rate_type": "oficial",
        "buy_rate": Decimal("1000.123456"),
        "sell_rate": Decimal("1000.654321"),
        "source": "bcra",
        "origin": ExchangeRate.ORIGIN_API,
        "fetched_at": FETCHED,
    }
    values.update(overrides)
    return service.register(**values)


def _lookup(service: ExchangeRateService, **overrides):
    values = {
        "base_currency": "USD",
        "quote_currency": "ARS",
        "rate_type": "oficial",
        "side": ExchangeRate.SIDE_SELL,
        "source": "bcra",
    }
    values.update(overrides)
    return service.get_exact(DAY, **values)


def test_register_and_exact_lookup(db):
    service = ExchangeRateService("admin")
    registration = _register(service)

    assert registration.created is True
    record = registration.record
    assert record.base_currency == "USD"
    assert record.quote_currency == "ARS"
    assert record.effective_date == DAY
    assert record.rate_type == "oficial"
    assert record.source == "bcra"
    assert record.origin == ExchangeRate.ORIGIN_API
    assert record.version == 1
    assert record.buy_rate == Decimal("1000.123456")
    assert record.sell_rate == Decimal("1000.654321")

    sell = _lookup(service)
    assert sell.requested_date == DAY
    assert sell.effective_date == DAY
    assert sell.base_currency == "USD"
    assert sell.quote_currency == "ARS"
    assert sell.rate_type == "oficial"
    assert sell.side == ExchangeRate.SIDE_SELL
    assert sell.source == "bcra"
    assert sell.value == Decimal("1000.654321")
    assert sell.buy_rate == Decimal("1000.123456")
    assert sell.sell_rate == Decimal("1000.654321")
    assert sell.record_id == record.id
    assert sell.version == 1
    assert sell.used_fallback is False
    assert sell.origin == ExchangeRate.ORIGIN_API

    buy = _lookup(service, side=ExchangeRate.SIDE_BUY)
    assert buy.value == Decimal("1000.123456")
    average = _lookup(service, side=ExchangeRate.SIDE_AVERAGE)
    assert average.value == Decimal("1000.388889")


def test_exact_lookup_never_uses_a_later_quote(db):
    service = ExchangeRateService("admin")
    _register(service, effective_date=PREVIOUS_DAY, sell_rate="1000.000000")
    _register(service, effective_date=DAY, sell_rate="1100.000000")

    previous = service.get_exact(
        PREVIOUS_DAY,
        base_currency="USD",
        quote_currency="ARS",
        rate_type="oficial",
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
    )
    assert previous.effective_date == PREVIOUS_DAY
    assert previous.value == Decimal("1000.000000")

    with pytest.raises(ExchangeRateNotFound):
        service.get_exact(
            date(2026, 11, 28),
            base_currency="USD",
            quote_currency="ARS",
            rate_type="oficial",
            side=ExchangeRate.SIDE_SELL,
            source="bcra",
        )


def test_fallback_uses_previous_date_and_marks_it(db):
    service = ExchangeRateService("admin")
    _register(service, effective_date=DAY)

    fallback = service.get_latest_before(
        date(2026, 11, 29),
        base_currency="USD",
        quote_currency="ARS",
        rate_type="oficial",
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
        allow_fallback=True,
    )
    assert fallback.requested_date == date(2026, 11, 29)
    assert fallback.effective_date == DAY
    assert fallback.used_fallback is True
    assert fallback.value == Decimal("1000.654321")

    with pytest.raises(ExchangeRateNotFound):
        service.get_latest_before(
            date(2026, 11, 29),
            base_currency="USD",
            quote_currency="ARS",
            rate_type="oficial",
            side=ExchangeRate.SIDE_SELL,
            source="bcra",
            allow_fallback=False,
        )


def test_missing_quote_has_a_clear_error(db):
    service = ExchangeRateService("admin")
    with pytest.raises(ExchangeRateNotFound) as error:
        _lookup(service)
    message = str(error.value)
    assert "USD/ARS" in message
    assert "oficial" in message
    assert DAY.isoformat() in message
    assert "bcra" in message


def test_currencies_and_types_are_not_mixed(db):
    service = ExchangeRateService("admin")
    _register(service)
    _register(service, rate_type="blue", sell_rate="1200.000000")
    _register(
        service,
        base_currency="BRL",
        quote_currency="ARS",
        sell_rate="250.000000",
    )

    blue = _lookup(service, rate_type="blue")
    assert blue.value == Decimal("1200.000000")
    brl = _lookup(service, base_currency="BRL", quote_currency="ARS")
    assert brl.value == Decimal("250.000000")

    # No se sustituye un tipo por otro.
    with pytest.raises(ExchangeRateNotFound):
        _lookup(service, rate_type="mep", base_currency="BRL")


def test_multiple_sources_require_explicit_source(db):
    service = ExchangeRateService("admin")
    _register(service, source="bcra", sell_rate="1000.000000")
    _register(service, source="manual", sell_rate="1100.000000")

    with pytest.raises(ExchangeRateAmbiguousSource) as error:
        _lookup(service, source=None)
    assert "bcra" in str(error.value)
    assert "manual" in str(error.value)

    manual = _lookup(service, source="manual")
    assert manual.value == Decimal("1100.000000")
    assert manual.source == "manual"


def test_repeated_registration_is_idempotent(db):
    service = ExchangeRateService("admin")
    first = _register(service)
    second = _register(service)

    assert first.created is True
    assert second.created is False
    assert second.record.id == first.record.id
    assert second.record.version == 1
    assert ExchangeRate.select().count() == 1
    assert (
        AuditLog.select()
        .where(AuditLog.module == "Cotizaciones")
        .count()
        == 1
    )


def test_correction_creates_new_version_and_keeps_history(db):
    service = ExchangeRateService("admin")
    first = _register(service)
    second = _register(service, sell_rate="1050.000000")

    assert second.created is True
    assert second.record.version == 2
    assert ExchangeRate.select().count() == 2

    latest = _lookup(service)
    assert latest.version == 2
    assert latest.value == Decimal("1050.000000")

    old = service.get_version(
        DAY,
        base_currency="USD",
        quote_currency="ARS",
        rate_type="oficial",
        version=1,
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
    )
    assert old.record_id == first.record.id
    assert old.value == Decimal("1000.654321")

    latest_range = service.get_range(
        DAY,
        DAY,
        base_currency="USD",
        quote_currency="ARS",
        rate_type="oficial",
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
        latest_only=True,
    )
    assert len(latest_range) == 1
    assert latest_range[0].version == 2

    all_versions = service.get_range(
        DAY,
        DAY,
        base_currency="USD",
        quote_currency="ARS",
        rate_type="oficial",
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
        latest_only=False,
    )
    assert [row.version for row in all_versions] == [1, 2]

    audits = list(
        AuditLog.select()
        .where(AuditLog.module == "Cotizaciones")
        .order_by(AuditLog.id)
    )
    assert len(audits) == 2
    assert audits[1].old_value["version"] == 1
    assert audits[1].new_value["version"] == 2


def test_history_records_are_immutable(db):
    service = ExchangeRateService("admin")
    record = _register(service).record

    record.sell_rate = Decimal("9999.000000")
    with pytest.raises(ValueError, match="inmutables"):
        record.save()
    with pytest.raises(ValueError, match="no se eliminan"):
        record.delete_instance()

    stored = ExchangeRate.get_by_id(record.id)
    assert stored.sell_rate == Decimal("1000.654321")


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_currency": "US"},
        {"quote_currency": "ARSX"},
        {"base_currency": "USD", "quote_currency": "USD"},
        {"rate_type": "   "},
        {"source": ""},
        {"origin": "otro"},
        {"buy_rate": "0"},
        {"sell_rate": "-1"},
        {"buy_rate": "NaN"},
        {"sell_rate": "Infinity"},
        {"buy_rate": "1000.1234567"},
        {"sell_rate": "1000000000000"},
        {"buy_rate": True},
        {"effective_date": "2026-11-27"},
    ],
)
def test_invalid_registration_values_are_rejected(db, overrides):
    service = ExchangeRateService("admin")
    with pytest.raises(InvalidExchangeRate):
        _register(service, **overrides)
    assert ExchangeRate.select().count() == 0


def test_invalid_side_and_version_are_rejected(db):
    service = ExchangeRateService("admin")
    _register(service)
    with pytest.raises(InvalidExchangeRate):
        _lookup(service, side="compra")
    with pytest.raises(InvalidExchangeRate):
        service.get_version(
            DAY,
            base_currency="USD",
            quote_currency="ARS",
            rate_type="oficial",
            version=0,
            side=ExchangeRate.SIDE_SELL,
            source="bcra",
        )


def test_conversion_direct_inverse_and_identity(db):
    service = ExchangeRateService("admin")
    registration = _register(service, buy_rate="999.500000", sell_rate="1000.500000")

    direct = service.convert(
        Decimal("100"),
        from_currency="USD",
        to_currency="ARS",
        on_date=DAY,
        rate_type="oficial",
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
        allow_fallback=False,
    )
    assert direct.identity is False
    assert direct.inverted is False
    assert direct.rate == Decimal("1000.500000")
    assert direct.converted_amount == Decimal("100050.00")
    assert direct.lookup.record_id == registration.record.id

    inverse = service.convert(
        Decimal("100050.00"),
        from_currency="ARS",
        to_currency="USD",
        on_date=DAY,
        rate_type="oficial",
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
        allow_fallback=False,
    )
    assert inverse.inverted is True
    assert inverse.lookup.record_id == registration.record.id
    assert inverse.converted_amount == Decimal("100.00")

    identity = service.convert(
        Decimal("123.456"),
        from_currency="USD",
        to_currency="USD",
        on_date=DAY,
        rate_type="oficial",
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
    )
    assert identity.identity is True
    assert identity.lookup is None
    assert identity.rate == Decimal("1")
    assert identity.converted_amount == Decimal("123.456")


def test_conversion_fallback_is_explicit(db):
    service = ExchangeRateService("admin")
    _register(service, effective_date=DAY)

    with pytest.raises(ExchangeRateNotFound):
        service.convert(
            Decimal("10"),
            from_currency="USD",
            to_currency="ARS",
            on_date=date(2026, 11, 29),
            rate_type="oficial",
            side=ExchangeRate.SIDE_SELL,
            source="bcra",
            allow_fallback=False,
        )

    converted = service.convert(
        Decimal("10"),
        from_currency="USD",
        to_currency="ARS",
        on_date=date(2026, 11, 29),
        rate_type="oficial",
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
        allow_fallback=True,
    )
    assert converted.lookup.used_fallback is True
    assert converted.lookup.effective_date == DAY
    assert converted.converted_amount == Decimal("10006.54")


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity"])
def test_conversion_rejects_non_finite_amount(db, amount):
    service = ExchangeRateService("admin")
    _register(service)
    with pytest.raises(InvalidExchangeRate):
        service.convert(
            Decimal(amount),
            from_currency="USD",
            to_currency="ARS",
            on_date=DAY,
            rate_type="oficial",
            side=ExchangeRate.SIDE_SELL,
            source="bcra",
        )


def test_conversion_can_pin_a_version(db):
    service = ExchangeRateService("admin")
    first = _register(service, sell_rate="1000.000000")
    _register(service, sell_rate="1100.000000")

    pinned = service.convert(
        Decimal("100"),
        from_currency="USD",
        to_currency="ARS",
        on_date=DAY,
        rate_type="oficial",
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
        version=1,
    )
    assert pinned.lookup.version == 1
    assert pinned.converted_amount == Decimal("100000.00")

    with pytest.raises(ExchangeRateNotFound):
        service.convert(
            Decimal("100"),
            from_currency="USD",
            to_currency="ARS",
            on_date=DAY,
            rate_type="oficial",
            side=ExchangeRate.SIDE_SELL,
            source="bcra",
            version=99,
        )


def test_decimal_precision_is_preserved(db):
    service = ExchangeRateService("admin")
    rate = Decimal("1234.567891")
    amount = Decimal("987654.321")
    registration = _register(
        service,
        buy_rate=rate,
        sell_rate=rate,
        base_currency="BRL",
        quote_currency="ARS",
    )
    assert registration.record.buy_rate == rate
    assert registration.record.sell_rate == rate

    lookup = service.get_exact(
        DAY,
        base_currency="BRL",
        quote_currency="ARS",
        rate_type="oficial",
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
    )
    assert lookup.value == rate

    converted = service.convert(
        amount,
        from_currency="BRL",
        to_currency="ARS",
        on_date=DAY,
        rate_type="oficial",
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
    )
    assert converted.converted_amount == quantize_money(amount * rate)


def _mysql_config() -> dict | None:
    host = os.getenv("FEMAG_TEST_MYSQL_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.getenv("FEMAG_TEST_MYSQL_PORT", "3306")),
        "user": os.getenv("FEMAG_TEST_MYSQL_USER", "root"),
        "password": os.getenv("FEMAG_TEST_MYSQL_PASSWORD", ""),
    }


@pytest.fixture()
def mysql_models():
    config = _mysql_config()
    if config is None:
        pytest.skip("MySQL de pruebas no configurado (FEMAG_TEST_MYSQL_*)")

    admin = pymysql.connect(**config, autocommit=True)
    database_name = f"femag_test_968_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    with admin.cursor() as cursor:
        cursor.execute(
            f"CREATE DATABASE `{database_name}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )

    database = MySQLDatabase(
        database_name,
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        charset="utf8mb4",
    )
    previous = database_proxy.obj
    bind_database(database)
    database.connect()
    try:
        database.create_tables([*ALL_MODELS, *SYNC_MODELS])
        yield database
    finally:
        database.close()
        bind_database(previous)
        try:
            with admin.cursor() as cursor:
                cursor.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
        finally:
            admin.close()


def _connection_id() -> int:
    row = database_proxy.obj.execute_sql("SELECT CONNECTION_ID()").fetchone()
    return int(row[0])


def _run_two_workers(functions) -> list[dict]:
    barrier = threading.Barrier(2)
    results: list[dict] = []

    def runner(function):
        try:
            barrier.wait(timeout=15)
            value = function()
            results.append(
                {
                    "ok": True,
                    "value": value,
                    "connection": _connection_id(),
                }
            )
        except Exception as exc:  # noqa: BLE001 - el test compara el tipo exacto
            results.append(
                {
                    "ok": False,
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "connection": _connection_id(),
                }
            )
        finally:
            database_proxy.obj.close()

    threads = [threading.Thread(target=runner, args=(fn,)) for fn in functions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert all(not thread.is_alive() for thread in threads), "hilo colgado"
    assert len(results) == 2, results
    return results


def _slow_audit(monkeypatch, delay: float = 0.4) -> None:
    original = AuditService.record

    def slow(self, **kwargs):
        time.sleep(delay)
        return original(self, **kwargs)

    monkeypatch.setattr(AuditService, "record", slow)


def test_mysql_schema_migration_creates_table_and_keeps_data(mysql_models):
    database = database_proxy.obj
    client = Client.create(
        name="Cliente migracion cotizaciones",
        cuit="30-70000968-1",
        iva_condition="RI",
    )
    table = ExchangeRate._meta.table_name
    database.execute_sql(f"DROP TABLE `{table}`")

    with pytest.raises(SchemaValidationError):
        validate_runtime_schema(database)

    ensure_runtime_schema(database)
    validate_runtime_schema(database)

    stored_client = Client.get_by_id(client.id)
    assert stored_client.name == "Cliente migracion cotizaciones"
    assert stored_client.cuit == "30-70000968-1"

    row = database.execute_sql(
        "SELECT engine FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name = %s",
        (table,),
    ).fetchone()
    assert row is not None and row[0].upper() == "INNODB"

    indexes = database.execute_sql(
        "SELECT index_name, non_unique, GROUP_CONCAT(column_name ORDER BY seq_in_index) "
        "FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND table_name = %s "
        "GROUP BY index_name, non_unique",
        (table,),
    ).fetchall()
    unique_columns = {
        columns
        for _name, non_unique, columns in indexes
        if int(non_unique) == 0
    }
    assert (
        "base_currency,quote_currency,rate_type,source,effective_date,version"
        in unique_columns
    )

    ensure_runtime_schema(database)
    validate_runtime_schema(database)


def test_mysql_same_quote_concurrent_is_one_record(mysql_models, monkeypatch):
    _slow_audit(monkeypatch)

    def register(user):
        return _register(ExchangeRateService(user))

    results = _run_two_workers(
        [lambda: register("A"), lambda: register("B")]
    )
    assert all(row["ok"] for row in results), results
    created = [row["value"].created for row in results]
    assert sorted(created) == [False, True]
    assert ExchangeRate.select().count() == 1
    assert ExchangeRate.get().version == 1
    assert len({row["connection"] for row in results}) == 2
    assert (
        AuditLog.select().where(AuditLog.module == "Cotizaciones").count() == 1
    )


def test_mysql_different_quotes_concurrent_create_versions(
    mysql_models, monkeypatch
):
    _slow_audit(monkeypatch)

    def register(user, sell):
        return _register(
            ExchangeRateService(user), sell_rate=sell
        )

    results = _run_two_workers(
        [
            lambda: register("A", "1000.000000"),
            lambda: register("B", "1100.000000"),
        ]
    )
    assert all(row["ok"] for row in results), results
    assert all(row["value"].created for row in results)
    records = list(ExchangeRate.select().order_by(ExchangeRate.version))
    assert [row.version for row in records] == [1, 2]
    assert len({row["connection"] for row in results}) == 2
    assert (
        AuditLog.select().where(AuditLog.module == "Cotizaciones").count() == 2
    )


def test_mysql_concurrent_corrections_preserve_all_versions(
    mysql_models, monkeypatch
):
    service = ExchangeRateService("admin")
    _register(service, sell_rate="1000.000000")
    _slow_audit(monkeypatch)

    def register(user, sell):
        return _register(
            ExchangeRateService(user), sell_rate=sell
        )

    results = _run_two_workers(
        [
            lambda: register("A", "1100.000000"),
            lambda: register("B", "1200.000000"),
        ]
    )
    assert all(row["ok"] for row in results), results
    assert all(row["value"].created for row in results)
    records = list(ExchangeRate.select().order_by(ExchangeRate.version))
    assert [row.version for row in records] == [1, 2, 3]
    assert len({row["connection"] for row in results}) == 2
    assert (
        AuditLog.select().where(AuditLog.module == "Cotizaciones").count() == 3
    )


def test_mysql_decimal_roundtrip_and_conversion(mysql_models):
    service = ExchangeRateService("admin")
    rate = Decimal("1234.567891")
    _register(service, sell_rate=rate)

    lookup = service.get_exact(
        DAY,
        base_currency="USD",
        quote_currency="ARS",
        rate_type="oficial",
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
    )
    assert lookup.value == rate
    converted = service.convert(
        Decimal("100"),
        from_currency="USD",
        to_currency="ARS",
        on_date=DAY,
        rate_type="oficial",
        side=ExchangeRate.SIDE_SELL,
        source="bcra",
    )
    assert converted.converted_amount == quantize_money(Decimal("100") * rate)
