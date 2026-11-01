"""Snapshot gerencial agregado de fabrica hacia FEMAG Web (#837).

Solo viajan agregados del mes, no ordenes, clientes ni cuentas corrientes.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timezone
from time import time
from uuid import uuid4

from app.models.sync import SyncCursor
from app.reports.managerial_dashboard import (
    ManagerialDashboardService,
    ReportPeriod,
)
from app.services.sync_service import SyncService

MONTH_SHORT = (
    "",
    "Ene",
    "Feb",
    "Mar",
    "Abr",
    "May",
    "Jun",
    "Jul",
    "Ago",
    "Sep",
    "Oct",
    "Nov",
    "Dic",
)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + offset
    return index // 12, index % 12 + 1


def _metric(metric) -> dict:
    return {
        "current": round(float(metric.current or 0), 2),
        "previous": round(float(metric.previous or 0), 2),
        "variation_percent": metric.variation_percent,
    }


def _period(period: ReportPeriod) -> dict:
    return {
        "start": period.start.isoformat(),
        "end": period.end.isoformat(),
        "label": period.label,
    }


def _top_row(row: dict, *, by_tonnes: bool = False) -> dict:
    total = round(float(row.get("total") or 0), 2)
    tonnes = round(float(row.get("tonnes") or 0), 3)
    previous_total = round(float(row.get("previous_total") or 0), 2)
    previous_tonnes = round(float(row.get("previous_tonnes") or 0), 3)
    current = tonnes if by_tonnes else total
    previous = previous_tonnes if by_tonnes else previous_total
    variation = (
        None
        if previous == 0
        else round((current - previous) / abs(previous) * 100, 1)
    )
    return {
        "name": str(row.get("name") or ""),
        "total": total,
        "tonnes": tonnes,
        "previous_total": previous_total,
        "previous_tonnes": previous_tonnes,
        "variation_percent": variation,
    }


class ManagerialSnapshotPublisher:
    def __init__(
        self,
        *,
        dashboard_service: ManagerialDashboardService | None = None,
        min_interval_minutes: int = 30,
        history_months: int = 24,
        history_interval_minutes: int = 24 * 60,
    ) -> None:
        self.dashboard_service = dashboard_service or ManagerialDashboardService()
        self.min_interval_minutes = int(min_interval_minutes)
        self.history_months = max(1, int(history_months))
        self.history_interval_minutes = int(history_interval_minutes)

    @staticmethod
    def _should_publish_stream(
        stream: str, minutes: int, *, now: datetime | None = None
    ) -> bool:
        if minutes <= 0:
            return True
        cursor = SyncCursor.get_or_none(SyncCursor.stream == stream)
        if cursor is None or cursor.last_synced_at is None:
            return True
        current = now or datetime.now(timezone.utc).replace(tzinfo=None)
        last = cursor.last_synced_at
        if last.tzinfo is not None:
            last = last.astimezone(timezone.utc).replace(tzinfo=None)
        return (current - last).total_seconds() >= minutes * 60

    def should_publish(self, *, now: datetime | None = None) -> bool:
        return self._should_publish_stream(
            SyncCursor.STREAM_FACTORY_MANAGERIAL,
            self.min_interval_minutes,
            now=now,
        )

    def should_publish_history(self, *, now: datetime | None = None) -> bool:
        return self._should_publish_stream(
            SyncCursor.STREAM_FACTORY_MANAGERIAL_HISTORY,
            self.history_interval_minutes,
            now=now,
        )

    def build(self, *, as_of: date | None = None) -> dict:
        today = as_of or date.today()
        period = ReportPeriod(today.replace(day=1), today, "Este mes")
        snapshot = self.dashboard_service.snapshot(period)
        last_month = today.strftime("%Y-%m")
        last_day = calendar.monthrange(today.year, today.month)[1]
        current_partial = today.day < last_day

        evolution = []
        for point in snapshot.monthly_evolution:
            month_start = date.fromisoformat(f"{point['period']}-01")
            evolution.append(
                {
                    "period": point["period"],
                    "label": MONTH_SHORT[month_start.month],
                    "total": round(float(point.get("total") or 0), 2),
                    "tonnes": round(float(point.get("tonnes") or 0), 3),
                    "orders": int(point.get("orders") or 0),
                    "partial": bool(
                        current_partial and point["period"] == last_month
                    ),
                }
            )

        return {
            "schema_version": "1.0",
            "snapshot_id": str(uuid4()),
            "generated_at": _iso_now(),
            "period": _period(snapshot.period),
            "previous_period": _period(snapshot.previous_period),
            "currency": snapshot.currency,
            "kpis": {
                "valued_dispatches": _metric(snapshot.valued_dispatches),
                "tonnes": _metric(snapshot.tonnes),
                "orders": _metric(snapshot.orders),
                "average_ticket": _metric(snapshot.average_ticket),
            },
            "monthly_evolution": evolution,
            "top_clients": [
                _top_row(row) for row in snapshot.top_clients[:5]
            ],
            "top_products": [
                _top_row(row, by_tonnes=True)
                for row in snapshot.top_products[:5]
            ],
        }

    def build_history(
        self, *, months: int | None = None, as_of: date | None = None
    ) -> list[dict]:
        """Cortes mensuales cerrados, del más viejo al mes en curso."""
        total = max(1, int(months or self.history_months))
        today = as_of or date.today()
        snapshots = []
        for offset in range(total - 1, 0, -1):
            year, month = _shift_month(today.year, today.month, -offset)
            end = date(year, month, calendar.monthrange(year, month)[1])
            snapshots.append(self.build(as_of=end))
        snapshots.append(self.build(as_of=today))
        return snapshots

    def publish(self, client, *, as_of: date | None = None) -> dict:
        snapshot = self.build(as_of=as_of)
        response = client.post_managerial_snapshot(snapshot)
        SyncService.set_cursor(
            SyncCursor.STREAM_FACTORY_MANAGERIAL,
            int(time()),
            synced_at=datetime.now(timezone.utc),
        )
        return {
            "snapshot": response,
            "snapshot_id": snapshot["snapshot_id"],
            "generated_at": snapshot["generated_at"],
        }

    def publish_history(
        self,
        client,
        *,
        months: int | None = None,
        as_of: date | None = None,
    ) -> dict:
        snapshots = self.build_history(months=months, as_of=as_of)
        for snapshot in snapshots:
            client.post_managerial_snapshot(snapshot)
        SyncService.set_cursor(
            SyncCursor.STREAM_FACTORY_MANAGERIAL_HISTORY,
            int(time()),
            synced_at=datetime.now(timezone.utc),
        )
        return {
            "months": len(snapshots),
            "first": snapshots[0]["period"]["start"],
            "last": snapshots[-1]["period"]["start"],
        }
