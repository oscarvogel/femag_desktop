"""Lectura del snapshot de recompra publicado por la fabrica (#837)."""

from __future__ import annotations

from datetime import date, timezone

from app.config.database import database_proxy
from app.models.sync import SyncProjection
from app.utils.datetime_utils import as_datetime
from webapp.managerial_dashboard_service import (
    MONTHS_SHORT,
    PERIOD_UID_PREFIX,
    ManagerialDashboardError,
    _days_in_month,
    _money_full,
    _month_name,
    _number,
    _time_label,
    _variation,
    period_uid,
    save_snapshot_projection,
)

STATUS_LABELS = {
    "sin_recompra": "Sin recompra",
    "compro_menos": "Compró menos",
    "igual": "Igual",
    "compro_mas": "Compró más",
    "nuevo": "Nuevo",
}


def _parse_datetime(value) -> datetime:
    parsed = as_datetime(value)
    if parsed is None:
        raise ManagerialDashboardError("El snapshot no tiene generated_at valido.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ManagerialDashboardError("El snapshot tiene fechas invalidas.") from exc


def _range_label(start: date, end: date) -> str:
    return f"{start.day}–{end.day} {_month_name(start.isoformat())}"


def _signed_number(value: float) -> str:
    amount = float(value or 0)
    if amount > 0:
        return f"+{_number(amount, 3)}"
    if amount < 0:
        return f"−{_number(abs(amount), 3)}"
    return "0,000"


def _date_label(value) -> str:
    parsed = as_datetime(value)
    if parsed is None:
        return "—"
    return parsed.strftime("%d/%m/%Y")


def _iso_date(value) -> str:
    parsed = as_datetime(value)
    if parsed is None:
        return ""
    return parsed.strftime("%Y-%m-%d")


def _clean_client_name(value) -> str:
    return " ".join(str(value or "").split())


def _client_key(value) -> str:
    return _clean_client_name(value).casefold()


class ManagerialRepurchaseService:
    @staticmethod
    def apply_snapshot(snapshot: dict) -> dict:
        if not isinstance(snapshot, dict):
            raise ManagerialDashboardError("El snapshot no es un objeto JSON.")
        if str(snapshot.get("schema_version") or "") != "1.0":
            raise ManagerialDashboardError("Version de snapshot no soportada.")
        snapshot_id = str(snapshot.get("snapshot_id") or "").strip()
        if not snapshot_id:
            raise ManagerialDashboardError("Falta snapshot_id.")
        generated_at = _parse_datetime(snapshot.get("generated_at"))
        current = snapshot.get("period")
        previous = snapshot.get("previous_period")
        summary = snapshot.get("summary")
        rows = snapshot.get("rows")
        if not isinstance(current, dict) or not isinstance(previous, dict):
            raise ManagerialDashboardError("Faltan los períodos del snapshot.")
        if not isinstance(summary, dict):
            raise ManagerialDashboardError("Falta el resumen de recompra.")
        if not isinstance(rows, list):
            raise ManagerialDashboardError("Faltan las filas de recompra.")
        _parse_date(current.get("start"))
        _parse_date(current.get("end"))
        _parse_date(previous.get("start"))
        _parse_date(previous.get("end"))
        for required in (
            "previous_tonnes",
            "current_tonnes",
            "diff_tonnes",
            "count_sin_recompra",
            "count_redujeron",
            "count_aumentaron",
            "count_nuevos",
        ):
            if required not in summary:
                raise ManagerialDashboardError(
                    f"Falta {required} en el resumen de recompra."
                )

        saved = save_snapshot_projection(
            SyncProjection.RESOURCE_REPURCHASE, snapshot, generated_at
        )
        return {
            "snapshot_id": snapshot_id,
            "generated_at": generated_at.isoformat(),
            "accepted": True,
            **saved,
        }

    @staticmethod
    def get_latest():
        return SyncProjection.get_or_none(
            (SyncProjection.resource_type == SyncProjection.RESOURCE_REPURCHASE)
            & (SyncProjection.resource_uid == "latest")
        )

    @staticmethod
    def get_for_period(start: str):
        try:
            normalized = date.fromisoformat(str(start)).isoformat()
        except (TypeError, ValueError):
            return None
        return SyncProjection.get_or_none(
            (SyncProjection.resource_type == SyncProjection.RESOURCE_REPURCHASE)
            & (SyncProjection.resource_uid == period_uid(normalized))
        )

    @classmethod
    def latest_view(cls) -> dict:
        projection = cls.get_latest()
        if projection is None:
            return {"empty": True}
        try:
            return _build_view(projection.payload)
        except (ManagerialDashboardError, TypeError, ValueError, KeyError) as exc:
            return {"empty": True, "error": str(exc)}

    @classmethod
    def view_for_period(cls, start: str) -> dict:
        projection = cls.get_for_period(start)
        if projection is None:
            return {"empty": True}
        try:
            return _build_view(projection.payload)
        except (ManagerialDashboardError, TypeError, ValueError, KeyError) as exc:
            return {"empty": True, "error": str(exc)}

    @classmethod
    def client_history(
        cls,
        client_name: str,
        period_start: str | None = None,
        *,
        months: int = 12,
    ) -> dict:
        """Compras mensuales de un cliente a partir de los cortes publicados."""
        name = _clean_client_name(client_name)
        if not name:
            return {"empty": True, "error": "Falta el cliente."}
        if database_proxy.obj is None:
            return {
                "empty": True,
                "error": "La nube todavía no tiene datos de recompra.",
            }
        key = _client_key(name)
        snapshots: dict[date, dict] = {}
        rows = SyncProjection.select().where(
            (SyncProjection.resource_type == SyncProjection.RESOURCE_REPURCHASE)
            & (SyncProjection.resource_uid.startswith(PERIOD_UID_PREFIX))
        )
        for projection in rows:
            payload = (
                projection.payload
                if isinstance(projection.payload, dict)
                else {}
            )
            period = payload.get("period") or {}
            try:
                start = date.fromisoformat(str(period.get("start")))
                end = date.fromisoformat(str(period.get("end")))
            except (TypeError, ValueError):
                continue
            snapshots[start] = {
                "end": end,
                "rows": {
                    _client_key(row.get("client_name")): row
                    for row in (payload.get("rows") or [])
                    if isinstance(row, dict)
                },
            }
        if not snapshots:
            return {
                "empty": True,
                "error": "Todavía no se publicaron meses de recompra.",
            }
        anchor = None
        if period_start:
            try:
                anchor = date.fromisoformat(str(period_start))
            except (TypeError, ValueError):
                anchor = None
        eligible = [
            start for start in snapshots if anchor is None or start <= anchor
        ]
        if not eligible:
            eligible = list(snapshots)
        eligible.sort()
        eligible = eligible[-max(1, int(months)) :]

        points = []
        previous_tonnes = None
        last_seen = None
        max_tonnes = 0.0
        for index, start in enumerate(eligible):
            info = snapshots[start]
            end = info["end"]
            row = info["rows"].get(key)
            tonnes = float(row.get("current_tonnes") or 0) if row else 0.0
            total = float(row.get("current_total") or 0) if row else 0.0
            if row is not None:
                last_seen = row
            variation = None
            if index > 0:
                if (
                    row is not None
                    and row.get("variation_percent") is not None
                ):
                    variation = float(row["variation_percent"])
                elif previous_tonnes is not None and previous_tonnes > 0.0005:
                    variation = round(
                        (tonnes - previous_tonnes) / previous_tonnes * 100, 1
                    )
            delta, direction = _variation(variation)
            max_tonnes = max(max_tonnes, tonnes)
            points.append(
                {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "label": (
                        f"{MONTHS_SHORT[start.month].capitalize()} {start.year}"
                    ),
                    "short": MONTHS_SHORT[start.month],
                    "range": f"{start:%d/%m/%Y} – {end:%d/%m/%Y}",
                    "tonnes": round(tonnes, 3),
                    "tonnes_text": _number(tonnes, 2),
                    "total": round(total, 2),
                    "total_text": _money_full(total),
                    "variation": variation,
                    "variation_text": delta,
                    "direction": direction,
                    "partial": end.day < _days_in_month(end),
                    "last_purchase": (
                        _date_label(row.get("current_last_date"))
                        if row
                        else "—"
                    ),
                }
            )
            previous_tonnes = tonnes
        for point in points:
            point["bar"] = (
                round(point["tonnes"] / max_tonnes * 100, 1)
                if max_tonnes
                else 0
            )

        with_purchase = [
            point for point in points if point["tonnes"] > 0.0005
        ]
        if not with_purchase:
            return {
                "empty": True,
                "client": name,
                "error": (
                    "El cliente no registra compras en los meses disponibles."
                ),
            }

        total_tonnes = round(sum(point["tonnes"] for point in points), 3)
        total_value = round(sum(point["total"] for point in points), 2)
        best = max(points, key=lambda point: point["tonnes"])
        worst = min(with_purchase, key=lambda point: point["tonnes"])
        average = total_tonnes / len(points) if points else 0
        salesperson = "—"
        display_name = name
        if last_seen is not None:
            salesperson = (
                _clean_client_name(last_seen.get("salesperson_name")) or "—"
            )
            display_name = (
                _clean_client_name(last_seen.get("client_name")) or name
            )
        return {
            "empty": False,
            "client": display_name,
            "salesperson": salesperson,
            "range": f"{points[0]['label']} – {points[-1]['label']}",
            "months_count": len(points),
            "active_months": len(with_purchase),
            "total_tonnes": total_tonnes,
            "total_tonnes_text": _number(total_tonnes, 2),
            "total_value": total_value,
            "total_value_text": _money_full(total_value),
            "average_tonnes": round(average, 3),
            "average_tonnes_text": _number(average, 2),
            "best": {
                "label": best["label"],
                "tonnes_text": best["tonnes_text"],
            },
            "worst": {
                "label": worst["label"],
                "tonnes_text": worst["tonnes_text"],
            },
            "latest": {
                "label": points[-1]["label"],
                "tonnes_text": points[-1]["tonnes_text"],
                "partial": points[-1]["partial"],
            },
            "points": points,
        }


def _build_view(payload: dict) -> dict:
    current = payload["period"]
    previous = payload["previous_period"]
    summary = payload["summary"]
    current_start = _parse_date(current["start"])
    current_end = _parse_date(current["end"])
    previous_start = _parse_date(previous["start"])
    previous_end = _parse_date(previous["end"])
    variation_text, variation_direction = _variation(
        summary.get("variation_percent")
    )
    diff = float(summary.get("diff_tonnes") or 0)
    previous_tn = float(summary.get("previous_tonnes") or 0)
    current_tn = float(summary.get("current_tonnes") or 0)
    lost = float(summary.get("lost_tonnes") or 0)
    reduction = float(summary.get("reduction_tonnes") or 0)
    increase = float(summary.get("increase_tonnes") or 0)
    new = float(summary.get("new_tonnes") or 0)
    reconciled = float(summary.get("reconciled_diff_tonnes") or 0)
    count_sin = int(summary.get("count_sin_recompra") or 0)
    count_menos = int(summary.get("count_redujeron") or 0)
    count_mas = int(summary.get("count_aumentaron") or 0)
    count_nuevos = int(summary.get("count_nuevos") or 0)
    count_igual = int(summary.get("count_sin_cambios") or 0)

    rows = []
    for row in payload.get("rows") or []:
        status = str(row.get("status") or "")
        row_delta, row_direction = _variation(row.get("variation_percent"))
        rows.append(
            {
                "client": str(row.get("client_name") or "Sin nombre"),
                "client_raw": _clean_client_name(row.get("client_name")),
                "salesperson": str(row.get("salesperson_name") or "—"),
                "last_purchase": _date_label(
                    row.get("current_last_date")
                    or row.get("previous_last_date")
                ),
                "previous_tonnes": _number(row.get("previous_tonnes"), 3),
                "current_tonnes": _number(row.get("current_tonnes"), 3),
                "diff": _signed_number(row.get("diff_tonnes")),
                "variation": row_delta,
                "direction": row_direction,
                "previous_raw": float(row.get("previous_tonnes") or 0),
                "current_raw": float(row.get("current_tonnes") or 0),
                "diff_raw": float(row.get("diff_tonnes") or 0),
                "variation_raw": (
                    float(row.get("variation_percent"))
                    if row.get("variation_percent") is not None
                    else -1_000_000_000
                ),
                "last_raw": _iso_date(
                    row.get("current_last_date")
                    or row.get("previous_last_date")
                ),
                "total_raw": float(row.get("current_total") or 0),
                "current_total": _money_full(row.get("current_total")),
                "status": status,
                "status_label": STATUS_LABELS.get(status, status),
            }
        )

    status_options = [
        {
            "value": status,
            "label": STATUS_LABELS[status],
            "count": sum(1 for row in rows if row["status"] == status),
        }
        for status in STATUS_LABELS
        if any(row["status"] == status for row in rows)
    ]
    return {
        "empty": False,
        "snapshot_time": _time_label(payload.get("generated_at")),
        "period_start": current_start.isoformat(),
        "current_label": _range_label(current_start, current_end),
        "previous_label": _range_label(previous_start, previous_end),
        "previous_range": f"{previous_start:%d/%m/%Y} – {previous_end:%d/%m/%Y}",
        "current_range": f"{current_start:%d/%m/%Y} – {current_end:%d/%m/%Y}",
        "previous_tonnes": _number(previous_tn, 2),
        "current_tonnes": _number(current_tn, 2),
        "compare_percent": (
            round(current_tn / previous_tn * 100, 1) if previous_tn else 0
        ),
        "previous_total": _money_full(summary.get("previous_total")),
        "current_total": _money_full(summary.get("current_total")),
        "diff_tonnes": _signed_number(diff),
        "variation": variation_text,
        "variation_direction": variation_direction,
        "variation_abs": _number(abs(float(summary.get("variation_percent") or 0)), 1),
        "diff_abs": _number(abs(diff), 2),
        "diff_word": "menos" if diff < 0 else ("más" if diff > 0 else "igual"),
        "count_sin": count_sin,
        "count_menos": count_menos,
        "count_mas": count_mas,
        "count_nuevos": count_nuevos,
        "count_igual": count_igual,
        "lost_tonnes": _number(lost, 2),
        "reduction_tonnes": _number(abs(reduction), 2),
        "increase_tonnes": _number(abs(increase), 2),
        "new_tonnes": _number(new, 2),
        "reconciled": _signed_number(reconciled),
        "reconciliation_ok": bool(summary.get("reconciliation_ok")),
        "rows": rows,
        "status_options": status_options,
    }
