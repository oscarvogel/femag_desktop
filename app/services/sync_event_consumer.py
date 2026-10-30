"""Consumidor de eventos cloud -> fabrica (#804/#805).

Aplica solo los cambios permitidos: lote y fecha de elaboracion. No toca
cantidades, stock, remitos ni contabilidad.
"""

from __future__ import annotations

from datetime import date

from app.models.load_orders import (
    LoadOrder,
    LoadOrderLooseAllocation,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.models.sync import SyncCursor, SyncEntityMap, SyncInbox
from app.services.audit_service import AuditService
from app.services.sync_service import SyncService

LOTE_EVENT = "order_lote_fecha_updated"
CONTENT_EVENT = "order_content_lote_fecha_updated"


def _parse_date(value) -> date | None:
    raw = (value or "").strip() if isinstance(value, str) else ""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("La fecha de elaboracion no tiene formato AAAA-MM-DD.") from exc


class SyncEventConsumer:
    def __init__(self, client, *, limit: int = 50):
        self.client = client
        self.limit = int(limit)
        self.audit = AuditService()

    def pull_and_apply(self) -> dict:
        cursor = SyncService.get_cursor(SyncCursor.STREAM_CLOUD)
        response = self.client.get_events(cursor.cursor_value, limit=self.limit)
        events = response.get("events") or []
        applied = 0
        conflicts = 0
        rejected = 0
        duplicates = 0

        for event in events:
            event_id = str(event.get("event_id") or "")
            event_cursor = int(event.get("cursor") or 0)
            if not event_id:
                continue
            inbox, created = SyncService.record_inbox_event(event, cursor=event_cursor)
            if not created:
                duplicate_result = self._ack_existing(inbox)
                if duplicate_result is not None:
                    self.client.ack_event(
                        event_id,
                        duplicate_result,
                        inbox.last_error,
                    )
                    SyncService.set_cursor(SyncCursor.STREAM_CLOUD, event_cursor)
                    duplicates += 1
                    continue

            result, reason = self._apply_event(event, inbox)
            if result == "applied":
                SyncService.set_inbox_status(inbox, SyncInbox.STATUS_APPLIED)
                applied += 1
            elif result == "conflict":
                SyncService.set_inbox_status(
                    inbox, SyncInbox.STATUS_CONFLICT, error=reason
                )
                SyncService.record_conflict(inbox, reason or "Conflicto de sync.")
                conflicts += 1
            else:
                SyncService.set_inbox_status(
                    inbox, SyncInbox.STATUS_REJECTED, error=reason
                )
                if reason:
                    SyncService.record_conflict(
                        inbox, reason or "Evento de sync rechazado."
                    )
                rejected += 1

            self.client.ack_event(event_id, result, reason)
            SyncService.set_cursor(SyncCursor.STREAM_CLOUD, event_cursor)

        return {
            "received": len(events),
            "applied": applied,
            "conflicts": conflicts,
            "rejected": rejected,
            "duplicates": duplicates,
        }

    @staticmethod
    def _ack_existing(inbox: SyncInbox) -> str | None:
        if inbox.status == SyncInbox.STATUS_APPLIED:
            return "applied"
        if inbox.status == SyncInbox.STATUS_CONFLICT:
            return "conflict"
        if inbox.status == SyncInbox.STATUS_REJECTED:
            return "rejected"
        return None

    def _apply_event(self, event: dict, inbox: SyncInbox) -> tuple[str, str | None]:
        event_type = event.get("event_type")
        if event_type == LOTE_EVENT:
            return self._apply_line_event(event, inbox)
        if event_type == CONTENT_EVENT:
            return self._apply_content_event(event, inbox)
        return "rejected", f"Evento no soportado: {event_type}"

    def _apply_line_event(self, event: dict, inbox: SyncInbox) -> tuple[str, str | None]:
        payload = event.get("payload") or {}
        order_uid = str(payload.get("order_uid") or "").strip()
        line_uid = str(payload.get("line_uid") or "").strip()
        if not order_uid or not line_uid:
            return "rejected", "El evento no trae order_uid/line_uid."

        order_map = SyncEntityMap.get_or_none(
            (SyncEntityMap.entity_type == SyncEntityMap.ENTITY_ORDER)
            & (SyncEntityMap.global_uid == order_uid)
        )
        line_map = SyncEntityMap.get_or_none(
            (SyncEntityMap.entity_type == SyncEntityMap.ENTITY_ORDER_LINE)
            & (SyncEntityMap.global_uid == line_uid)
        )
        if order_map is None or line_map is None:
            return "rejected", "La orden o el renglon no tienen mapeo local."

        order = LoadOrder.get_or_none(LoadOrder.id == int(order_map.local_id))
        if order is None:
            return "rejected", "La orden local ya no existe."
        if order.status == LoadOrder.STATUS_ANNULLED:
            return "rejected", f"La orden #{order.order_number} esta anulada."
        line = LoadOrderProduct.get_or_none(
            (LoadOrderProduct.id == int(line_map.local_id))
            & (LoadOrderProduct.order == order)
        )
        if line is None:
            return "rejected", "El renglon local ya no existe."

        expected = int(
            payload.get("expected_version")
            or event.get("aggregate_version")
            or 1
        )
        local_version = int(order_map.local_version or 1)
        if expected != local_version:
            return (
                "conflict",
                f"Version local {local_version} distinta de la esperada {expected}.",
            )

        lote = (payload.get("lote") or "").strip() or None
        if lote and len(lote) > 255:
            return "rejected", "El lote supera los 255 caracteres."
        try:
            fecha = _parse_date(payload.get("fecha_elaboracion"))
        except ValueError as exc:
            return "rejected", str(exc)

        line.lote = lote
        line.fecha_elaboracion = fecha
        line.save(only=[LoadOrderProduct.lote, LoadOrderProduct.fecha_elaboracion])
        self.audit.record(
            user="sync",
            module="Despachos",
            action="carga de lote (sync)",
            record_ref=f"LoadOrderProduct:{line.id}",
            new_value={
                "orden": order.order_number,
                "renglon": line.id,
                "lote": line.lote,
                "fecha_elaboracion": (
                    line.fecha_elaboracion.isoformat()
                    if line.fecha_elaboracion
                    else None
                ),
                "event_id": inbox.event_id,
            },
        )
        return "applied", None

    def _apply_content_event(
        self, event: dict, inbox: SyncInbox
    ) -> tuple[str, str | None]:
        payload = event.get("payload") or {}
        order_uid = str(payload.get("order_uid") or "").strip()
        content_uid = str(payload.get("content_uid") or "").strip()
        content_type = str(payload.get("content_type") or "").strip()
        if not order_uid or not content_uid:
            return "rejected", "El evento no trae order_uid/content_uid."
        if content_type not in {"pallet", "loose"}:
            return "rejected", f"Tipo de contenido no soportado: {content_type}"

        order_map = SyncEntityMap.get_or_none(
            (SyncEntityMap.entity_type == SyncEntityMap.ENTITY_ORDER)
            & (SyncEntityMap.global_uid == order_uid)
        )
        entity_type = (
            SyncEntityMap.ENTITY_PALLET_CONTENT
            if content_type == "pallet"
            else SyncEntityMap.ENTITY_LOOSE_CONTENT
        )
        content_map = SyncEntityMap.get_or_none(
            (SyncEntityMap.entity_type == entity_type)
            & (SyncEntityMap.global_uid == content_uid)
        )
        if order_map is None or content_map is None:
            return "rejected", "La orden o el contenido no tienen mapeo local."

        order = LoadOrder.get_or_none(LoadOrder.id == int(order_map.local_id))
        if order is None:
            return "rejected", "La orden local ya no existe."
        if order.status == LoadOrder.STATUS_ANNULLED:
            return "rejected", f"La orden #{order.order_number} esta anulada."

        expected = int(
            payload.get("expected_version")
            or event.get("aggregate_version")
            or 1
        )
        local_version = int(order_map.local_version or 1)
        if expected != local_version:
            return (
                "conflict",
                f"Version local {local_version} distinta de la esperada {expected}.",
            )

        lote = (payload.get("lote") or "").strip() or None
        if lote and len(lote) > 255:
            return "rejected", "El lote supera los 255 caracteres."
        try:
            fecha = _parse_date(payload.get("fecha_elaboracion"))
        except ValueError as exc:
            return "rejected", str(exc)

        if content_type == "pallet":
            allocation = LoadOrderPalletAllocation.get_or_none(
                LoadOrderPalletAllocation.id == int(content_map.local_id)
            )
            if allocation is None or allocation.pallet.order_id != order.id:
                return "rejected", "El contenido del pallet ya no existe."
            record_ref = f"LoadOrderPalletAllocation:{allocation.id}"
            extra = {"pallet": allocation.pallet.sequence}
        else:
            allocation = LoadOrderLooseAllocation.get_or_none(
                (LoadOrderLooseAllocation.id == int(content_map.local_id))
                & (LoadOrderLooseAllocation.order == order)
            )
            if allocation is None:
                return "rejected", "El contenido suelto ya no existe."
            record_ref = f"LoadOrderLooseAllocation:{allocation.id}"
            extra = {}

        allocation.lote = lote
        allocation.fecha_elaboracion = fecha
        allocation.save(
            only=[
                LoadOrderPalletAllocation.lote
                if content_type == "pallet"
                else LoadOrderLooseAllocation.lote,
                LoadOrderPalletAllocation.fecha_elaboracion
                if content_type == "pallet"
                else LoadOrderLooseAllocation.fecha_elaboracion,
            ]
        )
        self.audit.record(
            user="sync",
            module="Despachos",
            action="carga de lote (sync)",
            record_ref=record_ref,
            new_value={
                "orden": order.order_number,
                "contenido": allocation.id,
                "tipo": content_type,
                "lote": allocation.lote,
                "fecha_elaboracion": (
                    allocation.fecha_elaboracion.isoformat()
                    if allocation.fecha_elaboracion
                    else None
                ),
                "event_id": inbox.event_id,
                **extra,
            },
        )
        return "applied", None
