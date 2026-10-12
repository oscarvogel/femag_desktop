from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

from peewee import JOIN, fn

from app.config.database import database_proxy
from app.models.accounting import ClientAccountMovement
from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.models.masters import Client, Product, Salesperson


DEFAULT_EFFECTIVE_ORDER_STATUSES = (LoadOrder.STATUS_ISSUED, LoadOrder.STATUS_CLOSED)
DEFAULT_CURRENCY = "ARS"

_ONE_DAY = timedelta(days=1)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - _ONE_DAY).day


def _day_in_month(year: int, month: int, day: int) -> date:
    """Resolve a day-of-month in another month, clamping to its real length.

    ``day_in_month(2025, 2, 31)`` is 28/02/2025: February never has 31 days,
    and comparing against it must not raise.
    """
    return date(year, month, min(day, _days_in_month(year, month)))


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _variation_percent(current: float, previous: float) -> float | None:
    if previous == 0:
        return None if current != 0 else 0.0
    return round(((current - previous) / abs(previous)) * 100, 1)


@dataclass(frozen=True)
class ReportPeriod:
    start: date
    end: date
    label: str = "Personalizado"

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("La fecha hasta no puede ser anterior a la fecha desde.")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def month_span(self) -> int:
        """How many calendar months the period touches, counting both ends."""
        return (self.end.year - self.start.year) * 12 + (self.end.month - self.start.month) + 1

    def previous_equivalent(self) -> "ReportPeriod":
        """Equivalent calendar period, not the N days immediately before it.

        Comparing "este mes" (01/10 → 12/10) against the preceding 12 days
        (19/09 → 30/09) mixes a partial month with the tail of the previous one,
        so the percentage moves with the day the dashboard is opened. The
        equivalent period is the same calendar slice one period back:

        - one day → the day before;
        - a period inside a single month → the same day range of the previous
          month, clamping to its real length;
        - a full calendar month → the previous full month, with its own length;
        - an accumulation starting on day 1 across months (such as "este año")
          → the same accumulation of the previous year, so the comparison never
          overlaps the period it is comparing.
        """
        label = f"{self.label} anterior"

        if self.days == 1:
            previous = self.start - _ONE_DAY
            return ReportPeriod(previous, previous, label)

        if self.start.day == 1 and self.month_span > 1:
            return ReportPeriod(
                _day_in_month(self.start.year - 1, self.start.month, self.start.day),
                _day_in_month(self.end.year - 1, self.end.month, self.end.day),
                label,
            )

        target_year, target_month = _previous_month(self.start.year, self.start.month)
        if self.start.day == 1 and self.end.day == _days_in_month(self.end.year, self.end.month):
            return ReportPeriod(
                date(target_year, target_month, 1),
                date(target_year, target_month, _days_in_month(target_year, target_month)),
                label,
            )

        previous_start = _day_in_month(target_year, target_month, self.start.day)
        previous_end = _day_in_month(target_year, target_month, self.end.day)
        if previous_end < previous_start:
            previous_end = date(target_year, target_month, _days_in_month(target_year, target_month))
        return ReportPeriod(previous_start, previous_end, label)

    def describe_range(self) -> str:
        """Human readable range, used to make the comparison auditable."""
        if self.start == self.end:
            return f"{self.start:%d/%m/%Y}"
        return f"{self.start:%d/%m/%Y} → {self.end:%d/%m/%Y}"

    @classmethod
    def preset(cls, key: str, *, today: date | None = None) -> "ReportPeriod":
        current = today or date.today()
        normalized = key.strip().lower().replace("_", " ")
        if normalized in {"hoy", "today"}:
            return cls(current, current, "Hoy")
        if normalized in {"este mes", "mes actual", "current month"}:
            return cls(current.replace(day=1), current, "Este mes")
        if normalized in {"mes anterior", "previous month"}:
            first_this_month = current.replace(day=1)
            end = first_this_month - timedelta(days=1)
            return cls(end.replace(day=1), end, "Mes anterior")
        if normalized in {"este año", "ano actual", "año actual", "current year"}:
            return cls(date(current.year, 1, 1), current, "Este año")
        raise ValueError(f"Período predefinido desconocido: {key!r}.")


@dataclass(frozen=True)
class MetricComparison:
    current: float
    previous: float

    @property
    def variation_percent(self) -> float | None:
        if self.previous == 0:
            return None if self.current != 0 else 0.0
        return round(((self.current - self.previous) / abs(self.previous)) * 100, 1)


@dataclass(frozen=True)
class ManagerialSnapshot:
    period: ReportPeriod
    previous_period: ReportPeriod
    valued_dispatches: MetricComparison
    tonnes: MetricComparison
    orders: MetricComparison
    average_ticket: MetricComparison
    total_receivables: float
    overdue_receivables: float
    monthly_evolution: tuple[dict, ...]
    top_clients: tuple[dict, ...]
    top_products: tuple[dict, ...]
    order_statuses: tuple[dict, ...]
    effective_statuses: tuple[str, ...]
    currency: str


class ManagerialDashboardService:
    """Central source of truth for the first managerial dashboard.

    Issued and closed load orders are effective dispatches by default.
    In FEMAG, an issued order already represents merchandise dispatched;
    pending orders are not yet effective dispatches. Physical pallet/loose
    allocations are the primary source for dispatched kilos. Any quantity not
    physically allocated falls back to the product's configured unit weight,
    so partial preparation is not double counted.
    """

    def __init__(
        self,
        *,
        effective_statuses: Iterable[str] = DEFAULT_EFFECTIVE_ORDER_STATUSES,
        currency: str = DEFAULT_CURRENCY,
    ) -> None:
        self.effective_statuses = tuple(effective_statuses)
        if not self.effective_statuses:
            raise ValueError("Debe existir al menos un estado efectivo para el dashboard.")
        self.currency = currency

    def snapshot(self, period: ReportPeriod) -> ManagerialSnapshot:
        previous = period.previous_equivalent()
        current = self._period_metrics(period)
        before = self._period_metrics(previous)
        return ManagerialSnapshot(
            period=period,
            previous_period=previous,
            valued_dispatches=MetricComparison(current["valued_dispatches"], before["valued_dispatches"]),
            tonnes=MetricComparison(current["tonnes"], before["tonnes"]),
            orders=MetricComparison(current["orders"], before["orders"]),
            average_ticket=MetricComparison(current["average_ticket"], before["average_ticket"]),
            total_receivables=self.total_receivables(),
            overdue_receivables=self.overdue_receivables(as_of=period.end),
            monthly_evolution=tuple(self.monthly_evolution(period.end, months=12)),
            top_clients=tuple(self.top_clients(period)),
            top_products=tuple(self.top_products(period)),
            order_statuses=tuple(self.order_status_distribution(period)),
            effective_statuses=self.effective_statuses,
            currency=self.currency,
        )

    def _period_metrics(self, period: ReportPeriod) -> dict[str, float]:
        if database_proxy.obj is None:
            return {"valued_dispatches": 0.0, "tonnes": 0.0, "orders": 0.0, "average_ticket": 0.0}

        order_filter = self._effective_order_filter(period)
        order_count = LoadOrder.select().where(order_filter).count()
        total = (
            LoadOrderProduct.select(fn.COALESCE(fn.SUM(LoadOrderProduct.total), 0))
            .join(LoadOrder)
            .where(order_filter)
            .scalar()
        )
        valued_dispatches = round(float(total or 0), 2)
        tonnes = round(self._dispatch_kilos(period) / 1000.0, 3)
        average_ticket = round(valued_dispatches / order_count, 2) if order_count else 0.0
        return {
            "valued_dispatches": valued_dispatches,
            "tonnes": tonnes,
            "orders": float(order_count),
            "average_ticket": average_ticket,
        }

    def _dispatch_line_rows(self, period: ReportPeriod) -> list[dict]:
        if database_proxy.obj is None:
            return []
        return list(
            LoadOrderProduct.select(
                LoadOrderProduct.order.alias("order_id"),
                LoadOrderProduct.destination.alias("destination_id"),
                LoadOrderProduct.product.alias("product_id"),
                LoadOrderProduct.quantity.alias("quantity"),
                LoadOrderProduct.total.alias("total"),
                LoadOrder.date.alias("order_date"),
                Product.name.alias("product_name"),
                Product.peso_unitario_kg.alias("fallback_weight"),
                Client.id.alias("client_id"),
                Client.name.alias("client_name"),
                Salesperson.id.alias("salesperson_id"),
                Salesperson.name.alias("salesperson_name"),
            )
            .join(LoadOrder)
            .switch(LoadOrderProduct)
            .join(Product)
            .switch(LoadOrderProduct)
            .join(LoadOrderDestination, on=(LoadOrderProduct.destination == LoadOrderDestination.id))
            .join(Client, on=(LoadOrderDestination.client == Client.id))
            .join(Salesperson, JOIN.LEFT_OUTER, on=(Client.salesperson == Salesperson.id))
            .where(self._effective_order_filter(period))
            .dicts()
        )

    def _physical_allocations(self, period: ReportPeriod) -> dict[tuple[int, int, int], dict[str, float]]:
        physical: dict[tuple[int, int, int], dict[str, float]] = defaultdict(
            lambda: {"quantity": 0.0, "kilos": 0.0}
        )
        order_filter = self._effective_order_filter(period)

        pallet_rows = (
            LoadOrderPalletAllocation.select(
                LoadOrderPallet.order.alias("order_id"),
                LoadOrderPalletAllocation.destination.alias("destination_id"),
                LoadOrderPalletAllocation.product.alias("product_id"),
                LoadOrderPalletAllocation.quantity.alias("quantity"),
                LoadOrderPalletAllocation.peso_unitario_kg.alias("weight"),
            )
            .join(LoadOrderPallet)
            .join(LoadOrder)
            .where(order_filter)
            .dicts()
        )
        for row in pallet_rows:
            key = (int(row["order_id"]), int(row["destination_id"]), int(row["product_id"]))
            quantity = float(row["quantity"] or 0)
            weight = float(row["weight"] or 0)
            physical[key]["quantity"] += quantity
            physical[key]["kilos"] += quantity * weight

        loose_rows = (
            LoadOrderLooseAllocation.select(
                LoadOrderLooseAllocation.order.alias("order_id"),
                LoadOrderLooseAllocation.destination.alias("destination_id"),
                LoadOrderLooseAllocation.product.alias("product_id"),
                LoadOrderLooseAllocation.quantity.alias("quantity"),
                LoadOrderLooseAllocation.peso_unitario_kg.alias("weight"),
            )
            .join(LoadOrder)
            .where(order_filter)
            .dicts()
        )
        for row in loose_rows:
            key = (int(row["order_id"]), int(row["destination_id"]), int(row["product_id"]))
            quantity = float(row["quantity"] or 0)
            weight = float(row["weight"] or 0)
            physical[key]["quantity"] += quantity
            physical[key]["kilos"] += quantity * weight
        return physical

    def _dispatch_breakdown(self, period: ReportPeriod) -> list[dict]:
        physical = self._physical_allocations(period)
        rows: list[dict] = []
        for line in self._dispatch_line_rows(period):
            key = (int(line["order_id"]), int(line["destination_id"]), int(line["product_id"]))
            actual = physical.get(key, {"quantity": 0.0, "kilos": 0.0})
            line_quantity = max(float(line["quantity"] or 0), 0.0)
            physical_quantity = min(max(float(actual["quantity"]), 0.0), line_quantity)
            # If bad historical data allocates more than the ordered quantity,
            # keep the physical kilos but do not add a negative fallback.
            physical_kilos = max(float(actual["kilos"]), 0.0)
            remaining_quantity = max(line_quantity - physical_quantity, 0.0)
            fallback_weight = max(float(line["fallback_weight"] or 0), 0.0)
            rows.append(
                {
                    **line,
                    "kilos": physical_kilos + (remaining_quantity * fallback_weight),
                }
            )
        return rows

    def _dispatch_kilos(self, period: ReportPeriod) -> float:
        return round(sum(float(row["kilos"]) for row in self._dispatch_breakdown(period)), 3)

    def total_receivables(self) -> float:
        if database_proxy.obj is None:
            return 0.0
        total = (
            ClientAccountMovement.select(fn.COALESCE(fn.SUM(ClientAccountMovement.total_amount), 0))
            .where(ClientAccountMovement.currency == self.currency)
            .scalar()
        )
        return round(max(float(total or 0), 0.0), 2)

    def overdue_receivables(self, *, as_of: date | None = None) -> float:
        """Estimate overdue exposure with two grouped ledger queries.

        Payments are not allocated to individual documents yet. For each client,
        overdue positive documents are therefore capped by the client's current
        positive balance, preserving the existing conservative V1 rule without
        issuing N+1 queries.
        """
        if database_proxy.obj is None:
            return 0.0
        reference_date = as_of or date.today()
        balance_rows = (
            ClientAccountMovement.select(
                ClientAccountMovement.client.alias("client_id"),
                fn.COALESCE(fn.SUM(ClientAccountMovement.total_amount), 0).alias("balance"),
            )
            .where(ClientAccountMovement.currency == self.currency)
            .group_by(ClientAccountMovement.client)
            .dicts()
        )
        overdue_rows = (
            ClientAccountMovement.select(
                ClientAccountMovement.client.alias("client_id"),
                fn.COALESCE(fn.SUM(ClientAccountMovement.total_amount), 0).alias("overdue"),
            )
            .where(
                ClientAccountMovement.currency == self.currency,
                ClientAccountMovement.due_date.is_null(False),
                ClientAccountMovement.due_date < reference_date,
                ClientAccountMovement.total_amount > 0,
            )
            .group_by(ClientAccountMovement.client)
            .dicts()
        )
        balances = {int(row["client_id"]): max(float(row["balance"] or 0), 0.0) for row in balance_rows}
        overdue = {int(row["client_id"]): max(float(row["overdue"] or 0), 0.0) for row in overdue_rows}
        total = sum(min(balance, overdue.get(client_id, 0.0)) for client_id, balance in balances.items())
        return round(total, 2)

    def _client_aggregates(self, period: ReportPeriod) -> dict[int, dict]:
        aggregated: dict[int, dict] = {}
        for row in self._dispatch_breakdown(period):
            client_id = int(row["client_id"])
            target = aggregated.setdefault(
                client_id,
                {"client_id": client_id, "name": row["client_name"], "total": 0.0, "kilos": 0.0},
            )
            target["total"] += float(row["total"] or 0)
            target["kilos"] += float(row["kilos"] or 0)
        return aggregated

    def _product_aggregates(self, period: ReportPeriod) -> dict[int, dict]:
        aggregated: dict[int, dict] = {}
        for row in self._dispatch_breakdown(period):
            product_id = int(row["product_id"])
            target = aggregated.setdefault(
                product_id,
                {"product_id": product_id, "name": row["product_name"], "total": 0.0, "kilos": 0.0},
            )
            target["total"] += float(row["total"] or 0)
            target["kilos"] += float(row["kilos"] or 0)
        return aggregated

    def top_clients(self, period: ReportPeriod, *, limit: int = 10) -> list[dict]:
        current = self._client_aggregates(period)
        previous = self._client_aggregates(period.previous_equivalent())
        ordered = sorted(current.values(), key=lambda row: row["total"], reverse=True)[:limit]
        return [
            {
                "client_id": row["client_id"],
                "name": row["name"],
                "total": round(row["total"], 2),
                "tonnes": round(row["kilos"] / 1000.0, 3),
                "previous_total": round(previous.get(row["client_id"], {}).get("total", 0.0), 2),
                "previous_tonnes": round(previous.get(row["client_id"], {}).get("kilos", 0.0) / 1000.0, 3),
                "variation_percent": _variation_percent(
                    row["total"], previous.get(row["client_id"], {}).get("total", 0.0)
                ),
            }
            for row in ordered
        ]

    def top_products(self, period: ReportPeriod, *, limit: int = 10) -> list[dict]:
        current = self._product_aggregates(period)
        previous = self._product_aggregates(period.previous_equivalent())
        ordered = sorted(current.values(), key=lambda row: row["kilos"], reverse=True)[:limit]
        return [
            {
                "product_id": row["product_id"],
                "name": row["name"],
                "total": round(row["total"], 2),
                "tonnes": round(row["kilos"] / 1000.0, 3),
                "previous_total": round(previous.get(row["product_id"], {}).get("total", 0.0), 2),
                "previous_tonnes": round(previous.get(row["product_id"], {}).get("kilos", 0.0) / 1000.0, 3),
                "variation_percent": _variation_percent(
                    row["total"], previous.get(row["product_id"], {}).get("total", 0.0)
                ),
            }
            for row in ordered
        ]

    def product_client_repurchase(
        self,
        current: ReportPeriod,
        previous: ReportPeriod | None = None,
        *,
        product_id: int | None = None,
        client_id: int | None = None,
        salesperson_id: int | None = None,
        client_query: str | None = None,
        limit: int | None = None,
        order_by: str = "default",
    ) -> list[dict]:
        """Compara cliente x artículo entre dos períodos equivalentes.

        Fuente única: :meth:`_dispatch_breakdown` (órdenes efectivas
        ``Emitida``/``Cerrada``, kilos físicos de pallets + suelto con fallback
        a peso configurado, sin duplicar por destinos). Criterio principal:
        kilos (toneladas); el valorizado es contexto y no clasifica.

        Clasificación por kilos con tolerancia de 0,5 kg para ruido de redondeo:

        - ``sin_recompra``: kilos antes > 0,5 y ahora <= 0,5;
        - ``compro_menos``: kilos en ambos períodos y actual < anterior;
        - ``compro_mas``: kilos en ambos períodos y actual > anterior;
        - ``nuevo``: kilos antes <= 0,5 y ahora > 0,5 (nuevo *en el período
          comparado*, no necesariamente cliente nuevo de FEMAG);
        - ``igual``: diferencia dentro de la tolerancia.

        Devoluciones: viven en ``LoadOrderReturnLine`` (circuito de cierre) y
        hoy no descuentan el KPI valorizado ni los kilos del breakdown, que
        además fija pisos en 0. Por eso no existen netos negativos: una fila
        con kilos negativos futuros se clasifica por la misma regla numérica
        (actual <= 0,5 con anterior > 0,5 → ``sin_recompra``).

        Vendedor: ``LoadOrder`` no guarda vendedor histórico; se informa la
        asignación *actual* ``Client.salesperson`` como proxy operativo y se
        documenta como tal en UI/export. El filtro ``salesperson_id`` usa esa
        misma asignación actual.

        Si ``product_id`` es None se comparan todos los artículos.
        ``order_by`` admite ``"default"`` (estado + TN anterior desc),
        ``"previous_tonnes"``, ``"variation"`` y ``"client"``.
        """
        previous = previous or current.previous_equivalent()
        wanted = (client_query or "").strip().lower()

        def aggregate(period: ReportPeriod) -> dict[tuple[int, int], dict]:
            agg: dict[tuple[int, int], dict] = {}
            for row in self._dispatch_breakdown(period):
                pid = int(row["product_id"])
                if product_id is not None and pid != product_id:
                    continue
                cid = int(row["client_id"])
                if client_id is not None and cid != client_id:
                    continue
                row_sales = int(row["salesperson_id"]) if row.get("salesperson_id") else None
                if salesperson_id is not None and row_sales != salesperson_id:
                    continue
                if wanted and wanted not in str(row["client_name"] or "").lower():
                    continue
                key = (cid, pid)
                target = agg.setdefault(
                    key,
                    {
                        "client_id": cid,
                        "client_name": row["client_name"],
                        "product_id": pid,
                        "product_name": row["product_name"],
                        "salesperson_id": row_sales,
                        "salesperson_name": row.get("salesperson_name") or "",
                        "quantity": 0.0,
                        "kilos": 0.0,
                        "total": 0.0,
                        "orders": set(),
                        "last_date": None,
                    },
                )
                target["quantity"] += float(row["quantity"] or 0)
                target["kilos"] += float(row["kilos"] or 0)
                target["total"] += float(row["total"] or 0)
                target["orders"].add(int(row["order_id"]))
                candidate = row.get("order_date")
                if candidate is not None and (target["last_date"] is None or candidate > target["last_date"]):
                    target["last_date"] = candidate
                if row_sales is not None and target.get("salesperson_id") is None:
                    target["salesperson_id"] = row_sales
                    target["salesperson_name"] = row.get("salesperson_name") or ""
            return agg

        def iso(d) -> str | None:
            return d.isoformat() if hasattr(d, "isoformat") else (str(d) if d else None)

        cur = aggregate(current)
        prev = aggregate(previous)
        rows: list[dict] = []
        for key in sorted(cur.keys() | prev.keys()):
            c = cur.get(key, {"quantity": 0.0, "kilos": 0.0, "total": 0.0, "orders": set(), "last_date": None})
            p = prev.get(key, {"quantity": 0.0, "kilos": 0.0, "total": 0.0, "orders": set(), "last_date": None})
            base = cur.get(key) or prev.get(key) or {}
            cur_kg = float(c["kilos"])
            prev_kg = float(p["kilos"])
            if prev_kg > 0.5 and cur_kg <= 0.5:
                status = "sin_recompra"
            elif prev_kg <= 0.5 and cur_kg > 0.5:
                status = "nuevo"
            elif abs(cur_kg - prev_kg) <= 0.5:
                status = "igual"
            elif cur_kg < prev_kg:
                status = "compro_menos"
            else:
                status = "compro_mas"
            rows.append(
                {
                    "client_id": key[0],
                    "client_name": base.get("client_name", ""),
                    "product_id": key[1],
                    "product_name": base.get("product_name", ""),
                    "salesperson_id": base.get("salesperson_id"),
                    "salesperson_name": base.get("salesperson_name", ""),
                    "salesperson_is_current_assignment": True,
                    "previous_quantity": round(float(p["quantity"]), 3),
                    "previous_kilos": round(prev_kg, 3),
                    "previous_tonnes": round(prev_kg / 1000.0, 3),
                    "previous_total": round(float(p["total"]), 2),
                    "previous_orders": len(p.get("orders") or set()),
                    "previous_last_date": iso(p.get("last_date")),
                    "current_quantity": round(float(c["quantity"]), 3),
                    "current_kilos": round(cur_kg, 3),
                    "current_tonnes": round(cur_kg / 1000.0, 3),
                    "current_total": round(float(c["total"]), 2),
                    "current_orders": len(c.get("orders") or set()),
                    "current_last_date": iso(c.get("last_date")),
                    "diff_kilos": round(cur_kg - prev_kg, 3),
                    "diff_tonnes": round((cur_kg - prev_kg) / 1000.0, 3),
                    "variation_kilos_percent": _variation_percent(cur_kg, prev_kg),
                    "variation_total_percent": _variation_percent(float(c["total"]), float(p["total"])),
                    "status": status,
                }
            )
        if order_by == "previous_tonnes":
            rows.sort(key=lambda r: (-r["previous_kilos"], -r["current_kilos"], r["client_name"]))
        elif order_by == "variation":
            rows.sort(
                key=lambda r: (
                    -(r["variation_kilos_percent"] if r["variation_kilos_percent"] is not None else -999999.0),
                    -r["previous_kilos"],
                )
            )
        elif order_by == "client":
            rows.sort(key=lambda r: (r["client_name"] or "", r["product_name"] or ""))
        else:
            order = {"sin_recompra": 0, "compro_menos": 1, "igual": 2, "compro_mas": 3, "nuevo": 4}
            rows.sort(key=lambda r: (order.get(r["status"], 9), -r["previous_kilos"], -r["current_kilos"]))
        if limit is not None and limit >= 0:
            rows = rows[:limit]
        return rows

    def product_repurchase_summary(
        self,
        current: ReportPeriod,
        previous: ReportPeriod | None = None,
        *,
        product_id: int | None = None,
    ) -> dict:
        """Resumen gerencial por producto con conciliación exacta en TN.

        Variación neta = pérdidas por sin recompra + reducciones recurrentes
        + aumentos recurrentes + incorporaciones del período. Los ``igual``
        aportan 0 por definición (dentro de tolerancia) y se informan aparte.
        """
        previous = previous or current.previous_equivalent()
        rows = self.product_client_repurchase(current, previous, product_id=product_id)
        by_status: dict[str, list[dict]] = {}
        for row in rows:
            by_status.setdefault(row["status"], []).append(row)

        def tons(items: list[dict], field: str) -> float:
            return round(sum(float(r[field]) for r in items), 3)

        prev_tn = round(sum(r["previous_tonnes"] for r in rows), 3)
        cur_tn = round(sum(r["current_tonnes"] for r in rows), 3)
        prev_total = round(sum(r["previous_total"] for r in rows), 2)
        cur_total = round(sum(r["current_total"] for r in rows), 2)
        lost = by_status.get("sin_recompra", [])
        less = by_status.get("compro_menos", [])
        more = by_status.get("compro_mas", [])
        new = by_status.get("nuevo", [])
        same = by_status.get("igual", [])
        lost_tn = tons(lost, "previous_tonnes")
        reduction_tn = round(sum(r["diff_tonnes"] for r in less), 3)
        increase_tn = round(sum(r["diff_tonnes"] for r in more), 3)
        new_tn = tons(new, "current_tonnes")
        reconciled = round(-lost_tn + reduction_tn + increase_tn + new_tn, 3)
        return {
            "product_id": product_id,
            "current_range": current.describe_range(),
            "previous_range": previous.describe_range(),
            "previous_tonnes": prev_tn,
            "current_tonnes": cur_tn,
            "diff_tonnes": round(cur_tn - prev_tn, 3),
            "variation_percent": _variation_percent(cur_tn * 1000.0, prev_tn * 1000.0),
            "previous_total": prev_total,
            "current_total": cur_total,
            "buyers_previous": len({r["client_id"] for r in rows if r["previous_kilos"] > 0.5}),
            "buyers_current": len({r["client_id"] for r in rows if r["current_kilos"] > 0.5}),
            "count_sin_recompra": len(lost),
            "count_redujeron": len(less),
            "count_aumentaron": len(more),
            "count_nuevos": len(new),
            "count_sin_cambios": len(same),
            "lost_tonnes": lost_tn,
            "reduction_tonnes": reduction_tn,
            "increase_tonnes": increase_tn,
            "new_tonnes": new_tn,
            "reconciled_diff_tonnes": reconciled,
            "reconciliation_ok": abs(reconciled - round(cur_tn - prev_tn, 3)) < 0.002,
        }

    def order_status_distribution(self, period: ReportPeriod) -> list[dict]:
        if database_proxy.obj is None:
            return []
        rows = (
            LoadOrder.select(LoadOrder.status, fn.COUNT(LoadOrder.id).alias("count"))
            .where(LoadOrder.date.between(period.start, period.end))
            .group_by(LoadOrder.status)
            .order_by(LoadOrder.status)
            .dicts()
        )
        return [{"status": row["status"], "count": int(row["count"] or 0)} for row in rows]

    def monthly_evolution(self, end: date, *, months: int = 12) -> list[dict]:
        if months <= 0:
            return []
        points: list[dict] = []
        year, month = end.year, end.month
        starts: list[date] = []
        for _ in range(months):
            starts.append(date(year, month, 1))
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        for start in reversed(starts):
            if start.month == 12:
                next_month = date(start.year + 1, 1, 1)
            else:
                next_month = date(start.year, start.month + 1, 1)
            month_end = min(next_month - timedelta(days=1), end)
            period = ReportPeriod(start, month_end, start.strftime("%m/%Y"))
            metrics = self._period_metrics(period)
            # Comparación día por día: el mes parcial actual (ej. 01/10 → 12/10)
            # se compara contra el mismo corte del mes anterior (01/09 → 12/09),
            # no contra el mes anterior completo. Los meses completos se comparan
            # contra el mes anterior completo gracias a previous_equivalent().
            previous = period.previous_equivalent()
            previous_metrics = self._period_metrics(previous)
            points.append(
                {
                    "period": start.strftime("%Y-%m"),
                    "label": start.strftime("%m/%Y"),
                    "total": metrics["valued_dispatches"],
                    "tonnes": metrics["tonnes"],
                    "orders": int(metrics["orders"]),
                    "previous_total": previous_metrics["valued_dispatches"],
                    "previous_tonnes": previous_metrics["tonnes"],
                    "previous_orders": int(previous_metrics["orders"]),
                    "previous_range": previous.describe_range(),
                    "variation_percent": _variation_percent(
                        metrics["valued_dispatches"], previous_metrics["valued_dispatches"]
                    ),
                    "variation_tonnes": _variation_percent(
                        metrics["tonnes"], previous_metrics["tonnes"]
                    ),
                    "variation_orders": _variation_percent(
                        metrics["orders"], previous_metrics["orders"]
                    ),
                }
            )
        return points

    def _effective_order_filter(self, period: ReportPeriod):
        return (
            LoadOrder.status.in_(self.effective_statuses)
            & LoadOrder.date.between(period.start, period.end)
        )
