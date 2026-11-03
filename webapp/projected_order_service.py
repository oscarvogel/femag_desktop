"""Ordenes proyectadas desde fabrica (#364/#805).

La nube muestra la orden por pallet y contenido. Cada contenido (pallet o
mercaderia suelta) tiene su propio lote/fecha y se encola para que el agente lo
aplique en la fabrica.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date, datetime

from app.models.sync import SyncOutbox, SyncProjection, utc_now_naive
from app.services.sync_service import SyncService
from app.services.sync_snapshot_service import SyncSnapshotService
from webapp.load_groups import (
    LOOSE_SLOT,
    LoadContent,
    LoadLine,
    build_groups,
    fallback_key,
    unique_slots,
)
from webapp.order_service import OrderUnavailableError, parse_optional_date

LINE_EVENT = "order_lote_fecha_updated"
CONTENT_EVENT = "order_content_lote_fecha_updated"
CONTENT_PALLET = "pallet_content"
CONTENT_LOOSE = "loose_content"


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
    fecha_envasado: date | None


@dataclass(frozen=True)
class ProjectedContent:
    id: str
    kind: str
    product: ProjectedProduct
    quantity: float
    unit: str
    lote: str | None
    fecha_elaboracion: date | None
    fecha_envasado: date | None
    client_name: str
    destination: str
    # Linea de despacho a la que pertenece el contenido (#873). La fabrica la
    # publica para que la nube pueda agrupar la carga por linea. Si no viene
    # (fabrica sin actualizar) la nube agrupa por producto, cliente y destino.
    line_uid: str | None = None


@dataclass(frozen=True)
class ProjectedPallet:
    sequence: int
    contents: tuple[ProjectedContent, ...]


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
    pallets: tuple[ProjectedPallet, ...] = ()
    loose_contents: tuple[ProjectedContent, ...] = ()
    has_contents: bool = False

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


def _content_from_dict(
    item: dict,
    *,
    kind: str,
    fallback_client: str,
    fallback_destination: str,
) -> ProjectedContent | None:
    content_id = str(item.get("content_uid") or "").strip()
    if not content_id:
        return None
    return ProjectedContent(
        id=content_id,
        kind=kind,
        product=ProjectedProduct(name=str(item.get("product_name") or "-")),
        quantity=float(item.get("quantity") or 0),
        unit=str(item.get("unit") or ""),
        lote=item.get("lote"),
        fecha_elaboracion=_parse_date(item.get("fecha_elaboracion")),
        fecha_envasado=_parse_date(item.get("fecha_envasado")),
        client_name=str(item.get("client_name") or fallback_client or "-"),
        destination=str(item.get("destination") or fallback_destination or "-"),
        line_uid=(str(item.get("line_uid")).strip() or None)
        if item.get("line_uid")
        else None,
    )


def _fallback_destination(payload: dict) -> str:
    destination = payload.get("destination") or {}
    return " - ".join(
        part
        for part in (
            str(destination.get("address") or "").strip(),
            str(destination.get("city") or "").strip(),
        )
        if part
    ) or "-"


def _parse_pallets(payload: dict, fallback_client: str, fallback_destination: str):
    pallets = []
    for item in payload.get("pallets") or []:
        if not isinstance(item, dict):
            continue
        contents = tuple(
            content
            for raw in (item.get("contents") or [])
            if isinstance(raw, dict)
            for content in (
                _content_from_dict(
                    raw,
                    kind=CONTENT_PALLET,
                    fallback_client=fallback_client,
                    fallback_destination=fallback_destination,
                ),
            )
            if content is not None
        )
        if not contents:
            continue
        pallets.append(
            ProjectedPallet(
                sequence=int(item.get("sequence") or 0),
                contents=contents,
            )
        )
    return tuple(pallets)


def _parse_loose_contents(payload: dict, fallback_client: str, fallback_destination: str):
    return tuple(
        content
        for raw in (payload.get("loose_contents") or [])
        if isinstance(raw, dict)
        for content in (
            _content_from_dict(
                raw,
                kind=CONTENT_LOOSE,
                fallback_client=fallback_client,
                fallback_destination=fallback_destination,
            ),
        )
        if content is not None
    )


def _pending_ids(order: ProjectedOrder) -> list[str]:
    ids = [line.id for line in projected_order_lines(order) if line.id]
    ids.extend(
        content.id
        for pallet in order.pallets
        for content in pallet.contents
    )
    ids.extend(content.id for content in order.loose_contents)
    return ids


def projected_order_has_pending_sync(order: ProjectedOrder) -> bool:
    ids = _pending_ids(order)
    if not ids:
        return False
    return (
        SyncOutbox.select()
        .where(
            (SyncOutbox.status == SyncOutbox.STATUS_PENDING)
            & (SyncOutbox.aggregate_id.in_(ids))
            & (
                SyncOutbox.event_type.in_([LINE_EVENT, CONTENT_EVENT])
            )
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
    client_name = str(client.get("name") or "-")
    destination_label = _fallback_destination(payload)
    truck_domain = payload.get("truck_domain") or payload.get("truck") or ""
    pallets = _parse_pallets(payload, client_name, destination_label)
    loose_contents = _parse_loose_contents(
        payload, client_name, destination_label
    )
    order = ProjectedOrder(
        order_uid=projection.resource_uid,
        order_number=int(projection.order_number or 0),
        qr_token=projection.qr_token or "",
        status=projection.status or "",
        version=int(projection.version or 1),
        date=_parse_date(payload.get("order_date")),
        client=ProjectedClient(name=client_name),
        truck=ProjectedTruck(domain=str(truck_domain or "-")),
        payload=payload,
        pallets=pallets,
        loose_contents=loose_contents,
        has_contents=bool(pallets or loose_contents),
    )
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
        pallets=order.pallets,
        loose_contents=order.loose_contents,
        has_contents=order.has_contents,
        pending_sync=projected_order_has_pending_sync(order),
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
                fecha_envasado=_parse_date(item.get("fecha_envasado")),
            )
        )
    return lines


def projected_line_context(order: ProjectedOrder, lines: list[ProjectedLine]) -> dict:
    payload = order.payload or {}
    client = payload.get("client") or {}
    context = {
        "client": str(client.get("name") or "-"),
        "delivery": _fallback_destination(payload),
        "pallets": [
            int(item.get("sequence"))
            for item in (payload.get("pallets") or [])
            if isinstance(item, dict) and item.get("sequence") is not None
        ],
        "is_loose": False,
    }
    return {line.id: dict(context) for line in lines}


def projected_load_lines(order: ProjectedOrder) -> list[LoadLine]:
    """Agrupa la carga de una orden proyectada por linea de despacho (#873).

    La ficha pide una linea (producto + cliente + destino) y no un pallet. Los
    contenidos se agrupan por el ``line_uid`` que publica la fabrica y, si no
    viene, por producto + cliente + destino.
    """

    buckets: dict[str, dict] = {}

    def bucket_for(
        line_uid: str | None, product: str, client: str, destination: str
    ) -> dict:
        key = f"p{line_uid}" if line_uid else fallback_key(product, client, destination)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "key": key,
                "line_uid": line_uid,
                "product": product,
                "client": client,
                "destination": destination,
                "contents": [],
            }
            buckets[key] = bucket
        return bucket

    def add_content(bucket: dict, content: ProjectedContent, slot: str, label: str) -> None:
        bucket["contents"].append(
            LoadContent(
                id=content.id,
                kind=content.kind,
                slot=slot,
                slot_label=label,
                pallet_sequence=None if slot == LOOSE_SLOT else int(slot),
                product=content.product.name,
                quantity=float(content.quantity or 0),
                unit=content.unit or "",
                lote=content.lote,
                fecha_elaboracion=content.fecha_elaboracion,
                fecha_envasado=content.fecha_envasado,
            )
        )

    for pallet in order.pallets:
        for content in pallet.contents:
            bucket = bucket_for(
                content.line_uid,
                content.product.name,
                content.client_name,
                content.destination,
            )
            add_content(bucket, content, str(pallet.sequence), f"P{pallet.sequence}")

    for content in order.loose_contents:
        bucket = bucket_for(
            content.line_uid,
            content.product.name,
            content.client_name,
            content.destination,
        )
        add_content(bucket, content, LOOSE_SLOT, "SUELTO")

    # Lineas publicadas que todavia no tienen ningun contenido asignado: se
    # muestran igual para poder completarles el lote a nivel de linea.
    published_lines = {line.id: line for line in projected_order_lines(order)}
    for line in projected_order_lines(order):
        if not line.id:
            continue
        key = f"p{line.id}"
        if key in buckets:
            continue
        payload = order.payload or {}
        client = str((payload.get("client") or {}).get("name") or "-")
        buckets[key] = {
            "key": key,
            "line_uid": line.id,
            "product": line.product.name,
            "client": client,
            "destination": _fallback_destination(payload),
            "contents": [],
            "quantity": float(line.quantity or 0),
            "unit": line.unit or "",
            "line_values": (
                (line.lote or "").strip(),
                line.fecha_elaboracion.isoformat()
                if line.fecha_elaboracion
                else "",
                line.fecha_envasado.isoformat() if line.fecha_envasado else "",
            ),
        }

    result: list[LoadLine] = []
    for bucket in buckets.values():
        contents = unique_slots(tuple(bucket["contents"]))
        quantity = bucket.get("quantity")
        if quantity is None:
            quantity = sum(content.quantity for content in contents)
        unit = bucket.get("unit") or (contents[0].unit if contents else "")
        line_values = bucket.get("line_values")
        if line_values is None:
            published = published_lines.get(bucket["line_uid"] or "")
            line_values = (
                (published.lote or "").strip() if published is not None else "",
                published.fecha_elaboracion.isoformat()
                if published is not None and published.fecha_elaboracion
                else "",
                published.fecha_envasado.isoformat()
                if published is not None and published.fecha_envasado
                else "",
            )
        result.append(
            LoadLine(
                key=bucket["key"],
                product=bucket["product"],
                client=bucket["client"],
                destination=bucket["destination"],
                quantity=float(quantity or 0),
                unit=unit,
                contents=contents,
                groups=build_groups(contents, line_values),
                line_uid=bucket["line_uid"],
            )
        )
    return result


def _update_content_in_payload(
    payload: dict,
    content_id: str,
    *,
    kind: str,
    lote: str | None,
    fecha_elaboracion: date | None,
    fecha_envasado: date | None,
) -> bool:
    collections = (
        [payload.get("pallets") or []]
        if kind == CONTENT_PALLET
        else [payload.get("loose_contents") or []]
    )
    for collection in collections:
        for group in collection:
            if kind == CONTENT_PALLET:
                candidates = group.get("contents") or [] if isinstance(group, dict) else []
            else:
                candidates = [group]
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                if str(item.get("content_uid") or "") != content_id:
                    continue
                item["lote"] = lote
                item["fecha_elaboracion"] = (
                    fecha_elaboracion.isoformat() if fecha_elaboracion else None
                )
                item["fecha_envasado"] = (
                    fecha_envasado.isoformat() if fecha_envasado else None
                )
                return True
    return False


def _upsert_content_event(
    order: ProjectedOrder,
    content_id: str,
    *,
    content_type: str,
    lote: str | None,
    fecha_elaboracion: date | None,
    fecha_envasado: date | None,
) -> None:
    payload = {
        "order_uid": order.order_uid,
        "content_uid": content_id,
        "content_type": "pallet" if content_type == CONTENT_PALLET else "loose",
        "lote": lote,
        "fecha_elaboracion": (
            fecha_elaboracion.isoformat() if fecha_elaboracion else None
        ),
        "fecha_envasado": (
            fecha_envasado.isoformat() if fecha_envasado else None
        ),
        "expected_version": order.version,
    }
    existing = SyncOutbox.get_or_none(
        (SyncOutbox.event_type == CONTENT_EVENT)
        & (SyncOutbox.aggregate_type == content_type)
        & (SyncOutbox.aggregate_id == content_id)
        & (SyncOutbox.status == SyncOutbox.STATUS_PENDING)
    )
    if existing is not None:
        existing.payload = payload
        existing.aggregate_version = order.version
        existing.occurred_at = utc_now_naive()
        existing.save(
            only=[
                SyncOutbox.payload,
                SyncOutbox.aggregate_version,
                SyncOutbox.occurred_at,
            ]
        )
        return
    SyncService.enqueue_event(
        event_type=CONTENT_EVENT,
        aggregate_type=content_type,
        aggregate_id=content_id,
        payload=payload,
        aggregate_version=order.version,
        idempotency_key=f"content:{order.order_uid}:{content_id}:{order.version}",
    )


def update_projected_content(
    order: ProjectedOrder,
    content_id: str,
    *,
    content_type: str,
    lote: str | None,
    fecha_elaboracion: str | None,
    fecha_envasado: str | None = None,
) -> bool:
    projection = SyncProjection.get_or_none(
        (SyncProjection.resource_type == SyncProjection.RESOURCE_ORDER)
        & (SyncProjection.resource_uid == order.order_uid)
    )
    if projection is None:
        raise OrderUnavailableError("La orden proyectada ya no existe.")

    payload = deepcopy(projection.payload or {})
    normalized_lote = (lote or "").strip() or None
    if normalized_lote and len(normalized_lote) > 255:
        raise ValueError("El lote no puede superar los 255 caracteres.")
    new_date = parse_optional_date(fecha_elaboracion)
    new_packaging_date = parse_optional_date(fecha_envasado)

    content = next(
        (
            item
            for pallet in order.pallets
            for item in pallet.contents
            if item.id == content_id
        ),
        None,
    ) if content_type == CONTENT_PALLET else next(
        (item for item in order.loose_contents if item.id == content_id),
        None,
    )
    if content is None:
        raise ValueError("El contenido indicado no pertenece a esta orden.")
    if (
        content.lote == normalized_lote
        and content.fecha_elaboracion == new_date
        and content.fecha_envasado == new_packaging_date
    ):
        return False

    if not _update_content_in_payload(
        payload,
        content_id,
        kind=content_type,
        lote=normalized_lote,
        fecha_elaboracion=new_date,
        fecha_envasado=new_packaging_date,
    ):
        raise ValueError("El contenido indicado no pertenece a esta orden.")

    projection.payload = payload
    projection.save(only=[SyncProjection.payload])
    _upsert_content_event(
        order,
        content_id,
        content_type=content_type,
        lote=normalized_lote,
        fecha_elaboracion=new_date,
        fecha_envasado=new_packaging_date,
    )
    return True


def update_projected_line(
    order: ProjectedOrder,
    line_id: str,
    *,
    lote: str | None,
    fecha_elaboracion: str | None,
    fecha_envasado: str | None = None,
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
    new_packaging_date = parse_optional_date(fecha_envasado)
    old_date = _parse_date(target.get("fecha_elaboracion"))
    old_packaging_date = _parse_date(target.get("fecha_envasado"))
    if (
        target.get("lote") == normalized_lote
        and old_date == new_date
        and old_packaging_date == new_packaging_date
    ):
        return False

    target["lote"] = normalized_lote
    target["fecha_elaboracion"] = new_date.isoformat() if new_date else None
    target["fecha_envasado"] = (
        new_packaging_date.isoformat() if new_packaging_date else None
    )
    projection.payload = payload
    projection.save(only=[SyncProjection.payload])

    event_payload = {
        "order_uid": order.order_uid,
        "line_uid": line_id,
        "lote": normalized_lote,
        "fecha_elaboracion": new_date.isoformat() if new_date else None,
        "fecha_envasado": (
            new_packaging_date.isoformat() if new_packaging_date else None
        ),
        "expected_version": order.version,
    }
    existing = SyncOutbox.get_or_none(
        (SyncOutbox.event_type == LINE_EVENT)
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
            event_type=LINE_EVENT,
            aggregate_type="order_line",
            aggregate_id=line_id,
            payload=event_payload,
            aggregate_version=order.version,
            idempotency_key=f"lote:{order.order_uid}:{line_id}:{order.version}",
        )
    return True
