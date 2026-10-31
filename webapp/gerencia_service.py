"""Vista BI ejecutiva para /gerencia (#837)."""

from __future__ import annotations

from datetime import date
from html import escape

from app.config.database import database_proxy
from app.models.sync import SyncProjection
from app.utils.datetime_utils import as_datetime
from webapp.managerial_dashboard_service import (
    ManagerialDashboardService,
    _money_compact,
    _money_full,
    _month_name,
    _number,
    _time_label,
    _variation,
)
from webapp.managerial_repurchase_service import ManagerialRepurchaseService


def _signed(value: float, formatter) -> str:
    amount = float(value or 0)
    if amount > 0:
        return f"+{formatter(amount)}"
    if amount < 0:
        return f"−{formatter(abs(amount))}"
    return formatter(0)


def _date(value) -> str:
    parsed = as_datetime(value)
    return parsed.strftime("%d/%m/%Y") if parsed else "—"


def _range_label(period: dict) -> str:
    start = date.fromisoformat(period["start"])
    end = date.fromisoformat(period["end"])
    return f"{start:%d/%m/%Y} – {end:%d/%m/%Y}"


def _month_label(period: dict) -> str:
    end = date.fromisoformat(period["end"])
    return f"{_month_name(end.isoformat()).capitalize()} {end.year}"


def _price_tn(value: float) -> str:
    return f"$ {_number(float(value or 0) / 1_000_000, 3)} M"


def _waterfall_svg(items: list[dict]) -> str:
    max_value = max(
        [abs(float(item["value"])) for item in items[:1] + items[-1:]] or [0]
    )
    cumulative = 0.0
    cumulative_values = []
    for item in items:
        value = float(item["value"])
        if item["kind"] in {"base", "end"}:
            cumulative = value
        else:
            cumulative += value
        cumulative_values.append(max(cumulative, 0.0))
    max_value = max(max_value, max(cumulative_values, default=0.0))
    max_value = max(100, int((max_value * 1.12 + 99) // 100 * 100))
    top, bottom, height = 20, 195, 175
    width = 680
    bar_width = 64
    step = 94
    start_x = 68
    colors = {
        "base": "#20265f",
        "end": "#293e86",
        "neg": "#dc2626",
        "pos": "#059669",
    }
    parts = [
        f'<svg viewBox="0 0 {width} 235" role="img" aria-label="Puente de variación de volumen">'
    ]
    for index in range(4):
        value = max_value * index / 3
        y = bottom - (value / max_value) * height
        parts.append(
            f'<line x1="48" y1="{y:.1f}" x2="660" y2="{y:.1f}" '
            f'stroke="{"#cbd5e1" if index == 0 else "#f1f5f9"}" stroke-width="{1.2 if index == 0 else 1}"/>'
        )
        parts.append(
            f'<text x="42" y="{y + 4:.1f}" text-anchor="end" fill="#64748b" '
            f'font-size="10" font-weight="600">{_number(value, 0)}</text>'
        )
    parts.append(
        f'<text x="42" y="{bottom + 4}" text-anchor="end" fill="#64748b" '
        f'font-size="9" font-weight="700">0 TN</text>'
    )
    cumulative = 0.0
    previous_end = None
    for index, item in enumerate(items):
        value = float(item["value"])
        kind = item["kind"]
        if kind in {"base", "end"}:
            start, end = 0.0, value
            cumulative = value
        elif value >= 0:
            start, end = cumulative, cumulative + value
            cumulative = end
        else:
            start, end = cumulative + value, cumulative
            cumulative = end
        x = start_x + index * step
        y = bottom - (max(start, end) / max_value) * height
        bar_height = max(2.0, abs(end - start) / max_value * height)
        if previous_end is not None:
            parts.append(
                f'<line x1="{x - 30}" y1="{previous_end:.1f}" x2="{x}" '
                f'y2="{previous_end:.1f}" stroke="#94a3b8" stroke-dasharray="3 2"/>'
            )
        parts.append(
            f'<rect x="{x}" y="{y:.1f}" width="{bar_width}" height="{bar_height:.1f}" '
            f'rx="3" fill="{colors[kind]}"/>'
        )
        label = item["label"]
        parts.append(
            f'<text x="{x + bar_width / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
            f'fill="#0f172a" font-size="11" font-weight="800">'
            f'{_signed(value, lambda number: _number(number, 1)) if kind not in {"base", "end"} else _number(value, 1)}</text>'
        )
        parts.append(
            f'<text x="{x + bar_width / 2:.1f}" y="{bottom + 17}" text-anchor="middle" '
            f'fill="#334155" font-size="10" font-weight="700">{escape(label)}</text>'
        )
        parts.append(
            f'<text x="{x + bar_width / 2:.1f}" y="{bottom + 29}" text-anchor="middle" '
            f'fill="#64748b" font-size="9">{escape(item.get("sub", ""))}</text>'
        )
        previous_end = bottom - (end / max_value) * height
    parts.append("</svg>")
    return "".join(parts)


class GerenciaService:
    @staticmethod
    def _projections():
        manager = ManagerialDashboardService.get_latest()
        repurchase = ManagerialRepurchaseService.get_latest()
        return manager, repurchase

    @classmethod
    def shell_context(cls, active: str) -> dict:
        manager, repurchase = cls._projections()
        manager_payload = manager.payload if manager else {}
        repurchase_payload = repurchase.payload if repurchase else {}
        summary = repurchase_payload.get("summary") or {}
        period = manager_payload.get("period") or {}
        previous = manager_payload.get("previous_period") or {}
        synced_orders = 0
        if database_proxy.obj is not None:
            synced_orders = (
                SyncProjection.select()
                .where(
                    SyncProjection.resource_type
                    == SyncProjection.RESOURCE_ORDER
                )
                .count()
            )
        return {
            "active": active,
            "snapshot_time": _time_label(manager_payload.get("generated_at"))
            if manager_payload
            else "",
            "period_label": _month_label(period) if period else "Sin datos",
            "period_range": _range_label(period) if period else "",
            "comparison_range": _range_label(previous) if previous else "",
            "synced_orders": synced_orders,
            "recompra_count": int(summary.get("count_sin_recompra") or 0),
        }

    @classmethod
    def dashboard_view(cls) -> dict:
        manager, repurchase = cls._projections()
        if manager is None:
            return {"empty": True}
        payload = manager.payload
        summary = (repurchase.payload.get("summary") if repurchase else {}) or {}
        rows = (repurchase.payload.get("rows") if repurchase else []) or []
        sales = float(payload["kpis"]["valued_dispatches"].get("current") or 0)
        previous_sales = float(
            payload["kpis"]["valued_dispatches"].get("previous") or 0
        )
        tonnes = float(payload["kpis"]["tonnes"].get("current") or 0)
        previous_tonnes = float(
            payload["kpis"]["tonnes"].get("previous") or 0
        )
        orders = float(payload["kpis"]["orders"].get("current") or 0)
        previous_orders = float(payload["kpis"]["orders"].get("previous") or 0)
        ticket = float(payload["kpis"]["average_ticket"].get("current") or 0)
        previous_ticket = float(
            payload["kpis"]["average_ticket"].get("previous") or 0
        )
        price = sales / tonnes if tonnes else 0
        previous_price = previous_sales / previous_tonnes if previous_tonnes else 0
        buyers = int(summary.get("buyers_current") or 0)
        previous_buyers = int(summary.get("buyers_previous") or 0)
        retained = max(previous_buyers - int(summary.get("count_sin_recompra") or 0), 0)
        retention = (retained / previous_buyers * 100) if previous_buyers else 0
        sales_delta, sales_direction = _variation(
            payload["kpis"]["valued_dispatches"].get("variation_percent")
        )
        tonnes_delta, tonnes_direction = _variation(
            payload["kpis"]["tonnes"].get("variation_percent")
        )
        orders_delta, orders_direction = _variation(
            payload["kpis"]["orders"].get("variation_percent")
        )
        price_delta, price_direction = _variation(
            round((price - previous_price) / previous_price * 100, 1)
            if previous_price
            else None
        )
        buyers_delta, buyers_direction = _variation(
            round((buyers - previous_buyers) / previous_buyers * 100, 1)
            if previous_buyers
            else None
        )
        lost = float(summary.get("lost_tonnes") or 0)
        less = float(summary.get("reduction_tonnes") or 0)
        more = float(summary.get("increase_tonnes") or 0)
        new = float(summary.get("new_tonnes") or 0)
        gross_loss = lost + abs(less)
        gross_gain = more + new
        recovery = (gross_gain / gross_loss * 100) if gross_loss else 0
        has_repurchase = bool(summary)

        products = []
        top_products = payload.get("top_products") or []
        max_product_tn = max(
            [float(row.get("tonnes") or 0) for row in top_products] or [0]
        )
        for row in top_products[:5]:
            current_tn = float(row.get("tonnes") or 0)
            previous_tn = float(row.get("previous_tonnes") or 0)
            current_total = float(row.get("total") or 0)
            variation = (
                round((current_tn - previous_tn) / previous_tn * 100, 1)
                if previous_tn
                else None
            )
            delta, direction = _variation(variation)
            products.append(
                {
                    "name": str(row.get("name") or ""),
                    "current_tn": _number(current_tn, 1),
                    "previous_tn": _number(previous_tn, 1),
                    "current_total": _money_compact(current_total),
                    "price_tn": _price_tn(current_total / current_tn)
                    if current_tn
                    else "—",
                    "delta": delta,
                    "direction": direction,
                    "variation_value": variation,
                    "share": round(current_tn / tonnes * 100, 1) if tonnes else 0,
                    "bar": round(current_tn / max_product_tn * 100, 1)
                    if max_product_tn
                    else 0,
                    "previous_bar": round(previous_tn / max_product_tn * 100, 1)
                    if max_product_tn
                    else 0,
                }
            )
        clients = []
        top_clients = payload.get("top_clients") or []
        max_client_total = max(
            [float(row.get("total") or 0) for row in top_clients] or [0]
        )
        for row in top_clients[:5]:
            current_total = float(row.get("total") or 0)
            previous_total = float(row.get("previous_total") or 0)
            delta, direction = _variation(row.get("variation_percent"))
            clients.append(
                {
                    "name": str(row.get("name") or ""),
                    "current_total": _money_compact(current_total),
                    "previous_total": _money_compact(previous_total),
                    "current_tn": _number(row.get("tonnes"), 1),
                    "delta": delta,
                    "direction": direction,
                    "share": round(current_total / sales * 100, 1) if sales else 0,
                    "bar": round(current_total / max_client_total * 100, 1)
                    if max_client_total
                    else 0,
                }
            )
        risk_rows = [
            row
            for row in rows
            if row.get("status") == "sin_recompra"
        ]
        risk_rows.sort(key=lambda row: -float(row.get("previous_tonnes") or 0))
        risks = [
            {
                "name": str(row.get("client_name") or ""),
                "salesperson": str(row.get("salesperson_name") or "Directo"),
                "last": _date(row.get("previous_last_date")),
                "previous_tn": _number(row.get("previous_tonnes"), 1),
                "previous_total": _money_compact(row.get("previous_total")),
            }
            for row in risk_rows[:5]
        ]
        cohort_total = previous_buyers + int(summary.get("count_nuevos") or 0)
        cohort = [
            ("Sin Recompra", int(summary.get("count_sin_recompra") or 0), "red", f"−{_number(lost, 1)} TN"),
            ("Compraron Menos", int(summary.get("count_redujeron") or 0), "amber", f"−{_number(abs(less), 1)} TN"),
            ("Volumen Estable", int(summary.get("count_sin_cambios") or 0), "navy", "Sin variación"),
            ("Compraron Más", int(summary.get("count_aumentaron") or 0), "green", f"+{_number(more, 1)} TN"),
            ("Nuevos / Recuperados", int(summary.get("count_nuevos") or 0), "emerald", f"+{_number(new, 1)} TN"),
        ]
        cohort_view = [
            {
                "label": label,
                "count": count,
                "percent": round(count / cohort_total * 100, 1) if cohort_total else 0,
                "color": color,
                "detail": detail,
            }
            for label, count, color, detail in cohort
        ]
        diagnosis = ""
        if summary:
            move = "por debajo" if tonnes < previous_tonnes else "por encima"
            diagnosis = (
                f"El volumen físico está <strong>{abs(tonnes - previous_tonnes):.1f} TN {move}</strong> "
                f"de septiembre ({_number(abs(tonnes - previous_tonnes) / previous_tonnes * 100 if previous_tonnes else 0, 1)}%). "
                f"La entrada de <strong>{int(summary.get('count_nuevos') or 0)} clientes nuevos "
                f"(+{_number(new, 1)} TN)</strong> y el crecimiento de "
                f"<strong>{int(summary.get('count_aumentaron') or 0)} cuentas activas "
                f"(+{_number(more, 1)} TN)</strong> compensaron el "
                f"<strong>{_number(recovery, 0)}%</strong> de la baja de "
                f"<strong>{int(summary.get('count_sin_recompra') or 0)} clientes sin recompra "
                f"(−{_number(lost, 1)} TN)</strong>."
            )
        waterfall_items = [
            {"label": "Sep 2026", "value": previous_tonnes, "kind": "base", "sub": f"{previous_buyers} clientes"},
            {"label": "Sin recompra", "value": -lost, "kind": "neg", "sub": f"{int(summary.get('count_sin_recompra') or 0)} clientes"},
            {"label": "Compraron −", "value": less, "kind": "neg", "sub": f"{int(summary.get('count_redujeron') or 0)} clientes"},
            {"label": "Compraron +", "value": more, "kind": "pos", "sub": f"{int(summary.get('count_aumentaron') or 0)} clientes"},
            {"label": "Nuevos / Rec.", "value": new, "kind": "pos", "sub": f"{int(summary.get('count_nuevos') or 0)} clientes"},
            {"label": "Oct 2026", "value": tonnes, "kind": "end", "sub": f"{buyers} clientes"},
        ]
        for item in waterfall_items:
            item["value_text"] = (
                _signed(item["value"], lambda number: _number(number, 1))
                if item["kind"] not in {"base", "end"}
                else _number(item["value"], 1)
            )
        return {
            "empty": False,
            "has_repurchase": has_repurchase,
            "diagnosis": diagnosis,
            "kpis": {
                "sales": {
                    "value": _money_compact(sales),
                    "delta": sales_delta,
                    "direction": sales_direction,
                    "previous": _money_compact(previous_sales),
                    "diff": _signed(sales - previous_sales, _money_compact),
                    "meter": round(sales / previous_sales * 100, 1) if previous_sales else 0,
                },
                "tonnes": {
                    "value": f"{_number(tonnes, 1)} TN",
                    "delta": tonnes_delta,
                    "direction": tonnes_direction,
                    "previous": f"{_number(previous_tonnes, 1)} TN",
                    "diff": _signed(tonnes - previous_tonnes, lambda value: f"{_number(value, 1)} TN"),
                    "meter": round(tonnes / previous_tonnes * 100, 1) if previous_tonnes else 0,
                },
                "buyers": {
                    "value": f"{buyers} cuentas",
                    "delta": buyers_delta,
                    "direction": buyers_direction,
                    "previous": f"{previous_buyers} cuentas",
                    "retention": _number(retention, 1),
                    "meter": round(buyers / previous_buyers * 100, 1) if previous_buyers else 0,
                },
                "orders": {
                    "value": f"{int(round(orders))} cargas",
                    "delta": orders_delta,
                    "direction": orders_direction,
                    "previous": f"{int(round(previous_orders))} cargas",
                    "average": _number(tonnes / orders, 1) if orders else "0,0",
                    "meter": round(orders / previous_orders * 100, 1) if previous_orders else 0,
                },
                "price": {
                    "value": _price_tn(price),
                    "delta": price_delta,
                    "direction": price_direction,
                    "previous": _price_tn(previous_price),
                    "ticket": _money_compact(ticket) if ticket else _money_compact(previous_ticket),
                    "meter": round(price / previous_price * 100, 1) if previous_price else 0,
                },
            },
            "waterfall": {
                "items": waterfall_items,
                "svg": _waterfall_svg(waterfall_items),
                "gross_loss": _number(gross_loss, 1),
                "gross_gain": _number(gross_gain, 1),
                "recovery": _number(recovery, 1),
            "count_loss": int(summary.get("count_sin_recompra") or 0) + int(summary.get("count_redujeron") or 0),
            "count_gain": int(summary.get("count_nuevos") or 0) + int(summary.get("count_aumentaron") or 0),
            },
            "top_clients": clients,
            "top_clients_share": _number(sum(float(row.get("total") or 0) for row in top_clients[:5]) / sales * 100, 1) if sales else "0,0",
            "best_product": max(
                [row for row in products if (row["variation_value"] or 0) > 0],
                key=lambda row: row["variation_value"],
                default=None,
            ),
            "worst_product": min(
                [row for row in products if (row["variation_value"] or 0) < 0],
                key=lambda row: row["variation_value"],
                default=None,
            ),
            "products": products,
            "cohort": cohort_view,
            "cohort_total": cohort_total,
            "risks": risks,
        }
