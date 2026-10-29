"""Estado durable de FEMAG Sync: IDs, outbox, inbox, cursores y conflictos (#804)."""

from datetime import datetime, timedelta

from app.models.sync import (
    SyncConflict,
    SyncCursor,
    SyncEntityMap,
    SyncInbox,
    SyncOutbox,
)
from app.services.sync_service import (
    MAX_ATTEMPTS,
    RETRY_BASE_SECONDS,
    SyncService,
)

NOW = datetime(2026, 10, 29, 12, 0)


def _event(event_id="evento-1", cursor=10):
    return {
        "event_id": event_id,
        "event_type": "order_lote_fecha_updated",
        "origin": "cloud",
        "aggregate_type": "order_line",
        "aggregate_id": "linea-uid",
        "aggregate_version": 3,
        "cursor": cursor,
        "occurred_at": "2026-10-29T12:00:00Z",
        "payload": {"lote": "LOTE-1", "fecha_elaboracion": "2026-10-29"},
    }


def test_sync_tables_are_created(db):
    tables = set(db.get_tables())

    assert "syncentitymap" in tables
    assert "syncoutbox" in tables
    assert "syncinbox" in tables
    assert "synccursor" in tables
    assert "syncconflict" in tables


def test_entity_uids_are_stable_per_entity(db):
    first = SyncService.ensure_entity_uid(SyncEntityMap.ENTITY_ORDER, 123)
    again = SyncService.ensure_entity_uid(SyncEntityMap.ENTITY_ORDER, "123")
    other = SyncService.ensure_entity_uid(SyncEntityMap.ENTITY_ORDER, 124)

    assert first.global_uid == again.global_uid
    assert first.global_uid != other.global_uid
    assert SyncEntityMap.select().count() == 2


def test_enqueue_event_is_idempotent(db):
    first, created = SyncService.enqueue_event(
        event_type="order_updated",
        aggregate_type="order",
        aggregate_id="orden-uid",
        payload={"estado": "Emitida"},
        event_id="00000000-0000-0000-0000-000000000001",
        idempotency_key="orden-uid:v1",
    )
    second, created_again = SyncService.enqueue_event(
        event_type="order_updated",
        aggregate_type="order",
        aggregate_id="orden-uid",
        payload={"estado": "Emitida"},
        event_id="00000000-0000-0000-0000-000000000001",
        idempotency_key="orden-uid:v1",
    )

    assert created is True
    assert created_again is False
    assert first.id == second.id
    assert SyncOutbox.select().count() == 1


def test_outbox_retries_with_backoff_and_ends_in_dead_letter(db):
    event, _ = SyncService.enqueue_event(
        event_type="order_updated",
        aggregate_type="order",
        aggregate_id="orden-uid",
        payload={},
        available_at=NOW,
    )

    assert [item.id for item in SyncService.next_pending(now=NOW)] == [event.id]

    SyncService.mark_failed(event, "red caida", now=NOW)
    event = SyncOutbox.get_by_id(event.id)
    assert event.status == SyncOutbox.STATUS_PENDING
    assert event.attempts == 1
    assert event.next_attempt_at > NOW
    assert SyncService.next_pending(now=NOW) == []

    now = NOW
    for _ in range(MAX_ATTEMPTS - 1):
        now = now + timedelta(seconds=RETRY_BASE_SECONDS * 120)
        event = SyncOutbox.get_by_id(event.id)
        SyncService.mark_failed(event, "red caida", now=now)

    event = SyncOutbox.get_by_id(event.id)
    assert event.status == SyncOutbox.STATUS_DEAD_LETTER
    assert event.attempts == MAX_ATTEMPTS


def test_inbox_deduplicates_by_event_id(db):
    first, created = SyncService.record_inbox_event(_event())
    second, created_again = SyncService.record_inbox_event(_event())

    assert created is True
    assert created_again is False
    assert first.id == second.id
    assert SyncInbox.select().count() == 1
    assert first.cursor_value == 10


def test_cursor_persists_and_status_summary_is_observable(db):
    cursor = SyncService.set_cursor(
        SyncCursor.STREAM_CLOUD,
        42,
        synced_at=NOW,
    )
    again = SyncService.get_cursor(SyncCursor.STREAM_CLOUD)
    summary = SyncService.status_summary()

    assert cursor.cursor_value == 42
    assert again.cursor_value == 42
    assert summary["cursors"][SyncCursor.STREAM_CLOUD]["cursor"] == 42
    assert "last_synced_at" in summary["cursors"][SyncCursor.STREAM_CLOUD]


def test_conflict_goes_to_review_queue_and_can_be_resolved(db):
    inbox, _ = SyncService.record_inbox_event(_event("evento-conflicto", cursor=20))
    conflict = SyncService.record_conflict(inbox, "La orden cambió en fábrica.")
    again = SyncService.record_conflict(inbox, "Otro motivo.")

    assert conflict.id == again.id
    assert SyncConflict.select().where(SyncConflict.status == "open").count() == 1

    SyncService.resolve_conflict(
        conflict,
        resolved_by="admin",
        resolution="Se revisó con el operario.",
        now=NOW,
    )
    conflict = SyncConflict.get_by_id(conflict.id)
    assert conflict.status == SyncConflict.STATUS_RESOLVED
    assert conflict.resolved_by == "admin"

def test_ensure_runtime_schema_creates_sync_tables(tmp_path):
    from peewee import SqliteDatabase

    from app.config.database import bind_database
    from app.config.schema import ensure_runtime_schema, validate_sync_schema

    database = SqliteDatabase(str(tmp_path / "sync-schema.sqlite3"))
    bind_database(database)
    database.connect(reuse_if_open=True)
    try:
        ensure_runtime_schema(database)
        validate_sync_schema(database)
        tables = set(database.get_tables())
        assert "syncoutbox" in tables
        assert "syncinbox" in tables
    finally:
        database.close()
