from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date

from app.models.load_orders import LoadOrder, LoadOrderDestination, LoadOrderProduct
from app.models.masters import Carrier, ClientAddress
from app.reports.managerial_dashboard import (
    DEFAULT_EFFECTIVE_ORDER_STATUSES,
    ManagerialDashboardService,
    ReportPeriod,
)


@dataclass(frozen=True)
class SalesDispatchFilters:
    start: date
    end: date
    client_id: int | None = None
    product_id: int | None = None
    carrier_id: int | None = None
    statuses: tuple[str, ...] | None = None
    destination: str | None = None
    sort_by: str = "date"
    descending: bool = False

    @property
    def period(self) -> ReportPeriod:
        return ReportPeriod(self.start, self.end, "Informe ventas/despachos")


@dataclass(frozen=True)
class SalesDispatchTotals:
    net: float
    vat: float
    total: float
    kilos: float
    tonnes: float
    orders: int
    lines: int


@dataclass(frozen=True)
class SalesDispatchReportResult:
    filters: SalesDispatchFilters
    rows: tuple[dict, ...]
    totals: SalesDispatchTotals


class ManagerialSalesDispatchService:
    """Auditable detail behind the managerial sales/dispatch KPIs.

    The service deliberately delegates dispatched-kilo calculation to
    ``ManagerialDashboardService``. This keeps pallet/loose/fallback weight rules
    identical between the dashboard and the detailed report.
    """

    SORT_KEYS = {
        "date": lambda row: (row["date"], row["order_number"], row["line_id"]),
        "order": lambda row: (row["order_number"], row["line_id"]),
        "client": lambda row: (row["client_name"].casefold(), row["date"], row["order_number"]),
        "product": lambda row: (row["product_name"].casefold(), row["date"], row["order_number"]),
        "total": lambda row: (row["total"], row["date"], row["order_number"]),
        "tonnes": lambda row: (row["tonnes"], row["date"], row["order_number"]),
    }

    def report(self, filters: SalesDispatchFilters) -> SalesDispatchReportResult:
        statuses = tuple(filters.statuses or DEFAULT_EFFECTIVE_ORDER_STATUSES)
        if not statuses:
            statuses = tuple(DEFAULT_EFFECTIVE_ORDER_STATUSES)

        dashboard = ManagerialDashboardService(effective_statuses=statuses)
        breakdown = dashboard._dispatch_breakdown(filters.period)
        rows = self._enrich_rows(breakdown)
        rows = [row for row in rows if self._matches(row, filters)]

        sort_key = self.SORT_KEYS.get(filters.sort_by, self.SORT_KEYS["date"])
        rows.sort(key=sort_key, reverse=filters.descending)
        totals = self._totals(rows)
        return SalesDispatchReportResult(filters=filters, rows=tuple(rows), totals=totals)

    @staticmethod
    def _enrich_rows(breakdown: list[dict]) -> list[dict]:
        if not breakdown:
            return []

        order_ids = {int(row["order_id"]) for row in breakdown}
        destination_ids = {int(row["destination_id"]) for row in breakdown}

        orders = {
            order.id: order
            for order in LoadOrder.select().where(LoadOrder.id.in_(order_ids))
        }
        carriers = {
            carrier.id: carrier.name
            for carrier in Carrier.select().where(
                Carrier.id.in_({order.carrier_id for order in orders.values()})
            )
        }
        destinations = {
            destination.id: destination
            for destination in LoadOrderDestination.select().where(
                LoadOrderDestination.id.in_(destination_ids)
            )
        }
        address_ids = {
            destination.delivery_address_id
            for destination in destinations.values()
            if destination.delivery_address_id is not None
        }
        addresses = {
            address.id: address
            for address in ClientAddress.select().where(ClientAddress.id.in_(address_ids))
        }

        line_queues: dict[tuple[int, int, int], deque[LoadOrderProduct]] = defaultdict(deque)
        line_query = (
            LoadOrderProduct.select()
            .where(LoadOrderProduct.order.in_(order_ids))
            .order_by(LoadOrderProduct.id)
        )
        for line in line_query:
            if line.destination_id is None:
                continue
            key = (line.order_id, line.destination_id, line.product_id)
            line_queues[key].append(line)

        enriched: list[dict] = []
        for source in breakdown:
            key = (
                int(source["order_id"]),
                int(source["destination_id"]),
                int(source["product_id"]),
            )
            queue = line_queues.get(key)
            if not queue:
                continue
            line = queue.popleft()
            order = orders.get(line.order_id)
            destination = destinations.get(line.destination_id)
            if order is None or destination is None:
                continue
            address = addresses.get(destination.delivery_address_id)
            destination_label = ""
            if address is not None:
                destination_label = " · ".join(
                    part for part in (address.city, address.address) if (part or "").strip()
                )

            kilos = round(float(source.get("kilos") or 0), 3)
            enriched.append(
                {
                    "line_id": line.id,
                    "date": order.date,
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "status": order.status,
                    "carrier_id": order.carrier_id,
                    "carrier_name": carriers.get(order.carrier_id, ""),
                    "client_id": int(source["client_id"]),
                    "client_name": source["client_name"],
                    "destination_id": destination.id,
                    "destination": destination_label,
                    "product_id": int(source["product_id"]),
                    "product_name": source["product_name"],
                    "quantity": round(float(line.quantity or 0), 3),
                    "unit": line.unit,
                    "kilos": kilos,
                    "tonnes": round(kilos / 1000.0, 3),
                    "unit_net_price": round(float(line.precio_neto_unitario or 0), 2),
                    "net": round(float(line.neto_gravado or line.neto_subtotal or 0), 2),
                    "vat": round(float(line.iva_importe or 0), 2),
                    "total": round(float(line.total or 0), 2),
                }
            )
        return enriched

    @staticmethod
    def _matches(row: dict, filters: SalesDispatchFilters) -> bool:
        if filters.client_id is not None and row["client_id"] != filters.client_id:
            return False
        if filters.product_id is not None and row["product_id"] != filters.product_id:
            return False
        if filters.carrier_id is not None and row["carrier_id"] != filters.carrier_id:
            return False
        if filters.statuses and row["status"] not in filters.statuses:
            return False
        if filters.destination:
            needle = filters.destination.strip().casefold()
            if needle and needle not in row["destination"].casefold():
                return False
        return True

    @staticmethod
    def _totals(rows: list[dict]) -> SalesDispatchTotals:
        valid_rows = [row for row in rows if row["status"] != LoadOrder.STATUS_ANNULLED]
        net = round(sum(float(row["net"]) for row in valid_rows), 2)
        vat = round(sum(float(row["vat"]) for row in valid_rows), 2)
        total = round(sum(float(row["total"]) for row in valid_rows), 2)
        kilos = round(sum(float(row["kilos"]) for row in valid_rows), 3)
        return SalesDispatchTotals(
            net=net,
            vat=vat,
            total=total,
            kilos=kilos,
            tonnes=round(kilos / 1000.0, 3),
            orders=len({row["order_id"] for row in valid_rows}),
            lines=len(valid_rows),
        )
