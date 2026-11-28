"""Informe HTML autocontenido con graficos de la comparacion ARS/USD (#974)."""

from __future__ import annotations

import base64
import html
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Iterable, Sequence

from app.reports.budget_usd_comparison import (
    COVERAGE_MISSING,
    SOURCE_LABELS,
    SIDE_LABELS,
    TYPE_LABELS,
    BudgetUsdComparisonResult,
    monthly_evolution,
    type_comparison,
)

_COLORS = (
    "#293e86",
    "#3558a8",
    "#0f766e",
    "#b45309",
    "#7c3aed",
    "#be123c",
    "#64748b",
)

_LOGO_PATH = Path(__file__).resolve().parents[1] / "ui" / "assets" / "branding" / "femag-logo-ui.png"


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


def _compact(value: float) -> str:
    amount = float(value)
    if abs(amount) >= 1_000_000_000:
        return f"{_num(amount / 1_000_000_000, 1)} MM"
    if abs(amount) >= 1_000_000:
        return f"{_num(amount / 1_000_000, 1)} M"
    if abs(amount) >= 1_000:
        return f"{_num(amount / 1_000, 0)} mil"
    return _num(amount, 0)


def _esc(value) -> str:
    return html.escape(str(value or ""))


def _badge(text: str, kind: str = "neutral") -> str:
    return f'<span class="badge badge-{kind}">{_esc(text)}</span>'


def _coverage_badge(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    kind = "ok" if number >= 99.9 else "warn" if number >= 80 else "bad"
    return _badge(f"{_num(number, 1)}%", kind)


def _logo_data_uri() -> str:
    try:
        from PIL import Image

        with Image.open(_LOGO_PATH) as image:
            image.thumbnail((80, 80))
            buffer = BytesIO()
            image.save(buffer, format="PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        return ""


def _bar_chart(
    labels: Sequence[str],
    values: Sequence[float | None],
    *,
    title: str,
    subtitle: str,
    color: str,
    formatter,
    compact_formatter=_compact,
) -> str:
    width, height = 960, 330
    left, right, top, bottom = 86, 24, 44, 58
    plot_w = width - left - right
    plot_h = height - top - bottom
    maximum = max((abs(float(v)) for v in values if v is not None), default=0.0) or 1.0
    step = plot_w / max(1, len(values))
    bar_w = max(5.0, min(54.0, step * 0.58))
    grid = []
    for index in range(5):
        value = maximum * index / 4
        y = top + plot_h - (value / maximum) * plot_h
        grid.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" '
            'stroke="#e2e8f0" stroke-width="1" stroke-dasharray="3 4"/>'
        )
        grid.append(
            f'<text x="{left-12}" y="{y+4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#64748b">{_esc(compact_formatter(value))}</text>'
        )
    bars = []
    gradient_id = f"barGradient{color.replace('#', '')}"
    for index, (label, value) in enumerate(zip(labels, values)):
        if value is None:
            continue
        bar_h = max(0.0, (float(value) / maximum) * plot_h)
        x = left + index * step + (step - bar_w) / 2
        y = top + plot_h - bar_h
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
            f'rx="5" fill="url(#{gradient_id})" opacity=".94">'
            f"<title>{_esc(label)}: {_esc(formatter(value))}</title></rect>"
        )
        bars.append(
            f'<text x="{x + bar_w/2:.1f}" y="{max(top+10, y-7):.1f}" '
            f'text-anchor="middle" font-size="10.5" font-weight="700" '
            f'fill="#334155">{_esc(compact_formatter(value))}</text>'
        )
        if len(labels) <= 16 or index % 2 == 0:
            bars.append(
                f'<text x="{x + bar_w/2:.1f}" y="{height-22}" text-anchor="middle" '
                f'font-size="11" fill="#64748b">{_esc(label)}</text>'
            )
    return f"""
    <div class="chart-card">
      <div class="chart-head"><div><h3>{_esc(title)}</h3><p>{_esc(subtitle)}</p></div>
        <span class="chart-legend" style="--legend:{color}">{_esc(title.split(' por ')[0])}</span></div>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(title)}">
        <defs><linearGradient id="{gradient_id}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="{color}" stop-opacity=".95"/>
          <stop offset="1" stop-color="{color}" stop-opacity=".55"/>
        </linearGradient></defs>
        {''.join(grid)}
        {''.join(bars)}
      </svg>
    </div>"""


def _hline_chart(
    labels: Sequence[str],
    values: Sequence[float | None],
    coverages: Sequence[float],
    *,
    title: str,
    formatter,
) -> str:
    width, height = 960, 28 + max(1, len(values)) * 44
    left, right, top = 168, 116, 24
    plot_w = width - left - right
    maximum = max((abs(float(v)) for v in values if v is not None), default=0.0) or 1.0
    parts = []
    for index, (label, value, coverage) in enumerate(zip(labels, values, coverages)):
        y = top + index * 44
        no_data = not coverage
        parts.append(
            f'<text x="{left-12}" y="{y+16}" text-anchor="end" font-size="12" '
            f'font-weight="650" fill="#334155">{_esc(label)}</text>'
        )
        parts.append(
            f'<rect x="{left}" y="{y}" width="{plot_w}" height="22" rx="6" fill="#eef2f7"/>'
        )
        if value is not None and float(value) > 0:
            bar_w = max(2.0, (float(value) / maximum) * plot_w)
            color = _COLORS[index % len(_COLORS)]
            parts.append(
                f'<rect x="{left}" y="{y}" width="{bar_w:.1f}" height="22" rx="6" '
                f'fill="{color}" opacity=".9"><title>{_esc(label)}: {_esc(formatter(value))}'
                f" · cobertura {_num(coverage, 1)}%</title></rect>"
            )
        else:
            parts.append(
                f'<text x="{left+12}" y="{y+15}" font-size="11" fill="#94a3b8">'
                "Sin cotizacion</text>"
            )
        parts.append(
            f'<text x="{width-right+8}" y="{y+15}" font-size="12" font-weight="700" '
            f'fill="#17324d">{_esc(formatter(value) if not no_data else "-")}</text>'
        )
        parts.append(
            f'<text x="{width-right+8}" y="{y+30}" font-size="10" fill="#64748b">'
            f"cobertura {_num(coverage, 1)}%</text>"
        )
    return f"""
    <div class="chart-card">
      <div class="chart-head"><div><h3>{_esc(title)}</h3>
        <p>Total convertido en el rango, por criterio de cotizacion.</p></div></div>
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(title)}">
        {''.join(parts)}
      </svg>
    </div>"""


def _table(headers: Sequence[str], rows: Iterable[Sequence], *, css="") -> str:
    head = "".join(f"<th>{_esc(item)}</th>" for item in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f'<div class="table-wrap"><table class="{css}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _month_rows(months) -> list[tuple]:
    return [
        (
            _esc(item.label),
            str(item.budgets),
            _money(item.total_ars),
            _usd(item.total_usd),
            _pct(item.variation_ars),
            _pct(item.variation_usd),
            _coverage_badge(item.coverage_percent),
        )
        for item in months
    ]


def _comparison_rows(comparisons) -> list[tuple]:
    return [
        (
            _esc(TYPE_LABELS.get(item.rate_type, item.rate_type)),
            str(item.budgets),
            _usd(item.total_usd) if item.covered_budgets else "-",
            _num(item.weighted_rate, 6) if item.covered_budgets else "-",
            _coverage_badge(item.coverage_percent),
            _usd(item.difference_usd) if item.difference_usd is not None else "-",
            _pct(item.difference_percent) if item.difference_percent is not None else "-",
        )
        for item in comparisons
    ]


def _summary_rows(results) -> list[tuple]:
    return [
        (
            _esc(TYPE_LABELS.get(item.rate_type, item.rate_type)),
            _esc(SOURCE_LABELS.get(item.source or "any", item.source or "Cualquiera")),
            _esc(SIDE_LABELS.get(item.filters.side, item.filters.side)),
            str(item.summary.total_budgets),
            _money(item.summary.total_ars),
            _usd(item.summary.total_usd),
            _num(item.summary.weighted_rate, 6),
            _coverage_badge(item.summary.coverage_percent),
        )
        for item in results
    ]


def _detail_parts(results) -> str:
    parts = []
    for index, item in enumerate(results):
        rows = [
            (
                row.issue_date.strftime("%d/%m/%Y"),
                f"PRES-{row.budget_number:06d}",
                _esc(row.client_name),
                _badge("Anulado" if row.status == "annulled" else "Activo", "muted" if row.status == "annulled" else "neutral"),
                _money(row.total_ars),
                _num(row.rate, 6),
                row.rate_effective_date.strftime("%d/%m/%Y")
                if row.rate_effective_date
                else "-",
                _esc(row.rate_source or "-"),
                _badge("Fallback", "warn") if row.used_fallback else "-",
                _badge("Exacta", "ok") if row.coverage == "exact" else _badge("Anterior", "warn") if row.coverage == "prior" else _badge("Sin cotizacion", "bad"),
                _usd(row.total_usd),
            )
            for row in item.rows
        ]
        parts.append(
            f'<details {"open" if index == 0 else ""}>'
            f'<summary><span>{_esc(TYPE_LABELS.get(item.rate_type, item.rate_type))}</span>'
            f'<span class="details-meta">{len(item.rows)} presupuestos</span></summary>'
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
                css="detail-table",
            )
            + "</details>"
        )
    return "".join(parts)


def _missing_rows(results) -> list[tuple]:
    return [
        (
            _esc(TYPE_LABELS.get(item.rate_type, item.rate_type)),
            row.issue_date.strftime("%d/%m/%Y"),
            f"PRES-{row.budget_number:06d}",
            _esc(row.client_name),
            _money(row.total_ars),
        )
        for item in results
        for row in item.rows
        if row.coverage == COVERAGE_MISSING
    ]


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
    comparison_labels = [TYPE_LABELS.get(item.rate_type, item.rate_type) for item in comparisons]
    comparison_values = [float(item.total_usd) for item in comparisons]
    comparison_coverages = [float(item.coverage_percent) for item in comparisons]
    missing = _missing_rows(items)
    logo = _logo_data_uri()

    subtitle = (
        f"{first.filters.start_date:%d/%m/%Y} — {first.filters.end_date:%d/%m/%Y} · "
        f"{SOURCE_LABELS.get(first.source or 'any', first.source or 'Cualquiera')} · "
        f"{SIDE_LABELS.get(first.filters.side, first.filters.side)}"
    )
    executive = (
        f"Se analizaron <strong>{blue.summary.total_budgets}</strong> presupuestos por "
        f"<strong>{_money(blue.summary.total_ars)}</strong>, equivalentes a "
        f"<strong>{_usd(blue.summary.total_usd)}</strong> con el criterio "
        f"<strong>{_esc(TYPE_LABELS.get(blue.rate_type, blue.rate_type))} / "
        f"{_esc(SIDE_LABELS.get(blue.filters.side, blue.filters.side))}</strong>. "
        f"La cobertura de cotizacion es <strong>{_num(blue.summary.coverage_percent, 1)}%</strong>."
    )
    document = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FEMAG · Presupuestos ARS/USD</title>
<style>
:root {{
  --navy-950:#0f1433; --navy-900:#171b49; --navy-800:#20265f; --navy-700:#293e86;
  --blue-600:#3558a8; --blue-500:#4165ad; --blue-100:#e8eff8;
  --red-600:#dc2626; --red-100:#fee2e2; --red-050:#fef2f2;
  --emerald-600:#059669; --emerald-100:#d1fae5; --emerald-050:#ecfdf5;
  --amber-600:#b45309; --amber-100:#fef3c7;
  --slate-950:#090d16; --slate-900:#0f172a; --slate-800:#1e293b; --slate-700:#334155;
  --slate-600:#475569; --slate-500:#64748b; --slate-400:#94a3b8;
  --slate-300:#cbd5e1; --slate-200:#e2e8f0; --slate-100:#f1f5f9; --slate-050:#f8fafc;
  --white:#fff; --radius:12px; --shadow:0 1px 2px rgba(15,23,42,.04),0 8px 24px rgba(15,23,42,.05);
  --font:"Figtree","Segoe UI",system-ui,-apple-system,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace;
}}
* {{ box-sizing:border-box; }}
html {{ scroll-behavior:smooth; }}
body {{ margin:0; background:var(--slate-100); color:var(--slate-900); font:13.5px/1.5 var(--font); font-variant-numeric:tabular-nums; -webkit-font-smoothing:antialiased; }}
a {{ color:inherit; }}
.brandbar {{ background:var(--navy-950); color:#fff; border-bottom:3px solid var(--red-600); }}
.brandbar-inner {{ max-width:1240px; margin:0 auto; padding:12px 22px; display:flex; align-items:center; justify-content:space-between; gap:16px; }}
.brand {{ display:flex; align-items:center; gap:12px; }}
.brand img {{ width:40px; height:40px; object-fit:contain; border-radius:9px; background:rgba(255,255,255,.06); }}
.brand strong {{ display:block; font-size:14px; letter-spacing:.06em; }}
.brand span {{ display:block; color:var(--slate-400); font-size:10.5px; letter-spacing:.05em; text-transform:uppercase; }}
.brandbar .conf {{ font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.09em; color:#cbd5e1; }}
nav.toc {{ position:sticky; top:0; z-index:5; background:rgba(255,255,255,.92); backdrop-filter:blur(10px); border-bottom:1px solid var(--slate-200); }}
.toc-inner {{ max-width:1240px; margin:0 auto; padding:8px 22px; display:flex; align-items:center; gap:18px; overflow-x:auto; }}
.toc a {{ font-size:11.5px; font-weight:750; color:var(--slate-600); text-decoration:none; white-space:nowrap; }}
.toc a:hover {{ color:var(--navy-800); }}
.toc .print {{ margin-left:auto; border:1px solid var(--slate-300); background:#fff; border-radius:6px; padding:6px 10px; font:700 11px var(--font); color:var(--navy-800); cursor:pointer; }}
main {{ max-width:1240px; margin:0 auto; padding:26px 22px 52px; }}
.hero {{ background:linear-gradient(135deg,var(--navy-950),var(--navy-800)); color:#fff; border-radius:16px; padding:28px 30px; box-shadow:var(--shadow); position:relative; overflow:hidden; }}
.hero:after {{ content:""; position:absolute; width:380px; height:380px; right:-120px; top:-180px; border-radius:50%; background:radial-gradient(circle,rgba(255,255,255,.13),transparent 65%); }}
.hero .eyebrow {{ font-size:10px; font-weight:800; letter-spacing:.14em; text-transform:uppercase; color:#93c5fd; }}
.hero h1 {{ margin:8px 0 6px; font-size:32px; line-height:1.1; letter-spacing:-.03em; }}
.hero .period {{ color:#cbd5e1; font-size:13px; }}
.hero .exec {{ position:relative; z-index:1; max-width:820px; margin:16px 0 0; color:#e2e8f0; font-size:13.5px; }}
.hero .exec strong {{ color:#fff; }}
.hero-stats {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:18px; position:relative; z-index:1; }}
.hero-stat {{ background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.12); border-radius:10px; padding:10px 14px; min-width:150px; }}
.hero-stat span {{ display:block; color:#93c5fd; font-size:9.5px; font-weight:800; text-transform:uppercase; letter-spacing:.08em; }}
.hero-stat strong {{ display:block; margin-top:4px; font-size:18px; color:#fff; }}
.cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:18px 0 26px; }}
.card {{ background:#fff; border:1px solid var(--slate-200); border-radius:var(--radius); padding:15px 17px; box-shadow:var(--shadow); }}
.card .label {{ color:var(--slate-500); font-size:9.5px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }}
.card .value {{ margin-top:6px; font-size:21px; font-weight:800; letter-spacing:-.02em; color:var(--navy-900); }}
.card .sub {{ margin-top:4px; color:var(--slate-500); font-size:11.5px; }}
.card.accent {{ border-top:3px solid var(--blue-600); }}
.card.good {{ border-top:3px solid var(--emerald-600); }}
.card.warn {{ border-top:3px solid var(--amber-600); }}
section {{ margin:34px 0 0; scroll-margin-top:58px; }}
.section-head {{ display:flex; align-items:end; justify-content:space-between; gap:16px; margin-bottom:12px; }}
.section-head h2 {{ margin:0; font-size:21px; letter-spacing:-.02em; color:var(--slate-950); }}
.section-head p {{ margin:3px 0 0; color:var(--slate-500); font-size:12px; }}
.chart-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
.chart-card {{ background:#fff; border:1px solid var(--slate-200); border-radius:var(--radius); padding:14px 14px 8px; box-shadow:var(--shadow); overflow:auto; }}
.chart-head {{ display:flex; justify-content:space-between; gap:10px; align-items:start; margin-bottom:4px; }}
.chart-head h3 {{ margin:0; font-size:14px; color:var(--slate-900); }}
.chart-head p {{ margin:2px 0 0; font-size:11px; color:var(--slate-500); }}
.chart-legend {{ font-size:9.5px; font-weight:800; color:var(--slate-600); text-transform:uppercase; letter-spacing:.06em; white-space:nowrap; }}
.chart-legend:before {{ content:""; display:inline-block; width:8px; height:8px; border-radius:2px; background:var(--legend); margin-right:5px; }}
.chart-card svg {{ width:100%; height:auto; min-width:620px; display:block; }}
.table-wrap {{ background:#fff; border:1px solid var(--slate-200); border-radius:var(--radius); box-shadow:var(--shadow); overflow:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th,td {{ padding:9px 11px; border-bottom:1px solid var(--slate-100); text-align:left; white-space:nowrap; }}
th {{ background:var(--slate-050); color:var(--slate-500); font-size:9.5px; font-weight:800; letter-spacing:.06em; text-transform:uppercase; position:sticky; top:0; }}
tbody tr:nth-child(even) {{ background:#fbfcfe; }}
tbody tr:hover {{ background:var(--blue-100); }}
td:nth-child(n+4) {{ text-align:right; }}
td:last-child {{ text-align:right; }}
.badge {{ display:inline-flex; align-items:center; justify-content:center; border-radius:999px; padding:2px 8px; font-size:9.5px; font-weight:800; letter-spacing:.03em; white-space:nowrap; }}
.badge-ok {{ background:var(--emerald-050); color:var(--emerald-600); border:1px solid #a7f3d0; }}
.badge-warn {{ background:var(--amber-100); color:var(--amber-600); border:1px solid #fde68a; }}
.badge-bad {{ background:var(--red-050); color:var(--red-600); border:1px solid #fecaca; }}
.badge-neutral {{ background:var(--slate-100); color:var(--slate-600); border:1px solid var(--slate-200); }}
.badge-muted {{ background:var(--slate-050); color:var(--slate-400); border:1px solid var(--slate-200); }}
details {{ background:#fff; border:1px solid var(--slate-200); border-radius:var(--radius); box-shadow:var(--shadow); margin:10px 0; overflow:hidden; }}
details summary {{ cursor:pointer; padding:13px 16px; font-weight:750; display:flex; align-items:center; justify-content:space-between; gap:12px; list-style:none; }}
details summary::-webkit-details-marker {{ display:none; }}
details summary:after {{ content:"+"; color:var(--blue-600); font-weight:800; font-size:16px; }}
details[open] summary:after {{ content:"−"; }}
.details-meta {{ margin-left:auto; color:var(--slate-500); font-size:11px; font-weight:500; }}
details .table-wrap {{ border:0; border-top:1px solid var(--slate-100); border-radius:0; box-shadow:none; }}
.note {{ color:var(--slate-500); font-size:11.5px; line-height:1.6; margin:10px 0 0; }}
.method {{ background:#fff; border:1px solid var(--slate-200); border-left:4px solid var(--navy-700); border-radius:var(--radius); padding:16px 18px; box-shadow:var(--shadow); }}
.method h3 {{ margin:0 0 6px; font-size:14px; }}
.method p {{ margin:4px 0; color:var(--slate-600); font-size:12px; }}
.footer {{ margin-top:36px; padding-top:16px; border-top:1px solid var(--slate-200); color:var(--slate-400); font-size:10.5px; display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
.empty {{ background:#fff; border:1px dashed var(--slate-300); color:var(--slate-500); border-radius:var(--radius); padding:18px; text-align:center; }}
@media (max-width:980px) {{ .chart-grid {{ grid-template-columns:1fr; }} .cards {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
@media (max-width:620px) {{ main {{ padding:16px 12px 32px; }} .brandbar-inner {{ padding:10px 14px; }} .hero {{ padding:20px; }} .hero h1 {{ font-size:25px; }} .cards {{ grid-template-columns:1fr; }} .toc-inner {{ padding:7px 14px; }} .chart-card svg {{ min-width:560px; }} }}
@media print {{
  body {{ background:#fff; }}
  nav.toc {{ display:none; }}
  main {{ max-width:none; padding:0; }}
  .brandbar {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  .hero, .card, .chart-card, .table-wrap, details, .method {{ box-shadow:none; break-inside:avoid; }}
  section {{ break-inside:avoid; }}
  details {{ break-inside:avoid; }}
  details:not([open]) {{ display:none; }}
}}
</style>
</head>
<body>
<header class="brandbar"><div class="brandbar-inner">
  <div class="brand">{f'<img src="{logo}" alt="FEMAG">' if logo else ''}
    <div><strong>FEMAG</strong><span>Inteligencia comercial</span></div>
  </div>
  <div class="conf">Informe confidencial · uso interno</div>
</div></header>
<nav class="toc"><div class="toc-inner">
  <a href="#resumen">Resumen</a><a href="#evolucion">Evolucion</a><a href="#tipos">Tipos</a><a href="#detalle">Detalle</a><a href="#metodologia">Metodologia</a>
  <button class="print" onclick="window.print()">Imprimir / PDF</button>
</div></nav>
<main>
  <div class="hero" id="resumen">
    <div class="eyebrow">Analisis de presupuestos · ARS / USD</div>
    <h1>Presupuestos en dolares</h1>
    <div class="period">{_esc(subtitle)} · Generado {_esc(generated.strftime('%d/%m/%Y %H:%M'))}</div>
    <p class="exec">{executive}</p>
    <div class="hero-stats">
      <div class="hero-stat"><span>Presupuestos</span><strong>{blue.summary.total_budgets}</strong></div>
      <div class="hero-stat"><span>Total ARS</span><strong>{_money(blue.summary.total_ars)}</strong></div>
      <div class="hero-stat"><span>Total USD</span><strong>{_usd(blue.summary.total_usd)}</strong></div>
      <div class="hero-stat"><span>Cobertura</span><strong>{_num(blue.summary.coverage_percent, 1)}%</strong></div>
    </div>
  </div>

  <div class="cards">
    <div class="card accent"><div class="label">Presupuestos analizados</div><div class="value">{blue.summary.total_budgets}</div><div class="sub">del {first.filters.start_date:%d/%m/%Y} al {first.filters.end_date:%d/%m/%Y}</div></div>
    <div class="card"><div class="label">Total en pesos</div><div class="value">{_money(blue.summary.total_ars)}</div><div class="sub">importe original de los presupuestos</div></div>
    <div class="card"><div class="label">Total en dolares</div><div class="value">{_usd(blue.summary.total_usd)}</div><div class="sub">{_esc(TYPE_LABELS.get(blue.rate_type, blue.rate_type))} · {_esc(SIDE_LABELS.get(blue.filters.side, blue.filters.side))}</div></div>
    <div class="card good"><div class="label">Cobertura de cotizacion</div><div class="value">{_num(blue.summary.coverage_percent, 1)}%</div><div class="sub">{blue.summary.exact_budgets} exactas · {blue.summary.prior_budgets} anteriores · {blue.summary.missing_budgets} faltantes</div></div>
  </div>

  <section id="evolucion">
    <div class="section-head"><div><h2>Evolucion mensual</h2><p>Presupuestos convertidos a su fecha, con variacion contra el mes anterior.</p></div></div>
    <div class="chart-grid">
      {_bar_chart(month_labels, ars_values, title="Presupuestos en ARS por mes", subtitle="Importe original, sin conversion.", color="#293e86", formatter=_money)}
      {_bar_chart(month_labels, usd_values, title="Presupuestos en USD por mes", subtitle="Conversion con la cotizacion de cada presupuesto.", color="#3558a8", formatter=_usd)}
    </div>
    {_table(("Mes", "Presupuestos", "Total ARS", "Total USD", "Var ARS", "Var USD", "Cobertura"), _month_rows(months))}
  </section>

  <section id="tipos">
    <div class="section-head"><div><h2>Comparativo por tipo</h2><p>Mismo universo de presupuestos, distinto criterio de cotizacion.</p></div></div>
    {_hline_chart(comparison_labels, comparison_values, comparison_coverages, title="Total USD por tipo de cotizacion", formatter=_usd)}
    {_table(("Tipo", "Presupuestos", "Total USD", "Cotizacion ponderada", "Cobertura", "Dif. USD vs blue", "Dif. % vs blue"), _comparison_rows(comparisons))}
  </section>

  <section id="detalle">
    <div class="section-head"><div><h2>Detalle por presupuesto</h2><p>Cada fila conserva tipo, fuente, fecha efectiva y version de la cotizacion.</p></div></div>
    {_detail_parts(items)}
    <div class="table-wrap" style="margin-top:14px">
      <table><thead><tr><th>Tipo</th><th>Fecha</th><th>Presupuesto</th><th>Cliente</th><th>Total ARS</th></tr></thead>
      <tbody>{''.join(f'<tr><td>{row[0]}</td><td>{row[1]}</td><td>{row[2]}</td><td>{row[3]}</td><td style="text-align:right">{row[4]}</td></tr>' for row in missing) or '<tr><td colspan="5">No hay presupuestos sin cotizacion.</td></tr>'}</tbody></table>
    </div>
    <p class="note">Los faltantes no se convierten a cero. Se informan para que Gerencia decida si completa la cotizacion o acepta el fallback.</p>
  </section>

  <section id="metodologia" class="method">
    <h3>Metodologia y criterio</h3>
    <p><strong>Formula:</strong> USD = ARS / cotizacion (ARS por 1 USD).</p>
    <p><strong>Criterio:</strong> cada hoja y cada columna usan un solo tipo de cotizacion y una sola fuente. La punta seleccionada es {_esc(SIDE_LABELS.get(first.filters.side, first.filters.side))}.</p>
    <p><strong>Cobertura:</strong> exacta si existe cotizacion en la fecha; anterior si se permite y se usa la inmediata previa; faltante si no hay ninguna. La fecha efectiva, fuente y version quedan en el detalle.</p>
    <p><strong>Alcance:</strong> solo lectura. No se modifican presupuestos, importes, remitos, F150 ni ordenes de carga.</p>
    <div class="footer"><span>FEMAG · Informe generado desde el Dashboard gerencial</span><span>{_esc(generated.strftime('%Y-%m-%d %H:%M:%S %Z'))}</span></div>
  </section>
</main>
</body></html>"""
    target.write_text(document, encoding="utf-8")
    return target
