"""Aplicacion de snapshots de ordenes en la nube (#804).

La fabrica publica snapshots versionados. La nube los guarda como proyeccion
de lectura, sin crear movimientos ni modificar la base de fabrica.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config.database import database_proxy
from app.models.sync import SyncCursor, SyncProjection, utc_now_naive
from app.services.sync_service import SyncService

REQUIRED_ORDER_FIELDS = (
    "order_uid",
    "order_number",
    "qr_token",
    "version",
    "status",
    "order_date",
    "lines",
)


class SyncSnapshotError(ValueError):
    pass


class SyncVersionConflict(SyncSnapshotError):
    pass


class SyncTokenConflict(SyncSnapshotError):
    pass


def _parse_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


class SyncSnapshotService:
    @staticmethod
    def apply_order_snapshot(order: dict) -> tuple[SyncProjection, bool]:
        if not isinstance(order, dict):
            raise SyncSnapshotError("La orden del snapshot no es un objeto.")
        missing = [field for field in REQUIRED_ORDER_FIELDS if field not in order]
        if missing:
            raise SyncSnapshotError(
                "Falta en la orden: " + ", ".join(sorted(missing))
            )

        order_uid = str(order["order_uid"]).strip()
        qr_token = str(order["qr_token"]).strip()
        if not order_uid or not qr_token:
            raise SyncSnapshotError("La orden debe tener order_uid y qr_token.")
        version = int(order["version"])

        existing = SyncProjection.get_or_none(
            (SyncProjection.resource_type == SyncProjection.RESOURCE_ORDER)
            & (SyncProjection.resource_uid == order_uid)
        )
        token_owner = SyncProjection.get_or_none(SyncProjection.qr_token == qr_token)
        if token_owner is not None and token_owner.resource_uid != order_uid:
            raise SyncTokenConflict(
                f"El token QR {qr_token} ya pertenece a otra orden."
            )
        if existing is not None and int(existing.version) > version:
            raise SyncVersionConflict(
                f"La version {version} es menor que la publicada "
                f"({existing.version}) para la orden {order_uid}."
            )

        values = {
            "qr_token": qr_token,
            "order_number": int(order["order_number"]),
            "status": str(order["status"]),
            "version": version,
            "payload": order,
            "source_updated_at": _parse_datetime(order.get("updated_at")),
            "cancelled_at": _parse_datetime(order.get("cancelled_at")),
        }
        if existing is None:
            projection = SyncProjection.create(
                resource_type=SyncProjection.RESOURCE_ORDER,
                resource_uid=order_uid,
                published_at=_parse_datetime(order.get("published_at"))
                or utc_now_naive(),
                **values,
            )
            return projection, True

        existing.qr_token = values["qr_token"]
        existing.order_number = values["order_number"]
        existing.status = values["status"]
        existing.version = values["version"]
        existing.payload = values["payload"]
        existing.source_updated_at = values["source_updated_at"]
        existing.cancelled_at = values["cancelled_at"]
        existing.save(
            only=[
                SyncProjection.qr_token,
                SyncProjection.order_number,
                SyncProjection.status,
                SyncProjection.version,
                SyncProjection.payload,
                SyncProjection.source_updated_at,
                SyncProjection.cancelled_at,
            ]
        )
        return existing, False

    @classmethod
    def apply_snapshot(cls, snapshot: dict) -> dict:
        if not isinstance(snapshot, dict):
            raise SyncSnapshotError("El snapshot no es un objeto JSON.")
        orders = snapshot.get("orders")
        if not isinstance(orders, list):
            raise SyncSnapshotError("El snapshot no trae una lista de orders.")
        try:
            cursor_value = int(snapshot.get("cursor") or 0)
        except (TypeError, ValueError) as exc:
            raise SyncSnapshotError("El cursor del snapshot no es valido.") from exc

        created = 0
        updated = 0
        with database_proxy.atomic():
            for order in orders:
                _, was_created = cls.apply_order_snapshot(order)
                if was_created:
                    created += 1
                else:
                    updated += 1
            SyncService.set_cursor(
                SyncCursor.STREAM_FACTORY,
                cursor_value,
                synced_at=_parse_datetime(snapshot.get("generated_at")),
            )
        return {
            "snapshot_id": snapshot.get("snapshot_id"),
            "accepted": len(orders),
            "created": created,
            "updated": updated,
            "cursor": cursor_value,
        }

    @staticmethod
    def get_order_by_token(token: str) -> SyncProjection | None:
        return SyncProjection.get_or_none(
            (SyncProjection.resource_type == SyncProjection.RESOURCE_ORDER)
            & (SyncProjection.qr_token == (token or "").strip())
        )

    @staticmethod
    def get_order_by_uid(order_uid: str) -> SyncProjection | None:
        return SyncProjection.get_or_none(
            (SyncProjection.resource_type == SyncProjection.RESOURCE_ORDER)
            & (SyncProjection.resource_uid == (order_uid or "").strip())
        )
