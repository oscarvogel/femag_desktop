"""#970: persistencia y concurrencia de la importacion historica en MySQL."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pymysql
import pytest
from peewee import MySQLDatabase

from app.config.database import bind_database, database_proxy
from app.models import ALL_MODELS, SYNC_MODELS
from app.models.exchange_rates import ExchangeRate
from app.services.exchange_rate_history_import_service import (
    HistoricalExchangeRateImportService,
)
from app.services.exchange_rate_providers import ProviderOutcome, ProviderRate
from app.services.exchange_rate_service import ExchangeRateService

D1 = date(2026, 11, 19)
D2 = date(2026, 11, 20)
D3 = date(2026, 11, 21)
FETCHED = datetime(2026, 11, 27, 12, tzinfo=timezone.utc)


def _mysql_config():
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
    database_name = f"femag_test_970_{os.getpid()}_{uuid.uuid4().hex[:8]}"
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


class FakeProvider:
    name = "argentinadatos"

    def __init__(self, rates=()):
        self.rates = tuple(rates)

    def fetch_series(self, *, base_currency, rate_type, start_date, end_date):
        return ProviderOutcome(
            provider=self.name,
            rates=tuple(
                rate
                for rate in self.rates
                if rate.base_currency == base_currency
                and rate.rate_type == rate_type
                and start_date <= rate.effective_date <= end_date
            ),
        )


def _rate(effective, sell="1100.000000", source="argentinadatos"):
    return ProviderRate(
        base_currency="USD",
        quote_currency="ARS",
        effective_date=effective,
        rate_type="oficial",
        source=source,
        buy_rate=Decimal("1000.000000"),
        sell_rate=Decimal(sell),
        origin="historical_import",
        fetched_at=FETCHED,
    )


def _service(provider):
    return HistoricalExchangeRateImportService(provider=provider)


def _run_workers(functions):
    barrier = threading.Barrier(2)
    results = []

    def runner(function):
        try:
            barrier.wait(timeout=15)
            results.append({"ok": True, "value": function()})
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "ok": False,
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        finally:
            try:
                database_proxy.obj.close()
            except Exception:
                pass

    threads = [threading.Thread(target=runner, args=(fn,)) for fn in functions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert all(not thread.is_alive() for thread in threads), "hilo colgado"
    assert len(results) == 2, results
    return results


def test_mysql_import_and_idempotent_second_run(mysql_models):
    provider = FakeProvider([_rate(D2), _rate(D3, sell="1200.000000")])
    service = _service(provider)
    first = service.import_range(
        start_date=D2, end_date=D3, rate_types=("oficial",)
    )
    second = service.import_range(
        start_date=D2, end_date=D3, rate_types=("oficial",)
    )

    assert first.imported == 2
    assert second.imported == 0
    assert second.skipped_existing == 2
    assert ExchangeRate.select().count() == 2
    rows = list(ExchangeRate.select().order_by(ExchangeRate.effective_date))
    assert rows[0].buy_rate == Decimal("1000.000000")
    assert rows[1].sell_rate == Decimal("1200.000000")


def test_mysql_refresh_creates_version(mysql_models):
    provider = FakeProvider([_rate(D2, sell="1100.000000")])
    service = _service(provider)
    service.import_range(start_date=D2, end_date=D2, rate_types=("oficial",))

    provider.rates = (_rate(D2, sell="1300.000000"),)
    result = service.import_range(
        start_date=D2,
        end_date=D2,
        rate_types=("oficial",),
        refresh=True,
    )

    assert result.new_versions == 1
    rows = list(ExchangeRate.select().order_by(ExchangeRate.version))
    assert [row.version for row in rows] == [1, 2]
    assert rows[0].sell_rate == Decimal("1100.000000")
    assert rows[1].sell_rate == Decimal("1300.000000")


def test_mysql_concurrent_imports_are_idempotent(mysql_models):
    service_a = _service(FakeProvider([_rate(D2)]))
    service_b = _service(FakeProvider([_rate(D2)]))

    results = _run_workers(
        [
            lambda: service_a.import_range(
                start_date=D2, end_date=D2, rate_types=("oficial",)
            ).as_dict(),
            lambda: service_b.import_range(
                start_date=D2, end_date=D2, rate_types=("oficial",)
            ).as_dict(),
        ]
    )
    assert all(row["ok"] for row in results), results
    assert ExchangeRate.select().count() == 1
    assert ExchangeRate.get().version == 1
    assert sorted(row["value"]["imported"] for row in results) == [0, 1]


def test_mysql_does_not_replace_other_source(mysql_models):
    ExchangeRateService("admin").register(
        base_currency="USD",
        quote_currency="ARS",
        effective_date=D2,
        rate_type="oficial",
        buy_rate="1500.000000",
        sell_rate="1600.000000",
        source="dolarapi",
    )
    result = _service(FakeProvider([_rate(D2)])).import_range(
        start_date=D2, end_date=D2, rate_types=("oficial",)
    )

    assert result.imported == 0
    assert result.skipped_other_source == 1
    rows = list(ExchangeRate.select())
    assert len(rows) == 1
    assert rows[0].source == "dolarapi"
    assert rows[0].sell_rate == Decimal("1600.000000")
