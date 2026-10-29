"""Publicacion de ordenes de fabrica hacia FEMAG Web (#804).

Construye snapshots a partir de los modelos locales. No modifica ordenes ni
dispara movimientos: solo lee y publica.
"""

from __future__ import annotations

from datetime import datetime, timezone
from time import time
from uuid import uuid4

from app.models.load_orders import LoadOrder, LoadOrderPallet, LoadOrderProduct
from app.models.sync import SyncCursor, SyncEntityMap
from app.services.sync_service import SyncService

PUBLISHABLE_STATUSES = (
    LoadOrder.STATUS_PENDING,
    LoadOrder.STATUS_ISSUED,
    LoadOrder.STATUS_CLOSED,
    LoadOrder.STATUS_ANNULLED,
)


class SyncPublishError(ValueError):
    pass


def _as_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value) -> str | None:
    parsed = _as_datetime(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SyncOrderPublisher:
    def __init__(self, *, limit: int | None = None):
        self.limit = limit

    def orders(self) -> list[LoadOrder]:
        query = (
            LoadOrder.select()
            .where(LoadOrder.status.in_(PUBLISHABLE_STATUSES))
            .order_by(LoadOrder.id)
        )
        if self.limit:
            query = query.limit(self.limit)
        return list(query)

    @staticmethod
    def _client_for_order(order: LoadOrder):
        if order.client is not None:
            return order.client
        for destination in order.destinations:
            if destination.client is not None:
                return destination.client
        raise SyncPublishError(f"La orden #{order.order_number} no tiene cliente.")

    @staticmethod
    def _destination_for_order(order: LoadOrder):
        if order.delivery_address is not None:
            return order.delivery_address
        for destination in order.destinations:
            if destination.delivery_address is not None:
                return destination.delivery_address
        raise SyncPublishError(
            f"La orden #{order.order_number} no tiene domicilio de entrega."
        )

    def build_order(self, order: LoadOrder) -> dict:
        client = self._client_for_order(order)
        destination = self._destination_for_order(order)
        order_entity = SyncService.ensure_entity_uid(
            SyncEntityMap.ENTITY_ORDER, order.id
        )
        client_entity = SyncService.ensure_entity_uid(
            SyncEntityMap.ENTITY_CLIENT, client.id
        )
        destination_entity = SyncService.ensure_entity_uid(
            SyncEntityMap.ENTITY_DESTINATION, destination.id
        )
        now = _iso_now()
        lines = list(
            LoadOrderProduct.select()
            .where(LoadOrderProduct.order == order)
            .order_by(LoadOrderProduct.id)
        )
        pallets = list(
            LoadOrderPallet.select()
            .where(LoadOrderPallet.order == order)
            .order_by(LoadOrderPallet.sequence)
        )

        return {
            "order_uid": order_entity.global_uid,
            "order_number": int(order.order_number),
            "qr_token": order.ensure_qr_token(),
            "status": order.status,
            "version": int(order_entity.local_version or 1),
            "order_date": order.date.isoformat() if order.date else None,
            "published_at": now,
            "updated_at": _iso(order.updated_at) or now,
            "cancelled_at": (
                _iso(order.updated_at) if order.status == LoadOrder.STATUS_ANNULLED else None
            ),
            "client": {
                "client_uid": client_entity.global_uid,
                "name": client.name,
            },
            "destination": {
                "destination_uid": destination_entity.global_uid,
                "city": destination.city or "",
                "address": destination.address or "",
            },
            "lines": [
                {
                    "line_uid": SyncService.ensure_entity_uid(
                        SyncEntityMap.ENTITY_ORDER_LINE, line.id
                    ).global_uid,
                    "product_name": line.product.name,
                    "quantity": float(line.quantity or 0),
                    "unit": line.unit,
                    "lote": line.lote,
                    "fecha_elaboracion": (
                        line.fecha_elaboracion.isoformat()
                        if line.fecha_elaboracion
                        else None
                    ),
                }
                for line in lines
            ],
            "pallets": [
                {
                    "pallet_uid": SyncService.ensure_entity_uid(
                        SyncEntityMap.ENTITY_PALLET, pallet.id
                    ).global_uid,
                    "sequence": int(pallet.sequence),
                    "type": (
                        pallet.pallet_type.type if pallet.pallet_type else None
                    ),
                    "weight_kg": float(pallet.weight or 0),
                }
                for pallet in pallets
            ],
        }

    def build_snapshot(self, orders: list[LoadOrder] | None = None) -> tuple[dict, list[dict]]:
        orders = self.orders() if orders is None else orders
        payloads: list[dict] = []
        skipped: list[dict] = []
        for order in orders:
            try:
                payloads.append(self.build_order(order))
            except SyncPublishError as exc:
                skipped.append(
                    {"order_number": order.order_number, "reason": str(exc)}
                )
        snapshot = {
            "schema_version": "1.0",
            "snapshot_id": str(uuid4()),
            "generated_at": _iso_now(),
            # Segundos: el cursor se guarda en una columna INT de MySQL.
            "cursor": int(time()),
            "orders": payloads,
        }
        return snapshot, skipped

    def publish_snapshot(self, client, *, orders: list[LoadOrder] | None = None) -> dict:
        snapshot, skipped = self.build_snapshot(orders)
        response = client.post_snapshot(snapshot)
        SyncService.set_cursor(
            SyncCursor.STREAM_FACTORY_SNAPSHOT,
            int(snapshot["cursor"]),
            synced_at=_as_datetime(snapshot["generated_at"]),
        )
        return {
            "snapshot": response,
            "orders": len(snapshot["orders"]),
            "skipped": skipped,
        }
