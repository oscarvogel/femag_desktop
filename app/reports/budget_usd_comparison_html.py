"""Informe HTML autocontenido con graficos de la comparacion ARS/USD (#974)."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

from app.reports.budget_usd_comparison import (
    COVERAGE_MISSING,
    COVERAGE_PRIOR,
    SOURCE_LABELS,
    SIDE_LABELS,
    TYPE_LABELS,
    BudgetUsdComparisonResult,
    monthly_evolution,
    type_comparison,
)

_COLORS = (
    "#17324d",
    "#2563eb",
    "#0f766e",
    "#b45309",
    "#7c3aed",
    "#be123c",
    "#475569",
)


def _num(value, decimals: int = 2) -> str:
    if value is None:
        return "-"
    text = f"{float(value):,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _money(value) -> str:
    return f"$ {_num(value, 2)}" if value is not None else "-"


def _usd(value) -> str:
    return f"USD {_num(value, 2)}" if value is not None else "-"


def _pct(value) -> str:
    if value is None:
        return "-"
    prefix = "+" if float(value) > 0 else ""
    return f"{prefix}{_num(value, 1)}%"


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _bar_chart(
    labels: Sequence[str],
    values: Sequence[float | None],
    *,
    title: str,
    color: str,
    formatter,
) -> str:
    width, height = 960, 300
    left, right, top, bottom = 90, 24, 36, 54
    plot_w = width - left - right
    plot_h = height - top - bottom
    maximum = max((abs(float(v)) for v in values if v is not None), default=0.0) or 1.0
    step = plot_w / max(1, len(values))
    bar_w = max(4.0, min(48.0, step * 0.62))
    bars = []
    grid = []
    for index in range(5):
        value = maximum * index / 4
        y = top + plot_h - (value / maximum) * plot_h
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" '
            'stroke="#dbe3ec" stroke-width="1"/>'
        )
        grid.append(
            f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#5b6b7c">{_esc(_compact(value))}</text>'
        )
    for index, (label, value) in enumerate(zip(labels, values)):
        if value is None:
            continue
        bar_h = max(0.0, (float(value) / maximum) * plot_h)
        x = left + index * step + (step - bar_w) / 2
        y = top + plot_h - bar_h
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
            f'height="{bar_h:.1f}" rx="3" fill="{color}">'
            f"<title>{_esc(label)}: {_esc(formatter(value))}</title></rect>"
        )
        if len(labels) <= 16 or index % 2 == 0:
            bars.append(
                f'<text x="{x + bar_w/2:.1f}" y="{height-20}" text-anchor="middle" '
                f'font-size="11" fill="#425466">{_esc(label)}</text>'
            )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_esc(title)}">'
        f'<text x="{left}" y="18" font-size="14" font-weight="700" '
        f'fill="#17324d">{_esc(title)}</text>'
        + "".join(grid)
        + "".join(bars)
        + "</svg>"
    )


def _horizontal_bars(
    labels: Sequence[str],
    values: Sequence[float | None],
    *,
    title: str,
    formatter,
) -> str:
    width, height = 960, 40 + max(1, len(values)) * 38
    left, right, top = 150, 90, 34
    plot_w = width - left - right
    maximum = max((abs(float(v)) for v in values if v is not None), default=0.0) or 1.0
    parts = [
        f'<text x="18" y="20" font-size="14" font-weight="700" '
        f'fill="#17324d">{_esc(title)}</text>'
    ]
    for index, (label, value) in enumerate(zip(labels, values)):
        y = top + index * 38
        parts.append(
            f'<text x="{left-10}" y="{y+15}" text-anchor="end" '
            f'font-size="12" fill="#425466">{_esc(label)}</text>'
        )
        parts.append(
            f'<rect x="{left}" y="{y}" width="{plot_w}" height="20" '
            f'rx="4" fill="#edf2f7"/>'
        )
        if value is not None and float(value) > 0:
            bar_w = max(2.0, (float(value) / maximum) * plot_w)
            parts.append(
                f'<rect x="{left}" y="{y}" width="{bar_w:.1f}" height="20" '
                f'rx="4" fill="{_COLORS[index % len(_COLORS)]}">'
                f"<title>{_esc(label)}: {_esc(formatter(value))}</title></rect>"
            )
        parts.append(
            f'<text x="{width-right+10}" y="{y+15}" font-size="12" '
            f'fill="#17324d">{_esc(formatter(value))}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_esc(title)}">' + "".join(parts) + "</svg>"
    )


def _compact(value: float) -> str:
    amount = float(value)
    if abs(amount) >= 1_000_000_000:
        return f"{_num(amount / 1_000_000_000, 1)} MM"
    if abs(amount) >= 1_000_000:
        return f"{_num(amount / 1_000_000, 1)} M"
    if abs(amount) >= 1_000:
        return f"{_num(amount / 1_000, 0)} mil"
    return _num(amount, 0)


def _table(headers: Sequence[str], rows: Iterable[Sequence], *, css="") -> str:
    head = "".join(f"<th>{_esc(item)}</th>" for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f'<table class="{css}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def export_budget_usd_comparison_html(
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
    generated = generated_at or datetime.now().astimezone()
    first = items[0]
    blue = next((item for item in items if item.rate_type == "blue"), first)
    months = monthly_evolution(blue.rows)
    comparisons = type_comparison(items, base_type="blue")

    month_labels = [item.label for item in months]
    ars_values = [float(item.total_ars) for item in months]
    usd_values = [float(item.total_usd) for item in months]

    summary_rows = [
        (
            _esc(TYPE_LABELS.get(item.rate_type, item.rate_type)),
            _esc(SOURCE_LABELS.get(item.source or "any", item.source or "Cualquiera")),
            _esc(SIDE_LABELS.get(item.filters.side, item.filters.side)),
            str(item.summary.total_budgets),
            f"{_num(item.summary.coverage_percent, 1)}%",
            _money(item.summary.total_ars),
            _usd(item.summary.total_usd),
            _num(item.summary.weighted_rate, 6),
        )
        for item in items
    ]
    month_rows = [
        (
            _esc(item.label),
            str(item.budgets),
            _money(item.total_ars),
            _usd(item.total_usd),
            _pct(item.variation_ars),
            _pct(item.variation_usd),
            f"{_num(item.coverage_percent, 1)}%",
        )
        for item in months
    ]
    comparison_rows = [
        (
            _esc(TYPE_LABELS.get(item.rate_type, item.rate_type)),
            str(item.budgets),
            _usd(item.total_usd) if item.covered_budgets else "-",
            _pct(item.weighted_rate),
            f"{_num(item.coverage_percent, 1)}%",
            _usd(item.difference_usd) if item.difference_usd is not None else "-",
            _pct(item.difference_percent),
        )
        for item in comparisons
    ]
    missing_rows = [
        (
            _esc(TYPE_LABELS.get(item.rate_type, item.rate_type)),
            row.issue_date.strftime("%d/%m/%Y"),
            f"PRES-{row.budget_number:06d}",
            _esc(row.client_name),
            _money(row.total_ars),
        )
        for item in items
        for row in item.rows
        if row.coverage == COVERAGE_MISSING
    ]

    detail_parts = []
    for index, item in enumerate(items):
        rows = [
            (
                row.issue_date.strftime("%d/%m/%Y"),
                f"PRES-{row.budget_number:06d}",
                _esc(row.client_name),
                _esc(row.status),
                _money(row.total_ars),
                _num(row.rate, 6),
                row.rate_effective_date.strftime("%d/%m/%Y")
                if row.rate_effective_date
                else "-",
                _esc(row.rate_source or "-"),
                "Si" if row.used_fallback else "No",
                _esc(
                    {
                        "exact": "Exacta",
                        "prior": "Anterior",
                        "missing": "Sin cotizacion",
                    }.get(row.coverage, row.coverage)
                ),
                _usd(row.total_usd),
            )
            for row in item.rows
        ]
        detail_parts.append(
            f'<details {"open" if index == 0 else ""}>'
            f"<summary>{_esc(TYPE_LABELS.get(item.rate_type, item.rate_type))}"
            f" ({len(item.rows)})</summary>"
            + _table(
                (
                    "Fecha",
                    "Presupuesto",
                    "Cliente",
                    "Estado",
                    "ARS",
                    "Cotizacion",
                    "Fecha efectiva",
                    "Fuente",
                    "Fallback",
                    "Cobertura",
                    "USD",
                ),
                rows,
            )
            + "</details>"
        )

    subtitle = (
        f"{first.filters.start_date:%d/%m/%Y} a {first.filters.end_date:%d/%m/%Y} · "
        f"{SOURCE_LABELS.get(first.source or 'any', first.source or 'Cualquiera')} · "
        f"{SIDE_LABELS.get(first.filters.side, first.filters.side)}"
    )
    document = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Comparacion de presupuestos ARS/USD</title>
<style>
:root {{ color-scheme: light; --ink:#17324d; --muted:#5b6b7c; --line:#dbe3ec; --bg:#f4f7fb; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }}
main {{ max-width:1200px; margin:0 auto; padding:28px 20px 48px; }}
h1 {{ margin:0 0 4px; font-size:26px; }}
h2 {{ margin:28px 0 10px; font-size:18px; }}
.sub {{ color:var(--muted); margin-bottom:18px; }}
.cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:16px 0 22px; }}
.card {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
.card span {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
.card strong {{ display:block; margin-top:6px; font-size:20px; }}
.chart {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:10px; margin:12px 0; overflow:auto; }}
table {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line); border-radius:12px; overflow:hidden; }}
th,td {{ padding:8px 10px; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap; }}
th {{ background:#eaf0f7; font-size:12px; text-transform:uppercase; letter-spacing:.03em; }}
td:nth-child(n+4) {{ text-align:right; }}
details {{ margin:10px 0; background:#fff; border:1px solid var(--line); border-radius:12px; padding:10px 12px; }}
summary {{ cursor:pointer; font-weight:650; }}
.note {{ color:var(--muted); font-size:12px; margin-top:6px; }}
@media (max-width:800px) {{ .cards {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} main {{ padding:18px 10px; }} }}
@media print {{ body {{ background:#fff; }} .chart, table, .card, details {{ break-inside:avoid; }} }}
</style>
</head>
<body><main>
<h1>Comparacion de presupuestos ARS/USD</h1>
<div class="sub">{_esc(subtitle)} · generado {_esc(generated.strftime('%d/%m/%Y %H:%M'))}</div>

<div class="cards">
<div class="card"><span>Total presupuestos</span><strong>{blue.summary.total_budgets}</strong></div>
<div class="card"><span>Total ARS</span><strong>{_money(blue.summary.total_ars)}</strong></div>
<div class="card"><span>Total USD (blue)</span><strong>{_usd(blue.summary.total_usd)}</strong></div>
<div class="card"><span>Cobertura</span><strong>{_num(blue.summary.coverage_percent, 1)}%</strong></div>
</div>

<h2>Evolucion mensual</h2>
<div class="chart">{_bar_chart(month_labels, ars_values, title="Presupuestos en ARS por mes", color="#17324d", formatter=_money)}</div>
<div class="chart">{_bar_chart(month_labels, usd_values, title="Presupuestos en USD por mes", color="#2563eb", formatter=_usd)}</div>
{_table(("Mes", "Presupuestos", "Total ARS", "Total USD", "Var ARS", "Var USD", "Cobertura"), month_rows)}

<h2>Comparativo por tipo</h2>
<div class="chart">{_horizontal_bars([TYPE_LABELS.get(item.rate_type, item.rate_type) for item in comparisons], [float(item.total_usd) for item in comparisons], title="Total USD por tipo de cotizacion", formatter=_usd)}</div>
{_table(("Tipo", "Presupuestos", "Total USD", "Cotizacion ponderada", "Cobertura", "Dif. USD vs blue", "Dif. % vs blue"), comparison_rows)}

<h2>Resumen por tipo</h2>
{_table(("Tipo", "Fuente", "Punta", "Presupuestos", "Cobertura", "Total ARS", "Total USD", "Cotizacion ponderada"), summary_rows)}

<h2>Detalle por presupuesto</h2>
{''.join(detail_parts)}

<h2>Sin cotizacion</h2>
{_table(("Tipo", "Fecha", "Presupuesto", "Cliente", "Total ARS"), missing_rows) if missing_rows else '<p class="note">No hay presupuestos sin cotizacion.</p>'}

<p class="note">Regla: USD = ARS / cotizacion (ARS por 1 USD). La cotizacion anterior solo se usa si esta permitida y queda marcada. No se modifican presupuestos.</p>
</main></body></html>"""
    target.write_text(document, encoding="utf-8")
    return target
