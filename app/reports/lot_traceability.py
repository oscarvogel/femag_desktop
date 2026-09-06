from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.models.masters import Client, ClientAddress, Product


@dataclass(frozen=True)
class LotTraceabilityFilters:
    lote: str | None = None
    elaboration_from: date | None = None
    elaboration_to: date | None = None
    client_id: int | None = None
    destination: str | None = None
    product_id: int | None = None
    dispatch_from: date | None = None
    dispatch_to: date | None = None
    order_number: int | None = None
    status: str | None = None


@dataclass(frozen=True)
class LotTraceabilityTotals:
    dispatched_quantity: float
    dispatched_kilos: float
    clients: int
    destinations: int
    orders: int
    first_dispatch: date | None
    last_dispatch: date | None


@dataclass(frozen=True)
class LotTraceabilityResult:
    filters: LotTraceabilityFilters
    totals: LotTraceabilityTotals
    rows: tuple[dict, ...]


class LotTraceabilityService:
    """Lot traceability V1 (issue #388).

    Source of truth is the dispatch line lote/fecha (structured fields,
    never inferred from free text) crossed with the physical assignment
    (pallet sequence or loose). Lines without physical assignment are
    reported as unassigned so nothing is silently lost; over-assigned
    quantities are capped like the managerial kilo fallback.

    Finer-than-line multi-lot pallet contents belong to #364.
    """

    UNASSIGNED_LABEL = "Sin asignar"
    LOOSE_LABEL = "Suelto"

    def report(self, filters: LotTraceabilityFilters) -> LotTraceabilityResult:
        self._validate(filters)
        rows = [row for row in self._all_rows() if self._matches(row, filters)]
        rows.sort(key=lambda row: (row["dispatch_date"], row["order_number"], row["pallet"] or ""))
        totals = self._totals(rows)
        return LotTraceabilityResult(filters=filters, totals=totals, rows=tuple(rows))

    @staticmethod
    def _validate(filters: LotTraceabilityFilters) -> None:
        if filters.dispatch_from and filters.dispatch_to and filters.dispatch_from > filters.dispatch_to:
            raise ValueError("La fecha de despacho desde no puede ser posterior a la fecha hasta.")
        if (
            filters.elaboration_from
            and filters.elaboration_to
            and filters.elaboration_from > filters.elaboration_to
        ):
            raise ValueError("La fecha de elaboración desde no puede ser posterior a la fecha hasta.")

    def _all_rows(self) -> list[dict]:
        lines = (
            LoadOrderProduct.select()
            .where((LoadOrderProduct.lote.is_null(False)) & (LoadOrderProduct.lote != ""))
            .order_by(LoadOrderProduct.id)
        )
        if not lines:
            return []
        order_ids = {line.order_id for line in lines}
        orders = {order.id: order for order in LoadOrder.select().where(LoadOrder.id.in_(order_ids))}
        destination_ids = {line.destination_id for line in lines if line.destination_id is not None}
        destinations = (
            {
                destination.id: destination
                for destination in LoadOrderDestination.select().where(
                    LoadOrderDestination.id.in_(destination_ids)
                )
            }
            if destination_ids
            else {}
        )
        address_ids = {
            destination.delivery_address_id
            for destination in destinations.values()
            if destination.delivery_address_id is not None
        }
        addresses = (
            {
                address.id: address
                for address in ClientAddress.select().where(ClientAddress.id.in_(address_ids))
            }
            if address_ids
            else {}
        )
        client_ids = {line.destination.client_id if line.destination_id else None for line in lines}
        client_ids |= {order.client_id for order in orders.values()}
        clients = (
            {
                client.id: client
                for client in Client.select().where(Client.id.in_({i for i in client_ids if i}))
            }
            if client_ids
            else {}
        )
        product_ids = {line.product_id for line in lines}
        products = {
            product.id: product
            for product in Product.select().where(Product.id.in_(product_ids))
        }
        physical = self._physical_by_key(order_ids)
        rows: list[dict] = []
        for line in lines:
            order = orders.get(line.order_id)
            if order is None:
                continue
            rows.extend(
                self._line_rows(
                    line=line,
                    order=order,
                    destinations=destinations,
                    addresses=addresses,
                    clients=clients,
                    products=products,
                    physical=physical,
                )
            )
        return rows

    def _physical_by_key(self, order_ids: set[int]) -> dict[tuple[int, int, int], list[dict]]:
        grouped: dict[tuple[int, int, int], list[dict]] = defaultdict(list)
        pallet_rows = (
            LoadOrderPalletAllocation.select(
                LoadOrderPallet.order.alias("order_id"),
                LoadOrderPalletAllocation.destination.alias("destination_id"),
                LoadOrderPalletAllocation.product.alias("product_id"),
                LoadOrderPalletAllocation.quantity.alias("quantity"),
                LoadOrderPalletAllocation.peso_unitario_kg.alias("weight"),
                LoadOrderPallet.sequence.alias("sequence"),
            )
            .join(LoadOrderPallet)
            .where(LoadOrderPallet.order.in_(order_ids))
            .dicts()
        )
        for row in pallet_rows:
            key = (int(row["order_id"]), int(row["destination_id"]), int(row["product_id"]))
            grouped[key].append(
                {
                    "pallet": f"Pallet {int(row['sequence'])}",
                    "quantity": float(row["quantity"] or 0),
                    "kilos": float(row["quantity"] or 0) * float(row["weight"] or 0),
                }
            )
        loose_rows = (
            LoadOrderLooseAllocation.select(
                LoadOrderLooseAllocation.order.alias("order_id"),
                LoadOrderLooseAllocation.destination.alias("destination_id"),
                LoadOrderLooseAllocation.product.alias("product_id"),
                LoadOrderLooseAllocation.quantity.alias("quantity"),
                LoadOrderLooseAllocation.peso_unitario_kg.alias("weight"),
            )
            .where(LoadOrderLooseAllocation.order.in_(order_ids))
            .dicts()
        )
        for row in loose_rows:
            key = (int(row["order_id"]), int(row["destination_id"]), int(row["product_id"]))
            grouped[key].append(
                {
                    "pallet": self.LOOSE_LABEL,
                    "quantity": float(row["quantity"] or 0),
                    "kilos": float(row["quantity"] or 0) * float(row["weight"] or 0),
                }
            )
        return grouped

    def _line_rows(
        self, *, line: LoadOrderProduct, order: LoadOrder, destinations, addresses, clients, products, physical
    ) -> list[dict]:
        destination = destinations.get(line.destination_id) if line.destination_id else None
        client = clients.get(destination.client_id) if destination else clients.get(order.client_id)
        product = products.get(line.product_id)
        address = addresses.get(destination.delivery_address_id) if destination and destination.delivery_address_id else None
        destination_label = ""
        if address is not None:
            destination_label = " · ".join(
                part for part in (address.city, address.address) if (part or "").strip()
            )
        base = {
            "line_id": line.id,
            "lote": (line.lote or "").strip(),
            "elaboration_date": line.fecha_elaboracion,
            "product_id": line.product_id,
            "product_name": product.name if product else "",
            "unit": line.unit,
            "order_id": order.id,
            "order_number": order.order_number,
            "dispatch_date": order.date,
            "order_status": order.status,
            "client_id": client.id if client else None,
            "client_name": client.name if client else "",
            "destination_id": destination.id if destination else None,
            "destination": destination_label,
            "carrier_name": order.carrier.name if order.carrier_id else "",
            "driver_name": order.driver.name if order.driver_id else "",
            "truck_domain": order.truck.domain if order.truck_id else "",
        }
        key = (line.order_id, line.destination_id or 0, line.product_id)
        assignments = list(physical.get(key, []))
        line_quantity = max(float(line.quantity or 0), 0.0)
        fallback_weight = max(float(product.peso_unitario_kg or 0) if product else 0.0, 0.0)
        rows: list[dict] = []
        remaining = line_quantity
        for assignment in assignments:
            if remaining <= 0:
                break
            take = min(max(assignment["quantity"], 0.0), remaining)
            if take <= 0:
                continue
            share = take / assignment["quantity"] if assignment["quantity"] else 0.0
            rows.append(
                {
                    **base,
                    "pallet": assignment["pallet"],
                    "quantity": round(take, 3),
                    "kilos": round(assignment["kilos"] * share, 3),
                }
            )
            remaining = round(remaining - take, 3)
        if remaining > 0:
            rows.append(
                {
                    **base,
                    "pallet": self.UNASSIGNED_LABEL,
                    "quantity": round(remaining, 3),
                    "kilos": round(remaining * fallback_weight, 3),
                }
            )
        return rows

    @staticmethod
    def _matches(row: dict, filters: LotTraceabilityFilters) -> bool:
        if filters.status is not None:
            if row["order_status"] != filters.status:
                return False
        elif row["order_status"] == LoadOrder.STATUS_ANNULLED:
            return False
        if filters.lote is not None and row["lote"].casefold() != filters.lote.strip().casefold():
            return False
        if filters.elaboration_from and (row["elaboration_date"] is None or row["elaboration_date"] < filters.elaboration_from):
            return False
        if filters.elaboration_to and (row["elaboration_date"] is None or row["elaboration_date"] > filters.elaboration_to):
            return False
        if filters.client_id is not None and row["client_id"] != filters.client_id:
            return False
        if filters.destination:
            needle = filters.destination.strip().casefold()
            if needle and needle not in row["destination"].casefold():
                return False
        if filters.product_id is not None and row["product_id"] != filters.product_id:
            return False
        if filters.dispatch_from and row["dispatch_date"] < filters.dispatch_from:
            return False
        if filters.dispatch_to and row["dispatch_date"] > filters.dispatch_to:
            return False
        if filters.order_number is not None and row["order_number"] != filters.order_number:
            return False
        return True

    @staticmethod
    def _totals(rows: list[dict]) -> LotTraceabilityTotals:
        dates = [row["dispatch_date"] for row in rows if row["dispatch_date"] is not None]
        return LotTraceabilityTotals(
            dispatched_quantity=round(sum(float(row["quantity"]) for row in rows), 3),
            dispatched_kilos=round(sum(float(row["kilos"]) for row in rows), 3),
            clients=len({row["client_id"] for row in rows if row["client_id"] is not None}),
            destinations=len({row["destination_id"] for row in rows if row["destination_id"] is not None}),
            orders=len({row["order_id"] for row in rows}),
            first_dispatch=min(dates) if dates else None,
            last_dispatch=max(dates) if dates else None,
        )
