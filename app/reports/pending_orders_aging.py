from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from app.models.load_orders import (
    LoadOrder,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.models.remittances import Remittance


@dataclass(frozen=True)
class PendingOrdersFilters:
    start: date | None = None
    end: date | None = None
    status: str | None = None
    client_id: int | None = None
    carrier_id: int | None = None
    min_age_days: int = 0
    pending_stage: str | None = None


@dataclass(frozen=True)
class PendingOrdersTotals:
    open_orders: int
    over_1_day: int
    over_3_days: int
    over_7_days: int
    incomplete_pallets: int
    incomplete_traceability: int
    pending_closure: int


@dataclass(frozen=True)
class PendingOrdersResult:
    filters: PendingOrdersFilters
    rows: tuple[dict, ...]
    totals: PendingOrdersTotals


class PendingOrdersAgingService:
    STAGE_PREPARATION = "Pendiente de preparación"
    STAGE_INCOMPLETE = "Preparación incompleta"
    STAGE_TRACEABILITY = "Trazabilidad/lotes incompletos"
    STAGE_READY = "Lista para emitir"
    STAGE_CLOSURE = "Emitida pendiente de cierre"
    STAGE_DOCUMENTAL = "Pendiente documental"

    def report(self, filters: PendingOrdersFilters, *, today: date | None = None) -> PendingOrdersResult:
        if filters.start and filters.end and filters.start > filters.end:
            raise ValueError("La fecha desde no puede ser posterior a la fecha hasta.")
        today = today or date.today()
        query = LoadOrder.select().where(LoadOrder.status.in_(LoadOrder.ACTIVE_STATUSES))
        if filters.start:
            query = query.where(LoadOrder.date >= filters.start)
        if filters.end:
            query = query.where(LoadOrder.date <= filters.end)
        if filters.status:
            query = query.where(LoadOrder.status == filters.status)
        if filters.client_id:
            query = query.where(LoadOrder.client == filters.client_id)
        if filters.carrier_id:
            query = query.where(LoadOrder.carrier == filters.carrier_id)

        rows = []
        for order in query.order_by(LoadOrder.date, LoadOrder.order_number):
            row = self._row(order, today)
            if row["age_days"] < max(0, filters.min_age_days):
                continue
            if filters.pending_stage and row["pending_stage"] != filters.pending_stage:
                continue
            rows.append(row)

        totals = PendingOrdersTotals(
            open_orders=len(rows),
            over_1_day=sum(row["age_days"] > 1 for row in rows),
            over_3_days=sum(row["age_days"] > 3 for row in rows),
            over_7_days=sum(row["age_days"] > 7 for row in rows),
            incomplete_pallets=sum(row["pending_quantity"] > 0 for row in rows),
            incomplete_traceability=sum(row["traceability_pending"] for row in rows),
            pending_closure=sum(row["status"] == LoadOrder.STATUS_ISSUED for row in rows),
        )
        return PendingOrdersResult(filters=filters, rows=tuple(rows), totals=totals)

    def _row(self, order: LoadOrder, today: date) -> dict:
        products = list(
            LoadOrderProduct.select()
            .where(LoadOrderProduct.order == order)
            .order_by(LoadOrderProduct.id)
        )
        pallet_allocations = list(
            LoadOrderPalletAllocation.select()
            .join_from(LoadOrderPalletAllocation, __import__("app.models.load_orders", fromlist=["LoadOrderPallet"]).LoadOrderPallet)
            .where(__import__("app.models.load_orders", fromlist=["LoadOrderPallet"]).LoadOrderPallet.order == order)
        )
        loose_allocations = list(
            LoadOrderLooseAllocation.select().where(LoadOrderLooseAllocation.order == order)
        )

        requested = sum((Decimal(str(line.quantity or 0)) for line in products), Decimal("0"))
        assigned = sum((Decimal(str(line.quantity or 0)) for line in pallet_allocations), Decimal("0"))
        assigned += sum((Decimal(str(line.quantity or 0)) for line in loose_allocations), Decimal("0"))
        pending_quantity = max(Decimal("0"), requested - assigned)

        pallet_ids = {line.pallet_id for line in pallet_allocations}
        pallet_count = len(pallet_ids)
        complete_pallets = pallet_count if pending_quantity == 0 and pallet_count else 0

        traceability_missing_lines = sum(
            1 for line in products if not (line.lote or "").strip() or line.fecha_elaboracion is None
        )
        traceability_pending = traceability_missing_lines > 0

        active_remittance = (
            Remittance.select()
            .where(
                (Remittance.source_order == order)
                & (Remittance.status != Remittance.STATUS_ANNULLED)
            )
            .exists()
        )

        if order.status == LoadOrder.STATUS_ISSUED:
            pending_stage = self.STAGE_CLOSURE
            pending_reason = "La orden fue emitida y todavía no fue cerrada."
        elif not products or (pallet_count == 0 and not loose_allocations):
            pending_stage = self.STAGE_PREPARATION
            pending_reason = "La orden todavía no tiene preparación de mercadería."
        elif pending_quantity > 0:
            pending_stage = self.STAGE_INCOMPLETE
            pending_reason = f"Faltan asignar {pending_quantity.normalize()} unidades a pallets o mercadería suelta."
        elif traceability_pending:
            pending_stage = self.STAGE_TRACEABILITY
            pending_reason = f"Hay {traceability_missing_lines} línea(s) sin lote o fecha de elaboración."
        elif not active_remittance:
            pending_stage = self.STAGE_DOCUMENTAL
            pending_reason = "La preparación está completa pero no hay remito activo asociado."
        else:
            pending_stage = self.STAGE_READY
            pending_reason = "La preparación y el respaldo documental están completos."

        destinations = []
        for destination in order.destinations:
            client_name = destination.client.name if destination.client_id else ""
            address = destination.delivery_address
            label = client_name
            if address is not None:
                location = " - ".join(part for part in (address.city, address.address) if part)
                label = f"{label} · {location}" if location else label
            if label and label not in destinations:
                destinations.append(label)

        age_days = max(0, (today - order.date).days)
        return {
            "order_id": order.id,
            "order_number": order.order_number,
            "date": order.date,
            "age_days": age_days,
            "client_name": order.client.name if order.client_id else (destinations[0] if destinations else ""),
            "destinations": " | ".join(destinations),
            "status": order.status,
            "current_stage": "Emitida" if order.status == LoadOrder.STATUS_ISSUED else "Preparación",
            "pending_stage": pending_stage,
            "pending_reason": pending_reason,
            "requested_quantity": requested,
            "assigned_quantity": assigned,
            "pending_quantity": pending_quantity,
            "pallets_expected": pallet_count if pallet_count else (1 if requested > 0 else 0),
            "pallets_complete": complete_pallets,
            "traceability_pending": traceability_pending,
            "traceability_missing_lines": traceability_missing_lines,
            "remittance_pending": not active_remittance,
            "closure_pending": order.status == LoadOrder.STATUS_ISSUED,
            "carrier_name": order.carrier.name if order.carrier_id else "",
            "driver_name": order.driver.name if order.driver_id else "",
            "truck_domain": order.truck.domain if order.truck_id else "",
            "observations": order.observations or "",
        }
