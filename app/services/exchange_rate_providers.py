"""Proveedores HTTP de cotizaciones para el job central (#969).

Este modulo no conoce ``ExchangeRateService``: solo devuelve ``ProviderRate``
normalizados. La persistencia, el versionado y la idempotencia siguen siendo
responsabilidad de #968.

Convencion: ``base_currency`` es la moneda cotizada (1 unidad) y
``quote_currency`` la moneda del precio. ``USD/ARS`` son pesos por dolar.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any, Mapping, Protocol
from urllib import error, parse, request

from app.models.exchange_rates import ExchangeRate

#: Argentina es UTC-3 fijo (sin horario de verano desde 2009). Se evita
#: ``zoneinfo`` porque Windows no trae la base de zonas y ``tzdata`` no es
#: dependencia del proyecto.
ZONA_AR = timezone(timedelta(hours=-3))

#: Tipos de dolar que publica DolarAPI y que entran en el alcance del epic.
DOLARAPI_CASAS = {
    "oficial": "oficial",
    "blue": "blue",
    "bolsa": "mep",
    "contadoconliqui": "ccl",
    "mayorista": "mayorista",
    "tarjeta": "tarjeta",
}

#: Casa de ArgentinaDatos por tipo canonico. ArgentinaDatos conserva los
#: nombres de DolarAPI para ``bolsa`` y ``contadoconliqui``.
ARGENTINADATOS_CASAS = {
    "oficial": "oficial",
    "blue": "blue",
    "mep": "bolsa",
    "ccl": "contadoconliqui",
    "mayorista": "mayorista",
    "tarjeta": "tarjeta",
}

#: Types covered by each history source.
USD_RATE_TYPES = tuple(DOLARAPI_CASAS.values())
BNA_RATE_TYPE = "bna"


class ProviderError(RuntimeError):
    """Error controlado de un proveedor."""


class ProviderHTTPError(ProviderError):
    """Error HTTP. ``retryable`` indica si el cliente ya reintento."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class ProviderPayloadError(ProviderError):
    """La respuesta llego pero no tiene el formato esperado."""


class HttpClient(Protocol):
    def get_text(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> str: ...

    def get_json(self, url: str) -> Any: ...


class UrllibHttpClient:
    """Cliente HTTP minimo con timeout y reintentos acotados.

    Solo reintenta errores transitorios: timeout, error de red, 429 y 5xx.
    Un 4xx de validacion no se reitera. ``sleep`` se inyecta para que los
    tests no esperen.
    """

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        retries: int = 2,
        backoff: float = 0.5,
        sleep=time.sleep,
        opener=request.urlopen,
    ):
        self.timeout = float(timeout)
        self.retries = max(0, int(retries))
        self.backoff = max(0.0, float(backoff))
        self._sleep = sleep
        self._opener = opener

    def get_text(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> str:
        request_headers = {
            "Accept": "application/json, text/html;q=0.9, */*;q=0.1",
            "User-Agent": "FEMAG-Desktop/1.0 (cotizaciones)",
        }
        if headers:
            request_headers.update(headers)
        last_error: ProviderError | None = None
        for attempt in range(self.retries + 1):
            http_request = request.Request(url, headers=request_headers)
            try:
                with self._opener(http_request, timeout=self.timeout) as response:
                    payload = response.read()
                    charset = "utf-8"
                    try:
                        charset = response.headers.get_content_charset() or charset
                    except AttributeError:
                        pass
                    return payload.decode(charset, errors="replace")
            except error.HTTPError as exc:
                status = int(exc.code)
                retryable = status == 429 or 500 <= status < 600
                try:
                    exc.close()
                except Exception:
                    pass
                last_error = ProviderHTTPError(
                    f"HTTP {status} al consultar {url}",
                    status=status,
                    retryable=retryable,
                )
                if not retryable or attempt >= self.retries:
                    raise last_error from None
            except (error.URLError, TimeoutError, OSError) as exc:
                last_error = ProviderHTTPError(
                    f"No se pudo conectar con {url}: {exc}",
                    retryable=True,
                )
                if attempt >= self.retries:
                    raise last_error from None
            if attempt < self.retries:
                self._sleep(self.backoff * (2**attempt))
        raise last_error or ProviderHTTPError(f"No se pudo consultar {url}")

    def get_json(self, url: str) -> Any:
        text = self.get_text(url)
        try:
            return json.loads(text, parse_float=Decimal, parse_int=Decimal)
        except (TypeError, ValueError) as exc:
            raise ProviderPayloadError(
                f"JSON invalido al consultar {url}: {exc}"
            ) from None


@dataclass(frozen=True, order=True)
class RateGap:
    """Combinacion fecha/tipo/moneda que falta en la base."""

    base_currency: str
    quote_currency: str
    rate_type: str
    effective_date: date


@dataclass(frozen=True)
class ProviderRate:
    """Cotizacion normalizada, lista para ``ExchangeRateService.register``."""

    base_currency: str
    quote_currency: str
    effective_date: date
    rate_type: str
    source: str
    buy_rate: Decimal
    sell_rate: Decimal
    origin: str = ExchangeRate.ORIGIN_API
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class ProviderOutcome:
    """Resultado de un proveedor: datos, errores y advertencias."""

    provider: str
    rates: tuple[ProviderRate, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class ExchangeRateProvider(Protocol):
    name: str

    def fetch(
        self,
        *,
        today: date,
        missing: frozenset[RateGap] = frozenset(),
    ) -> ProviderOutcome: ...


def _decimal_rate(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ProviderPayloadError(f"{label} no informado.")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ProviderPayloadError(f"{label} no es un decimal valido.") from None
    if not parsed.is_finite() or parsed <= 0:
        raise ProviderPayloadError(f"{label} debe ser finito y mayor que cero.")
    return parsed


def _parse_buy_sell(
    payload: Mapping[str, Any],
    *,
    label: str,
    warnings: list[str],
) -> tuple[Decimal, Decimal] | None:
    try:
        buy = _decimal_rate(payload.get("compra"), f"{label}: compra")
        sell = _decimal_rate(payload.get("venta"), f"{label}: venta")
    except ProviderPayloadError as exc:
        warnings.append(str(exc))
        return None
    return buy, sell


def _parse_iso_date(value: Any, label: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise ProviderPayloadError(f"{label}: falta fecha.")
    # ArgentinaDatos publica ``fecha`` como fecha pura. No debe convertirse
    # desde UTC: ``2026-11-26`` a las 00:00 UTC caeria el 25 en ART.
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise ProviderPayloadError(
                f"{label}: fecha invalida {value!r}."
            ) from None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ProviderPayloadError(f"{label}: fecha invalida {value!r}.") from None
    if parsed.tzinfo is None:
        # Un timestamp sin zona se interpreta en la zona del mercado.
        return parsed.replace(tzinfo=ZONA_AR).date()
    return parsed.astimezone(ZONA_AR).date()


class DolarApiProvider:
    """Cotizaciones actuales de DolarAPI (oficial, blue, MEP, CCL, etc.)."""

    name = "dolarapi"

    def __init__(
        self,
        client: HttpClient,
        *,
        base_url: str = "https://dolarapi.com",
    ):
        self.client = client
        self.base_url = base_url.rstrip("/")

    def fetch(
        self,
        *,
        today: date,
        missing: frozenset[RateGap] = frozenset(),
    ) -> ProviderOutcome:
        del missing  # DolarAPI solo publica la cotizacion vigente.
        rates: dict[tuple[str, str], ProviderRate] = {}
        errors: list[str] = []
        warnings: list[str] = []
        fetched_at = datetime.now(timezone.utc)

        try:
            payload = self.client.get_json(f"{self.base_url}/v1/dolares")
        except ProviderError as exc:
            errors.append(f"DolarAPI /v1/dolares: {exc}")
        else:
            self._collect_list(
                payload,
                today=today,
                fetched_at=fetched_at,
                rates=rates,
                warnings=warnings,
            )

        try:
            payload = self.client.get_json(
                f"{self.base_url}/v1/cotizaciones/brl"
            )
        except ProviderError as exc:
            errors.append(f"DolarAPI /v1/cotizaciones/brl: {exc}")
        else:
            self._collect_item(
                payload,
                today=today,
                fetched_at=fetched_at,
                rates=rates,
                warnings=warnings,
            )

        return ProviderOutcome(
            provider=self.name,
            rates=tuple(rates.values()),
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def _collect_list(
        self,
        payload: Any,
        *,
        today: date,
        fetched_at: datetime,
        rates: dict[tuple[str, str], ProviderRate],
        warnings: list[str],
    ) -> None:
        if not isinstance(payload, list):
            warnings.append("DolarAPI /v1/dolares: respuesta inesperada.")
            return
        for item in payload:
            self._collect_item(
                item,
                today=today,
                fetched_at=fetched_at,
                rates=rates,
                warnings=warnings,
            )

    def _collect_item(
        self,
        payload: Any,
        *,
        today: date,
        fetched_at: datetime,
        rates: dict[tuple[str, str], ProviderRate],
        warnings: list[str],
    ) -> None:
        if not isinstance(payload, Mapping):
            warnings.append("DolarAPI: item inesperado.")
            return
        currency = str(payload.get("moneda") or "").strip().upper()
        casa = str(payload.get("casa") or "").strip().lower()
        if currency == "USD":
            rate_type = DOLARAPI_CASAS.get(casa)
        elif currency == "BRL":
            rate_type = "oficial" if casa == "oficial" else None
        else:
            return
        if rate_type is None:
            # Cripto, EUR y pares fuera de alcance no son un error.
            return
        label = f"DolarAPI {currency}/{casa or '-'}"
        amounts = _parse_buy_sell(payload, label=label, warnings=warnings)
        if amounts is None:
            return
        try:
            effective = _parse_iso_date(
                payload.get("fechaActualizacion"),
                f"{label} fechaActualizacion",
            )
        except ProviderPayloadError as exc:
            warnings.append(str(exc))
            return
        if effective > today:
            warnings.append(
                f"{label}: fecha efectiva {effective.isoformat()} posterior a hoy; "
                "se descarta."
            )
            return
        buy, sell = amounts
        rates[(currency, rate_type)] = ProviderRate(
            base_currency=currency,
            quote_currency="ARS",
            effective_date=effective,
            rate_type=rate_type,
            source=self.name,
            buy_rate=buy,
            sell_rate=sell,
            origin=ExchangeRate.ORIGIN_API,
            fetched_at=fetched_at,
        )


class _BnaTableParser(HTMLParser):
    """Extrae filas de la tabla HTML del cotizador del Banco Nacion."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _parse_ar_decimal(text: str) -> Decimal:
    cleaned = str(text).strip().replace(" ", "")
    if not cleaned:
        raise ProviderPayloadError("BNA: valor vacio.")
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation:
        raise ProviderPayloadError(f"BNA: valor invalido {text!r}.") from None
    if not parsed.is_finite() or parsed <= 0:
        raise ProviderPayloadError(f"BNA: valor invalido {text!r}.")
    return parsed


def _parse_bna_date(text: str) -> date:
    try:
        return datetime.strptime(str(text).strip(), "%d/%m/%Y").date()
    except ValueError:
        raise ProviderPayloadError(f"BNA: fecha invalida {text!r}.") from None


class BnaProvider:
    """Cotizacion de billetes del Banco Nacion (HTML publico).

    El endpoint devuelve las cotizaciones mas cercanas a la fecha pedida. Se
    aceptan solo filas con fecha igual o anterior a la pedida, nunca posterior,
    y se descartan las mas viejas que ``lookback_days``.
    """

    name = "bna"

    def __init__(
        self,
        client: HttpClient,
        *,
        base_url: str = "https://www.bna.com.ar",
        lookback_days: int = 7,
    ):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.lookback_days = max(0, int(lookback_days))

    def fetch(
        self,
        *,
        today: date,
        missing: frozenset[RateGap] = frozenset(),
    ) -> ProviderOutcome:
        dates = {today}
        earliest = today - timedelta(days=self.lookback_days)
        for gap in missing:
            if gap.rate_type != BNA_RATE_TYPE:
                continue
            if gap.base_currency not in {"USD", "BRL"}:
                continue
            if earliest <= gap.effective_date <= today:
                dates.add(gap.effective_date)

        rates: dict[tuple[str, date], ProviderRate] = {}
        errors: list[str] = []
        warnings: list[str] = []
        fetched_at = datetime.now(timezone.utc)

        for requested in sorted(dates):
            url = self._url(requested)
            try:
                html = self.client.get_text(
                    url, headers={"Accept-Language": "es-AR"}
                )
            except ProviderError as exc:
                errors.append(f"BNA {requested.isoformat()}: {exc}")
                continue
            try:
                rows = self._parse_rows(html)
            except ProviderPayloadError as exc:
                warnings.append(str(exc))
                continue
            found_exact = False
            for row in rows:
                row_date = row["date"]
                if row_date > requested or row_date > today:
                    continue
                if row_date < earliest:
                    continue
                if row_date == requested:
                    found_exact = True
                rates[(row["currency"], row_date)] = ProviderRate(
                    base_currency=row["currency"],
                    quote_currency="ARS",
                    effective_date=row_date,
                    rate_type=BNA_RATE_TYPE,
                    source=self.name,
                    buy_rate=row["buy"],
                    sell_rate=row["sell"],
                    origin=ExchangeRate.ORIGIN_SCRAPE,
                    fetched_at=fetched_at,
                )
            if not found_exact:
                warnings.append(
                    f"BNA no publico cotizacion para {requested.isoformat()}; "
                    "se conservaron las fechas anteriores disponibles."
                )

        return ProviderOutcome(
            provider=self.name,
            rates=tuple(rates.values()),
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def _url(self, requested: date) -> str:
        query = parse.urlencode(
            [
                ("id", "billetes"),
                ("fecha", requested.strftime("%d/%m/%Y")),
                ("idMoneda", "22"),
                ("idMoneda", "23"),
            ]
        )
        return f"{self.base_url}/Cotizador/HistoricoPrincipales?{query}"

    def _parse_rows(self, html: str) -> list[dict]:
        parser = _BnaTableParser()
        parser.feed(html)
        parsed: list[dict] = []
        for cells in parser.rows:
            if len(cells) < 4:
                continue
            label = " ".join(cells[0].split()).lower()
            if label.startswith("dolar u"):
                currency = "USD"
                divisor = Decimal("1")
            elif label.startswith("real"):
                # El propio BNA advierte "cotizacion cada 100 unidades".
                currency = "BRL"
                divisor = Decimal("100")
            else:
                continue
            try:
                buy = _parse_ar_decimal(cells[1]) / divisor
                sell = _parse_ar_decimal(cells[2]) / divisor
                row_date = _parse_bna_date(cells[3])
            except ProviderPayloadError:
                continue
            parsed.append(
                {
                    "currency": currency,
                    "buy": buy,
                    "sell": sell,
                    "date": row_date,
                }
            )
        if not parsed and "no hay cotizaciones" not in html.lower():
            # La pagina puede no traer tabla por un cambio de formato. No se
            # inventa nada: se informa para que el job lo registre.
            raise ProviderPayloadError(
                "BNA: no se encontro la tabla de cotizaciones esperada."
            )
        return parsed


class ArgentinaDatosProvider:
    """Historial diario de ArgentinaDatos para recuperar faltantes recientes."""

    name = "argentinadatos"

    def __init__(
        self,
        client: HttpClient,
        *,
        base_url: str = "https://api.argentinadatos.com",
    ):
        self.client = client
        self.base_url = base_url.rstrip("/")

    def fetch(
        self,
        *,
        today: date,
        missing: frozenset[RateGap] = frozenset(),
    ) -> ProviderOutcome:
        del today
        rates: dict[tuple[str, str, date], ProviderRate] = {}
        errors: list[str] = []
        warnings: list[str] = []
        fetched_at = datetime.now(timezone.utc)
        seen: set[tuple[str, str, date]] = set()

        for gap in sorted(missing):
            key = (gap.base_currency, gap.rate_type, gap.effective_date)
            if key in seen:
                continue
            seen.add(key)
            if gap.base_currency == "USD":
                casa = ARGENTINADATOS_CASAS.get(gap.rate_type)
                if casa is None:
                    continue
                url = self._url_dolar(casa, gap.effective_date)
            elif gap.base_currency == "BRL" and gap.rate_type == "oficial":
                url = self._url_brl(gap.effective_date)
            else:
                continue
            try:
                payload = self.client.get_json(url)
            except ProviderHTTPError as exc:
                if exc.status == 404:
                    warnings.append(
                        f"ArgentinaDatos sin dato para "
                        f"{gap.base_currency}/{gap.rate_type} "
                        f"{gap.effective_date.isoformat()}."
                    )
                else:
                    errors.append(
                        f"ArgentinaDatos {gap.effective_date.isoformat()}: {exc}"
                    )
                continue
            except ProviderError as exc:
                errors.append(
                    f"ArgentinaDatos {gap.effective_date.isoformat()}: {exc}"
                )
                continue
            if not isinstance(payload, Mapping):
                warnings.append(
                    f"ArgentinaDatos {gap.effective_date.isoformat()}: "
                    "respuesta inesperada."
                )
                continue
            if payload.get("error"):
                warnings.append(
                    f"ArgentinaDatos sin dato para "
                    f"{gap.effective_date.isoformat()}: {payload.get('error')}"
                )
                continue
            label = f"ArgentinaDatos {gap.base_currency}/{gap.rate_type}"
            amounts = _parse_buy_sell(payload, label=label, warnings=warnings)
            if amounts is None:
                continue
            try:
                effective = _parse_iso_date(
                    payload.get("fecha"),
                    f"{label} fecha",
                )
            except ProviderPayloadError as exc:
                warnings.append(str(exc))
                continue
            if effective != gap.effective_date:
                warnings.append(
                    f"{label}: se pidio {gap.effective_date.isoformat()} y llego "
                    f"{effective.isoformat()}; se descarta."
                )
                continue
            buy, sell = amounts
            rates[(gap.base_currency, gap.rate_type, effective)] = ProviderRate(
                base_currency=gap.base_currency,
                quote_currency="ARS",
                effective_date=effective,
                rate_type=gap.rate_type,
                source=self.name,
                buy_rate=buy,
                sell_rate=sell,
                origin=ExchangeRate.ORIGIN_HISTORICAL_IMPORT,
                fetched_at=fetched_at,
            )

        return ProviderOutcome(
            provider=self.name,
            rates=tuple(rates.values()),
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    def _url_dolar(self, casa: str, requested: date) -> str:
        return (
            f"{self.base_url}/v1/cotizaciones/dolares/{casa}/"
            f"{requested.year:04d}/{requested.month:02d}/{requested.day:02d}"
        )

    def _url_brl(self, requested: date) -> str:
        return (
            f"{self.base_url}/v1/cotizaciones/brl/"
            f"{requested.year:04d}/{requested.month:02d}/{requested.day:02d}"
        )
