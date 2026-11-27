"""#970: importacion historica, cobertura y conciliacion con presupuestos."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.budgets import Budget
from app.models.exchange_rates import ExchangeRate
from app.models.masters import Client
from app.services.exchange_rate_history_import_service import (
    HistoricalExchangeRateImportService,
    HistoricalImportError,
    STATUS_DRY_RUN,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_PARTIAL,
)
from app.services.exchange_rate_providers import (
    ArgentinaDatosProvider,
    ProviderHTTPError,
    ProviderOutcome,
    ProviderRate,
    UrllibHttpClient,
)
from app.services.exchange_rate_service import ExchangeRateService

D1 = date(2026, 11, 19)
D2 = date(2026, 11, 20)
D3 = date(2026, 11, 21)
D4 = date(2026, 11, 22)
D5 = date(2026, 11, 23)
D6 = date(2026, 11, 24)
D7 = date(2026, 11, 25)
FETCHED = datetime(2026, 11, 27, 12, tzinfo=timezone.utc)


class FakeSeriesProvider:
    name = "argentinadatos"

    def __init__(self, series=None, errors=None, raises=None):
        self.series = series or {}
        self.errors = errors or {}
        self.raises = raises
        self.calls: list[tuple[str, str, date, date]] = []

    def fetch_series(self, *, base_currency, rate_type, start_date, end_date):
        self.calls.append((base_currency, rate_type, start_date, end_date))
        if self.raises is not None:
            raise self.raises
        key = (base_currency, rate_type)
        if key in self.errors:
            return ProviderOutcome(
                provider=self.name,
                errors=(self.errors[key],),
            )
        rates = [
            item
            for item in self.series.get(key, ())
            if start_date <= item.effective_date <= end_date
        ]
        return ProviderOutcome(provider=self.name, rates=tuple(rates))


def _rate(
    effective,
    *,
    base="USD",
    rate_type="oficial",
    buy="1000.000000",
    sell="1100.000000",
    source="argentinadatos",
):
    return ProviderRate(
        base_currency=base,
        quote_currency="ARS",
        effective_date=effective,
        rate_type=rate_type,
        source=source,
        buy_rate=Decimal(buy),
        sell_rate=Decimal(sell),
        origin="historical_import",
        fetched_at=FETCHED,
    )


def _client():
    return Client.create(
        name="Cliente historico",
        cuit="30-70000970-1",
        iva_condition="RI",
    )


def _budget(client, issue_date, number):
    return Budget.create(
        budget_number=number,
        client=client,
        origin=Budget.ORIGIN_MANUAL,
        issue_date=issue_date,
    )


def _service(provider):
    return HistoricalExchangeRateImportService(provider=provider)


def test_audit_budgets_discovers_range_and_counts(db):
    client = _client()
    _budget(client, D2, 1)
    _budget(client, D2, 2)
    _budget(client, D7, 3)

    audit = _service(FakeSeriesProvider()).audit_budgets()

    assert audit.total_budgets == 3
    assert audit.distinct_dates == 2
    assert audit.first_date == D2
    assert audit.last_date == D7
    assert audit.count_by_date[D2] == 2
    assert audit.dates == (D2, D7)


def test_import_initial_and_second_run_is_idempotent(db):
    provider = FakeSeriesProvider(
        {("USD", "oficial"): [_rate(D2, buy="1000"), _rate(D5, buy="1100")]}
    )
    service = _service(provider)
    first = service.import_range(
        start_date=D2, end_date=D5, rate_types=("oficial",)
    )
    second = service.import_range(
        start_date=D2, end_date=D5, rate_types=("oficial",)
    )

    assert first.status == STATUS_OK
    assert first.imported == 2
    assert first.fetched == 2
    assert first.provider_requests == 1
    assert second.imported == 0
    assert second.skipped_existing == 2
    assert ExchangeRate.select().count() == 2
    assert provider.calls[0] == ("USD", "oficial", D2, D5)


def test_second_run_with_other_types_does_not_overwrite_source(db):
    ExchangeRateService("admin").register(
        base_currency="USD",
        quote_currency="ARS",
        effective_date=D2,
        rate_type="oficial",
        buy_rate="1500",
        sell_rate="1600",
        source="dolarapi",
    )
    provider = FakeSeriesProvider(
        {("USD", "oficial"): [_rate(D2, source="argentinadatos")]}
    )
    result = _service(provider).import_range(start_date=D2, end_date=D2)

    assert result.imported == 0
    assert result.skipped_other_source == 1
    rows = list(ExchangeRate.select().order_by(ExchangeRate.source))
    assert len(rows) == 1
    assert rows[0].source == "dolarapi"
    assert rows[0].sell_rate == Decimal("1600")


def test_refresh_correction_creates_a_new_version(db):
    provider = FakeSeriesProvider(
        {("USD", "oficial"): [_rate(D2, sell="1100")]}
    )
    service = _service(provider)
    service.import_range(start_date=D2, end_date=D2)

    provider.series[("USD", "oficial")] = [_rate(D2, sell="1200")]
    result = service.import_range(
        start_date=D2,
        end_date=D2,
        refresh=True,
    )

    assert result.imported == 0
    assert result.new_versions == 1
    rows = list(ExchangeRate.select().order_by(ExchangeRate.version))
    assert [row.version for row in rows] == [1, 2]
    assert rows[0].sell_rate == Decimal("1100")
    assert rows[1].sell_rate == Decimal("1200")


def test_refresh_without_changes_is_unchanged(db):
    provider = FakeSeriesProvider(
        {("USD", "oficial"): [_rate(D2, sell="1100")]}
    )
    service = _service(provider)
    service.import_range(start_date=D2, end_date=D2)
    result = service.import_range(
        start_date=D2,
        end_date=D2,
        refresh=True,
    )

    assert result.unchanged == 1
    assert result.new_versions == 0
    assert ExchangeRate.select().count() == 1


def test_max_records_allows_resume_without_duplicates(db):
    provider = FakeSeriesProvider(
        {
            ("USD", "oficial"): [
                _rate(D1),
                _rate(D2),
                _rate(D3),
                _rate(D4),
                _rate(D5),
            ]
        }
    )
    service = _service(provider)
    first = service.import_range(
        start_date=D1, end_date=D5, max_records=2
    )
    assert first.status == STATUS_PARTIAL
    assert first.imported == 2
    assert first.deferred == 3

    second = service.import_range(
        start_date=D1, end_date=D5, max_records=2
    )
    assert second.imported == 2
    assert second.deferred == 1

    third = service.import_range(
        start_date=D1, end_date=D5, max_records=2
    )
    assert third.imported == 1
    assert third.deferred == 0
    assert ExchangeRate.select().count() == 5


def test_dry_run_counts_without_writing(db):
    provider = FakeSeriesProvider(
        {("USD", "oficial"): [_rate(D2), _rate(D5)]}
    )
    result = _service(provider).import_range(
        start_date=D2, end_date=D5, dry_run=True, max_records=1
    )

    assert result.status == STATUS_DRY_RUN
    assert result.dry_run is True
    assert result.imported == 2
    assert ExchangeRate.select().count() == 0


def test_weekend_without_provider_rows_is_not_artificial(db):
    provider = FakeSeriesProvider(
        {("USD", "oficial"): [_rate(D2)]}
    )
    result = _service(provider).import_range(start_date=D2, end_date=D4)

    assert result.imported == 1
    assert ExchangeRate.select().count() == 1
    assert D3 in result.missing_publication
    assert D4 in result.missing_publication
    assert D3 not in result.missing_coverage


def test_holiday_is_classified_as_no_publication(db):
    holiday = D5
    provider = FakeSeriesProvider(
        {("USD", "oficial"): [_rate(D2)]}
    )
    result = _service(provider).import_range(
        start_date=D2,
        end_date=D5,
        holidays={holiday},
    )

    assert holiday in result.missing_publication
    assert holiday not in result.missing_coverage


def test_weekday_without_coverage_is_reported(db):
    provider = FakeSeriesProvider(
        {("USD", "oficial"): [_rate(D2), _rate(D5)]}
    )
    result = _service(provider).import_range(
        start_date=D2, end_date=D6
    )

    assert D3 in result.missing_publication
    assert D4 in result.missing_publication
    assert D6 in result.missing_coverage
    assert D6 not in result.missing_publication


def test_provider_error_keeps_other_type_data_and_marks_partial(db):
    provider = FakeSeriesProvider(
        {
            ("USD", "oficial"): [_rate(D2)],
            ("USD", "blue"): [],
        },
        errors={("USD", "blue"): "HTTP 500"},
    )
    result = _service(provider).import_range(
        start_date=D2,
        end_date=D2,
        rate_types=("oficial", "blue"),
    )

    assert result.status == STATUS_PARTIAL
    assert result.imported == 1
    assert any("500" in item for item in result.errors)
    assert ExchangeRate.select().count() == 1


def test_internet_failure_preserves_existing_rows(db):
    provider = FakeSeriesProvider(
        {("USD", "oficial"): [_rate(D2)]}
    )
    service = _service(provider)
    service.import_range(start_date=D2, end_date=D2)

    provider.raises = ProviderHTTPError("sin internet", retryable=True)
    result = service.import_range(start_date=D2, end_date=D2)

    assert result.status == STATUS_ERROR
    assert result.imported == 0
    assert ExchangeRate.select().count() == 1


def test_decimal_precision_is_preserved(db):
    exact = Decimal("1234.567891")
    provider = FakeSeriesProvider(
        {("USD", "oficial"): [_rate(D2, buy=exact, sell=exact)]}
    )
    _service(provider).import_range(start_date=D2, end_date=D2)

    stored = ExchangeRate.get()
    assert stored.buy_rate == exact
    assert stored.sell_rate == exact


def test_coverage_counts_exact_prior_and_missing_budgets(db):
    client = _client()
    _budget(client, D2, 1)
    _budget(client, D3, 2)
    _budget(client, date(2026, 1, 2), 3)
    service = _service(FakeSeriesProvider())
    ExchangeRateService("admin").register(
        base_currency="USD",
        quote_currency="ARS",
        effective_date=D1,
        rate_type="oficial",
        buy_rate="1000",
        sell_rate="1100",
        source="argentinadatos",
    )
    ExchangeRateService("admin").register(
        base_currency="USD",
        quote_currency="ARS",
        effective_date=D2,
        rate_type="oficial",
        buy_rate="1000",
        sell_rate="1100",
        source="argentinadatos",
    )

    coverage = service.coverage(source="argentinadatos")

    assert coverage.total_budgets == 3
    assert coverage.exact_budgets == 1
    assert coverage.prior_budgets == 1
    assert coverage.missing_budgets == 1
    assert coverage.exact_dates == (D2,)
    assert coverage.prior_dates == (D3,)
    assert coverage.missing_dates == (date(2026, 1, 2),)


def test_import_for_budgets_uses_discovered_range(db):
    client = _client()
    _budget(client, D2, 1)
    _budget(client, D4, 2)
    provider = FakeSeriesProvider(
        {("USD", "oficial"): [_rate(D2), _rate(D3), _rate(D4)]}
    )
    result = _service(provider).import_for_budgets(
        rate_types=("oficial",)
    )

    assert result.start_date == D2
    assert result.end_date == D4
    assert result.imported == 3
    assert result.budget_audit.total_budgets == 2
    assert result.coverage[0].exact_budgets == 2


def test_unsupported_source_is_rejected(db):
    with pytest.raises(HistoricalImportError):
        _service(FakeSeriesProvider()).import_range(
            start_date=D2,
            end_date=D2,
            source="bna",
        )


def test_max_requests_is_enforced_before_http(db):
    provider = FakeSeriesProvider()
    with pytest.raises(HistoricalImportError):
        _service(provider).import_range(
            start_date=D2,
            end_date=D2,
            rate_types=("oficial", "blue"),
            max_requests=1,
        )
    assert provider.calls == []


def test_brl_series_is_normalized_per_unit(db):
    provider = FakeSeriesProvider(
        {
            ("BRL", "oficial"): [
                _rate(D2, base="BRL", rate_type="oficial", buy="275.6705", sell="275.8111"),
            ]
        }
    )
    result = _service(provider).import_range(
        start_date=D2,
        end_date=D2,
        base_currency="BRL",
        rate_types=("oficial",),
    )
    assert result.imported == 1
    stored = ExchangeRate.get()
    assert stored.base_currency == "BRL"
    assert stored.sell_rate == Decimal("275.8111")


class _FakeHttp:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_json(self, url):
        self.calls.append(url)
        return self.payload

    def get_text(self, url, *, headers=None):
        raise AssertionError("no se esperaba texto")


def test_argentinadatos_fetch_series_filters_and_maps_decimal():
    payload = [
        {"casa": "oficial", "compra": 1000, "venta": 1100, "fecha": "2026-11-19"},
        {"casa": "oficial", "compra": 1010, "venta": 1110, "fecha": "2026-11-20"},
        {"casa": "oficial", "compra": 1020, "venta": 1120, "fecha": "2026-11-21"},
        {"casa": "blue", "compra": 2000, "venta": 2100, "fecha": "2026-11-20"},
    ]
    http = _FakeHttp(payload)
    provider = ArgentinaDatosProvider(http, base_url="https://ad.test")

    outcome = provider.fetch_series(
        base_currency="USD",
        rate_type="oficial",
        start_date=D2,
        end_date=D3,
    )

    assert [rate.effective_date for rate in outcome.rates] == [D2, D3]
    assert outcome.rates[0].buy_rate == Decimal("1010")
    assert outcome.rates[0].source == "argentinadatos"
    assert outcome.rates[0].origin == "historical_import"
    assert http.calls == ["https://ad.test/v1/cotizaciones/dolares/oficial"]


def test_argentinadatos_fetch_series_rejects_invalid_rows():
    payload = [
        {"casa": "oficial", "compra": None, "venta": 1100, "fecha": "2026-11-20"},
        {"casa": "oficial", "compra": 1000, "venta": 1100, "fecha": "mal"},
        {"casa": "oficial", "compra": 1000, "venta": 1100, "fecha": "2026-11-20"},
    ]
    outcome = ArgentinaDatosProvider(
        _FakeHttp(payload), base_url="https://ad.test"
    ).fetch_series(
        base_currency="USD",
        rate_type="oficial",
        start_date=D2,
        end_date=D2,
    )
    assert len(outcome.rates) == 1
    assert outcome.warnings


def test_argentinadatos_fetch_series_brl_endpoint():
    payload = [
        {
            "moneda": "BRL",
            "casa": "oficial",
            "compra": 275.6705,
            "venta": 275.8111,
            "fecha": "2026-11-20",
        }
    ]
    http = _FakeHttp(payload)
    outcome = ArgentinaDatosProvider(
        http, base_url="https://ad.test"
    ).fetch_series(
        base_currency="BRL",
        rate_type="oficial",
        start_date=D2,
        end_date=D2,
    )
    assert len(outcome.rates) == 1
    assert http.calls == ["https://ad.test/v1/cotizaciones/brl"]


def test_argentinadatos_fetch_series_http_error():
    class Broken:
        def get_json(self, url):
            raise ProviderHTTPError("HTTP 503", status=503, retryable=True)

    outcome = ArgentinaDatosProvider(
        Broken(), base_url="https://ad.test"
    ).fetch_series(
        base_currency="USD",
        rate_type="oficial",
        start_date=D2,
        end_date=D2,
    )
    assert outcome.rates == ()
    assert any("503" in item for item in outcome.errors)


def test_argentinadatos_fetch_series_rejects_non_list_payload():
    outcome = ArgentinaDatosProvider(
        _FakeHttp({"error": "raro"}), base_url="https://ad.test"
    ).fetch_series(
        base_currency="USD",
        rate_type="oficial",
        start_date=D2,
        end_date=D2,
    )
    assert outcome.rates == ()
    assert outcome.errors


@pytest.mark.skipif(
    os.getenv("FEMAG_RUN_LIVE_RATE_TESTS") != "1",
    reason="prueba HTTP real: definir FEMAG_RUN_LIVE_RATE_TESTS=1",
)
def test_live_argentinadatos_series():
    provider = ArgentinaDatosProvider(UrllibHttpClient(timeout=30))
    outcome = provider.fetch_series(
        base_currency="USD",
        rate_type="oficial",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 10),
    )
    assert not outcome.errors, outcome.errors
    assert outcome.rates
    assert all(
        date(2026, 11, 1) <= rate.effective_date <= date(2026, 11, 10)
        for rate in outcome.rates
    )
    assert all(rate.source == "argentinadatos" for rate in outcome.rates)
