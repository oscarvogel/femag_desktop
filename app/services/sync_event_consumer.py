"""Consumidor de eventos cloud -> fabrica (#804/#805).

Aplica solo los cambios permitidos: lote y fecha de elaboracion. No toca
cantidades, stock, remitos ni contabilidad.
"""

from __future__ import annotations

from datetime import date

from app.models.load_orders import LoadOrder, LoadOrderProduct
from app.models.sync import SyncCursor, SyncEntityMap, SyncInbox
from app.services.audit_service import AuditService
from app.services.sync_service import SyncService

LOTE_EVENT = "order_lote_fecha_updated"


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
        if event.get("event_type") != LOTE_EVENT:
            return (
                "rejected",
                f"Evento no soportado: {event.get('event_type')}",
            )

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
