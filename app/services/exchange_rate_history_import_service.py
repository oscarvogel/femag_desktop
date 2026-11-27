"""Importacion historica de cotizaciones para presupuestos (#970).

Reutiliza el modelo y el servicio de #968. No toca presupuestos: solo lee
``budget.issue_date`` para descubrir el rango necesario y evaluar cobertura.

La fuente historica prevista es ArgentinaDatos, que publica la serie completa
por tipo en un solo endpoint. El servicio acepta cualquier proveedor que
implemente ``fetch_series``; la CLI usa ArgentinaDatos por defecto.
"""

from __future__ import annotations

import bisect
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence

from peewee import PeeweeException, fn

from app.models.budgets import Budget
from app.models.exchange_rates import ExchangeRate
from app.services.exchange_rate_providers import (
    ARGENTINADATOS_CASAS,
    HistoricalSeriesProvider,
    ProviderHTTPError,
    ProviderOutcome,
    ZONA_AR,
)
from app.services.exchange_rate_service import (
    ExchangeRateError,
    ExchangeRateService,
)

DEFAULT_SOURCE = "argentinadatos"
DEFAULT_MAX_REQUESTS = 20
DEFAULT_MAX_RECORDS = 5000
STATUS_OK = "ok"
STATUS_PARTIAL = "partial"
STATUS_ERROR = "error"
STATUS_DRY_RUN = "dry_run"


class HistoricalImportError(RuntimeError):
    """Error de configuracion o de datos del importador."""


@dataclass(frozen=True)
class BudgetDateAudit:
    """Fechas de presupuestos descubiertas dinamicamente."""

    total_budgets: int
    distinct_dates: int
    first_date: date | None
    last_date: date | None
    count_by_date: Mapping[date, int] = field(default_factory=dict)

    @property
    def dates(self) -> tuple[date, ...]:
        return tuple(sorted(self.count_by_date))

    def as_dict(self) -> dict:
        return {
            "total_budgets": self.total_budgets,
            "distinct_dates": self.distinct_dates,
            "first_date": self.first_date.isoformat() if self.first_date else None,
            "last_date": self.last_date.isoformat() if self.last_date else None,
            "count_by_date": {
                key.isoformat(): value
                for key, value in sorted(self.count_by_date.items())
            },
        }


@dataclass(frozen=True)
class BudgetCoverage:
    """Cobertura de cotizaciones para las fechas de presupuestos."""

    base_currency: str
    quote_currency: str
    rate_type: str
    source: str | None
    total_budgets: int
    distinct_dates: int
    exact_budgets: int
    prior_budgets: int
    missing_budgets: int
    exact_dates: tuple[date, ...] = ()
    prior_dates: tuple[date, ...] = ()
    missing_dates: tuple[date, ...] = ()

    def as_dict(self) -> dict:
        return {
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "rate_type": self.rate_type,
            "source": self.source,
            "total_budgets": self.total_budgets,
            "distinct_dates": self.distinct_dates,
            "exact_budgets": self.exact_budgets,
            "prior_budgets": self.prior_budgets,
            "missing_budgets": self.missing_budgets,
            "exact_dates": [item.isoformat() for item in self.exact_dates],
            "prior_dates": [item.isoformat() for item in self.prior_dates],
            "missing_dates": [item.isoformat() for item in self.missing_dates],
        }


@dataclass(frozen=True)
class TypeImportReport:
    base_currency: str
    rate_type: str
    provider: str
    fetched: int = 0
    existing: int = 0
    imported: int = 0
    unchanged: int = 0
    new_versions: int = 0
    skipped_existing: int = 0
    skipped_other_source: int = 0
    deferred: int = 0
    missing_publication: tuple[date, ...] = ()
    missing_coverage: tuple[date, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "base_currency": self.base_currency,
            "rate_type": self.rate_type,
            "provider": self.provider,
            "fetched": self.fetched,
            "existing": self.existing,
            "imported": self.imported,
            "unchanged": self.unchanged,
            "new_versions": self.new_versions,
            "skipped_existing": self.skipped_existing,
            "skipped_other_source": self.skipped_other_source,
            "deferred": self.deferred,
            "missing_publication": [
                item.isoformat() for item in self.missing_publication
            ],
            "missing_coverage": [item.isoformat() for item in self.missing_coverage],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class HistoricalImportResult:
    status: str
    source: str
    base_currency: str
    quote_currency: str
    start_date: date
    end_date: date
    rate_types: tuple[str, ...]
    started_at: datetime
    finished_at: datetime
    provider_requests: int = 0
    fetched: int = 0
    existing: int = 0
    imported: int = 0
    unchanged: int = 0
    new_versions: int = 0
    skipped_existing: int = 0
    skipped_other_source: int = 0
    deferred: int = 0
    missing_publication: tuple[date, ...] = ()
    missing_coverage: tuple[date, ...] = ()
    reports: tuple[TypeImportReport, ...] = ()
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    budget_audit: BudgetDateAudit | None = None
    coverage: tuple[BudgetCoverage, ...] = ()
    dry_run: bool = False

    @property
    def has_writes(self) -> bool:
        return self.imported + self.new_versions + self.unchanged > 0

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "source": self.source,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "rate_types": list(self.rate_types),
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "provider_requests": self.provider_requests,
            "fetched": self.fetched,
            "existing": self.existing,
            "imported": self.imported,
            "unchanged": self.unchanged,
            "new_versions": self.new_versions,
            "skipped_existing": self.skipped_existing,
            "skipped_other_source": self.skipped_other_source,
            "deferred": self.deferred,
            "missing_publication": [
                item.isoformat() for item in self.missing_publication
            ],
            "missing_coverage": [
                item.isoformat() for item in self.missing_coverage
            ],
            "reports": [report.as_dict() for report in self.reports],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "budget_audit": self.budget_audit.as_dict() if self.budget_audit else None,
            "coverage": [item.as_dict() for item in self.coverage],
            "dry_run": self.dry_run,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)


def _range_dates(start: date, end: date) -> tuple[date, ...]:
    total = (end - start).days
    return tuple(start + timedelta(days=offset) for offset in range(total + 1))


def _default_types(base_currency: str) -> tuple[str, ...]:
    if base_currency == "BRL":
        return ("oficial",)
    return tuple(ARGENTINADATOS_CASAS)


class HistoricalExchangeRateImportService:
    """Importa series historicas y reconcilia contra presupuestos."""

    def __init__(
        self,
        *,
        current_user: str = "sistema",
        provider: HistoricalSeriesProvider | None = None,
        rate_service: ExchangeRateService | None = None,
        clock=None,
    ):
        if provider is None:
            from app.services.exchange_rate_providers import (
                ArgentinaDatosProvider,
                UrllibHttpClient,
            )

            provider = ArgentinaDatosProvider(UrllibHttpClient())
        self.provider = provider
        self.rate_service = rate_service or ExchangeRateService(current_user)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # Descubrimiento de presupuestos y cobertura
    # ------------------------------------------------------------------
    def audit_budgets(self) -> BudgetDateAudit:
        try:
            rows = (
                Budget.select(
                    Budget.issue_date,
                    fn.COUNT(Budget.id).alias("total"),
                )
                .group_by(Budget.issue_date)
                .order_by(Budget.issue_date)
            )
            counts = {
                row.issue_date: int(row.total)
                for row in rows
                if row.issue_date is not None
            }
        except PeeweeException as exc:
            raise HistoricalImportError(
                "No se pudo leer budget.issue_date. Verifique que la base sea "
                "la de FEMAG y que la tabla budget exista."
            ) from exc
        dates = sorted(counts)
        return BudgetDateAudit(
            total_budgets=sum(counts.values()),
            distinct_dates=len(dates),
            first_date=dates[0] if dates else None,
            last_date=dates[-1] if dates else None,
            count_by_date=counts,
        )

    def coverage(
        self,
        *,
        base_currency: str = "USD",
        quote_currency: str = "ARS",
        rate_type: str = "oficial",
        source: str | None = DEFAULT_SOURCE,
        budget_audit: BudgetDateAudit | None = None,
    ) -> BudgetCoverage:
        audit = budget_audit or self.audit_budgets()
        if not audit.count_by_date:
            return BudgetCoverage(
                base_currency=base_currency,
                quote_currency=quote_currency,
                rate_type=rate_type,
                source=source,
                total_budgets=0,
                distinct_dates=0,
                exact_budgets=0,
                prior_budgets=0,
                missing_budgets=0,
            )

        end = audit.last_date
        query = ExchangeRate.select().where(
            (ExchangeRate.base_currency == base_currency)
            & (ExchangeRate.quote_currency == quote_currency)
            & (ExchangeRate.rate_type == rate_type)
            & (ExchangeRate.effective_date <= end)
        )
        if source:
            query = query.where(ExchangeRate.source == source)
        by_date: dict[date, ExchangeRate] = {}
        for row in query.order_by(ExchangeRate.effective_date, ExchangeRate.version):
            current = by_date.get(row.effective_date)
            if current is None or row.version > current.version:
                by_date[row.effective_date] = row
        available_dates = sorted(by_date)

        exact_dates: list[date] = []
        prior_dates: list[date] = []
        missing_dates: list[date] = []
        exact_budgets = prior_budgets = missing_budgets = 0
        for budget_date, count in sorted(audit.count_by_date.items()):
            if budget_date in by_date:
                exact_dates.append(budget_date)
                exact_budgets += count
                continue
            index = bisect.bisect_left(available_dates, budget_date)
            if index > 0:
                prior_dates.append(budget_date)
                prior_budgets += count
            else:
                missing_dates.append(budget_date)
                missing_budgets += count
        return BudgetCoverage(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate_type=rate_type,
            source=source,
            total_budgets=audit.total_budgets,
            distinct_dates=audit.distinct_dates,
            exact_budgets=exact_budgets,
            prior_budgets=prior_budgets,
            missing_budgets=missing_budgets,
            exact_dates=tuple(exact_dates),
            prior_dates=tuple(prior_dates),
            missing_dates=tuple(missing_dates),
        )

    # ------------------------------------------------------------------
    # Importacion
    # ------------------------------------------------------------------
    def import_range(
        self,
        *,
        start_date: date,
        end_date: date,
        base_currency: str = "USD",
        quote_currency: str = "ARS",
        rate_types: Sequence[str] | None = None,
        source: str = DEFAULT_SOURCE,
        dry_run: bool = False,
        refresh: bool = False,
        max_records: int | None = DEFAULT_MAX_RECORDS,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        holidays: Iterable[date] = (),
        on_progress=None,
    ) -> HistoricalImportResult:
        start = _as_date(start_date, "La fecha desde")
        end = _as_date(end_date, "La fecha hasta")
        if end < start:
            raise HistoricalImportError(
                "La fecha desde no puede ser posterior a la fecha hasta."
            )
        base = str(base_currency or "").strip().upper()
        quote = str(quote_currency or "").strip().upper()
        if base == quote:
            raise HistoricalImportError(
                "La moneda base y la cotizada no pueden ser iguales."
            )
        if base not in {"USD", "BRL"}:
            raise HistoricalImportError(
                "ArgentinaDatos solo aporta series USD/ARS y BRL/ARS."
            )
        if quote != "ARS":
            raise HistoricalImportError(
                "ArgentinaDatos solo cotiza contra ARS."
            )
        if str(self.provider.name) != source:
            raise HistoricalImportError(
                f"El proveedor configurado es {self.provider.name!r}, "
                f"no {source!r}."
            )
        types = tuple(rate_types or _default_types(base))
        if not types:
            raise HistoricalImportError("Debe indicar al menos un tipo.")
        if max_requests < 1:
            raise HistoricalImportError("max_requests debe ser mayor que cero.")
        if len(types) > max_requests:
            raise HistoricalImportError(
                f"Se pidieron {len(types)} tipos y el limite es {max_requests} "
                "solicitudes. Ajuste --max-requests."
            )
        limit = None if max_records is None else max(0, int(max_records))
        holiday_set = {item for item in holidays}

        started_at = self.clock().astimezone(timezone.utc)
        all_dates = _range_dates(start, end)
        reports: list[TypeImportReport] = []
        all_errors: list[str] = []
        all_warnings: list[str] = []
        missing_publication: set[date] = set()
        missing_coverage: set[date] = set()
        fetched = existing = imported = unchanged = new_versions = 0
        skipped_existing = skipped_other_source = deferred = 0
        writes = 0

        for rate_type in types:
            report, counts = self._import_type(
                start=start,
                end=end,
                base=base,
                quote=quote,
                rate_type=rate_type,
                source=source,
                dry_run=dry_run,
                refresh=refresh,
                limit=limit,
                writes=writes,
                holidays=holiday_set,
                all_dates=all_dates,
            )
            reports.append(report)
            if on_progress is not None:
                on_progress(report)
            (
                type_fetched,
                type_existing,
                type_imported,
                type_unchanged,
                type_versions,
                type_skipped,
                type_other_source,
                type_deferred,
            ) = counts
            fetched += type_fetched
            existing += type_existing
            imported += type_imported
            unchanged += type_unchanged
            new_versions += type_versions
            skipped_existing += type_skipped
            skipped_other_source += type_other_source
            deferred += type_deferred
            writes += type_imported + type_versions
            missing_publication.update(report.missing_publication)
            missing_coverage.update(report.missing_coverage)
            all_errors.extend(report.errors)
            all_warnings.extend(report.warnings)

        if dry_run:
            status = STATUS_PARTIAL if all_errors else STATUS_DRY_RUN
        elif all_errors and (imported + new_versions + unchanged) == 0:
            status = STATUS_ERROR
        elif all_errors or deferred:
            status = STATUS_PARTIAL
        else:
            status = STATUS_OK

        budget_audit = None
        coverage: list[BudgetCoverage] = []
        if self._budget_table_available():
            budget_audit = self.audit_budgets()
            for rate_type in types:
                coverage.append(
                    self.coverage(
                        base_currency=base,
                        quote_currency=quote,
                        rate_type=rate_type,
                        source=source,
                        budget_audit=budget_audit,
                    )
                )

        return HistoricalImportResult(
            status=status,
            source=source,
            base_currency=base,
            quote_currency=quote,
            start_date=start,
            end_date=end,
            rate_types=types,
            started_at=started_at,
            finished_at=self.clock().astimezone(timezone.utc),
            provider_requests=len(types),
            fetched=fetched,
            existing=existing,
            imported=imported,
            unchanged=unchanged,
            new_versions=new_versions,
            skipped_existing=skipped_existing,
            skipped_other_source=skipped_other_source,
            deferred=deferred,
            missing_publication=tuple(sorted(missing_publication)),
            missing_coverage=tuple(sorted(missing_coverage)),
            reports=tuple(reports),
            errors=tuple(all_errors),
            warnings=tuple(all_warnings),
            budget_audit=budget_audit,
            coverage=tuple(coverage),
            dry_run=dry_run,
        )

    def import_for_budgets(
        self,
        *,
        base_currency: str = "USD",
        quote_currency: str = "ARS",
        rate_types: Sequence[str] | None = None,
        source: str = DEFAULT_SOURCE,
        dry_run: bool = False,
        refresh: bool = False,
        max_records: int | None = DEFAULT_MAX_RECORDS,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        holidays: Iterable[date] = (),
        on_progress=None,
    ) -> HistoricalImportResult:
        audit = self.audit_budgets()
        if audit.first_date is None or audit.last_date is None:
            raise HistoricalImportError("No hay presupuestos para analizar.")
        return self.import_range(
            start_date=audit.first_date,
            end_date=audit.last_date,
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate_types=rate_types,
            source=source,
            dry_run=dry_run,
            refresh=refresh,
            max_records=max_records,
            max_requests=max_requests,
            holidays=holidays,
            on_progress=on_progress,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _import_type(
        self,
        *,
        start: date,
        end: date,
        base: str,
        quote: str,
        rate_type: str,
        source: str,
        dry_run: bool,
        refresh: bool,
        limit: int | None,
        writes: int,
        holidays: set[date],
        all_dates: tuple[date, ...],
    ) -> tuple[TypeImportReport, tuple[int, ...]]:
        try:
            outcome = self.provider.fetch_series(
                base_currency=base,
                rate_type=rate_type,
                start_date=start,
                end_date=end,
            )
        except ProviderHTTPError as exc:
            outcome = ProviderOutcome(
                provider=self.provider.name,
                errors=(str(exc),),
            )
        except Exception as exc:  # noqa: BLE001 - el importador debe continuar
            outcome = ProviderOutcome(
                provider=getattr(self.provider, "name", "proveedor"),
                errors=(f"{type(exc).__name__}: {exc}",),
            )

        rows = list(
            ExchangeRate.select().where(
                (ExchangeRate.base_currency == base)
                & (ExchangeRate.quote_currency == quote)
                & (ExchangeRate.rate_type == rate_type)
                & (ExchangeRate.effective_date >= start)
                & (ExchangeRate.effective_date <= end)
            )
        )
        existing_by_date: dict[date, ExchangeRate] = {}
        source_by_date: dict[date, ExchangeRate] = {}
        for row in rows:
            current = existing_by_date.get(row.effective_date)
            if current is None or row.version > current.version:
                existing_by_date[row.effective_date] = row
            if row.source == source:
                current = source_by_date.get(row.effective_date)
                if current is None or row.version > current.version:
                    source_by_date[row.effective_date] = row

        fetched_rates = {
            rate.effective_date: rate
            for rate in outcome.rates
            if (
                start <= rate.effective_date <= end
                and rate.base_currency == base
                and rate.quote_currency == quote
                and rate.rate_type == rate_type
            )
        }
        available = set(existing_by_date) | set(fetched_rates)
        missing_publication: list[date] = []
        missing_coverage: list[date] = []
        for current in all_dates:
            if current in available:
                continue
            if current.weekday() >= 5 or current in holidays:
                missing_publication.append(current)
            else:
                missing_coverage.append(current)

        imported = unchanged = new_versions = skipped_existing = 0
        skipped_other_source = deferred = 0
        errors = list(outcome.errors)
        warnings = list(outcome.warnings)
        rates = sorted(fetched_rates.values(), key=lambda item: item.effective_date)
        for rate in rates:
            if rate.effective_date in existing_by_date:
                if refresh and rate.effective_date in source_by_date:
                    if limit is not None and not dry_run and writes >= limit:
                        deferred += 1
                        continue
                    if not dry_run:
                        try:
                            registration = self.rate_service.register(
                                base_currency=rate.base_currency,
                                quote_currency=rate.quote_currency,
                                effective_date=rate.effective_date,
                                rate_type=rate.rate_type,
                                buy_rate=rate.buy_rate,
                                sell_rate=rate.sell_rate,
                                source=rate.source,
                                origin=rate.origin,
                                fetched_at=rate.fetched_at,
                            )
                        except ExchangeRateError as exc:
                            errors.append(
                                f"{rate.base_currency}/{rate.rate_type} "
                                f"{rate.effective_date.isoformat()}: {exc}"
                            )
                            continue
                        if registration.created:
                            writes += 1
                            new_versions += 1
                        else:
                            unchanged += 1
                    else:
                        current = source_by_date[rate.effective_date]
                        if (
                            current.buy_rate == rate.buy_rate
                            and current.sell_rate == rate.sell_rate
                        ):
                            unchanged += 1
                        else:
                            new_versions += 1
                elif rate.effective_date in source_by_date:
                    skipped_existing += 1
                else:
                    skipped_other_source += 1
                continue

            if limit is not None and not dry_run and writes >= limit:
                deferred += 1
                continue
            if dry_run:
                imported += 1
                continue
            try:
                registration = self.rate_service.register(
                    base_currency=rate.base_currency,
                    quote_currency=rate.quote_currency,
                    effective_date=rate.effective_date,
                    rate_type=rate.rate_type,
                    buy_rate=rate.buy_rate,
                    sell_rate=rate.sell_rate,
                    source=rate.source,
                    origin=rate.origin,
                    fetched_at=rate.fetched_at,
                )
            except ExchangeRateError as exc:
                errors.append(
                    f"{rate.base_currency}/{rate.rate_type} "
                    f"{rate.effective_date.isoformat()}: {exc}"
                )
                continue
            if registration.created:
                imported += 1
                writes += 1
            else:
                unchanged += 1
                writes += 1

        report = TypeImportReport(
            base_currency=base,
            rate_type=rate_type,
            provider=self.provider.name,
            fetched=len(fetched_rates),
            existing=len(existing_by_date),
            imported=imported,
            unchanged=unchanged,
            new_versions=new_versions,
            skipped_existing=skipped_existing,
            skipped_other_source=skipped_other_source,
            deferred=deferred,
            missing_publication=tuple(missing_publication),
            missing_coverage=tuple(missing_coverage),
            errors=tuple(errors),
            warnings=tuple(warnings),
        )
        counts = (
            len(fetched_rates),
            len(existing_by_date),
            imported,
            unchanged,
            new_versions,
            skipped_existing,
            skipped_other_source,
            deferred,
        )
        return report, counts

    @staticmethod
    def _budget_table_available() -> bool:
        try:
            Budget.select().limit(1).exists()
            return True
        except PeeweeException:
            return False


def _as_date(value, label: str) -> date:
    if isinstance(value, datetime):
        return value.astimezone(ZONA_AR).date()
    if isinstance(value, date):
        return value
    raise HistoricalImportError(f"{label} debe ser una fecha.")


# Re-exportado para tests y consumidores que quieran distinguir el error.
__all__ = [
    "BudgetCoverage",
    "BudgetDateAudit",
    "DEFAULT_MAX_RECORDS",
    "DEFAULT_MAX_REQUESTS",
    "DEFAULT_SOURCE",
    "HistoricalExchangeRateImportService",
    "HistoricalImportError",
    "HistoricalImportResult",
    "STATUS_DRY_RUN",
    "STATUS_ERROR",
    "STATUS_OK",
    "STATUS_PARTIAL",
    "TypeImportReport",
]
