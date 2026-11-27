"""Servicio central de cotizaciones historicas y conversiones con Decimal.

Convencion: ``base_currency`` es la moneda cotizada (1 unidad) y
``quote_currency`` la moneda del precio. ``USD/ARS`` significa **pesos
argentinos por un dolar**.

Reglas que aplica este modulo:

- una cotizacion nunca se usa para una fecha posterior a la solicitada;
- el fallback a la ultima fecha anterior es explicito y queda marcado;
- nunca se cambia silenciosamente de ``rate_type``, ``source`` o punta;
- no se devuelve un valor ficticio (0, 1, promedio de la nada) si falta el dato;
- las correcciones crean una nueva ``version`` y conservan las anteriores;
- los importes se convierten siempre con ``Decimal``.

Politica de fuentes y versiones
-------------------------------

- La clave de una cotizacion es
  ``(base, quote, rate_type, source, effective_date, version)``.
- Registrar dos veces exactamente el mismo dato es idempotente: devuelve la
  ultima version con ``created=False`` y no genera auditoria nueva.
- Si el dato cambia para la misma clave, se crea ``version + 1``. Nada se
  actualiza ni se borra.
- Si hay varias fuentes para la misma fecha/tipo, la consulta exige
  ``source`` y falla con ``ExchangeRateAmbiguousSource`` en vez de elegir una.
- Sin ``version`` se usa la ultima version de la fuente elegida; con
  ``version`` se usa exactamente esa.

Ejemplos
--------

::

    service = ExchangeRateService("admin")
    service.register(
        base_currency="USD", quote_currency="ARS",
        effective_date=date(2026, 11, 27), rate_type="oficial",
        buy_rate=Decimal("1000.123456"), sell_rate=Decimal("1000.654321"),
        source="bcra", origin=ExchangeRate.ORIGIN_API,
    )
    cotizacion = service.get_latest_before(
        date(2026, 11, 29), base_currency="USD", quote_currency="ARS",
        rate_type="oficial", side="sell", source="bcra",
    )
    assert cotizacion.used_fallback is True

    conversion = service.convert(
        Decimal("1500.00"), from_currency="USD", to_currency="ARS",
        on_date=date(2026, 11, 27), rate_type="oficial",
        side="sell", source="bcra", version=1,
    )
    assert conversion.converted_amount == Decimal("1500981.48")
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from peewee import IntegrityError, MySQLDatabase

from app.config.database import database_proxy
from app.models.base import utc_now
from app.models.exchange_rates import ExchangeRate
from app.services.audit_service import AuditService
from app.services.money import quantize_money, to_decimal

RATE_QUANTUM = Decimal("0.000001")
#: Tope de ``DECIMAL(18,6)``: 12 digitos enteros y 6 decimales.
MAX_RATE = Decimal("1000000000000")
ROUNDING = ROUND_HALF_UP
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

#: Origen y punta se normalizan a minusculas; no se aceptan valores libres para
#: el origen.
VALID_ORIGINS = frozenset(ExchangeRate.ORIGINS)
VALID_SIDES = frozenset(ExchangeRate.SIDES)


class ExchangeRateError(ValueError):
    """Error de negocio del circuito de cotizaciones."""


class InvalidExchangeRate(ExchangeRateError):
    """Datos de cotizacion invalidos (moneda, fecha, valor, origen, etc.)."""


class ExchangeRateNotFound(ExchangeRateError):
    """No existe una cotizacion que cumpla exactamente el criterio pedido."""


class ExchangeRateAmbiguousSource(ExchangeRateError):
    """Hay mas de una fuente para la fecha/tipo y no se indico cual usar."""


@dataclass(frozen=True)
class ExchangeRateLookup:
    """Resultado completo de una consulta de cotizacion."""

    requested_date: date
    effective_date: date
    base_currency: str
    quote_currency: str
    rate_type: str
    side: str
    source: str
    value: Decimal
    buy_rate: Decimal
    sell_rate: Decimal
    record_id: int
    version: int
    used_fallback: bool
    origin: str
    fetched_at: datetime | None


@dataclass(frozen=True)
class ExchangeRateRegistration:
    """Resultado de registrar una cotizacion.

    ``created`` es ``False`` cuando la importacion repetida coincide con la
    ultima version y no se genero un registro nuevo.
    """

    record: ExchangeRate
    created: bool


@dataclass(frozen=True)
class ExchangeRateConversion:
    """Resultado de convertir un importe con una cotizacion identificada."""

    amount: Decimal
    from_currency: str
    to_currency: str
    converted_amount: Decimal
    rate: Decimal
    lookup: ExchangeRateLookup | None
    identity: bool = False
    inverted: bool = False


def _normalize_currency(value: str | None, label: str) -> str:
    text = str(value or "").strip().upper()
    if not _CURRENCY_RE.fullmatch(text):
        raise InvalidExchangeRate(
            f"{label} debe ser un codigo ISO de 3 letras (por ejemplo USD, ARS, BRL)."
        )
    return text


def _normalize_key(value: str | None, *, label: str, max_length: int) -> str:
    text = " ".join(str(value or "").strip().lower().split())
    if not text:
        raise InvalidExchangeRate(f"{label} no puede estar vacio.")
    if len(text) > max_length:
        raise InvalidExchangeRate(
            f"{label} no puede superar {max_length} caracteres."
        )
    return text


def _normalize_side(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text not in VALID_SIDES:
        raise InvalidExchangeRate(
            "La punta debe ser 'buy', 'sell' o 'average'."
        )
    return text


def _normalize_origin(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if text not in VALID_ORIGINS:
        raise InvalidExchangeRate(
            "El origen debe ser uno de: " + ", ".join(sorted(VALID_ORIGINS)) + "."
        )
    return text


def _normalize_rate(value, label: str) -> Decimal:
    if isinstance(value, bool):
        raise InvalidExchangeRate(f"{label} debe ser un numero decimal.")
    try:
        rate = to_decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise InvalidExchangeRate(f"{label} debe ser un numero decimal.") from None
    if not rate.is_finite() or rate <= 0:
        raise InvalidExchangeRate(
            f"{label} debe ser un numero finito y mayor que cero."
        )
    quantized = rate.quantize(RATE_QUANTUM, rounding=ROUNDING)
    if quantized != rate:
        # No se redondea en silencio: DECIMAL(18,6) guardaria otro valor y la
        # fuente quedaria mal representada.
        raise InvalidExchangeRate(f"{label} admite como maximo 6 decimales.")
    if quantized >= MAX_RATE:
        raise InvalidExchangeRate(f"{label} es demasiado grande.")
    return quantized


def _normalize_fetched_at(value: datetime | None) -> datetime:
    if value is None:
        return utc_now()
    if not isinstance(value, datetime):
        raise InvalidExchangeRate("La fecha/hora de obtencion debe ser datetime.")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _coerce_datetime(value) -> datetime | None:
    """Normaliza el valor leido de la base.

    SQLite devuelve el texto crudo cuando el ``datetime`` almacenado lleva
    zona horaria (peewee no lo reparsea); MySQL puede devolver ``datetime``
    sin zona. El resultado publico siempre es un ``datetime`` UTC o ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_date(value, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise InvalidExchangeRate(f"{label} debe ser una fecha.")


def _normalize_version(value) -> int:
    if isinstance(value, bool):
        raise InvalidExchangeRate("La version debe ser un entero positivo.")
    try:
        version = int(value)
    except (TypeError, ValueError):
        raise InvalidExchangeRate("La version debe ser un entero positivo.") from None
    if version <= 0:
        raise InvalidExchangeRate("La version debe ser un entero positivo.")
    return version


def _decimal_token(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _fingerprint(
    *,
    base_currency: str,
    quote_currency: str,
    effective_date: date,
    rate_type: str,
    source: str,
    buy_rate: Decimal,
    sell_rate: Decimal,
) -> str:
    payload = "|".join(
        (
            base_currency,
            quote_currency,
            effective_date.isoformat(),
            rate_type,
            source,
            _decimal_token(buy_rate),
            _decimal_token(sell_rate),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ExchangeRateService:
    """Registro inmutable y consultas historicas de cotizaciones."""

    def __init__(
        self,
        current_user: str,
        audit_service: AuditService | None = None,
    ):
        self.current_user = current_user
        self.audit_service = audit_service or AuditService()

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------
    def register(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        effective_date: date,
        rate_type: str,
        buy_rate,
        sell_rate,
        source: str,
        origin: str = ExchangeRate.ORIGIN_MANUAL,
        fetched_at: datetime | None = None,
        created_by: str | None = None,
    ) -> ExchangeRateRegistration:
        base = _normalize_currency(base_currency, "La moneda base")
        quote = _normalize_currency(quote_currency, "La moneda cotizada")
        if base == quote:
            raise InvalidExchangeRate(
                "La moneda base y la moneda cotizada no pueden ser iguales."
            )
        effective = _normalize_date(effective_date, "La fecha efectiva")
        type_key = _normalize_key(
            rate_type, label="El tipo de cotizacion", max_length=32
        )
        source_key = _normalize_key(
            source, label="La fuente", max_length=64
        )
        origin_key = _normalize_origin(origin)
        fetched = _normalize_fetched_at(fetched_at)
        buy = _normalize_rate(buy_rate, "El valor de compra")
        sell = _normalize_rate(sell_rate, "El valor de venta")
        fingerprint = _fingerprint(
            base_currency=base,
            quote_currency=quote,
            effective_date=effective,
            rate_type=type_key,
            source=source_key,
            buy_rate=buy,
            sell_rate=sell,
        )

        # El retry cubre la carrera de dos importaciones identicas cuando
        # todavia no existe ninguna fila para la clave (no hay fila que lockear).
        for attempt in range(3):
            try:
                with database_proxy.atomic():
                    rows = list(self._locked_history(
                        base=base,
                        quote=quote,
                        rate_type=type_key,
                        source=source_key,
                        effective_date=effective,
                    ))
                    latest = rows[0] if rows else None
                    if latest is not None and latest.fingerprint == fingerprint:
                        return ExchangeRateRegistration(latest, False)
                    version = latest.version + 1 if latest is not None else 1
                    record = ExchangeRate.create(
                        base_currency=base,
                        quote_currency=quote,
                        effective_date=effective,
                        rate_type=type_key,
                        buy_rate=buy,
                        sell_rate=sell,
                        source=source_key,
                        fetched_at=fetched,
                        origin=origin_key,
                        version=version,
                        fingerprint=fingerprint,
                        created_by=created_by or self.current_user,
                    )
                    self.audit_service.record(
                        user=self.current_user,
                        module="Cotizaciones",
                        action="registrar cotizacion",
                        record_ref=f"ExchangeRate:{record.id}",
                        old_value=self._snapshot(latest),
                        new_value=self._snapshot(record),
                        observation=f"version {version}",
                    )
                    return ExchangeRateRegistration(record, True)
            except IntegrityError:
                if attempt == 2:
                    raise
                # Otro puesto gano la creacion de la misma version. Se relee
                # la historia y se decide si fue idempotente o si toca otra
                # version con los datos nuevos.
                continue
        raise RuntimeError("No se pudo registrar la cotizacion.")

    @staticmethod
    def _locked_history(
        *,
        base: str,
        quote: str,
        rate_type: str,
        source: str,
        effective_date: date,
    ):
        query = ExchangeRate.select().where(
            (ExchangeRate.base_currency == base)
            & (ExchangeRate.quote_currency == quote)
            & (ExchangeRate.rate_type == rate_type)
            & (ExchangeRate.source == source)
            & (ExchangeRate.effective_date == effective_date)
        ).order_by(ExchangeRate.version.desc())
        if isinstance(database_proxy.obj, MySQLDatabase):
            query = query.for_update()
        return query

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    def get_exact(
        self,
        on_date: date,
        *,
        base_currency: str,
        quote_currency: str,
        rate_type: str,
        side: str,
        source: str | None = None,
        version=None,
    ) -> ExchangeRateLookup:
        requested = _normalize_date(on_date, "La fecha solicitada")
        base, quote, type_key, side_key = self._normalize_pair(
            base_currency, quote_currency, rate_type, side
        )
        source_key = self._resolve_source(
            base=base,
            quote=quote,
            rate_type=type_key,
            effective_date=requested,
            source=source,
        )
        query = ExchangeRate.select().where(
            (ExchangeRate.base_currency == base)
            & (ExchangeRate.quote_currency == quote)
            & (ExchangeRate.rate_type == type_key)
            & (ExchangeRate.source == source_key)
            & (ExchangeRate.effective_date == requested)
        )
        if version is not None:
            query = query.where(ExchangeRate.version == _normalize_version(version))
        else:
            query = query.order_by(ExchangeRate.version.desc())
        record = query.first()
        if record is None:
            raise ExchangeRateNotFound(
                self._missing_message(
                    requested=requested,
                    base=base,
                    quote=quote,
                    rate_type=type_key,
                    source=source_key,
                    version=version,
                )
            )
        return self._lookup(
            record,
            requested_date=requested,
            side=side_key,
            used_fallback=False,
        )

    def get_latest_before(
        self,
        on_date: date,
        *,
        base_currency: str,
        quote_currency: str,
        rate_type: str,
        side: str,
        source: str | None = None,
        allow_fallback: bool = True,
    ) -> ExchangeRateLookup:
        requested = _normalize_date(on_date, "La fecha solicitada")
        base, quote, type_key, side_key = self._normalize_pair(
            base_currency, quote_currency, rate_type, side
        )
        if not allow_fallback:
            return self.get_exact(
                requested,
                base_currency=base,
                quote_currency=quote,
                rate_type=type_key,
                side=side_key,
                source=source,
            )

        query = ExchangeRate.select().where(
            (ExchangeRate.base_currency == base)
            & (ExchangeRate.quote_currency == quote)
            & (ExchangeRate.rate_type == type_key)
            & (ExchangeRate.effective_date <= requested)
        )
        source_key = None
        if source is not None:
            source_key = _normalize_key(source, label="La fuente", max_length=64)
            query = query.where(ExchangeRate.source == source_key)
        latest_date_row = query.order_by(ExchangeRate.effective_date.desc()).first()
        if latest_date_row is None:
            raise ExchangeRateNotFound(
                self._missing_message(
                    requested=requested,
                    base=base,
                    quote=quote,
                    rate_type=type_key,
                    source=source_key,
                )
            )
        effective = latest_date_row.effective_date
        if source_key is None:
            source_key = self._resolve_source(
                base=base,
                quote=quote,
                rate_type=type_key,
                effective_date=effective,
                source=None,
            )
        record = (
            ExchangeRate.select()
            .where(
                (ExchangeRate.base_currency == base)
                & (ExchangeRate.quote_currency == quote)
                & (ExchangeRate.rate_type == type_key)
                & (ExchangeRate.source == source_key)
                & (ExchangeRate.effective_date == effective)
            )
            .order_by(ExchangeRate.version.desc())
            .first()
        )
        if record is None:
            raise ExchangeRateNotFound(
                self._missing_message(
                    requested=requested,
                    base=base,
                    quote=quote,
                    rate_type=type_key,
                    source=source_key,
                )
            )
        return self._lookup(
            record,
            requested_date=requested,
            side=side_key,
            used_fallback=effective < requested,
        )

    def get_version(
        self,
        effective_date: date,
        *,
        base_currency: str,
        quote_currency: str,
        rate_type: str,
        version,
        side: str,
        source: str | None = None,
    ) -> ExchangeRateLookup:
        effective = _normalize_date(effective_date, "La fecha efectiva")
        base, quote, type_key, side_key = self._normalize_pair(
            base_currency, quote_currency, rate_type, side
        )
        version_key = _normalize_version(version)
        source_key = self._resolve_source(
            base=base,
            quote=quote,
            rate_type=type_key,
            effective_date=effective,
            source=source,
        )
        record = (
            ExchangeRate.select()
            .where(
                (ExchangeRate.base_currency == base)
                & (ExchangeRate.quote_currency == quote)
                & (ExchangeRate.rate_type == type_key)
                & (ExchangeRate.source == source_key)
                & (ExchangeRate.effective_date == effective)
                & (ExchangeRate.version == version_key)
            )
            .first()
        )
        if record is None:
            raise ExchangeRateNotFound(
                self._missing_message(
                    requested=effective,
                    base=base,
                    quote=quote,
                    rate_type=type_key,
                    source=source_key,
                    version=version_key,
                )
            )
        return self._lookup(
            record,
            requested_date=effective,
            side=side_key,
            used_fallback=False,
        )

    def get_range(
        self,
        start_date: date,
        end_date: date,
        *,
        base_currency: str,
        quote_currency: str,
        rate_type: str,
        side: str,
        source: str | None = None,
        latest_only: bool = True,
    ) -> list[ExchangeRateLookup]:
        start = _normalize_date(start_date, "La fecha desde")
        end = _normalize_date(end_date, "La fecha hasta")
        if start > end:
            raise InvalidExchangeRate("La fecha desde no puede ser posterior a la hasta.")
        base, quote, type_key, side_key = self._normalize_pair(
            base_currency, quote_currency, rate_type, side
        )
        query = ExchangeRate.select().where(
            (ExchangeRate.base_currency == base)
            & (ExchangeRate.quote_currency == quote)
            & (ExchangeRate.rate_type == type_key)
            & (ExchangeRate.effective_date >= start)
            & (ExchangeRate.effective_date <= end)
        )
        if source is not None:
            query = query.where(
                ExchangeRate.source
                == _normalize_key(source, label="La fuente", max_length=64)
            )
        query = query.order_by(
            ExchangeRate.effective_date,
            ExchangeRate.source,
            ExchangeRate.version,
        )
        records = list(query)
        if latest_only:
            latest_by_date_source: dict[tuple[date, str], ExchangeRate] = {}
            for record in records:
                key = (record.effective_date, record.source)
                current = latest_by_date_source.get(key)
                if current is None or record.version > current.version:
                    latest_by_date_source[key] = record
            records = sorted(
                latest_by_date_source.values(),
                key=lambda row: (row.effective_date, row.source),
            )
        return [
            self._lookup(
                record,
                requested_date=record.effective_date,
                side=side_key,
                used_fallback=False,
            )
            for record in records
        ]

    def convert(
        self,
        amount,
        *,
        from_currency: str,
        to_currency: str,
        on_date: date,
        rate_type: str,
        side: str,
        source: str | None = None,
        allow_fallback: bool = False,
        version=None,
    ) -> ExchangeRateConversion:
        requested = _normalize_date(on_date, "La fecha solicitada")
        from_currency_key = _normalize_currency(from_currency, "La moneda origen")
        to_currency_key = _normalize_currency(to_currency, "La moneda destino")
        try:
            amount_value = to_decimal(amount)
        except (InvalidOperation, TypeError, ValueError):
            raise InvalidExchangeRate("El importe debe ser un numero decimal.") from None
        if not amount_value.is_finite():
            raise InvalidExchangeRate("El importe debe ser un numero finito.")
        if from_currency_key == to_currency_key:
            return ExchangeRateConversion(
                amount=amount_value,
                from_currency=from_currency_key,
                to_currency=to_currency_key,
                converted_amount=amount_value,
                rate=Decimal("1"),
                lookup=None,
                identity=True,
            )

        base, quote, type_key, side_key = self._normalize_pair(
            from_currency_key, to_currency_key, rate_type, side
        )
        lookup, inverted = self._lookup_for_conversion(
            requested=requested,
            base=base,
            quote=quote,
            rate_type=type_key,
            side=side_key,
            source=source,
            allow_fallback=allow_fallback,
            version=version,
        )
        if inverted:
            with localcontext() as context:
                context.prec = 34
                rate = Decimal("1") / lookup.value
        else:
            rate = lookup.value
        converted = quantize_money(amount_value * rate)
        return ExchangeRateConversion(
            amount=amount_value,
            from_currency=from_currency_key,
            to_currency=to_currency_key,
            converted_amount=converted,
            rate=rate,
            lookup=lookup,
            inverted=inverted,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_pair(base_currency, quote_currency, rate_type, side):
        base = _normalize_currency(base_currency, "La moneda base")
        quote = _normalize_currency(quote_currency, "La moneda cotizada")
        if base == quote:
            raise InvalidExchangeRate(
                "La moneda base y la moneda cotizada no pueden ser iguales."
            )
        type_key = _normalize_key(
            rate_type, label="El tipo de cotizacion", max_length=32
        )
        side_key = _normalize_side(side)
        return base, quote, type_key, side_key

    def _lookup_for_conversion(
        self,
        *,
        requested: date,
        base: str,
        quote: str,
        rate_type: str,
        side: str,
        source: str | None,
        allow_fallback: bool,
        version,
    ) -> tuple[ExchangeRateLookup, bool]:
        try:
            if version is not None:
                return (
                    self.get_version(
                        requested,
                        base_currency=base,
                        quote_currency=quote,
                        rate_type=rate_type,
                        version=version,
                        side=side,
                        source=source,
                    ),
                    False,
                )
            if allow_fallback:
                return (
                    self.get_latest_before(
                        requested,
                        base_currency=base,
                        quote_currency=quote,
                        rate_type=rate_type,
                        side=side,
                        source=source,
                        allow_fallback=True,
                    ),
                    False,
                )
            return (
                self.get_exact(
                    requested,
                    base_currency=base,
                    quote_currency=quote,
                    rate_type=rate_type,
                    side=side,
                    source=source,
                ),
                False,
            )
        except ExchangeRateNotFound as direct_error:
            if version is not None:
                raise
            # Se permite usar el par inverso solo si existe y se informa
            # explicitamente en el resultado. No se inventa ni se promedia.
            try:
                inverse = (
                    self.get_latest_before(
                        requested,
                        base_currency=quote,
                        quote_currency=base,
                        rate_type=rate_type,
                        side=side,
                        source=source,
                        allow_fallback=True,
                    )
                    if allow_fallback
                    else self.get_exact(
                        requested,
                        base_currency=quote,
                        quote_currency=base,
                        rate_type=rate_type,
                        side=side,
                        source=source,
                    )
                )
            except ExchangeRateNotFound:
                raise direct_error
            return inverse, True

    def _resolve_source(
        self,
        *,
        base: str,
        quote: str,
        rate_type: str,
        effective_date: date,
        source: str | None,
    ) -> str:
        if source is not None:
            return _normalize_key(source, label="La fuente", max_length=64)
        sources = [
            row.source
            for row in ExchangeRate.select(ExchangeRate.source)
            .where(
                (ExchangeRate.base_currency == base)
                & (ExchangeRate.quote_currency == quote)
                & (ExchangeRate.rate_type == rate_type)
                & (ExchangeRate.effective_date == effective_date)
            )
            .distinct()
            .order_by(ExchangeRate.source)
        ]
        if not sources:
            raise ExchangeRateNotFound(
                self._missing_message(
                    requested=effective_date,
                    base=base,
                    quote=quote,
                    rate_type=rate_type,
                    source=None,
                )
            )
        if len(sources) > 1:
            raise ExchangeRateAmbiguousSource(
                f"Hay varias fuentes para {base}/{quote} tipo {rate_type!r} "
                f"en {effective_date.isoformat()}: {', '.join(sources)}. "
                "Indique la fuente para no mezclar criterios."
            )
        return sources[0]

    @staticmethod
    def _lookup(
        record: ExchangeRate,
        *,
        requested_date: date,
        side: str,
        used_fallback: bool,
    ) -> ExchangeRateLookup:
        buy = record.buy_rate
        sell = record.sell_rate
        if side == ExchangeRate.SIDE_BUY:
            value = buy
        elif side == ExchangeRate.SIDE_SELL:
            value = sell
        else:
            value = ((buy + sell) / 2).quantize(RATE_QUANTUM, rounding=ROUNDING)
        return ExchangeRateLookup(
            requested_date=requested_date,
            effective_date=record.effective_date,
            base_currency=record.base_currency,
            quote_currency=record.quote_currency,
            rate_type=record.rate_type,
            side=side,
            source=record.source,
            value=value,
            buy_rate=buy,
            sell_rate=sell,
            record_id=record.id,
            version=record.version,
            used_fallback=used_fallback,
            origin=record.origin,
            fetched_at=_coerce_datetime(record.fetched_at),
        )

    @staticmethod
    def _snapshot(record: ExchangeRate | None) -> dict | None:
        if record is None:
            return None
        return {
            "id": record.id,
            "base_currency": record.base_currency,
            "quote_currency": record.quote_currency,
            "effective_date": record.effective_date.isoformat(),
            "rate_type": record.rate_type,
            "buy_rate": str(record.buy_rate),
            "sell_rate": str(record.sell_rate),
            "source": record.source,
            "fetched_at": (
                record.fetched_at.isoformat()
                if isinstance(record.fetched_at, datetime)
                else record.fetched_at
            ),
            "origin": record.origin,
            "version": record.version,
            "fingerprint": record.fingerprint,
        }

    @staticmethod
    def _missing_message(
        *,
        requested: date,
        base: str,
        quote: str,
        rate_type: str,
        source: str | None,
        version=None,
    ) -> str:
        source_text = source or "cualquiera"
        version_text = f", version {version}" if version is not None else ""
        return (
            f"No hay cotizacion {base}/{quote} tipo {rate_type!r} "
            f"para {requested.isoformat()} (fuente: {source_text}{version_text})."
        )
