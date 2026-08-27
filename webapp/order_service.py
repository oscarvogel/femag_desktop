from __future__ import annotations

from datetime import date

from peewee import DoesNotExist

from app.models.load_orders import LoadOrder, LoadOrderProduct

QR_PREFIX = "FEMAG:LOAD_ORDER:"


class OrderNotFoundError(LookupError):
    pass


class InvalidQrPayloadError(ValueError):
    pass


def normalize_qr_token(value: str) -> str:
    raw = (value or "").strip()
    if raw.startswith(QR_PREFIX):
        raw = raw[len(QR_PREFIX) :].strip()
    if not raw:
        raise InvalidQrPayloadError("El QR no contiene un identificador de orden válido.")
    if len(raw) > 64:
        raise InvalidQrPayloadError("El identificador de la orden no es válido.")
    return raw


def get_order_by_token(value: str) -> LoadOrder:
    token = normalize_qr_token(value)
    try:
        return LoadOrder.get(LoadOrder.qr_token == token)
    except DoesNotExist as exc:
        raise OrderNotFoundError("No se encontró una orden para este QR.") from exc


def order_lines(order: LoadOrder) -> list[LoadOrderProduct]:
    return list(
        LoadOrderProduct.select()
        .where(LoadOrderProduct.order == order)
        .order_by(LoadOrderProduct.id)
    )


def parse_optional_date(value: str | None) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("La fecha de elaboración debe tener formato AAAA-MM-DD.") from exc


def update_order_line(
    order: LoadOrder,
    line_id: int,
    *,
    lote: str | None,
    fecha_elaboracion: str | None,
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
    line.save(only=[LoadOrderProduct.lote, LoadOrderProduct.fecha_elaboracion])
    return line
