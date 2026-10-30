"""Snapshot de recompra por cliente, agregado por mes (#837)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from time import time
from uuid import uuid4

from app.models.sync import SyncCursor
from app.reports.managerial_dashboard import (
    ManagerialDashboardService,
    ReportPeriod,
)
from app.services.sync_service import SyncService

STATUS_ORDER = {
    "sin_recompra": 0,
    "compro_menos": 1,
    "igual": 2,
    "compro_mas": 3,
    "nuevo": 4,
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _variation(current: float, previous: float):
    if previous == 0:
        return None if current else 0.0
    return round((current - previous) / abs(previous) * 100, 1)


def _status(previous_kg: float, current_kg: float) -> str:
    if previous_kg > 0.5 and current_kg <= 0.5:
        return "sin_recompra"
    if previous_kg <= 0.5 and current_kg > 0.5:
        return "nuevo"
    if abs(current_kg - previous_kg) <= 0.5:
        return "igual"
    if current_kg < previous_kg:
        return "compro_menos"
    return "compro_mas"


def _period(period: ReportPeriod) -> dict:
    return {
        "start": period.start.isoformat(),
        "end": period.end.isoformat(),
        "label": period.label,
    }


class ManagerialRepurchasePublisher:
    def __init__(
        self,
        *,
        dashboard_service: ManagerialDashboardService | None = None,
        min_interval_minutes: int = 30,
    ) -> None:
        self.dashboard_service = dashboard_service or ManagerialDashboardService()
        self.min_interval_minutes = int(min_interval_minutes)

    def should_publish(self, *, now: datetime | None = None) -> bool:
        if self.min_interval_minutes <= 0:
            return True
        cursor = SyncCursor.get_or_none(
            SyncCursor.stream == SyncCursor.STREAM_FACTORY_REPURCHASE
        )
        if cursor is None or cursor.last_synced_at is None:
            return True
        current = now or datetime.now(timezone.utc).replace(tzinfo=None)
        last = cursor.last_synced_at
        if last.tzinfo is not None:
            last = last.astimezone(timezone.utc).replace(tzinfo=None)
        return (current - last).total_seconds() >= self.min_interval_minutes * 60

    @staticmethod
    def _aggregate_clients(product_rows: list[dict]) -> list[dict]:
        grouped: dict[int, dict] = {}
        for row in product_rows:
            client_id = int(row["client_id"])
            target = grouped.setdefault(
                client_id,
                {
                    "client_id": client_id,
                    "client_name": row.get("client_name") or "",
                    "salesperson_name": "",
                    "previous_kilos": 0.0,
                    "current_kilos": 0.0,
                    "previous_total": 0.0,
                    "current_total": 0.0,
                    "previous_last_date": None,
                    "current_last_date": None,
                },
            )
            target["previous_kilos"] += float(row.get("previous_kilos") or 0)
            target["current_kilos"] += float(row.get("current_kilos") or 0)
            target["previous_total"] += float(row.get("previous_total") or 0)
            target["current_total"] += float(row.get("current_total") or 0)
            if row.get("salesperson_name") and not target["salesperson_name"]:
                target["salesperson_name"] = row["salesperson_name"]
            for key in ("previous_last_date", "current_last_date"):
                value = row.get(key)
                if value and (
                    target[key] is None or str(value) > str(target[key])
                ):
                    target[key] = value

        rows = []
        for target in grouped.values():
            previous_kg = target["previous_kilos"]
            current_kg = target["current_kilos"]
            rows.append(
                {
                    "client_name": target["client_name"],
                    "salesperson_name": target["salesperson_name"],
                    "previous_last_date": target["previous_last_date"],
                    "current_last_date": target["current_last_date"],
                    "previous_tonnes": round(previous_kg / 1000.0, 3),
                    "current_tonnes": round(current_kg / 1000.0, 3),
                    "diff_tonnes": round((current_kg - previous_kg) / 1000.0, 3),
                    "variation_percent": _variation(current_kg, previous_kg),
                    "previous_total": round(target["previous_total"], 2),
                    "current_total": round(target["current_total"], 2),
                    "status": _status(previous_kg, current_kg),
                }
            )
        rows.sort(
            key=lambda row: (
                STATUS_ORDER.get(row["status"], 9),
                -row["previous_tonnes"],
                -row["current_tonnes"],
                row["client_name"],
            )
        )
        return rows

    @staticmethod
    def _summary(rows: list[dict], current: ReportPeriod, previous: ReportPeriod) -> dict:
        by_status: dict[str, list[dict]] = {}
        for row in rows:
            by_status.setdefault(row["status"], []).append(row)
        previous_tonnes = round(sum(row["previous_tonnes"] for row in rows), 3)
        current_tonnes = round(sum(row["current_tonnes"] for row in rows), 3)
        previous_total = round(sum(row["previous_total"] for row in rows), 2)
        current_total = round(sum(row["current_total"] for row in rows), 2)
        lost = by_status.get("sin_recompra", [])
        less = by_status.get("compro_menos", [])
        more = by_status.get("compro_mas", [])
        new = by_status.get("nuevo", [])
        same = by_status.get("igual", [])
        lost_tonnes = round(sum(row["previous_tonnes"] for row in lost), 3)
        reduction_tonnes = round(sum(row["diff_tonnes"] for row in less), 3)
        increase_tonnes = round(sum(row["diff_tonnes"] for row in more), 3)
        new_tonnes = round(sum(row["current_tonnes"] for row in new), 3)
        reconciled = round(
            -lost_tonnes + reduction_tonnes + increase_tonnes + new_tonnes, 3
        )
        diff_tonnes = round(current_tonnes - previous_tonnes, 3)
        return {
            "current_range": current.describe_range(),
            "previous_range": previous.describe_range(),
            "previous_tonnes": previous_tonnes,
            "current_tonnes": current_tonnes,
            "diff_tonnes": diff_tonnes,
            "variation_percent": _variation(
                current_tonnes * 1000.0, previous_tonnes * 1000.0
            ),
            "previous_total": previous_total,
            "current_total": current_total,
            "buyers_previous": sum(
                1 for row in rows if row["previous_tonnes"] > 0.0005
            ),
            "buyers_current": sum(
                1 for row in rows if row["current_tonnes"] > 0.0005
            ),
            "count_sin_recompra": len(lost),
            "count_redujeron": len(less),
            "count_aumentaron": len(more),
            "count_nuevos": len(new),
            "count_sin_cambios": len(same),
            "lost_tonnes": lost_tonnes,
            "reduction_tonnes": reduction_tonnes,
            "increase_tonnes": increase_tonnes,
            "new_tonnes": new_tonnes,
            "reconciled_diff_tonnes": reconciled,
            "reconciliation_ok": abs(reconciled - diff_tonnes) < 0.002,
        }

    def build(self, *, as_of: date | None = None) -> dict:
        today = as_of or date.today()
        current = ReportPeriod(today.replace(day=1), today, "Este mes")
        previous = current.previous_equivalent()
        product_rows = self.dashboard_service.product_client_repurchase(
            current, previous
        )
        rows = self._aggregate_clients(product_rows)
        return {
            "schema_version": "1.0",
            "snapshot_id": str(uuid4()),
            "generated_at": _iso_now(),
            "period": _period(current),
            "previous_period": _period(previous),
            "summary": self._summary(rows, current, previous),
            "rows": rows,
        }

    def publish(self, client, *, as_of: date | None = None) -> dict:
        snapshot = self.build(as_of=as_of)
        response = client.post_managerial_repurchase_snapshot(snapshot)
        SyncService.set_cursor(
            SyncCursor.STREAM_FACTORY_REPURCHASE,
            int(time()),
            synced_at=datetime.now(timezone.utc),
        )
        return {
            "snapshot": response,
            "snapshot_id": snapshot["snapshot_id"],
            "generated_at": snapshot["generated_at"],
        }
