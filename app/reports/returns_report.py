from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.models.accounting import ClientAccountMovement
from app.models.load_orders import (
    LoadOrder,
    LoadOrderClosure,
    LoadOrderDestination,
    LoadOrderProduct,
    LoadOrderReturnLine,
)
from app.models.masters import Client, ClientAddress, Product
from app.reports.managerial_sales_dispatch import (
    ManagerialSalesDispatchService,
    SalesDispatchFilters,
)


@dataclass(frozen=True)
class ReturnsFilters:
    start: date | None = None
    end: date | None = None
    client_id: int | None = None
    product_id: int | None = None
    lote: str | None = None
    reason: str | None = None
    status: str | None = None
    order_number: int | None = None


@dataclass(frozen=True)
class ReturnsTotals:
    returns: int
    returned_quantity: float
    returned_kilos: float
    credited_amount: float
    dispatched_gross: float
    net_amount: float
    return_rate_percent: float | None


@dataclass(frozen=True)
class ReturnsResult:
    filters: ReturnsFilters
    totals: ReturnsTotals
    rows: tuple[dict, ...]
    top_clients: tuple[dict, ...]
    top_products: tuple[dict, ...]
    top_lots: tuple[dict, ...]


class ReturnsReportService:
    """Returns and claims report (issue #391), read-only.

    Source of truth is LoadOrderReturnLine plus the generated
    return-credit movements. A credit reversed via
    TYPE_RETURN_CREDIT_REVERSAL no longer counts as effective but
    remains visible with resolution Revertida. Gross/net dispatch
    figures reuse the sales/dispatch service, never discounted
    silently.
    """

    RESOLUTION_CREDITED = "Con crédito"
    RESOLUTION_NO_CREDIT = "Sin crédito generado"
    RESOLUTION_REVERSED = "Revertida"

    def report(self, filters: ReturnsFilters) -> ReturnsResult:
        self._validate(filters)
        rows = [row for row in self._all_rows() if self._matches(row, filters)]
        rows.sort(key=lambda row: (row["return_date"], row["order_number"]))
        effective = [row for row in rows if not row["reversed"]]
        gross = self._dispatched_gross(filters)
        credited = round(sum(float(row["credit_amount"]) for row in effective), 2)
        totals = ReturnsTotals(
            returns=len(effective),
            returned_quantity=round(sum(float(row["returned_quantity"]) for row in effective), 3),
            returned_kilos=round(sum(float(row["kilos"]) for row in effective), 3),
            credited_amount=credited,
            dispatched_gross=gross,
            net_amount=round(gross - credited, 2),
            return_rate_percent=round(credited / gross * 100, 2) if gross else None,
        )
        return ReturnsResult(
            filters=filters,
            totals=totals,
            rows=tuple(rows),
            top_clients=self._top(effective, "client_id", "client_name"),
            top_products=self._top(effective, "product_id", "product_name"),
            top_lots=self._top(effective, "lote", "lote"),
        )

    @staticmethod
    def _validate(filters: ReturnsFilters) -> None:
        if filters.start and filters.end and filters.start > filters.end:
            raise ValueError("La fecha desde no puede ser posterior a la fecha hasta.")

    def _all_rows(self) -> list[dict]:
        return_lines = list(LoadOrderReturnLine.select().order_by(LoadOrderReturnLine.id))
        if not return_lines:
            return []
        closure_ids = {line.closure_id for line in return_lines}
        closures = {
            closure.id: closure
            for closure in LoadOrderClosure.select().where(LoadOrderClosure.id.in_(closure_ids))
        }
        order_ids = {closure.order_id for closure in closures.values()}
        orders = {
            order.id: order
            for order in LoadOrder.select().where(LoadOrder.id.in_(order_ids))
        } if order_ids else {}
        line_ids = {line.order_product_id for line in return_lines}
        order_products = {
            line.id: line
            for line in LoadOrderProduct.select().where(LoadOrderProduct.id.in_(line_ids))
        } if line_ids else {}
        destination_ids = {
            line.destination_id for line in order_products.values() if line.destination_id
        }
        destinations = {
            destination.id: destination
            for destination in LoadOrderDestination.select().where(
                LoadOrderDestination.id.in_(destination_ids)
            )
        } if destination_ids else {}
        address_ids = {
            destination.delivery_address_id
            for destination in destinations.values()
            if destination.delivery_address_id
        }
        addresses = {
            address.id: address
            for address in ClientAddress.select().where(ClientAddress.id.in_(address_ids))
        } if address_ids else {}
        client_ids = {line.client_id for line in return_lines}
        clients = {
            client.id: client
            for client in Client.select().where(Client.id.in_(client_ids))
        } if client_ids else {}
        product_ids = {line.product_id for line in order_products.values()}
        products = {
            product.id: product
            for product in Product.select().where(Product.id.in_(product_ids))
        } if product_ids else {}
        credit_by_closure_client, reversed_pairs = self._credit_maps(closure_ids)

        rows: list[dict] = []
        for return_line in return_lines:
            closure = closures.get(return_line.closure_id)
            if closure is None:
                continue
            order = orders.get(closure.order_id)
            if order is None:
                continue
            order_product = order_products.get(return_line.order_product_id)
            destination = destinations.get(order_product.destination_id) if order_product and order_product.destination_id else None
            client = clients.get(return_line.client_id)
            product = products.get(order_product.product_id) if order_product else None
            address = addresses.get(destination.delivery_address_id) if destination and destination.delivery_address_id else None
            destination_label = ""
            if address is not None:
                destination_label = " · ".join(
                    part for part in (address.city, address.address) if (part or "").strip()
                )
            return_date = closure.closed_at.date() if closure.closed_at else order.date
            weight = max(float(product.peso_unitario_kg or 0) if product else 0.0, 0.0)
            quantity = max(float(return_line.quantity or 0), 0.0)
            has_credit = (closure.id, return_line.client_id) in credit_by_closure_client
            reversed_ = (closure.id, return_line.client_id) in reversed_pairs
            if reversed_:
                resolution = self.RESOLUTION_REVERSED
            elif has_credit:
                resolution = self.RESOLUTION_CREDITED
            else:
                resolution = self.RESOLUTION_NO_CREDIT
            rows.append(
                {
                    "return_id": return_line.id,
                    "closure_id": closure.id,
                    "return_date": return_date,
                    "client_id": return_line.client_id,
                    "client_name": client.name if client else "",
                    "destination_id": destination.id if destination else None,
                    "destination": destination_label,
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "order_status": order.status,
                    "product_id": order_product.product_id if order_product else None,
                    "product_name": product.name if product else "",
                    "unit": order_product.unit if order_product else "",
                    "lote": (order_product.lote or "").strip() if order_product and order_product.lote else "",
                    "elaboration_date": order_product.fecha_elaboracion if order_product else None,
                    "dispatched_quantity": round(float(order_product.quantity or 0), 3) if order_product else 0.0,
                    "returned_quantity": round(quantity, 3),
                    "kilos": round(quantity * weight, 3),
                    "reason": return_line.reason or "",
                    "unit_price": round(float(return_line.unit_price or 0), 2),
                    "credit_amount": round(float(return_line.credit_amount or 0), 2),
                    "original_total": round(float(order_product.total or 0), 2) if order_product else 0.0,
                    "has_credit": has_credit,
                    "reversed": reversed_,
                    "resolution": resolution,
                }
            )
        return rows

    def _credit_maps(
        self, closure_ids: set[int]
    ) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
        if not closure_ids:
            return set(), set()
        credits = list(
            ClientAccountMovement.select().where(
                ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_RETURN_CREDIT,
                ClientAccountMovement.is_reversal == False,  # noqa: E712
            )
        )
        credit_by_closure_client: set[tuple[int, int]] = set()
        credit_ids: set[int] = set()
        for movement in credits:
            closure_id = self._closure_id_from_ref(movement.source_ref)
            if closure_id in closure_ids:
                credit_by_closure_client.add((closure_id, movement.client_id))
                credit_ids.add(movement.id)
        reversed_pairs: set[tuple[int, int]] = set()
        if credit_ids:
            reversals = ClientAccountMovement.select().where(
                ClientAccountMovement.movement_type
                == ClientAccountMovement.TYPE_RETURN_CREDIT_REVERSAL,
                ClientAccountMovement.reverses.in_(list(credit_ids)),
            )
            originals = {movement.reverses_id: movement for movement in reversals}
            for movement in credits:
                if movement.id in originals:
                    closure_id = self._closure_id_from_ref(movement.source_ref)
                    reversed_pairs.add((closure_id, movement.client_id))
        return credit_by_closure_client, reversed_pairs

    @staticmethod
    def _closure_id_from_ref(source_ref: str | None) -> int | None:
        # Format: LoadOrderClosure:<id>:ReturnCredit:<client_id>
        try:
            parts = (source_ref or "").split(":")
            return int(parts[1]) if len(parts) >= 2 else None
        except (ValueError, IndexError):
            return None

    def _dispatched_gross(self, filters: ReturnsFilters) -> float:
        end = filters.end or date.today()
        start = filters.start or date(end.year, 1, 1)
        dispatch = ManagerialSalesDispatchService().report(
            SalesDispatchFilters(start=start, end=end, client_id=filters.client_id)
        )
        return dispatch.totals.total

    @staticmethod
    def _matches(row: dict, filters: ReturnsFilters) -> bool:
        if filters.start and row["return_date"] < filters.start:
            return False
        if filters.end and row["return_date"] > filters.end:
            return False
        if filters.client_id is not None and row["client_id"] != filters.client_id:
            return False
        if filters.product_id is not None and row["product_id"] != filters.product_id:
            return False
        if filters.lote is not None and row["lote"].casefold() != filters.lote.strip().casefold():
            return False
        if filters.reason:
            needle = filters.reason.strip().casefold()
            if needle and needle not in row["reason"].casefold():
                return False
        if filters.status is not None and row["order_status"] != filters.status:
            return False
        if filters.order_number is not None and row["order_number"] != filters.order_number:
            return False
        return True

    @staticmethod
    def _top(rows: list[dict], id_key: str, name_key: str, *, limit: int = 10) -> tuple[dict, ...]:
        aggregated: dict[int | str, dict] = defaultdict(
            lambda: {"name": "", "credit": 0.0, "quantity": 0.0, "count": 0}
        )
        for row in rows:
            key = row[id_key] if row[id_key] not in (None, "") else f"row:{row['return_id']}"
            target = aggregated[key]
            target["name"] = row[name_key] or str(key)
            target["credit"] += float(row["credit_amount"] or 0)
            target["quantity"] += float(row["returned_quantity"] or 0)
            target["count"] += 1
        ordered = sorted(
            aggregated.values(), key=lambda item: item["credit"], reverse=True
        )[:limit]
        return tuple(
            {
                "name": item["name"],
                "credit": round(item["credit"], 2),
                "quantity": round(item["quantity"], 3),
                "count": item["count"],
            }
            for item in ordered
        )
