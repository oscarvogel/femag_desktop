"""Lectura del snapshot gerencial publicado por la fabrica (#837)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app.config.database import database_proxy
from app.models.sync import SyncProjection
from app.utils.datetime_utils import as_datetime

ART = timezone(timedelta(hours=-3))
MONTHS = (
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


class ManagerialDashboardError(ValueError):
    pass


def _parse_datetime(value) -> datetime:
    parsed = as_datetime(value)
    if parsed is None:
        raise ManagerialDashboardError("El snapshot no tiene generated_at valido.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _to_naive_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _require_mapping(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise ManagerialDashboardError(f"El snapshot no trae {name}.")
    return value


def _require_list(value, name: str) -> list:
    if not isinstance(value, list):
        raise ManagerialDashboardError(f"El snapshot no trae {name}.")
    return value


class ManagerialDashboardService:
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
        period = _require_mapping(snapshot.get("period"), "period")
        previous = _require_mapping(
            snapshot.get("previous_period"), "previous_period"
        )
        for value, name in ((period, "period"), (previous, "previous_period")):
            if not value.get("start") or not value.get("end"):
                raise ManagerialDashboardError(
                    f"El snapshot no trae fechas en {name}."
                )
            try:
                date.fromisoformat(str(value["start"]))
                date.fromisoformat(str(value["end"]))
            except ValueError as exc:
                raise ManagerialDashboardError(
                    f"Fechas invalidas en {name}."
                ) from exc
        kpis = _require_mapping(snapshot.get("kpis"), "kpis")
        for key in (
            "valued_dispatches",
            "tonnes",
            "orders",
            "average_ticket",
        ):
            _require_mapping(kpis.get(key), f"kpis.{key}")
        _require_list(snapshot.get("monthly_evolution"), "monthly_evolution")
        _require_list(snapshot.get("top_clients"), "top_clients")
        _require_list(snapshot.get("top_products"), "top_products")

        values = {
            "qr_token": None,
            "order_number": None,
            "status": None,
            "version": 1,
            "payload": snapshot,
            "source_updated_at": _to_naive_utc(generated_at),
            "published_at": _to_naive_utc(generated_at),
            "cancelled_at": None,
        }
        with database_proxy.atomic():
            projection = SyncProjection.get_or_none(
                (SyncProjection.resource_type == SyncProjection.RESOURCE_MANAGERIAL)
                & (SyncProjection.resource_uid == "latest")
            )
            if projection is None:
                SyncProjection.create(
                    resource_type=SyncProjection.RESOURCE_MANAGERIAL,
                    resource_uid="latest",
                    **values,
                )
            else:
                projection.payload = snapshot
                projection.source_updated_at = values["source_updated_at"]
                projection.published_at = values["published_at"]
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
            (SyncProjection.resource_type == SyncProjection.RESOURCE_MANAGERIAL)
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


def _number(value, decimals: int = 1) -> str:
    text = f"{float(value or 0):,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _integer(value) -> str:
    return f"{int(round(float(value or 0))):,}".replace(",", ".")


def _money_compact(value) -> str:
    amount = float(value or 0)
    if abs(amount) >= 1_000_000:
        return f"$ {_number(amount / 1_000_000, 1)} M"
    if abs(amount) >= 1_000:
        return f"$ {_number(amount / 1_000, 1)} mil"
    return f"$ {_number(amount, 0)}"


def _variation(value) -> tuple[str, str]:
    if value is None:
        return "Sin base", "flat"
    amount = float(value)
    if amount > 0:
        return f"+{_number(amount, 1)}%", "up"
    if amount < 0:
        return f"−{_number(abs(amount), 1)}%", "down"
    return "0,0%", "flat"


def _month_name(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        return ""
    return MONTHS[parsed.month]


def _time_label(value) -> str:
    parsed = as_datetime(value)
    if parsed is None:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ART).strftime("%d/%m, %H:%M")


def _metric(metric: dict, formatter) -> dict:
    current = float(metric.get("current") or 0)
    previous = float(metric.get("previous") or 0)
    text, direction = _variation(metric.get("variation_percent"))
    return {
        "value": formatter(current),
        "previous": formatter(previous),
        "delta": text,
        "direction": direction,
    }


class _ViewBuilder:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def build(self) -> dict:
        period = self.payload["period"]
        previous = self.payload["previous_period"]
        kpis = self.payload["kpis"]
        sales = float(kpis["valued_dispatches"].get("current") or 0)
        tonnes = float(kpis["tonnes"].get("current") or 0)
        breakdown = {
            "ventas": _metric(kpis["valued_dispatches"], _money_compact),
            "toneladas": _metric(kpis["tonnes"], lambda value: f"{_number(value, 1)} TN"),
            "pedidos": _metric(kpis["orders"], _integer),
            "ticket": _metric(kpis["average_ticket"], _money_compact),
        }

        clients = self._top_rows(
            self.payload.get("top_clients") or [], value_key="total"
        )
        products = self._top_rows(
            self.payload.get("top_products") or [],
            value_key="tonnes",
            variation_key="tonnes",
        )
        previous_month = _month_name(previous["start"])
        brief = {
            "before": "El mes va ",
            "value": breakdown["ventas"]["delta"],
            "after": f" respecto del mismo tramo de {previous_month}.",
        }
        chart = []
        for point in self.payload.get("monthly_evolution") or []:
            chart.append(
                {
                    "label": str(point.get("label") or ""),
                    "value": round(float(point.get("total") or 0), 2),
                    "partial": bool(point.get("partial")),
                }
            )
        return {
            "empty": False,
            "period_label": (
                f"{MONTHS[date.fromisoformat(period['end']).month].capitalize()} "
                f"{date.fromisoformat(period['end']).year}"
            ),
            "period_subtitle": (
                "Mes en curso · comparado con el mismo tramo de "
                f"{_month_name(previous['start'])}"
            ),
            "snapshot_time": _time_label(self.payload.get("generated_at")),
            "brief": brief,
            "kpis": breakdown,
            "chart": chart,
            "top_clients": clients,
            "top_products": products,
            "insights": self._insights(sales, tonnes, clients, products),
        }

    @staticmethod
    def _top_rows(
        rows: list,
        *,
        value_key: str,
        variation_key: str = "total",
    ) -> list[dict]:
        max_value = 0.0
        prepared = []
        for row in rows:
            total = float(row.get("total") or 0)
            tonnes = float(row.get("tonnes") or 0)
            current_value = total if value_key == "total" else tonnes
            previous_value = (
                float(row.get("previous_total") or 0)
                if variation_key == "total"
                else float(row.get("previous_tonnes") or 0)
            )
            variation = (
                None
                if previous_value == 0
                else round(((current_value - previous_value) / abs(previous_value)) * 100, 1)
            )
            max_value = max(max_value, current_value)
            prepared.append(
                {
                    "name": str(row.get("name") or "Sin nombre"),
                    "current": current_value,
                    "total": total,
                    "tonnes": tonnes,
                    "variation": variation,
                }
            )
        output = []
        for row in prepared:
            delta, direction = _variation(row["variation"])
            output.append(
                {
                    "name": row["name"],
                    "value": (
                        _money_compact(row["total"])
                        if value_key == "total"
                        else f"{_number(row['tonnes'], 1)} TN"
                    ),
                    "total": row["total"],
                    "tonnes": row["tonnes"],
                    "variation": row["variation"],
                    "delta": delta,
                    "direction": direction,
                    "bar_percent": (
                        round(row["current"] / max_value * 100, 1)
                        if max_value
                        else 0
                    ),
                }
            )
        return output

    @staticmethod
    def _insights(sales, tonnes, clients, products) -> list[dict]:
        insights = []
        if sales > 0 and clients:
            top5 = sum(float(row.get("total") or 0) for row in clients)
            share = round(top5 / sales * 100, 0)
            insights.append(
                {
                    "label": "Concentración",
                    "before": "El top 5 de clientes explica el ",
                    "value": f"{_number(share, 0)}%",
                    "after": " de la venta del mes.",
                }
            )
        if tonnes > 0 and products:
            top = products[0]
            share = round(float(top.get("tonnes") or 0) / tonnes * 100, 0)
            insights.append(
                {
                    "label": "Mezcla",
                    "before": "El producto principal aporta el ",
                    "value": f"{_number(share, 0)}%",
                    "after": " de las toneladas.",
                }
            )
        negative = next(
            (row for row in clients if row.get("variation") is not None and row["variation"] < 0),
            None,
        )
        if negative:
            insights.append(
                {
                    "label": "A vigilar",
                    "before": f"{negative['name']} cae ",
                    "value": f"{_number(abs(float(negative['variation'])), 1)}%",
                    "after": " contra el mismo tramo de septiembre.",
                }
            )
        return insights


def _build_view(payload: dict) -> dict:
    return _ViewBuilder(payload).build()
