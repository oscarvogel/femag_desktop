"""Comparacion historica de presupuestos ARS/USD (#973).

Lee presupuestos y cotizaciones; no modifica ninguna de las dos cosas. Cada
resultado conserva el tipo, la fuente, la fecha efectiva y la version de la
cotizacion usada.

Regla: ``USD = ARS / (ARS por 1 USD)``. Si no hay cotizacion exacta se puede
usar la inmediata anterior, siempre marcada. Si no hay ninguna, el presupuesto
queda sin cotizacion y no se convierte a cero.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Sequence

from app.models.budgets import Budget, BudgetItem
from app.models.exchange_rates import ExchangeRate
from app.models.masters import Client, Product
from app.services.money import quantize_money, to_decimal

RATE_TYPES = (
    "oficial",
    "blue",
    "mep",
    "ccl",
    "mayorista",
    "tarjeta",
    "bna",
)

TYPE_LABELS = {
    "oficial": "Oficial",
    "blue": "Blue",
    "mep": "MEP",
    "ccl": "CCL",
    "mayorista": "Mayorista",
    "tarjeta": "Tarjeta",
    "bna": "Banco Nacion",
}

SOURCE_LABELS = {
    "argentinadatos": "ArgentinaDatos",
    "dolarapi": "DolarAPI",
    "bna": "Banco Nacion",
    "any": "Cualquiera",
}

COVERAGE_EXACT = "exact"
COVERAGE_PRIOR = "prior"
COVERAGE_MISSING = "missing"

RATE_SIDE_BUY = "buy"
RATE_SIDE_SELL = "sell"
RATE_SIDE_AVERAGE = "average"
RATE_SIDES = (RATE_SIDE_BUY, RATE_SIDE_SELL, RATE_SIDE_AVERAGE)
SIDE_LABELS = {
    RATE_SIDE_BUY: "Compra",
    RATE_SIDE_SELL: "Venta",
    RATE_SIDE_AVERAGE: "Promedio",
}

RATE_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class BudgetUsdFilters:
    start_date: date
    end_date: date
    rate_type: str = "blue"
    source: str | None = "argentinadatos"
    side: str = RATE_SIDE_SELL
    include_annulled: bool = False
    allow_prior: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.start_date, datetime) or isinstance(self.end_date, datetime):
            raise ValueError("Las fechas del informe deben ser fechas, no datetime.")
        if self.end_date < self.start_date:
            raise ValueError("La fecha hasta no puede ser anterior a la fecha desde.")
        if self.rate_type not in RATE_TYPES:
            raise ValueError(f"Tipo de cotizacion invalido: {self.rate_type!r}.")
        if self.side not in RATE_SIDES:
            raise ValueError(f"Punta de cotizacion invalida: {self.side!r}.")
        if self.source == "any":
            object.__setattr__(self, "source", None)
        elif self.source:
            normalized = str(self.source).strip().lower()
            object.__setattr__(self, "source", normalized or None)


@dataclass(frozen=True)
class BudgetUsdRow:
    budget_id: int
    budget_number: int
    issue_date: date
    client_name: str
    status: str
    origin: str
    total_ars: Decimal
    rate: Decimal | None
    rate_effective_date: date | None
    rate_source: str | None
    rate_version: int | None
    used_fallback: bool
    total_usd: Decimal | None
    coverage: str
    warning: str = ""


@dataclass(frozen=True)
class BudgetUsdItemRow:
    budget_id: int
    budget_number: int
    issue_date: date
    client_name: str
    product_code: str
    product_name: str
    unit: str
    quantity: Decimal
    unit_price_ars: Decimal
    total_ars: Decimal
    rate: Decimal | None
    rate_effective_date: date | None
    coverage: str
    unit_price_usd: Decimal | None
    total_usd: Decimal | None


@dataclass(frozen=True)
class BudgetUsdSummary:
    total_budgets: int
    exact_budgets: int
    prior_budgets: int
    missing_budgets: int
    total_ars: Decimal
    converted_ars: Decimal
    uncovered_ars: Decimal
    total_usd: Decimal
    weighted_rate: Decimal | None
    coverage_percent: Decimal

    @property
    def covered_budgets(self) -> int:
        return self.exact_budgets + self.prior_budgets


@dataclass(frozen=True)
class BudgetUsdMonth:
    month: str
    label: str
    budgets: int
    total_ars: Decimal
    total_usd: Decimal
    coverage_percent: Decimal
    exact_budgets: int
    prior_budgets: int
    missing_budgets: int
    previous_total_ars: Decimal | None
    previous_total_usd: Decimal | None
    variation_ars: Decimal | None
    variation_usd: Decimal | None


@dataclass(frozen=True)
class BudgetUsdTypeComparison:
    rate_type: str
    source: str | None
    budgets: int
    total_ars: Decimal
    total_usd: Decimal
    weighted_rate: Decimal | None
    coverage_percent: Decimal
    covered_budgets: int
    difference_usd: Decimal | None
    difference_percent: Decimal | None


@dataclass(frozen=True)
class BudgetUsdComparisonResult:
    filters: BudgetUsdFilters
    rows: tuple[BudgetUsdRow, ...]
    items: tuple[BudgetUsdItemRow, ...]
    summary: BudgetUsdSummary
    generated_at: datetime

    @property
    def rate_type(self) -> str:
        return self.filters.rate_type

    @property
    def source(self) -> str | None:
        return self.filters.source


class BudgetUsdComparisonService:
    """Calcula la comparacion sin escribir en presupuestos ni cotizaciones."""

    def budget_date_range(self) -> tuple[date | None, date | None]:
        query = Budget.select(Budget.issue_date).where(
            Budget.status == Budget.STATUS_ACTIVE
        )
        dates = sorted(
            row.issue_date for row in query if row.issue_date is not None
        )
        return (dates[0], dates[-1]) if dates else (None, None)

    def compare(self, filters: BudgetUsdFilters) -> BudgetUsdComparisonResult:
        budgets = list(self._budgets(filters))
        rates = self._rates(filters)
        rate_dates = sorted(rates)
        rows: list[BudgetUsdRow] = []
        for budget in budgets:
            rate_row = None
            coverage = COVERAGE_MISSING
            used_fallback = False
            if budget.issue_date in rates:
                rate_row = rates[budget.issue_date]
                coverage = COVERAGE_EXACT
            elif filters.allow_prior:
                index = bisect.bisect_left(rate_dates, budget.issue_date) - 1
                if index >= 0:
                    rate_row = rates[rate_dates[index]]
                    coverage = COVERAGE_PRIOR
                    used_fallback = True

            total_ars = quantize_money(to_decimal(budget.total_amount))
            total_usd = None
            rate_value = None
            if rate_row is not None:
                rate_value = self._rate_value(rate_row, filters.side)
                if rate_value > 0:
                    total_usd = quantize_money(total_ars / rate_value)
                else:
                    rate_row = None
                    rate_value = None
                    coverage = COVERAGE_MISSING
                    used_fallback = False

            warning = ""
            if coverage == COVERAGE_MISSING:
                warning = (
                    "Sin cotizacion para la fecha ni anterior utilizable."
                )
            elif coverage == COVERAGE_PRIOR:
                warning = (
                    "Sin publicacion en la fecha; se uso la cotizacion anterior."
                )

            rows.append(
                BudgetUsdRow(
                    budget_id=int(budget.id),
                    budget_number=int(budget.budget_number),
                    issue_date=budget.issue_date,
                    client_name=str(budget.client.name if budget.client else ""),
                    status=budget.status,
                    origin=budget.origin,
                    total_ars=total_ars,
                    rate=rate_value,
                    rate_effective_date=(
                        rate_row.effective_date if rate_row is not None else None
                    ),
                    rate_source=rate_row.source if rate_row is not None else None,
                    rate_version=rate_row.version if rate_row is not None else None,
                    used_fallback=used_fallback,
                    total_usd=total_usd,
                    coverage=coverage,
                    warning=warning,
                )
            )

        summary = self._summary(rows)
        row_by_id = {row.budget_id: row for row in rows}
        items: list[BudgetUsdItemRow] = []
        if row_by_id:
            item_query = (
                BudgetItem.select(BudgetItem, Product)
                .join(Product)
                .where(BudgetItem.budget.in_(tuple(row_by_id)))
            )
            for item in item_query:
                row = row_by_id.get(int(item.budget_id))
                if row is None:
                    continue
                total_ars = quantize_money(to_decimal(item.total))
                unit_price_ars = to_decimal(item.unit_price)
                unit_price_usd = None
                total_usd = None
                if row.rate is not None and row.rate > 0:
                    unit_price_usd = (unit_price_ars / row.rate).quantize(
                        RATE_QUANTUM, rounding=ROUND_HALF_UP
                    )
                    total_usd = quantize_money(total_ars / row.rate)
                items.append(
                    BudgetUsdItemRow(
                        budget_id=row.budget_id,
                        budget_number=row.budget_number,
                        issue_date=row.issue_date,
                        client_name=row.client_name,
                        product_code=str(item.product.codigo or ""),
                        product_name=str(item.product.name or ""),
                        unit=str(item.unit or ""),
                        quantity=to_decimal(item.quantity),
                        unit_price_ars=unit_price_ars,
                        total_ars=total_ars,
                        rate=row.rate,
                        rate_effective_date=row.rate_effective_date,
                        coverage=row.coverage,
                        unit_price_usd=unit_price_usd,
                        total_usd=total_usd,
                    )
                )
        return BudgetUsdComparisonResult(
            filters=filters,
            rows=tuple(rows),
            items=tuple(items),
            summary=summary,
            generated_at=datetime.now(timezone.utc),
        )

    def compare_all(
        self, filters: BudgetUsdFilters, *, rate_types=None
    ) -> tuple[BudgetUsdComparisonResult, ...]:
        types = tuple(rate_types or RATE_TYPES)
        return tuple(
            self.compare(
                BudgetUsdFilters(
                    start_date=filters.start_date,
                    end_date=filters.end_date,
                    rate_type=rate_type,
                    source=filters.source,
                    side=filters.side,
                    include_annulled=filters.include_annulled,
                    allow_prior=filters.allow_prior,
                )
            )
            for rate_type in types
        )

    @staticmethod
    def _rate_value(row: ExchangeRate, side: str) -> Decimal:
        buy = to_decimal(row.buy_rate)
        sell = to_decimal(row.sell_rate)
        if side == RATE_SIDE_BUY:
            value = buy
        elif side == RATE_SIDE_AVERAGE:
            with localcontext() as context:
                context.prec = 28
                value = (buy + sell) / Decimal("2")
        else:
            value = sell
        return value.quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)

    def _budgets(self, filters: BudgetUsdFilters):
        query = (
            Budget.select(Budget, Client)
            .join(Client)
            .where(Budget.issue_date.between(filters.start_date, filters.end_date))
            .order_by(Budget.issue_date, Budget.budget_number)
        )
        if not filters.include_annulled:
            query = query.where(Budget.status == Budget.STATUS_ACTIVE)
        return query

    def _rates(self, filters: BudgetUsdFilters) -> dict[date, ExchangeRate]:
        query = ExchangeRate.select().where(
            (ExchangeRate.base_currency == "USD")
            & (ExchangeRate.quote_currency == "ARS")
            & (ExchangeRate.rate_type == filters.rate_type)
            & (ExchangeRate.effective_date <= filters.end_date)
        )
        if filters.source:
            query = query.where(ExchangeRate.source == filters.source)
        by_date: dict[date, ExchangeRate] = {}
        for row in query.order_by(ExchangeRate.effective_date, ExchangeRate.version):
            current = by_date.get(row.effective_date)
            if current is None or row.version > current.version:
                by_date[row.effective_date] = row
            elif row.version == current.version:
                # Con "cualquier fuente", mantener una eleccion estable.
                if str(row.source) < str(current.source):
                    by_date[row.effective_date] = row
        return by_date

    @staticmethod
    def _summary(rows: list[BudgetUsdRow]) -> BudgetUsdSummary:
        total_ars = quantize_money(sum((row.total_ars for row in rows), Decimal("0")))
        converted_ars = quantize_money(
            sum((row.total_ars for row in rows if row.total_usd is not None), Decimal("0"))
        )
        total_usd = quantize_money(
            sum((row.total_usd for row in rows if row.total_usd is not None), Decimal("0"))
        )
        exact = sum(1 for row in rows if row.coverage == COVERAGE_EXACT)
        prior = sum(1 for row in rows if row.coverage == COVERAGE_PRIOR)
        missing = sum(1 for row in rows if row.coverage == COVERAGE_MISSING)
        coverage_percent = Decimal("0.00")
        if total_ars > 0:
            with localcontext() as context:
                context.prec = 28
                coverage_percent = (converted_ars / total_ars * Decimal("100")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
        weighted_rate = None
        if total_usd > 0:
            with localcontext() as context:
                context.prec = 28
                weighted_rate = (converted_ars / total_usd).quantize(
                    RATE_QUANTUM, rounding=ROUND_HALF_UP
                )
        return BudgetUsdSummary(
            total_budgets=len(rows),
            exact_budgets=exact,
            prior_budgets=prior,
            missing_budgets=missing,
            total_ars=total_ars,
            converted_ars=converted_ars,
            uncovered_ars=quantize_money(total_ars - converted_ars),
            total_usd=total_usd,
            weighted_rate=weighted_rate,
            coverage_percent=coverage_percent,
        )

def _variation(current: Decimal, previous: Decimal | None) -> Decimal | None:
    if previous is None or previous == 0:
        return None if current else Decimal("0.00")
    with localcontext() as context:
        context.prec = 28
        return ((current - previous) / abs(previous) * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


def monthly_evolution(rows: Sequence[BudgetUsdRow]) -> tuple[BudgetUsdMonth, ...]:
    """Agrupa la comparacion por mes y calcula variacion contra el mes previo."""
    grouped: dict[str, list[BudgetUsdRow]] = {}
    for row in rows:
        grouped.setdefault(row.issue_date.strftime("%Y-%m"), []).append(row)

    result: list[BudgetUsdMonth] = []
    previous_ars: Decimal | None = None
    previous_usd: Decimal | None = None
    for month in sorted(grouped):
        month_rows = grouped[month]
        total_ars = quantize_money(
            sum((row.total_ars for row in month_rows), Decimal("0"))
        )
        total_usd = quantize_money(
            sum(
                (row.total_usd for row in month_rows if row.total_usd is not None),
                Decimal("0"),
            )
        )
        converted_ars = quantize_money(
            sum(
                (row.total_ars for row in month_rows if row.total_usd is not None),
                Decimal("0"),
            )
        )
        exact = sum(1 for row in month_rows if row.coverage == COVERAGE_EXACT)
        prior = sum(1 for row in month_rows if row.coverage == COVERAGE_PRIOR)
        missing = sum(1 for row in month_rows if row.coverage == COVERAGE_MISSING)
        coverage = Decimal("0.00")
        if total_ars > 0:
            with localcontext() as context:
                context.prec = 28
                coverage = (converted_ars / total_ars * Decimal("100")).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
        result.append(
            BudgetUsdMonth(
                month=month,
                label=f"{month[5:]}/{month[:4]}",
                budgets=len(month_rows),
                total_ars=total_ars,
                total_usd=total_usd,
                coverage_percent=coverage,
                exact_budgets=exact,
                prior_budgets=prior,
                missing_budgets=missing,
                previous_total_ars=previous_ars,
                previous_total_usd=previous_usd,
                variation_ars=_variation(total_ars, previous_ars),
                variation_usd=_variation(total_usd, previous_usd),
            )
        )
        previous_ars = total_ars
        previous_usd = total_usd
    return tuple(result)


def type_comparison(
    results: Sequence[BudgetUsdComparisonResult],
    *,
    base_type: str = "blue",
) -> tuple[BudgetUsdTypeComparison, ...]:
    """Compara el total USD de cada tipo contra el tipo base."""
    base = next((item for item in results if item.rate_type == base_type), None)
    base_usd = base.summary.total_usd if base is not None else None
    result: list[BudgetUsdTypeComparison] = []
    for item in results:
        difference = None
        difference_percent = None
        if base_usd is not None and item.summary.total_usd is not None:
            difference = quantize_money(item.summary.total_usd - base_usd)
            if base_usd > 0:
                with localcontext() as context:
                    context.prec = 28
                    difference_percent = (
                        difference / base_usd * Decimal("100")
                    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        result.append(
            BudgetUsdTypeComparison(
                rate_type=item.rate_type,
                source=item.source,
                budgets=item.summary.total_budgets,
                total_ars=item.summary.total_ars,
                total_usd=item.summary.total_usd,
                weighted_rate=item.summary.weighted_rate,
                coverage_percent=item.summary.coverage_percent,
                covered_budgets=item.summary.covered_budgets,
                difference_usd=difference,
                difference_percent=difference_percent,
            )
        )
    return tuple(result)
