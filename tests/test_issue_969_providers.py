"""#969: proveedores HTTP de cotizaciones, desacoplados del servicio #968."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from urllib import error

import pytest

from app.services.exchange_rate_providers import (
    ArgentinaDatosProvider,
    BnaProvider,
    DolarApiProvider,
    ProviderHTTPError,
    ProviderPayloadError,
    RateGap,
    UrllibHttpClient,
    ZONA_AR,
    _parse_iso_date,
)

TODAY = date(2026, 11, 27)
DAY = date(2026, 11, 26)
PREVIOUS = date(2026, 11, 25)


class FakeHttpClient:
    def __init__(self, *, json_payloads=None, text_payloads=None, errors=None):
        self.json_payloads = json_payloads or {}
        self.text_payloads = text_payloads or {}
        self.errors = errors or {}
        self.calls: list[tuple[str, str]] = []

    def get_json(self, url):
        self.calls.append(("json", url))
        if url in self.errors:
            raise self.errors[url]
        if url not in self.json_payloads:
            raise AssertionError(f"URL JSON no preparada: {url}")
        return self.json_payloads[url]

    def get_text(self, url, *, headers=None):
        self.calls.append(("text", url))
        if url in self.errors:
            raise self.errors[url]
        if url not in self.text_payloads:
            raise AssertionError(f"URL texto no preparada: {url}")
        return self.text_payloads[url]


def _dolar_item(casa, compra="1575", venta="1625", fecha="2026-11-26T18:00:00.000Z"):
    return {
        "moneda": "USD",
        "casa": casa,
        "nombre": casa,
        "compra": compra,
        "venta": venta,
        "fechaActualizacion": fecha,
    }


DOLARES = [
    _dolar_item("oficial"),
    _dolar_item("blue", "1690", "1710"),
    _dolar_item("bolsa", "1657.2", "1666.4"),
    _dolar_item("contadoconliqui", "1765.6", "1767.9"),
    _dolar_item("mayorista", "1592.5", "1601.5"),
    _dolar_item("tarjeta", "2047.5", "2112.5"),
    _dolar_item("cripto", "1747.94", "1752.96"),
]
BRL = {
    "moneda": "BRL",
    "casa": "oficial",
    "nombre": "Real Brasileño",
    "compra": 281.318,
    "venta": 281.4646,
    "fechaActualizacion": "2026-11-26T17:55:00.000Z",
}

DOLARAPI_DOLARES_URL = "https://rates.test/v1/dolares"
DOLARAPI_BRL_URL = "https://rates.test/v1/cotizaciones/brl"


def _dolarapi(client):
    return DolarApiProvider(client, base_url="https://rates.test")


def test_dolarapi_maps_types_dates_and_decimals():
    client = FakeHttpClient(
        json_payloads={
            DOLARAPI_DOLARES_URL: DOLARES,
            DOLARAPI_BRL_URL: BRL,
        }
    )
    outcome = _dolarapi(client).fetch(today=TODAY)

    assert outcome.errors == ()
    assert outcome.warnings == ()
    by_key = {(rate.base_currency, rate.rate_type): rate for rate in outcome.rates}
    assert set(by_key) == {
        ("USD", "oficial"),
        ("USD", "blue"),
        ("USD", "mep"),
        ("USD", "ccl"),
        ("USD", "mayorista"),
        ("USD", "tarjeta"),
        ("BRL", "oficial"),
    }
    assert ("USD", "cripto") not in by_key
    assert by_key[("USD", "oficial")].effective_date == DAY
    assert by_key[("USD", "oficial")].buy_rate == Decimal("1575")
    assert by_key[("USD", "mep")].sell_rate == Decimal("1666.4")
    assert by_key[("BRL", "oficial")].sell_rate == Decimal("281.4646")
    assert by_key[("USD", "oficial")].source == "dolarapi"
    assert by_key[("USD", "oficial")].origin == "api"
    assert by_key[("USD", "oficial")].fetched_at is not None


def test_dolarapi_uses_argentina_date_for_utc_timestamp():
    client = FakeHttpClient(
        json_payloads={
            DOLARAPI_DOLARES_URL: [
                _dolar_item(
                    "oficial",
                    fecha="2026-11-26T02:30:00.000Z",
                )
            ],
            DOLARAPI_BRL_URL: BRL,
        }
    )
    outcome = _dolarapi(client).fetch(today=TODAY)
    oficial = next(rate for rate in outcome.rates if rate.rate_type == "oficial")
    assert oficial.effective_date == PREVIOUS


def test_dolarapi_missing_side_is_not_invented():
    broken = _dolar_item("blue")
    broken.pop("compra")
    client = FakeHttpClient(
        json_payloads={
            DOLARAPI_DOLARES_URL: [broken, _dolar_item("oficial")],
            DOLARAPI_BRL_URL: BRL,
        }
    )
    outcome = _dolarapi(client).fetch(today=TODAY)
    types = {(rate.base_currency, rate.rate_type) for rate in outcome.rates}
    assert ("USD", "blue") not in types
    assert ("USD", "oficial") in types
    assert any("blue" in warning and "compra" in warning for warning in outcome.warnings)


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", None])
def test_dolarapi_invalid_rates_are_skipped(value):
    client = FakeHttpClient(
        json_payloads={
            DOLARAPI_DOLARES_URL: [
                _dolar_item("blue", value, "1710"),
                _dolar_item("oficial"),
            ],
            DOLARAPI_BRL_URL: BRL,
        }
    )
    outcome = _dolarapi(client).fetch(today=TODAY)
    types = {(rate.base_currency, rate.rate_type) for rate in outcome.rates}
    assert ("USD", "blue") not in types
    assert ("USD", "oficial") in types
    assert outcome.warnings


def test_dolarapi_invalid_and_future_dates_are_skipped():
    client = FakeHttpClient(
        json_payloads={
            DOLARAPI_DOLARES_URL: [
                _dolar_item("oficial", fecha="no-es-fecha"),
                _dolar_item("blue", fecha="2026-11-28T12:00:00.000Z"),
                _dolar_item("bolsa", fecha="2026-11-26T18:00:00.000Z"),
            ],
            DOLARAPI_BRL_URL: BRL,
        }
    )
    outcome = _dolarapi(client).fetch(today=TODAY)
    types = {rate.rate_type for rate in outcome.rates}
    assert types == {"mep", "oficial"}  # BRL oficial + USD mep
    assert len(outcome.warnings) >= 2


def test_dolarapi_partial_endpoint_failure_keeps_other_data():
    client = FakeHttpClient(
        json_payloads={DOLARAPI_BRL_URL: BRL},
        errors={
            DOLARAPI_DOLARES_URL: ProviderHTTPError(
                "HTTP 500", status=500, retryable=True
            )
        },
    )
    outcome = _dolarapi(client).fetch(today=TODAY)
    assert len(outcome.rates) == 1
    assert outcome.rates[0].base_currency == "BRL"
    assert any("500" in message for message in outcome.errors)


def test_dolarapi_total_failure_reports_errors():
    client = FakeHttpClient(
        errors={
            DOLARAPI_DOLARES_URL: ProviderHTTPError("timeout", retryable=True),
            DOLARAPI_BRL_URL: ProviderHTTPError("timeout", retryable=True),
        }
    )
    outcome = _dolarapi(client).fetch(today=TODAY)
    assert outcome.rates == ()
    assert len(outcome.errors) == 2


def _bna_html(rows):
    body = "".join(
        "<tr>"
        + "".join(f"<td>{cell}</td>" for cell in row)
        + "</tr>"
        for row in rows
    )
    return (
        "<table><thead><tr><th>Monedas</th><th>Compra</th>"
        "<th>Venta</th><th>Fecha</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


BNA_URL_25 = (
    "https://bna.test/Cotizador/HistoricoPrincipales?"
    "id=billetes&fecha=25%2F11%2F2026&idMoneda=22&idMoneda=23"
)
BNA_URL_26 = (
    "https://bna.test/Cotizador/HistoricoPrincipales?"
    "id=billetes&fecha=26%2F11%2F2026&idMoneda=22&idMoneda=23"
)
BNA_URL_27 = (
    "https://bna.test/Cotizador/HistoricoPrincipales?"
    "id=billetes&fecha=27%2F11%2F2026&idMoneda=22&idMoneda=23"
)


def _bna(client):
    return BnaProvider(client, base_url="https://bna.test", lookback_days=7)


def test_bna_parses_usd_and_brl_and_divides_real_by_100():
    html = _bna_html(
        [
            ["Dolar U.S.A", "1580,0000", "1630,0000", "25/11/2026"],
            ["Dolar U.S.A", "1575,0000", "1625,0000", "26/11/2026"],
            ["Real (*)", "26100,0000", "29100,0000", "26/11/2026"],
        ]
    )
    client = FakeHttpClient(text_payloads={BNA_URL_26: html})
    outcome = _bna(client).fetch(today=DAY)
    by_key = {(rate.base_currency, rate.effective_date): rate for rate in outcome.rates}
    assert by_key[("USD", PREVIOUS)].sell_rate == Decimal("1630.0000")
    assert by_key[("USD", DAY)].buy_rate == Decimal("1575.0000")
    assert by_key[("BRL", DAY)].buy_rate == Decimal("261.0000")
    assert by_key[("BRL", DAY)].sell_rate == Decimal("291.0000")
    assert by_key[("USD", DAY)].rate_type == "bna"
    assert by_key[("USD", DAY)].source == "bna"
    assert by_key[("USD", DAY)].origin == "scrape"


def test_bna_never_uses_a_later_date():
    html = _bna_html(
        [
            ["Dolar U.S.A", "1575,0000", "1625,0000", "26/11/2026"],
            ["Dolar U.S.A", "2000,0000", "2100,0000", "27/11/2026"],
        ]
    )
    client = FakeHttpClient(text_payloads={BNA_URL_26: html})
    outcome = _bna(client).fetch(today=DAY)
    assert [rate.effective_date for rate in outcome.rates] == [DAY]


def test_bna_no_data_is_a_warning_not_an_error():
    client = FakeHttpClient(
        text_payloads={
            BNA_URL_27: (
                "<html><body>No hay cotizaciones pendientes para esa fecha."
                "</body></html>"
            )
        }
    )
    outcome = _bna(client).fetch(today=TODAY)
    assert outcome.rates == ()
    assert outcome.errors == ()
    assert any("no publico" in warning for warning in outcome.warnings)


def test_bna_unexpected_html_is_reported():
    client = FakeHttpClient(text_payloads={BNA_URL_27: "<html>cambio</html>"})
    outcome = _bna(client).fetch(today=TODAY)
    assert outcome.rates == ()
    assert outcome.errors == ()
    assert any("tabla" in warning for warning in outcome.warnings)


def test_bna_http_error_is_reported_and_other_dates_continue():
    good = _bna_html([["Dolar U.S.A", "1575,0000", "1625,0000", "26/11/2026"]])
    client = FakeHttpClient(
        text_payloads={BNA_URL_26: good},
        errors={BNA_URL_25: ProviderHTTPError("HTTP 503", status=503)},
    )
    outcome = _bna(client).fetch(
        today=DAY,
        missing=frozenset(
            {RateGap("USD", "ARS", "bna", PREVIOUS)}
        ),
    )
    assert [rate.effective_date for rate in outcome.rates] == [DAY]
    assert any("503" in message for message in outcome.errors)


def test_bna_skips_rows_older_than_lookback():
    html = _bna_html([["Dolar U.S.A", "1000,0000", "1100,0000", "01/01/2020"]])
    client = FakeHttpClient(text_payloads={BNA_URL_27: html})
    outcome = _bna(client).fetch(today=TODAY)
    assert outcome.rates == ()


def _argentinadatos_url(casa, requested=DAY):
    return (
        "https://ad.test/v1/cotizaciones/dolares/"
        f"{casa}/{requested.year:04d}/{requested.month:02d}/{requested.day:02d}"
    )


def _ad(client):
    return ArgentinaDatosProvider(client, base_url="https://ad.test")


def test_argentinadatos_fetches_exact_dates_and_maps_mep_ccl():
    payloads = {
        _argentinadatos_url("oficial"): {
            "casa": "oficial",
            "compra": 1580,
            "venta": 1630,
            "fecha": "2026-11-26",
        },
        _argentinadatos_url("bolsa"): {
            "casa": "bolsa",
            "compra": 1664,
            "venta": 1688.7,
            "fecha": "2026-11-26",
        },
        _argentinadatos_url("contadoconliqui"): {
            "casa": "contadoconliqui",
            "compra": 1765.6,
            "venta": 1767.9,
            "fecha": "2026-11-26",
        },
    }
    client = FakeHttpClient(json_payloads=payloads)
    missing = frozenset(
        {
            RateGap("USD", "ARS", "oficial", DAY),
            RateGap("USD", "ARS", "mep", DAY),
            RateGap("USD", "ARS", "ccl", DAY),
        }
    )
    outcome = _ad(client).fetch(today=TODAY, missing=missing)

    assert outcome.errors == ()
    assert outcome.warnings == ()
    by_type = {rate.rate_type: rate for rate in outcome.rates}
    assert by_type["oficial"].sell_rate == Decimal("1630")
    assert by_type["mep"].sell_rate == Decimal("1688.7")
    assert by_type["ccl"].buy_rate == Decimal("1765.6")
    assert by_type["oficial"].source == "argentinadatos"
    assert by_type["oficial"].origin == "historical_import"
    assert any("bolsa" in url for _kind, url in client.calls)


def test_argentinadatos_rejects_a_different_date():
    client = FakeHttpClient(
        json_payloads={
            _argentinadatos_url("oficial"): {
                "casa": "oficial",
                "compra": 1565,
                "venta": 1615,
                "fecha": "2026-11-25",
            }
        }
    )
    outcome = _ad(client).fetch(
        today=TODAY,
        missing=frozenset({RateGap("USD", "ARS", "oficial", DAY)}),
    )
    assert outcome.rates == ()
    assert any("se descarta" in warning for warning in outcome.warnings)


def test_argentinadatos_404_is_a_warning():
    client = FakeHttpClient(
        errors={
            _argentinadatos_url("oficial"): ProviderHTTPError(
                "HTTP 404", status=404
            )
        }
    )
    outcome = _ad(client).fetch(
        today=TODAY,
        missing=frozenset({RateGap("USD", "ARS", "oficial", DAY)}),
    )
    assert outcome.rates == ()
    assert outcome.errors == ()
    assert any("sin dato" in warning for warning in outcome.warnings)


def test_argentinadatos_weekend_or_holiday_without_data_is_a_warning():
    saturday = date(2026, 11, 28)
    client = FakeHttpClient(
        errors={
            _argentinadatos_url("blue", saturday): ProviderHTTPError(
                "HTTP 404", status=404
            )
        }
    )
    outcome = _ad(client).fetch(
        today=date(2026, 11, 30),
        missing=frozenset({RateGap("USD", "ARS", "blue", saturday)}),
    )
    assert outcome.rates == ()
    assert outcome.errors == ()
    assert any("sin dato" in warning for warning in outcome.warnings)


def test_argentinadatos_500_and_invalid_payload_are_errors():
    client = FakeHttpClient(
        errors={
            _argentinadatos_url("oficial"): ProviderHTTPError(
                "HTTP 500", status=500, retryable=True
            )
        },
        json_payloads={
            _argentinadatos_url("blue"): {"error": "Not found"},
        },
    )
    outcome = _ad(client).fetch(
        today=TODAY,
        missing=frozenset(
            {
                RateGap("USD", "ARS", "oficial", DAY),
                RateGap("USD", "ARS", "blue", DAY),
            }
        ),
    )
    assert outcome.rates == ()
    assert any("500" in message for message in outcome.errors)
    assert any("Not found" in warning for warning in outcome.warnings)


def test_argentinadatos_brl_uses_its_own_endpoint():
    url = "https://ad.test/v1/cotizaciones/brl/2026/11/26"
    client = FakeHttpClient(
        json_payloads={
            url: {
                "moneda": "BRL",
                "casa": "oficial",
                "compra": 275.6705,
                "venta": 275.8111,
                "fecha": "2026-11-26",
            }
        }
    )
    outcome = _ad(client).fetch(
        today=TODAY,
        missing=frozenset({RateGap("BRL", "ARS", "oficial", DAY)}),
    )
    assert len(outcome.rates) == 1
    assert outcome.rates[0].base_currency == "BRL"
    assert outcome.rates[0].sell_rate == Decimal("275.8111")


def test_argentinadatos_without_missing_does_not_call_http():
    client = FakeHttpClient()
    outcome = _ad(client).fetch(today=TODAY)
    assert outcome.rates == ()
    assert client.calls == []


def test_parse_iso_date_keeps_plain_dates_and_converts_timestamps():
    assert _parse_iso_date("2026-11-26", "fecha") == DAY
    assert (
        _parse_iso_date("2026-11-26T02:30:00.000Z", "fecha") == PREVIOUS
    )
    assert (
        _parse_iso_date("2026-11-26T18:00:00.000Z", "fecha") == DAY
    )


class _FakeResponse:
    def __init__(self, body: bytes, charset: str | None = "utf-8"):
        self.body = body
        self.headers = self

    def get_content_charset(self):
        return self.charset

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _http_error(url, status):
    return error.HTTPError(url, status, "error", None, None)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_http_client_retries_transient_status_then_raises(status):
    calls = []
    sleeps = []

    def opener(_request, timeout):
        calls.append(timeout)
        raise _http_error("https://rates.test/x", status)

    client = UrllibHttpClient(
        timeout=7,
        retries=2,
        backoff=0.5,
        sleep=sleeps.append,
        opener=opener,
    )
    with pytest.raises(ProviderHTTPError) as captured:
        client.get_text("https://rates.test/x")
    assert captured.value.status == status
    assert captured.value.retryable is True
    assert calls == [7, 7, 7]
    assert sleeps == [0.5, 1.0]


def test_http_client_does_not_retry_400():
    calls = []

    def opener(_request, timeout):
        calls.append(timeout)
        raise _http_error("https://rates.test/x", 400)

    client = UrllibHttpClient(retries=2, sleep=lambda _s: None, opener=opener)
    with pytest.raises(ProviderHTTPError) as captured:
        client.get_text("https://rates.test/x")
    assert captured.value.status == 400
    assert captured.value.retryable is False
    assert calls == [15.0]


def test_http_client_retries_timeout_then_raises():
    calls = []

    def opener(_request, timeout):
        calls.append(timeout)
        raise TimeoutError("sin respuesta")

    client = UrllibHttpClient(
        retries=1, sleep=lambda _s: None, opener=opener
    )
    with pytest.raises(ProviderHTTPError) as captured:
        client.get_text("https://rates.test/x")
    assert captured.value.retryable is True
    assert len(calls) == 2


def test_http_client_invalid_json_is_not_retried():
    calls = []

    def opener(_request, timeout):
        calls.append(timeout)
        return _FakeResponse(b"{no-json")

    client = UrllibHttpClient(retries=2, sleep=lambda _s: None, opener=opener)
    with pytest.raises(ProviderPayloadError):
        client.get_json("https://rates.test/x")
    assert len(calls) == 1


def test_http_client_parses_json_numbers_as_decimal():
    def opener(_request, timeout):
        return _FakeResponse(b'{"compra": 1657.2, "venta": 1666.4}')

    client = UrllibHttpClient(opener=opener)
    payload = client.get_json("https://rates.test/x")
    assert payload == {
        "compra": Decimal("1657.2"),
        "venta": Decimal("1666.4"),
    }


@pytest.mark.skipif(
    os.getenv("FEMAG_RUN_LIVE_RATE_TESTS") != "1",
    reason="prueba HTTP real: definir FEMAG_RUN_LIVE_RATE_TESTS=1",
)
def test_live_dolarapi_and_bna_http():
    today = datetime.now(ZONA_AR).date()
    client = UrllibHttpClient(timeout=20)
    dolarapi = DolarApiProvider(client).fetch(today=today)
    assert not dolarapi.errors, dolarapi.errors
    assert any(
        rate.base_currency == "USD" and rate.rate_type == "oficial"
        for rate in dolarapi.rates
    )

    bna = BnaProvider(client).fetch(today=today)
    assert not bna.errors, bna.errors
    assert any(
        rate.base_currency == "USD" and rate.rate_type == "bna"
        for rate in bna.rates
    )

    yesterday = today - timedelta(days=1)
    ad = ArgentinaDatosProvider(client)
    outcome = ad.fetch(
        today=today,
        missing=frozenset(
            {
                RateGap("USD", "ARS", "oficial", yesterday),
                RateGap("USD", "ARS", "blue", yesterday),
            }
        ),
    )
    assert not outcome.errors, outcome.errors
    assert outcome.rates or outcome.warnings
