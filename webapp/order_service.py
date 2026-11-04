from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlparse

from peewee import DoesNotExist

from app.models.load_orders import (
    LoadOrder,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from webapp.load_groups import (
    LOOSE_SLOT,
    LoadContent,
    LoadGroup,
    LoadLine,
    build_groups,
    unique_slots,
)

QR_PREFIX = "FEMAG:LOAD_ORDER:"
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class OrderNotFoundError(LookupError):
    pass


class InvalidQrPayloadError(ValueError):
    pass


class OrderUnavailableError(LookupError):
    pass


def _token_from_url(raw: str) -> str | None:
    """Extrae el token de una URL ``/orden/<token>``, absoluta o relativa."""
    parsed = urlparse(raw)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) == 2 and parts[0] == "orden":
        return parts[1]
    return None


def normalize_qr_token(value: str) -> str:
    raw = (value or "").strip()
    if raw.startswith(QR_PREFIX):
        raw = raw[len(QR_PREFIX) :].strip()
    elif "://" in raw or raw.startswith("/orden/"):
        raw = _token_from_url(raw) or ""
    if not raw:
        raise InvalidQrPayloadError("El QR no contiene un identificador de orden válido.")
    if not TOKEN_PATTERN.fullmatch(raw):
        raise InvalidQrPayloadError("El identificador de la orden no es válido.")
    return raw


def get_order_by_token(value: str) -> LoadOrder:
    token = normalize_qr_token(value)
    try:
        order = LoadOrder.get(LoadOrder.qr_token == token)
    except DoesNotExist as exc:
        raise OrderNotFoundError("No se encontró una orden para este QR.") from exc
    if order.status == LoadOrder.STATUS_ANNULLED:
        raise OrderUnavailableError(
            f"La orden #{order.order_number} está anulada y no puede operarse desde el QR."
        )
    return order


def order_lines(order: LoadOrder) -> list[LoadOrderProduct]:
    return list(
        LoadOrderProduct.select()
        .where(LoadOrderProduct.order == order)
        .order_by(LoadOrderProduct.id)
    )


def _delivery_label(address) -> str:
    if address is None:
        return "-"
    parts = [address.address, address.city, address.province]
    return " · ".join(part for part in parts if part) or "-"


def order_line_context(order: LoadOrder, lines: list[LoadOrderProduct]) -> dict[int, dict[str, object]]:
    """Build operator-facing client/destination/pallet context for each order line."""
    contexts: dict[int, dict[str, object]] = {}

    pallet_allocations = list(
        LoadOrderPalletAllocation.select(LoadOrderPalletAllocation, LoadOrderPallet)
        .join(LoadOrderPallet)
        .where(LoadOrderPallet.order == order)
        .order_by(LoadOrderPallet.sequence)
    )
    loose_allocations = list(
        LoadOrderLooseAllocation.select().where(LoadOrderLooseAllocation.order == order)
    )

    for line in lines:
        destination = line.destination
        client = destination.client if destination is not None else order.client
        delivery_address = (
            destination.delivery_address if destination is not None else order.delivery_address
        )

        pallets: list[int] = []
        if destination is not None:
            pallets = [
                allocation.pallet.sequence
                for allocation in pallet_allocations
                if allocation.destination_id == destination.id
                and allocation.product_id == line.product_id
            ]
            is_loose = any(
                allocation.destination_id == destination.id
                and allocation.product_id == line.product_id
                for allocation in loose_allocations
            )
        else:
            is_loose = False

        contexts[line.id] = {
            "client": client.name if client is not None else "-",
            "delivery": _delivery_label(delivery_address),
            "pallets": pallets,
            "is_loose": is_loose,
        }

    return contexts


def parse_optional_date(value: str | None) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("La fecha de elaboración debe tener formato AAAA-MM-DD.") from exc


def _line_lookup(
    lines: list[LoadOrderProduct],
) -> tuple[dict[tuple[int, int], LoadOrderProduct], dict[int, LoadOrderProduct]]:
    """Indexa las lineas por destino y producto, y por producto sin destino.

    Es la misma regla que usa la fabrica para saber a que linea pertenece un
    contenido de pallet: primero la linea del mismo destino y producto y, si no
    hay, la linea del mismo producto sin destino.
    """

    by_key: dict[tuple[int, int], LoadOrderProduct] = {}
    by_product: dict[int, LoadOrderProduct] = {}
    for line in lines:
        if line.destination_id is None:
            by_product.setdefault(line.product_id, line)
        else:
            by_key.setdefault((line.destination_id, line.product_id), line)
    return by_key, by_product


def build_load_lines(order: LoadOrder) -> list[LoadLine]:
    """Arma las lineas de despacho a cargar de una orden local (#873).

    La carga no se pide pallet por pallet: cada linea agrupa los pallets que
    llevan su producto y cada grupo de la linea comparte lote y fecha.
    """

    lines = order_lines(order)
    contexts = order_line_context(order, lines)
    by_key, by_product = _line_lookup(lines)

    pallets = list(
        LoadOrderPallet.select()
        .where(LoadOrderPallet.order == order)
        .order_by(LoadOrderPallet.sequence)
    )
    sequences = {pallet.id: pallet.sequence for pallet in pallets}
    allocations = (
        LoadOrderPalletAllocation.select(LoadOrderPalletAllocation, LoadOrderPallet)
        .join(LoadOrderPallet)
        .where(LoadOrderPallet.order == order)
        .order_by(LoadOrderPallet.sequence, LoadOrderPalletAllocation.id)
    )
    loose_allocations = list(
        LoadOrderLooseAllocation.select()
        .where(LoadOrderLooseAllocation.order == order)
        .order_by(LoadOrderLooseAllocation.id)
    )

    contents_by_line: dict[int, list[LoadContent]] = {}
    for allocation in allocations:
        line = by_key.get((allocation.destination_id, allocation.product_id)) or (
            by_product.get(allocation.product_id)
        )
        if line is None:
            continue
        sequence = sequences.get(allocation.pallet_id)
        contents_by_line.setdefault(line.id, []).append(
            LoadContent(
                id=str(allocation.id),
                kind="pallet",
                slot=str(sequence) if sequence is not None else str(allocation.id),
                slot_label=f"P{sequence}" if sequence is not None else f"#{allocation.id}",
                pallet_sequence=sequence,
                product=allocation.product.name,
                quantity=float(allocation.quantity or 0),
                unit=allocation.product.unit or "",
                lote=allocation.lote,
                fecha_elaboracion=allocation.fecha_elaboracion,
                fecha_envasado=allocation.fecha_envasado,
            )
        )
    for allocation in loose_allocations:
        line = by_key.get((allocation.destination_id, allocation.product_id)) or (
            by_product.get(allocation.product_id)
        )
        if line is None:
            continue
        contents_by_line.setdefault(line.id, []).append(
            LoadContent(
                id=str(allocation.id),
                kind="loose",
                slot=LOOSE_SLOT,
                slot_label="SUELTO",
                pallet_sequence=None,
                product=allocation.product.name,
                quantity=float(allocation.quantity or 0),
                unit=allocation.product.unit or "",
                lote=allocation.lote,
                fecha_elaboracion=allocation.fecha_elaboracion,
                fecha_envasado=allocation.fecha_envasado,
            )
        )

    result: list[LoadLine] = []
    for line in lines:
        contents = unique_slots(tuple(contents_by_line.get(line.id, [])))
        context = contexts.get(line.id, {})
        result.append(
            LoadLine(
                key=f"n{line.id}",
                product=line.product.name,
                client=str(context.get("client") or "-"),
                destination=str(context.get("delivery") or "-"),
                quantity=float(line.quantity or 0),
                unit=line.unit or line.product.unit or "",
                contents=contents,
                groups=build_groups(
                    contents,
                    (
                        (line.lote or "").strip(),
                        line.fecha_elaboracion.isoformat()
                        if line.fecha_elaboracion
                        else "",
                        line.fecha_envasado.isoformat()
                        if line.fecha_envasado
                        else "",
                    ),
                ),
                line_id=line.id,
            )
        )
    return result


def update_order_content(
    order: LoadOrder,
    content_id: int,
    *,
    kind: str,
    lote: str | None,
    fecha_elaboracion: str | None,
    fecha_envasado: str | None = None,
) -> bool:
    """Guarda el lote y las fechas de un contenido de pallet o mercaderia suelta."""

    normalized_lote = (lote or "").strip() or None
    if normalized_lote and len(normalized_lote) > 255:
        raise ValueError("El lote no puede superar los 255 caracteres.")
    new_date = parse_optional_date(fecha_elaboracion)
    new_packaging_date = parse_optional_date(fecha_envasado)

    if kind == "loose":
        model = LoadOrderLooseAllocation
        allocation = model.get_or_none(
            (model.id == content_id) & (model.order == order)
        )
    else:
        model = LoadOrderPalletAllocation
        allocation = (
            LoadOrderPalletAllocation.select(
                LoadOrderPalletAllocation, LoadOrderPallet
            )
            .join(LoadOrderPallet)
            .where(
                (LoadOrderPalletAllocation.id == content_id)
                & (LoadOrderPallet.order == order)
            )
            .first()
        )
    if allocation is None:
        raise OrderNotFoundError("El contenido indicado no pertenece a esta orden.")

    if (
        allocation.lote == normalized_lote
        and allocation.fecha_elaboracion == new_date
        and allocation.fecha_envasado == new_packaging_date
    ):
        return False

    allocation.lote = normalized_lote
    allocation.fecha_elaboracion = new_date
    allocation.fecha_envasado = new_packaging_date
    allocation.save(
        only=[
            model.lote,
            model.fecha_elaboracion,
            model.fecha_envasado,
        ]
    )
    return True


def update_order_line(
    order: LoadOrder,
    line_id: int,
    *,
    lote: str | None,
    fecha_elaboracion: str | None,
    fecha_envasado: str | None = None,
) -> LoadOrderProduct:
    try:
        line = LoadOrderProduct.get(
            (LoadOrderProduct.id == line_id) & (LoadOrderProduct.order == order)
        )
    except DoesNotExist as exc:
        raise OrderNotFoundError("La línea indicada no pertenece a esta orden.") from exc

    normalized_lote = (lote or "").strip() or None
    if normalized_lote and len(normalized_lote) > 255:
        raise ValueError("El lote no puede superar los 255 caracteres.")

    line.lote = normalized_lote
    line.fecha_elaboracion = parse_optional_date(fecha_elaboracion)
    line.fecha_envasado = parse_optional_date(fecha_envasado)
    line.save(
        only=[
            LoadOrderProduct.lote,
            LoadOrderProduct.fecha_elaboracion,
            LoadOrderProduct.fecha_envasado,
        ]
    )
    return line
