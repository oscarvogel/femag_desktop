"""Lectura de ordenes proyectadas desde fabrica (#805).

La nube no crea ordenes: muestra la copia que publica el agente de sync. El
modelo es de solo lectura; la edicion de lote/fecha se implementa despues con
eventos cloud -> fabrica.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.models.sync import SyncProjection
from app.services.sync_snapshot_service import SyncSnapshotService
from webapp.order_service import OrderUnavailableError


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
    destination = payload.get("destination") or {}
    truck_domain = (
        payload.get("truck_domain")
        or payload.get("truck")
        or ""
    )
    return ProjectedOrder(
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
