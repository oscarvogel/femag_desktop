"""Lectura del snapshot de recompra publicado por la fabrica (#837)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.config.database import database_proxy
from app.models.sync import SyncProjection
from app.utils.datetime_utils import as_datetime
from webapp.managerial_dashboard_service import (
    ManagerialDashboardError,
    _money_full,
    _month_name,
    _number,
    _time_label,
    _variation,
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
    if isinstance(parsed, datetime):
        return parsed.strftime("%d/%m/%Y")
    return parsed.strftime("%d/%m/%Y")


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

        with database_proxy.atomic():
            projection = SyncProjection.get_or_none(
                (SyncProjection.resource_type == SyncProjection.RESOURCE_REPURCHASE)
                & (SyncProjection.resource_uid == "latest")
            )
            if projection is None:
                SyncProjection.create(
                    resource_type=SyncProjection.RESOURCE_REPURCHASE,
                    resource_uid="latest",
                    qr_token=None,
                    order_number=None,
                    status=None,
                    version=1,
                    payload=snapshot,
                    source_updated_at=generated_at.astimezone(
                        timezone.utc
                    ).replace(tzinfo=None),
                    published_at=generated_at.astimezone(
                        timezone.utc
                    ).replace(tzinfo=None),
                    cancelled_at=None,
                )
            else:
                projection.payload = snapshot
                projection.source_updated_at = generated_at.astimezone(
                    timezone.utc
                ).replace(tzinfo=None)
                projection.published_at = projection.source_updated_at
                projection.version = 1
                projection.save(
                    only=[
                        SyncProjection.payload,
                        SyncProjection.source_updated_at,
                        SyncProjection.published_at,
                        SyncProjection.version,
                    ]
                )
        return {
            "snapshot_id": snapshot_id,
            "generated_at": generated_at.isoformat(),
            "accepted": True,
        }

    @staticmethod
    def get_latest():
        return SyncProjection.get_or_none(
            (SyncProjection.resource_type == SyncProjection.RESOURCE_REPURCHASE)
            & (SyncProjection.resource_uid == "latest")
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
