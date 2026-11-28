"""Exportacion Excel de la comparacion de presupuestos ARS/USD (#973)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from app.reports.budget_usd_comparison import (
    COVERAGE_EXACT,
    COVERAGE_MISSING,
    COVERAGE_PRIOR,
    SOURCE_LABELS,
    SIDE_LABELS,
    TYPE_LABELS,
    BudgetUsdComparisonResult,
    monthly_evolution,
    type_comparison,
)

SUMMARY_SHEET = "Resumen"
EVOLUTION_SHEET = "Evolucion_mensual"
COMPARISON_SHEET = "Comparativo_tipos"
MISSING_SHEET = "Sin_cotizacion"
PRODUCTS_SHEET = "Productos"
CRITERIA_SHEET = "Criterio"


def _float(value) -> float | None:
    return None if value is None else float(value)


def _coverage_label(value: str) -> str:
    return {
        COVERAGE_EXACT: "Exacta",
        COVERAGE_PRIOR: "Anterior",
        COVERAGE_MISSING: "Sin cotizacion",
    }.get(value, value)


def _write_table(ws, headers: tuple[str, ...], rows: Iterable[tuple], widths=None) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append(list(row))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for index, header in enumerate(headers, start=1):
        width = widths[index - 1] if widths and index <= len(widths) else max(12, len(header) + 2)
        ws.column_dimensions[get_column_letter(index)].width = width


def export_budget_usd_comparison_xlsx(
    results: Iterable[BudgetUsdComparisonResult],
    path: Path | str,
    *,
    generated_at: datetime | None = None,
) -> Path:
    items = tuple(results)
    if not items:
        raise ValueError("No hay resultados para exportar.")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.remove(workbook.active)

    generated = generated_at or datetime.now().astimezone()
    first = items[0]

    summary = workbook.create_sheet(SUMMARY_SHEET)
    _write_table(
        summary,
        (
            "Tipo",
            "Descripcion",
            "Fuente",
            "Punta",
            "Desde",
            "Hasta",
            "Presupuestos",
            "Exactas",
            "Anteriores",
            "Sin cotizacion",
            "Cobertura %",
            "Total ARS",
            "ARS convertible",
            "ARS sin cobertura",
            "Total USD",
            "Cotizacion promedio ponderada",
        ),
        (
            (
                result.rate_type,
                TYPE_LABELS.get(result.rate_type, result.rate_type),
                SOURCE_LABELS.get(result.source or "any", result.source or "Cualquiera"),
                SIDE_LABELS.get(result.filters.side, result.filters.side),
                result.filters.start_date.isoformat(),
                result.filters.end_date.isoformat(),
                result.summary.total_budgets,
                result.summary.exact_budgets,
                result.summary.prior_budgets,
                result.summary.missing_budgets,
                _float(result.summary.coverage_percent),
                _float(result.summary.total_ars),
                _float(result.summary.converted_ars),
                _float(result.summary.uncovered_ars),
                _float(result.summary.total_usd),
                _float(result.summary.weighted_rate),
            )
            for result in items
        ),
        widths=(10, 18, 16, 10, 12, 12, 12, 10, 10, 14, 12, 16, 16, 18, 16, 22),
    )

    evolution_rows = []
    for result in items:
        for month in monthly_evolution(result.rows):
            evolution_rows.append(
                (
                    result.rate_type,
                    month.label,
                    "Si" if month.partial else "No",
                    month.budgets,
                    _float(month.total_ars),
                    _float(month.total_usd),
                    _float(month.variation_ars),
                    _float(month.variation_usd),
                    _float(month.coverage_percent),
                    month.exact_budgets,
                    month.prior_budgets,
                    month.missing_budgets,
                )
            )
    evolution = workbook.create_sheet(EVOLUTION_SHEET)
    _write_table(
        evolution,
        (
            "Tipo",
            "Mes",
            "Parcial",
            "Presupuestos",
            "Total ARS",
            "Total USD",
            "Var ARS %",
            "Var USD %",
            "Cobertura %",
            "Exactas",
            "Anteriores",
            "Sin cotizacion",
        ),
        evolution_rows,
        widths=(10, 10, 8, 12, 16, 16, 12, 12, 12, 10, 12, 14),
    )

    comparison = workbook.create_sheet(COMPARISON_SHEET)
    _write_table(
        comparison,
        (
            "Tipo",
            "Fuente",
            "Presupuestos",
            "Total ARS",
            "Total USD",
            "Cotizacion ponderada",
            "Cobertura %",
            "Comparables",
            "Cobertura comparable %",
            "Total USD comparable",
            "Diferencia USD vs blue",
            "Diferencia % vs blue",
        ),
        (
            (
                item.rate_type,
                SOURCE_LABELS.get(item.source or "any", item.source or "Cualquiera"),
                item.budgets,
                _float(item.total_ars),
                _float(item.total_usd),
                _float(item.weighted_rate),
                _float(item.coverage_percent),
                item.comparable_budgets,
                _float(item.comparable_coverage_percent),
                _float(item.comparable_total_usd),
                _float(item.difference_usd),
                _float(item.difference_percent),
            )
            for item in type_comparison(items, base_type="blue")
        ),
        widths=(10, 16, 12, 16, 16, 18, 12, 12, 20, 20, 22, 22),
    )

    missing_rows = []
    product_rows = []
    used_names: set[str] = set()
    for result in items:
        sheet_name = TYPE_LABELS.get(result.rate_type, result.rate_type)[:31]
        base_name = sheet_name
        suffix = 2
        while sheet_name in used_names:
            sheet_name = f"{base_name[:27]}_{suffix}"
            suffix += 1
        used_names.add(sheet_name)
        sheet = workbook.create_sheet(sheet_name)
        _write_table(
            sheet,
            (
                "Fecha presupuesto",
                "Presupuesto",
                "Cliente",
                "Estado",
                "Origen",
                "Total ARS",
                "Cotizacion",
                "Fecha efectiva",
                "Fuente",
                "Version",
                "Fallback",
                "Cobertura",
                "Total USD",
                "Observacion",
            ),
            (
                (
                    row.issue_date.isoformat(),
                    f"PRES-{row.budget_number:06d}",
                    row.client_name,
                    row.status,
                    row.origin,
                    _float(row.total_ars),
                    _float(row.rate),
                    row.rate_effective_date.isoformat() if row.rate_effective_date else "",
                    row.rate_source or "",
                    row.rate_version,
                    "Si" if row.used_fallback else "No",
                    _coverage_label(row.coverage),
                    _float(row.total_usd),
                    row.warning,
                )
                for row in result.rows
            ),
            widths=(16, 14, 28, 12, 12, 16, 14, 14, 16, 8, 10, 14, 16, 44),
        )
        for row in result.rows:
            if row.coverage == COVERAGE_MISSING:
                missing_rows.append(
                    (
                        result.rate_type,
                        row.issue_date.isoformat(),
                        f"PRES-{row.budget_number:06d}",
                        row.client_name,
                        _float(row.total_ars),
                        "Sin cotizacion exacta ni anterior",
                    )
                )
        for item in result.items:
            product_rows.append(
                (
                    result.rate_type,
                    item.issue_date.isoformat(),
                    f"PRES-{item.budget_number:06d}",
                    item.client_name,
                    item.product_code,
                    item.product_name,
                    item.unit,
                    _float(item.quantity),
                    _float(item.unit_price_ars),
                    _float(item.rate),
                    _float(item.unit_price_usd),
                    _float(item.total_ars),
                    _float(item.total_usd),
                    _coverage_label(item.coverage),
                )
            )

    products = workbook.create_sheet(PRODUCTS_SHEET)
    _write_table(
        products,
        (
            "Tipo",
            "Fecha presupuesto",
            "Presupuesto",
            "Cliente",
            "Codigo producto",
            "Producto",
            "Unidad",
            "Cantidad",
            "Precio unitario ARS",
            "Cotizacion",
            "Precio unitario USD",
            "Total ARS",
            "Total USD",
            "Cobertura",
        ),
        product_rows,
        widths=(10, 16, 14, 28, 14, 28, 8, 12, 18, 14, 18, 16, 16, 14),
    )

    missing = workbook.create_sheet(MISSING_SHEET)
    _write_table(
        missing,
        (
            "Tipo",
            "Fecha presupuesto",
            "Presupuesto",
            "Cliente",
            "Total ARS",
            "Motivo",
        ),
        missing_rows,
        widths=(10, 16, 14, 30, 16, 40),
    )

    criteria = workbook.create_sheet(CRITERIA_SHEET)
    criteria.append(("Criterio", "Valor"))
    criteria["A1"].font = Font(bold=True)
    criteria["B1"].font = Font(bold=True)
    criteria_rows = (
        ("Generado", generated.isoformat()),
        ("Desde", first.filters.start_date.isoformat()),
        ("Hasta", first.filters.end_date.isoformat()),
        ("Fuente", SOURCE_LABELS.get(first.source or "any", first.source or "Cualquiera")),
        ("Punta", SIDE_LABELS.get(first.filters.side, first.filters.side)),
        ("Incluye anulados", "Si" if first.filters.include_annulled else "No"),
        ("Permite cotizacion anterior", "Si" if first.filters.allow_prior else "No"),
        ("Formula", "USD = ARS / cotizacion (ARS por 1 USD)"),
        ("Tipos", ", ".join(result.rate_type for result in items)),
        ("Regla", "Cada hoja usa un solo tipo y fuente. Los faltantes no se convierten a cero."),
    )
    for row in criteria_rows:
        criteria.append(row)
    criteria.column_dimensions["A"].width = 30
    criteria.column_dimensions["B"].width = 80

    workbook.save(target)
    return target
