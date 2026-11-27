"""#973: comparacion de presupuestos ARS/USD por tipo, fuente y punta."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.budgets import Budget, BudgetItem
from app.models.exchange_rates import ExchangeRate
from app.models.masters import Client, Product
from app.reports.budget_usd_comparison import (
    COVERAGE_EXACT,
    COVERAGE_MISSING,
    COVERAGE_PRIOR,
    BudgetUsdComparisonService,
    BudgetUsdFilters,
)
from app.reports.budget_usd_comparison_export import export_budget_usd_comparison_xlsx
from app.services.exchange_rate_service import ExchangeRateService

D_BEFORE = date(2026, 11, 1)
D1 = date(2026, 11, 19)
D2 = date(2026, 11, 20)
D4 = date(2026, 11, 22)


def _client():
    return Client.create(
        name="Cliente USD",
        cuit="30-70000973-1",
        iva_condition="RI",
    )


def _budget(client, issue_date, number, total, *, status=Budget.STATUS_ACTIVE):
    return Budget.create(
        budget_number=number,
        client=client,
        origin=Budget.ORIGIN_MANUAL,
        issue_date=issue_date,
        status=status,
        total_amount=total,
    )


def _rates():
    service = ExchangeRateService("admin")
    for effective, buy, sell in (
        (D1, "1000", "1100"),
        (D2, "1050", "1150"),
    ):
        service.register(
            base_currency="USD",
            quote_currency="ARS",
            effective_date=effective,
            rate_type="blue",
            buy_rate=buy,
            sell_rate=sell,
            source="argentinadatos",
        )


def _filters(**overrides):
    values = {
        "start_date": D_BEFORE,
        "end_date": D4,
        "rate_type": "blue",
        "source": "argentinadatos",
        "side": "sell",
    }
    values.update(overrides)
    return BudgetUsdFilters(**values)


def test_compare_exact_prior_and_missing(db):
    client = _client()
    _budget(client, D_BEFORE, 1, 1000)
    _budget(client, D1, 2, 1100)
    _budget(client, D2, 3, 2300)
    _budget(client, D4, 4, 1150)
    _rates()

    result = BudgetUsdComparisonService().compare(_filters())

    assert [row.coverage for row in result.rows] == [
        COVERAGE_MISSING,
        COVERAGE_EXACT,
        COVERAGE_EXACT,
        COVERAGE_PRIOR,
    ]
    assert result.rows[1].rate == Decimal("1100.000000")
    assert result.rows[1].total_usd == Decimal("1.00")
    assert result.rows[2].total_usd == Decimal("2.00")
    assert result.rows[3].used_fallback is True
    assert result.rows[3].rate_effective_date == D2
    assert result.rows[3].total_usd == Decimal("1.00")
    assert result.rows[0].total_usd is None
    assert result.summary.total_budgets == 4
    assert result.summary.exact_budgets == 2
    assert result.summary.prior_budgets == 1
    assert result.summary.missing_budgets == 1
    assert result.summary.total_ars == Decimal("5550.00")
    assert result.summary.total_usd == Decimal("4.00")
    assert result.summary.weighted_rate == Decimal("1137.500000")
    assert result.summary.coverage_percent == Decimal("81.98")


def test_item_detail_uses_the_same_budget_rate(db):
    client = _client()
    budget = _budget(client, D1, 1, 1100)
    product = Product.create(name="Producto USD", unit="kg", codigo="P-USD")
    BudgetItem.create(
        budget=budget,
        product=product,
        quantity=2,
        unit="kg",
        unit_price=550,
        total=1100,
    )
    _rates()

    result = BudgetUsdComparisonService().compare(_filters())

    assert len(result.items) == 1
    item = result.items[0]
    assert item.product_name == "Producto USD"
    assert item.quantity == Decimal("2")
    assert item.unit_price_ars == Decimal("550")
    assert item.rate == Decimal("1100.000000")
    assert item.unit_price_usd == Decimal("0.500000")
    assert item.total_usd == Decimal("1.00")


def test_compare_supports_buy_and_average_side(db):
    client = _client()
    _budget(client, D1, 1, 1100)
    _rates()
    service = BudgetUsdComparisonService()

    buy = service.compare(_filters(side="buy"))
    average = service.compare(_filters(side="average"))

    assert buy.rows[0].rate == Decimal("1000.000000")
    assert buy.rows[0].total_usd == Decimal("1.10")
    assert average.rows[0].rate == Decimal("1050.000000")
    assert average.rows[0].total_usd == Decimal("1.05")


def test_compare_does_not_mix_sources(db):
    client = _client()
    _budget(client, D1, 1, 1100)
    _rates()
    ExchangeRateService("admin").register(
        base_currency="USD",
        quote_currency="ARS",
        effective_date=D1,
        rate_type="blue",
        buy_rate="1200",
        sell_rate="1200",
        source="dolarapi",
    )
    service = BudgetUsdComparisonService()

    arg = service.compare(_filters(source="argentinadatos"))
    dolar = service.compare(_filters(source="dolarapi"))
    any_source = service.compare(_filters(source="any"))

    assert arg.rows[0].rate_source == "argentinadatos"
    assert arg.rows[0].total_usd == Decimal("1.00")
    assert dolar.rows[0].rate_source == "dolarapi"
    assert dolar.rows[0].total_usd == Decimal("0.92")
    assert any_source.rows[0].rate_source == "argentinadatos"


def test_annulled_budgets_are_excluded_by_default(db):
    client = _client()
    _budget(client, D1, 1, 1100)
    _budget(client, D1, 2, 2200, status=Budget.STATUS_ANNULLED)
    _rates()
    service = BudgetUsdComparisonService()

    active = service.compare(_filters())
    with_annulled = service.compare(_filters(include_annulled=True))

    assert active.summary.total_budgets == 1
    assert active.summary.total_ars == Decimal("1100.00")
    assert with_annulled.summary.total_budgets == 2
    assert with_annulled.summary.total_ars == Decimal("3300.00")


def test_budget_date_range_uses_active_budgets(db):
    client = _client()
    _budget(client, D1, 1, 1100)
    _budget(client, D4, 2, 1100)
    _budget(client, D_BEFORE, 3, 1100, status=Budget.STATUS_ANNULLED)

    assert BudgetUsdComparisonService().budget_date_range() == (D1, D4)


def test_compare_all_and_export_workbook(db, tmp_path):
    client = _client()
    _budget(client, D1, 1, 1100)
    _rates()
    service = BudgetUsdComparisonService()
    results = service.compare_all(_filters(), rate_types=("oficial", "blue"))

    assert [result.rate_type for result in results] == ["oficial", "blue"]
    path = export_budget_usd_comparison_xlsx(results, tmp_path / "comparacion.xlsx")

    from openpyxl import load_workbook

    workbook = load_workbook(path)
    assert "Resumen" in workbook.sheetnames
    assert "Evolucion_mensual" in workbook.sheetnames
    assert "Comparativo_tipos" in workbook.sheetnames
    assert "Oficial" in workbook.sheetnames
    assert "Blue" in workbook.sheetnames
    assert "Productos" in workbook.sheetnames
    assert "Sin_cotizacion" in workbook.sheetnames
    assert "Criterio" in workbook.sheetnames
    assert workbook["Blue"].max_row == 2  # encabezado + un presupuesto
    assert workbook["Resumen"].max_row == 3  # encabezado + dos tipos


def test_monthly_evolution_calculates_variations(db):
    from app.reports.budget_usd_comparison import monthly_evolution

    october = date(2026, 10, 15)
    client = _client()
    _budget(client, october, 1, 1100)
    _budget(client, D2, 2, 2200)
    ExchangeRateService("admin").register(
        base_currency="USD",
        quote_currency="ARS",
        effective_date=october,
        rate_type="blue",
        buy_rate="1100",
        sell_rate="1100",
        source="argentinadatos",
    )
    _rates()

    result = BudgetUsdComparisonService().compare(
        _filters(start_date=date(2026, 10, 1))
    )
    months = monthly_evolution(result.rows)

    assert [month.label for month in months] == ["10/2026", "11/2026"]
    assert months[0].total_usd == Decimal("1.00")
    assert months[1].total_usd == Decimal("1.91")
    assert months[0].variation_usd is None
    assert months[1].variation_usd == Decimal("91.00")
    assert months[1].variation_ars == Decimal("100.00")


def test_monthly_evolution_and_type_comparison(db):
    from app.reports.budget_usd_comparison import monthly_evolution, type_comparison

    client = _client()
    _budget(client, D1, 1, 1100)
    _budget(client, D2, 2, 2300)
    _rates()
    service = BudgetUsdComparisonService()
    results = service.compare_all(_filters(), rate_types=("oficial", "blue"))
    blue = next(item for item in results if item.rate_type == "blue")

    months = monthly_evolution(blue.rows)
    comparison = type_comparison(results, base_type="blue")

    assert len(months) == 1
    assert months[0].month == "2026-11"
    assert months[0].budgets == 2
    assert months[0].total_usd == Decimal("3.00")
    assert months[0].variation_usd is None
    assert len(comparison) == 2
    by_type = {item.rate_type: item for item in comparison}
    assert by_type["blue"].difference_usd == Decimal("0.00")
    assert by_type["oficial"].difference_usd == Decimal("-3.00")


def test_dialog_shows_summary_without_writing(db):
    from PyQt5.QtWidgets import QApplication

    client = _client()
    _budget(client, D1, 1, 1100)
    _budget(client, D4, 2, 1150)
    _rates()
    app = QApplication.instance() or QApplication([])
    from app.ui.budget_usd_comparison import BudgetUsdComparisonDialog

    dialog = BudgetUsdComparisonDialog()
    try:
        assert dialog.table.rowCount() == 2
        assert dialog.evolution_table.rowCount() == 1
        assert dialog.comparison_table.rowCount() == 7
        assert dialog.total_usd_label.text().startswith("USD")
        assert dialog.table.item(1, 10).text() == "Anterior"
    finally:
        dialog.close()
        app.processEvents()


def test_invalid_filters_are_rejected(db):
    with pytest.raises(ValueError):
        _filters(start_date=D4, end_date=D1)
    with pytest.raises(ValueError):
        _filters(rate_type="otro")
    with pytest.raises(ValueError):
        _filters(side="otro")


def test_dashboard_has_budget_usd_access(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    app = QApplication.instance() or QApplication([])
    from app.ui.managerial_dashboard import ManagerialDashboardPage

    page = ManagerialDashboardPage()
    try:
        button = page.findChild(QPushButton, "managerialBudgetUsdButton")
        assert button is not None
        assert "USD" in button.text()
        open_button = page.findChild(QPushButton, "managerialBudgetUsdOpen")
        assert open_button is not None
    finally:
        page.close()
        app.processEvents()
