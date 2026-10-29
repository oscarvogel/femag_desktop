"""Servicio base de FEMAG Sync (#804).

Gestiona IDs globales estables, outbox/inbox durables, cursores y conflictos.
No habla con la red: el agente y la API usan estas primitivas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from peewee import IntegrityError

from app.models.sync import (
    SyncConflict,
    SyncCursor,
    SyncEntityMap,
    SyncInbox,
    SyncOutbox,
    utc_now_naive,
)

MAX_ATTEMPTS = 8
RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 300


def _parse_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return _naive_utc(value)
    if isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return _naive_utc(parsed)
    return None


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _now() -> datetime:
    return utc_now_naive()


class SyncService:
    # ------------------------------------------------------------------ IDs
    @staticmethod
    def ensure_entity_uid(
        entity_type: str,
        local_id,
        *,
        initial_version: int = 1,
    ) -> SyncEntityMap:
        local_key = str(local_id)
        existing = SyncEntityMap.get_or_none(
            (SyncEntityMap.entity_type == entity_type)
            & (SyncEntityMap.local_id == local_key)
        )
        if existing is not None:
            return existing
        try:
            return SyncEntityMap.create(
                entity_type=entity_type,
                local_id=local_key,
                global_uid=str(uuid4()),
                local_version=int(initial_version),
            )
        except IntegrityError:
            return SyncEntityMap.get(
                (SyncEntityMap.entity_type == entity_type)
                & (SyncEntityMap.local_id == local_key)
            )

    @staticmethod
    def bump_entity_version(entity: SyncEntityMap, *, published: bool = False) -> int:
        entity.local_version = int(entity.local_version or 0) + 1
        if published:
            entity.last_published_version = entity.local_version
        entity.save(only=[SyncEntityMap.local_version, SyncEntityMap.last_published_version])
        return entity.local_version

    @staticmethod
    def mark_entity_published(entity: SyncEntityMap, version: int | None = None) -> None:
        entity.last_published_version = int(version or entity.local_version)
        entity.save(only=[SyncEntityMap.last_published_version])

    # --------------------------------------------------------------- outbox
    @staticmethod
    def enqueue_event(
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict,
        aggregate_version: int = 1,
        idempotency_key: str | None = None,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
        available_at: datetime | None = None,
    ) -> tuple[SyncOutbox, bool]:
        event_id = str(event_id or uuid4())
        key = idempotency_key or event_id
        existing = SyncOutbox.get_or_none(
            (SyncOutbox.event_id == event_id)
            | (SyncOutbox.idempotency_key == key)
        )
        if existing is not None:
            return existing, False
        try:
            created = SyncOutbox.create(
                event_id=event_id,
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=str(aggregate_id),
                aggregate_version=int(aggregate_version),
                idempotency_key=key,
                payload=payload,
                occurred_at=_naive_utc(occurred_at) or _now(),
                next_attempt_at=_naive_utc(available_at),
            )
        except IntegrityError:
            existing = SyncOutbox.get(
                (SyncOutbox.event_id == event_id)
                | (SyncOutbox.idempotency_key == key)
            )
            return existing, False
        return created, True

    @staticmethod
    def next_pending(
        *,
        now: datetime | None = None,
        limit: int = 50,
    ) -> list[SyncOutbox]:
        now = _naive_utc(now) or _now()
        query = (
            SyncOutbox.select()
            .where(
                (SyncOutbox.status == SyncOutbox.STATUS_PENDING)
                & (
                    SyncOutbox.next_attempt_at.is_null(True)
                    | (SyncOutbox.next_attempt_at <= now)
                )
            )
            .order_by(SyncOutbox.id)
            .limit(limit)
        )
        return list(query)

    @staticmethod
    def mark_sent(event: SyncOutbox, *, now: datetime | None = None) -> None:
        event.status = SyncOutbox.STATUS_SENT
        event.sent_at = _naive_utc(now) or _now()
        event.last_error = None
        event.next_attempt_at = None
        event.save(
            only=[
                SyncOutbox.status,
                SyncOutbox.sent_at,
                SyncOutbox.last_error,
                SyncOutbox.next_attempt_at,
            ]
        )

    @staticmethod
    def mark_failed(
        event: SyncOutbox,
        error: str,
        *,
        now: datetime | None = None,
    ) -> None:
        now = _naive_utc(now) or _now()
        attempts = int(event.attempts or 0) + 1
        event.attempts = attempts
        event.last_error = str(error)[:2000]
        if attempts >= MAX_ATTEMPTS:
            event.status = SyncOutbox.STATUS_DEAD_LETTER
            event.next_attempt_at = None
        else:
            delay = min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * (2 ** (attempts - 1)))
            event.status = SyncOutbox.STATUS_PENDING
            event.next_attempt_at = now + timedelta(seconds=delay)
        event.save(
            only=[
                SyncOutbox.attempts,
                SyncOutbox.last_error,
                SyncOutbox.status,
                SyncOutbox.next_attempt_at,
            ]
        )

    # ---------------------------------------------------------------- inbox
    @staticmethod
    def record_inbox_event(
        event: dict,
        *,
        cursor: int | None = None,
    ) -> tuple[SyncInbox, bool]:
        try:
            event_id = str(event["event_id"])
            event_type = str(event["event_type"])
            aggregate_type = str(event["aggregate_type"])
            aggregate_id = str(event["aggregate_id"])
        except KeyError as exc:
            raise ValueError(f"Evento de sync incompleto: falta {exc.args[0]}.") from exc

        existing = SyncInbox.get_or_none(SyncInbox.event_id == event_id)
        if existing is not None:
            return existing, False
        try:
            created = SyncInbox.create(
                event_id=event_id,
                event_type=event_type,
                origin=str(event.get("origin") or "cloud"),
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                aggregate_version=int(event.get("aggregate_version") or 1),
                cursor_value=int(cursor if cursor is not None else event.get("cursor") or 0),
                payload=event.get("payload") or {},
                occurred_at=_parse_datetime(event.get("occurred_at")),
            )
        except IntegrityError:
            return SyncInbox.get(SyncInbox.event_id == event_id), False
        return created, True

    @staticmethod
    def set_inbox_status(
        inbox: SyncInbox,
        status: str,
        *,
        error: str | None = None,
        now: datetime | None = None,
    ) -> None:
        inbox.status = status
        inbox.last_error = str(error)[:2000] if error else None
        if status == SyncInbox.STATUS_APPLIED:
            inbox.applied_at = _naive_utc(now) or _now()
        inbox.save(
            only=[SyncInbox.status, SyncInbox.last_error, SyncInbox.applied_at]
        )

    # ------------------------------------------------------------- conflictos
    @staticmethod
    def record_conflict(inbox: SyncInbox, reason: str) -> SyncConflict:
        existing = SyncConflict.get_or_none(
            (SyncConflict.event_id == inbox.event_id)
            & (SyncConflict.status == SyncConflict.STATUS_OPEN)
        )
        if existing is not None:
            return existing
        return SyncConflict.create(
            event_id=inbox.event_id,
            event_type=inbox.event_type,
            aggregate_type=inbox.aggregate_type,
            aggregate_id=inbox.aggregate_id,
            payload=inbox.payload,
            reason=str(reason)[:2000],
        )

    @staticmethod
    def resolve_conflict(
        conflict: SyncConflict,
        *,
        resolved_by: str,
        resolution: str | None = None,
        ignored: bool = False,
        now: datetime | None = None,
    ) -> None:
        conflict.status = (
            SyncConflict.STATUS_IGNORED if ignored else SyncConflict.STATUS_RESOLVED
        )
        conflict.resolution = resolution
        conflict.resolved_by = resolved_by
        conflict.resolved_at = _naive_utc(now) or _now()
        conflict.save(
            only=[
                SyncConflict.status,
                SyncConflict.resolution,
                SyncConflict.resolved_by,
                SyncConflict.resolved_at,
            ]
        )

    # --------------------------------------------------------------- cursores
    @staticmethod
    def get_cursor(stream: str) -> SyncCursor:
        cursor, _ = SyncCursor.get_or_create(stream=stream)
        return cursor

    @staticmethod
    def set_cursor(
        stream: str,
        cursor_value: int,
        *,
        synced_at: datetime | None = None,
        error: str | None = None,
    ) -> SyncCursor:
        cursor = SyncService.get_cursor(stream)
        cursor.cursor_value = int(cursor_value)
        cursor.last_synced_at = _naive_utc(synced_at) or _now()
        cursor.last_error = str(error)[:2000] if error else None
        cursor.save(
            only=[
                SyncCursor.cursor_value,
                SyncCursor.last_synced_at,
                SyncCursor.last_error,
            ]
        )
        return cursor

    # ------------------------------------------------------------ observacion
    @staticmethod
    def status_summary() -> dict:
        outbox = {
            status: SyncOutbox.select()
            .where(SyncOutbox.status == status)
            .count()
            for status in (
                SyncOutbox.STATUS_PENDING,
                SyncOutbox.STATUS_SENT,
                SyncOutbox.STATUS_DEAD_LETTER,
            )
        }
        inbox = {
            status: SyncInbox.select()
            .where(SyncInbox.status == status)
            .count()
            for status in (
                SyncInbox.STATUS_PENDING,
                SyncInbox.STATUS_APPLIED,
                SyncInbox.STATUS_CONFLICT,
                SyncInbox.STATUS_REJECTED,
            )
        }
        return {
            "outbox": outbox,
            "inbox": inbox,
            "open_conflicts": SyncConflict.select()
            .where(SyncConflict.status == SyncConflict.STATUS_OPEN)
            .count(),
            "cursors": {
                cursor.stream: {
                    "cursor": cursor.cursor_value,
                    "last_synced_at": (
                        cursor.last_synced_at.isoformat()
                        if cursor.last_synced_at
                        else None
                    ),
                    "last_error": cursor.last_error,
                }
                for cursor in SyncCursor.select()
            },
        }
