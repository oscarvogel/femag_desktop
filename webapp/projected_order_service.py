"""Ordenes proyectadas desde fabrica (#805).

La nube no crea ordenes: muestra la copia que publica el agente y encola los
cambios de lote/fecha para que el agente los aplique en la fabrica.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime

from app.models.sync import SyncOutbox, SyncProjection, utc_now_naive
from app.services.sync_service import SyncService
from app.services.sync_snapshot_service import SyncSnapshotService
from webapp.order_service import OrderUnavailableError, parse_optional_date

LOTE_EVENT = "order_lote_fecha_updated"


@dataclass(frozen=True)
class ProjectedProduct:
    name: str


@dataclass(frozen=True)
class ProjectedLine:
    id: str
    product: ProjectedProduct
    quantity: float
    unit: str
    lote: str | None
    fecha_elaboracion: date | None


@dataclass(frozen=True)
class ProjectedClient:
    name: str


@dataclass(frozen=True)
class ProjectedTruck:
    domain: str


@dataclass(frozen=True)
class ProjectedOrder:
    order_uid: str
    order_number: int
    qr_token: str
    status: str
    version: int
    date: date | None
    client: ProjectedClient
    truck: ProjectedTruck
    payload: dict = field(repr=False)
    pending_sync: bool = False
    is_projected: bool = True

    def ensure_qr_token(self) -> str:
        return self.qr_token


def _parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def projected_order_has_pending_sync(lines: list[ProjectedLine]) -> bool:
    line_ids = [line.id for line in lines if line.id]
    if not line_ids:
        return False
    return (
        SyncOutbox.select()
        .where(
            (SyncOutbox.event_type == LOTE_EVENT)
            & (SyncOutbox.aggregate_type == "order_line")
            & (SyncOutbox.status == SyncOutbox.STATUS_PENDING)
            & (SyncOutbox.aggregate_id.in_(line_ids))
        )
        .exists()
    )


def get_projected_order_by_token(token: str) -> ProjectedOrder | None:
    projection = SyncSnapshotService.get_order_by_token(token)
    if projection is None:
        return None
    if (projection.status or "").strip().lower() == "anulada":
        raise OrderUnavailableError(
            f"La orden #{projection.order_number} esta anulada y no puede operarse."
        )
    payload = projection.payload or {}
    client = payload.get("client") or {}
    truck_domain = (
        payload.get("truck_domain")
        or payload.get("truck")
        or ""
    )
    order = ProjectedOrder(
        order_uid=projection.resource_uid,
        order_number=int(projection.order_number or 0),
        qr_token=projection.qr_token or "",
        status=projection.status or "",
        version=int(projection.version or 1),
        date=_parse_date(payload.get("order_date")),
        client=ProjectedClient(name=str(client.get("name") or "-")),
        truck=ProjectedTruck(domain=str(truck_domain or "-")),
        payload=payload,
    )
    lines = projected_order_lines(order)
    return ProjectedOrder(
        order_uid=order.order_uid,
        order_number=order.order_number,
        qr_token=order.qr_token,
        status=order.status,
        version=order.version,
        date=order.date,
        client=order.client,
        truck=order.truck,
        payload=order.payload,
        pending_sync=projected_order_has_pending_sync(lines),
    )


def projected_order_lines(order: ProjectedOrder) -> list[ProjectedLine]:
    lines = []
    for item in order.payload.get("lines") or []:
        if not isinstance(item, dict):
            continue
        lines.append(
            ProjectedLine(
                id=str(item.get("line_uid") or ""),
                product=ProjectedProduct(name=str(item.get("product_name") or "-")),
                quantity=float(item.get("quantity") or 0),
                unit=str(item.get("unit") or ""),
                lote=item.get("lote"),
                fecha_elaboracion=_parse_date(item.get("fecha_elaboracion")),
            )
        )
    return lines


def projected_line_context(order: ProjectedOrder, lines: list[ProjectedLine]) -> dict:
    payload = order.payload or {}
    client = payload.get("client") or {}
    destination = payload.get("destination") or {}
    delivery = " - ".join(
        part
        for part in (
            str(destination.get("address") or "").strip(),
            str(destination.get("city") or "").strip(),
        )
        if part
    ) or "-"
    pallets = [
        int(item.get("sequence"))
        for item in (payload.get("pallets") or [])
        if isinstance(item, dict) and item.get("sequence") is not None
    ]
    context = {
        "client": str(client.get("name") or "-"),
        "delivery": delivery,
        "pallets": pallets,
        "is_loose": False,
    }
    return {line.id: dict(context) for line in lines}


def update_projected_line(
    order: ProjectedOrder,
    line_id: str,
    *,
    lote: str | None,
    fecha_elaboracion: str | None,
) -> bool:
    projection = SyncProjection.get_or_none(
        (SyncProjection.resource_type == SyncProjection.RESOURCE_ORDER)
        & (SyncProjection.resource_uid == order.order_uid)
    )
    if projection is None:
        raise OrderUnavailableError("La orden proyectada ya no existe.")

    payload = deepcopy(projection.payload or {})
    target = None
    for item in payload.get("lines") or []:
        if isinstance(item, dict) and str(item.get("line_uid") or "") == line_id:
            target = item
            break
    if target is None:
        raise ValueError("La linea indicada no pertenece a esta orden.")

    normalized_lote = (lote or "").strip() or None
    if normalized_lote and len(normalized_lote) > 255:
        raise ValueError("El lote no puede superar los 255 caracteres.")
    new_date = parse_optional_date(fecha_elaboracion)
    old_date = _parse_date(target.get("fecha_elaboracion"))
    if target.get("lote") == normalized_lote and old_date == new_date:
        return False

    target["lote"] = normalized_lote
    target["fecha_elaboracion"] = new_date.isoformat() if new_date else None
    projection.payload = payload
    projection.save(only=[SyncProjection.payload])

    event_payload = {
        "order_uid": order.order_uid,
        "line_uid": line_id,
        "lote": normalized_lote,
        "fecha_elaboracion": new_date.isoformat() if new_date else None,
        "expected_version": order.version,
    }
    existing = SyncOutbox.get_or_none(
        (SyncOutbox.event_type == LOTE_EVENT)
        & (SyncOutbox.aggregate_type == "order_line")
        & (SyncOutbox.aggregate_id == line_id)
        & (SyncOutbox.status == SyncOutbox.STATUS_PENDING)
    )
    if existing is not None:
        existing.payload = event_payload
        existing.aggregate_version = order.version
        existing.occurred_at = utc_now_naive()
        existing.save(
            only=[
                SyncOutbox.payload,
                SyncOutbox.aggregate_version,
                SyncOutbox.occurred_at,
            ]
        )
    else:
        SyncService.enqueue_event(
            event_type=LOTE_EVENT,
            aggregate_type="order_line",
            aggregate_id=line_id,
            payload=event_payload,
            aggregate_version=order.version,
            idempotency_key=f"lote:{order.order_uid}:{line_id}:{order.version}",
        )
    return True
