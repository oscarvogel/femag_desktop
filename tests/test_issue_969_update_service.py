"""#969: orquestacion, lock, idempotencia y estado de la actualizacion diaria."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.exchange_rates import ExchangeRate
from app.models.system import AppParameter
from app.services.exchange_rate_providers import (
    ProviderHTTPError,
    ProviderOutcome,
    ProviderRate,
    RateGap,
)
from app.services.exchange_rate_service import ExchangeRateService
from app.services.exchange_rate_update_service import (
    LAST_ATTEMPT_AT_KEY,
    LAST_ATTEMPT_STATUS_KEY,
    LAST_ERROR_KEY,
    LAST_SUCCESS_AT_KEY,
    STATUS_DRY_RUN,
    STATUS_ERROR,
    STATUS_LOCKED,
    STATUS_OK,
    STATUS_PARTIAL,
    ExchangeRateUpdateService,
    FileJobLock,
)

TODAY = date(2026, 11, 27)
DAY = date(2026, 11, 26)
PREVIOUS = date(2026, 11, 25)


def _rate(
    *,
    base="USD",
    rate_type="oficial",
    effective=DAY,
    buy="1000.000000",
    sell="1100.000000",
    source="fake",
    origin="api",
):
    return ProviderRate(
        base_currency=base,
        quote_currency="ARS",
        effective_date=effective,
        rate_type=rate_type,
        source=source,
        buy_rate=Decimal(buy),
        sell_rate=Decimal(sell),
        origin=origin,
        fetched_at=datetime(2026, 11, 27, 12, tzinfo=timezone.utc),
    )


class FakeProvider:
    def __init__(self, name, *, rates=(), errors=(), warnings=(), raises=None):
        self.name = name
        self.rates = tuple(rates)
        self.errors = tuple(errors)
        self.warnings = tuple(warnings)
        self.raises = raises
        self.calls: list[frozenset[RateGap]] = []

    def fetch(self, *, today, missing=frozenset()):
        self.calls.append(frozenset(missing))
        if self.raises is not None:
            raise self.raises
        return ProviderOutcome(
            provider=self.name,
            rates=self.rates,
            errors=self.errors,
            warnings=self.warnings,
        )


def _service(tmp_path, *, live=None, history=None, clock=None):
    return ExchangeRateUpdateService(
        providers=live or [],
        history_providers=history or [],
        lock_path=tmp_path / "rates.lock",
        clock=clock,
    )


def _parameter(key):
    row = AppParameter.get_or_none(AppParameter.key == key)
    return row.value if row is not None else None


def test_run_registers_live_and_history_rates(db, tmp_path):
    live = FakeProvider("live", rates=[_rate()])
    history = FakeProvider(
        "history",
        rates=[_rate(rate_type="blue", effective=PREVIOUS, source="history")],
        warnings=("sin dato para un feriado",),
    )
    result = _service(tmp_path, live=[live], history=[history]).run(
        today=TODAY, lookback_days=2
    )

    assert result.status == STATUS_OK
    assert result.registered == 2
    assert result.failed == 0
    assert ExchangeRate.select().count() == 2
    assert _parameter(LAST_SUCCESS_AT_KEY) is not None
    assert _parameter(LAST_ATTEMPT_STATUS_KEY) == STATUS_OK
    assert "sin dato" in result.warnings[0]


def test_repeated_run_is_idempotent(db, tmp_path):
    live = FakeProvider("live", rates=[_rate()])
    service = _service(tmp_path, live=[live], history=[])
    first = service.run(today=TODAY, lookback_days=2)
    second = service.run(today=TODAY, lookback_days=2)

    assert first.registered == 1
    assert second.registered == 0
    assert second.unchanged == 1
    assert ExchangeRate.select().count() == 1
    assert ExchangeRate.get().version == 1


def test_correction_creates_version_and_preserves_history(db, tmp_path):
    live = FakeProvider("live", rates=[_rate(sell="1100.000000")])
    service = _service(tmp_path, live=[live], history=[])
    service.run(today=TODAY, lookback_days=2)
    live.rates = (_rate(sell="1200.000000"),)
    second = service.run(today=TODAY, lookback_days=2)

    assert second.registered == 1
    rows = list(ExchangeRate.select().order_by(ExchangeRate.version))
    assert [row.version for row in rows] == [1, 2]
    assert rows[0].sell_rate == Decimal("1100.000000")
    assert rows[1].sell_rate == Decimal("1200.000000")


def test_partial_provider_failure_keeps_data_and_marks_partial(db, tmp_path):
    live = FakeProvider("live", rates=[_rate()])
    history = FakeProvider(
        "history",
        errors=("HTTP 500",),
    )
    result = _service(tmp_path, live=[live], history=[history]).run(
        today=TODAY, lookback_days=2
    )

    assert result.status == STATUS_PARTIAL
    assert result.registered == 1
    assert ExchangeRate.select().count() == 1
    assert any("500" in message for message in result.errors)


def test_all_providers_fail_without_internet_preserves_existing(db, tmp_path):
    live = FakeProvider("live", rates=[_rate()])
    service = _service(tmp_path, live=[live], history=[])
    service.run(today=TODAY, lookback_days=2)
    last_success = _parameter(LAST_SUCCESS_AT_KEY)

    live.raises = ProviderHTTPError("sin internet", retryable=True)
    result = service.run(today=TODAY, lookback_days=2)

    assert result.status == STATUS_ERROR
    assert result.registered == 0
    assert ExchangeRate.select().count() == 1
    assert _parameter(LAST_SUCCESS_AT_KEY) == last_success
    assert "sin internet" in (_parameter(LAST_ERROR_KEY) or "")


def test_recovery_after_failure_registers_data(db, tmp_path):
    live = FakeProvider("live", raises=ProviderHTTPError("sin red"))
    service = _service(tmp_path, live=[live], history=[])
    failed = service.run(today=TODAY, lookback_days=2)
    assert failed.status == STATUS_ERROR

    live.raises = None
    live.rates = (_rate(),)
    recovered = service.run(today=TODAY, lookback_days=2)

    assert recovered.status == STATUS_OK
    assert recovered.registered == 1
    assert ExchangeRate.select().count() == 1


def test_gap_recovery_only_requests_previous_missing_days(db, tmp_path):
    service = ExchangeRateService("admin")
    service.register(
        base_currency="USD",
        quote_currency="ARS",
        effective_date=PREVIOUS,
        rate_type="oficial",
        buy_rate="1500",
        sell_rate="1600",
        source="live",
    )
    live = FakeProvider("live", rates=[])
    history = FakeProvider("history", rates=[])
    _service(tmp_path, live=[live], history=[history]).run(
        today=TODAY, lookback_days=3
    )

    missing = history.calls[0]
    assert RateGap("USD", "ARS", "oficial", TODAY) not in missing
    assert RateGap("USD", "ARS", "oficial", PREVIOUS) not in missing
    assert RateGap("USD", "ARS", "oficial", DAY) in missing
    assert RateGap("USD", "ARS", "oficial", TODAY - timedelta(days=3)) in missing
    assert RateGap("USD", "ARS", "blue", DAY) in missing


def test_lock_prevents_a_second_job(db, tmp_path):
    lock_path = tmp_path / "rates.lock"
    holder = FileJobLock(lock_path)
    assert holder.acquire() is True
    try:
        result = _service(tmp_path, live=[FakeProvider("live", rates=[_rate()])]).run(
            today=TODAY, lookback_days=2
        )
        assert result.status == STATUS_LOCKED
        assert result.locked is True
        assert ExchangeRate.select().count() == 0
    finally:
        holder.release()

    retry = _service(tmp_path, live=[FakeProvider("live", rates=[_rate()])]).run(
        today=TODAY, lookback_days=2
    )
    assert retry.status == STATUS_OK
    assert retry.registered == 1


def test_stale_lock_is_recovered_after_a_crash(db, tmp_path):
    lock_path = tmp_path / "rates.lock"
    lock_path.write_text(
        json.dumps({"pid": 999999, "started_at": "2026-01-01T00:00:00+00:00"}),
        encoding="utf-8",
    )
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).timestamp()
    os.utime(lock_path, (old, old))

    result = _service(tmp_path, live=[FakeProvider("live", rates=[_rate()])]).run(
        today=TODAY, lookback_days=2
    )
    assert result.status == STATUS_OK
    assert result.registered == 1
    assert not lock_path.exists()


def test_dry_run_does_not_persist_or_record_status(db, tmp_path):
    result = _service(
        tmp_path, live=[FakeProvider("live", rates=[_rate()])]
    ).run(today=TODAY, lookback_days=2, dry_run=True)

    assert result.status == STATUS_DRY_RUN
    assert result.dry_run is True
    assert result.registered == 0
    assert ExchangeRate.select().count() == 0
    assert _parameter(LAST_ATTEMPT_AT_KEY) is None


def test_last_success_and_last_error_are_tracked(db, tmp_path):
    live = FakeProvider("live", rates=[_rate()])
    service = _service(tmp_path, live=[live], history=[])
    service.run(today=TODAY, lookback_days=2)
    success_at = _parameter(LAST_SUCCESS_AT_KEY)
    summary = json.loads(_parameter("exchange_rate.last_success_summary"))
    assert summary["status"] == STATUS_OK
    assert summary["providers"][0]["provider"] == "live"

    live.raises = ProviderHTTPError("caida", retryable=True)
    service.run(today=TODAY, lookback_days=2)
    assert _parameter(LAST_SUCCESS_AT_KEY) == success_at
    assert "caida" in (_parameter(LAST_ERROR_KEY) or "")


def test_sources_are_independent_and_do_not_overwrite(db, tmp_path):
    live = FakeProvider("live", rates=[_rate(source="live")])
    history = FakeProvider(
        "history", rates=[_rate(source="history", sell="1200.000000")]
    )
    _service(tmp_path, live=[live], history=[history]).run(
        today=TODAY, lookback_days=2
    )

    rows = list(ExchangeRate.select().order_by(ExchangeRate.source))
    assert len(rows) == 2
    assert {row.source for row in rows} == {"live", "history"}
    assert {row.sell_rate for row in rows} == {
        Decimal("1100.000000"),
        Decimal("1200.000000"),
    }


def test_decimal_precision_is_preserved(db, tmp_path):
    exact = Decimal("1234.567891")
    _service(
        tmp_path,
        live=[FakeProvider("live", rates=[_rate(buy=exact, sell=exact)])],
    ).run(today=TODAY, lookback_days=2)
    stored = ExchangeRate.get()
    assert stored.buy_rate == exact
    assert stored.sell_rate == exact


def test_scrape_origin_is_persisted(db, tmp_path):
    rate = _rate(
        source="bna",
        rate_type="bna",
        origin="scrape",
    )
    result = _service(
        tmp_path, live=[FakeProvider("bna", rates=[rate])]
    ).run(today=TODAY, lookback_days=0)

    assert result.registered == 1
    assert ExchangeRate.get().origin == "scrape"


def test_no_data_is_not_an_error_and_does_not_mark_success(db, tmp_path):
    history = FakeProvider(
        "history",
        rates=[],
        warnings=("fin de semana sin publicacion",),
    )
    result = _service(tmp_path, live=[], history=[history]).run(
        today=TODAY, lookback_days=1
    )

    assert result.status == STATUS_OK
    assert result.registered == 0
    assert result.warnings
    assert ExchangeRate.select().count() == 0
    assert _parameter(LAST_SUCCESS_AT_KEY) is None


def test_unexpected_provider_exception_is_contained(db, tmp_path):
    live = FakeProvider("live", raises=RuntimeError("bug inesperado"))
    result = _service(tmp_path, live=[live], history=[]).run(
        today=TODAY, lookback_days=2
    )
    assert result.status == STATUS_ERROR
    assert any("bug inesperado" in message for message in result.errors)


def test_should_run_daily_bootstraps_and_waits_for_next_evening(db):
    from app.services.exchange_rate_update_service import should_run_daily

    evening = datetime(2026, 11, 28, 22, 0, tzinfo=timezone.utc)  # 19:00 ART
    assert should_run_daily(now=evening) is True
    AppParameter.create(key=LAST_SUCCESS_AT_KEY, value=evening.isoformat())
    assert should_run_daily(now=evening + timedelta(minutes=5)) is False
    next_morning = datetime(2026, 11, 29, 10, 0, tzinfo=timezone.utc)
    assert should_run_daily(now=next_morning) is False
    next_evening = datetime(2026, 11, 29, 22, 30, tzinfo=timezone.utc)
    assert should_run_daily(now=next_evening) is True


def test_should_run_daily_retries_a_failed_attempt_after_30_minutes(db):
    from app.services.exchange_rate_update_service import should_run_daily

    attempt = datetime(2026, 11, 28, 22, 0, tzinfo=timezone.utc)
    AppParameter.create(key=LAST_ATTEMPT_AT_KEY, value=attempt.isoformat())
    assert should_run_daily(now=attempt + timedelta(minutes=10)) is False
    assert should_run_daily(now=attempt + timedelta(minutes=31)) is True
