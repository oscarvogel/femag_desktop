"""#969: persistencia, idempotencia y concurrencia en MySQL/MariaDB real."""

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
from app.services.exchange_rate_providers import ProviderOutcome, ProviderRate
from app.services.exchange_rate_update_service import (
    ExchangeRateUpdateService,
    STATUS_LOCKED,
    STATUS_OK,
)

TODAY = date(2026, 11, 27)
DAY = date(2026, 11, 26)


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
    database_name = f"femag_test_969_{os.getpid()}_{uuid.uuid4().hex[:8]}"
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
    def __init__(self, name="fake", rates=()):
        self.name = name
        self.rates = tuple(rates)

    def fetch(self, *, today, missing=frozenset()):
        return ProviderOutcome(provider=self.name, rates=self.rates)


def _rate(sell="1100.000000", source="fake", rate_type="oficial"):
    return ProviderRate(
        base_currency="USD",
        quote_currency="ARS",
        effective_date=DAY,
        rate_type=rate_type,
        source=source,
        buy_rate=Decimal("1000.000000"),
        sell_rate=Decimal(sell),
        origin="api",
        fetched_at=datetime(2026, 11, 27, 12, tzinfo=timezone.utc),
    )


def _service(tmp_path, rates, *, lock=True):
    return ExchangeRateUpdateService(
        providers=[FakeProvider(rates=rates)],
        history_providers=[],
        lock_path=tmp_path / ("rates.lock" if lock else "unused.lock"),
    )


def _run_workers(functions):
    barrier = threading.Barrier(2)
    results = []

    def runner(function):
        try:
            barrier.wait(timeout=15)
            results.append({"ok": True, "value": function()})
        except Exception as exc:  # noqa: BLE001 - el test compara el tipo
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


def test_mysql_persists_idempotent_and_versions(mysql_models, tmp_path):
    service = _service(tmp_path, [_rate()])
    first = service.run(today=TODAY, lookback_days=0)
    second = service.run(today=TODAY, lookback_days=0)

    assert first.status == STATUS_OK
    assert first.registered == 1
    assert second.status == STATUS_OK
    assert second.registered == 0
    assert second.unchanged == 1
    assert ExchangeRate.select().count() == 1
    assert ExchangeRate.get().version == 1

    corrector = _service(tmp_path, [_rate(sell="1200.000000")])
    third = corrector.run(today=TODAY, lookback_days=0)
    assert third.registered == 1
    rows = list(ExchangeRate.select().order_by(ExchangeRate.version))
    assert [row.version for row in rows] == [1, 2]
    assert rows[0].sell_rate == Decimal("1100.000000")
    assert rows[1].sell_rate == Decimal("1200.000000")


def test_mysql_decimal_roundtrip_and_source_independence(mysql_models, tmp_path):
    rates = [
        _rate(sell="1234.567891", source="dolarapi"),
        _rate(sell="1300.000000", source="argentinadatos"),
    ]
    result = _service(tmp_path, rates).run(today=TODAY, lookback_days=0)
    assert result.registered == 2

    rows = list(ExchangeRate.select().order_by(ExchangeRate.source))
    assert {row.source for row in rows} == {"dolarapi", "argentinadatos"}
    assert {row.sell_rate for row in rows} == {
        Decimal("1234.567891"),
        Decimal("1300.000000"),
    }


def test_mysql_two_jobs_with_same_lock_only_one_runs(mysql_models, tmp_path):
    service_a = _service(tmp_path, [_rate()])
    service_b = _service(tmp_path, [_rate()])

    results = _run_workers(
        [
            lambda: service_a.run(today=TODAY, lookback_days=0).status,
            lambda: service_b.run(today=TODAY, lookback_days=0).status,
        ]
    )
    assert all(row["ok"] for row in results), results
    statuses = sorted(row["value"] for row in results)
    assert statuses == [STATUS_LOCKED, STATUS_OK]
    assert ExchangeRate.select().count() == 1


def test_mysql_two_jobs_without_lock_are_idempotent(mysql_models, tmp_path):
    service_a = _service(tmp_path, [_rate()], lock=False)
    service_b = _service(tmp_path, [_rate()], lock=False)

    results = _run_workers(
        [
            lambda: service_a.run(
                today=TODAY, lookback_days=0, use_lock=False
            ).as_dict(),
            lambda: service_b.run(
                today=TODAY, lookback_days=0, use_lock=False
            ).as_dict(),
        ]
    )
    assert all(row["ok"] for row in results), results
    assert ExchangeRate.select().count() == 1
    assert ExchangeRate.get().version == 1
    assert sorted(row["value"]["registered"] for row in results) == [0, 1]
