"""API maquina-a-maquina de FEMAG Sync (#804).

La fabrica inicia las conexiones y se autentica con un token de maquina. La
API no usa sesiones de usuario ni CSRF: no la llama un navegador.
"""

from __future__ import annotations

import hmac
import os

from flask import Blueprint, jsonify, request

from app.config.database import database_proxy
from app.config.schema import validate_sync_schema
from app.models.sync import SyncConflict, SyncOutbox, SyncProjection
from app.services.sync_service import SyncService
from app.services.sync_snapshot_service import (
    SyncSnapshotError,
    SyncSnapshotService,
    SyncTokenConflict,
    SyncVersionConflict,
)

sync_api = Blueprint("sync_api", __name__, url_prefix="/api/sync/v1")

MAX_EVENTS_PER_PULL = 200


def _machine_auth_error():
    expected = os.getenv("FEMAG_SYNC_API_TOKEN", "").strip()
    if not expected:
        return (
            jsonify(
                {
                    "error": "sync_disabled",
                    "message": "FEMAG_SYNC_API_TOKEN no está configurado.",
                }
            ),
            503,
        )
    provided = request.headers.get("Authorization", "")
    if not hmac.compare_digest(provided, f"Bearer {expected}"):
        return (
            jsonify(
                {
                    "error": "unauthorized",
                    "message": "Token de máquina inválido.",
                }
            ),
            401,
        )
    return None


@sync_api.before_request
def _guard_sync_api():
    error = _machine_auth_error()
    if error is not None:
        return error
    try:
        validate_sync_schema(database_proxy)
    except Exception:
        return (
            jsonify(
                {
                    "error": "sync_schema_missing",
                    "message": "Faltan las tablas de sincronización.",
                }
            ),
            503,
        )
    return None


def _event_json(event: SyncOutbox) -> dict:
    return {
        "schema_version": "1.0",
        "event_id": event.event_id,
        "event_type": event.event_type,
        "origin": "cloud",
        "occurred_at": (
            event.occurred_at.isoformat() if event.occurred_at else None
        ),
        "aggregate_type": event.aggregate_type,
        "aggregate_id": event.aggregate_id,
        "aggregate_version": event.aggregate_version,
        "idempotency_key": event.idempotency_key,
        "cursor": event.id,
        "payload": event.payload,
    }


@sync_api.post("/snapshots/orders")
def receive_order_snapshot():
    snapshot = request.get_json(silent=True)
    if not isinstance(snapshot, dict):
        return (
            jsonify(
                {
                    "error": "invalid_snapshot",
                    "message": "Se esperaba un objeto JSON.",
                }
            ),
            400,
        )
    try:
        result = SyncSnapshotService.apply_snapshot(snapshot)
    except SyncVersionConflict as exc:
        return (
            jsonify({"error": "version_conflict", "message": str(exc)}),
            409,
        )
    except SyncTokenConflict as exc:
        return (
            jsonify({"error": "token_conflict", "message": str(exc)}),
            409,
        )
    except SyncSnapshotError as exc:
        return (
            jsonify({"error": "invalid_snapshot", "message": str(exc)}),
            422,
        )
    return jsonify(result)


@sync_api.get("/events")
def pull_events():
    try:
        cursor = max(0, int(request.args.get("cursor", 0)))
        limit = min(
            MAX_EVENTS_PER_PULL,
            max(1, int(request.args.get("limit", 50))),
        )
    except (TypeError, ValueError):
        return (
            jsonify(
                {
                    "error": "invalid_cursor",
                    "message": "cursor y limit deben ser enteros.",
                }
            ),
            400,
        )

    events = list(
        SyncOutbox.select()
        .where(
            (SyncOutbox.id > cursor)
            & (SyncOutbox.status == SyncOutbox.STATUS_PENDING)
        )
        .order_by(SyncOutbox.id)
        .limit(limit)
    )
    payload = [_event_json(event) for event in events]
    next_cursor = payload[-1]["cursor"] if payload else cursor
    return jsonify({"events": payload, "next_cursor": next_cursor})


@sync_api.post("/events/<event_id>/ack")
def ack_event(event_id: str):
    event = SyncOutbox.get_or_none(SyncOutbox.event_id == event_id)
    if event is None:
        return (
            jsonify(
                {
                    "error": "not_found",
                    "message": "Evento de sync inexistente.",
                }
            ),
            404,
        )

    body = request.get_json(silent=True) or {}
    result = str(body.get("result") or "").strip().lower()
    if result not in {"applied", "conflict", "rejected"}:
        return (
            jsonify(
                {
                    "error": "invalid_result",
                    "message": "result debe ser applied, conflict o rejected.",
                }
            ),
            422,
        )

    if result == "applied":
        SyncService.mark_sent(event)
        return jsonify({"event_id": event.event_id, "result": result})

    reason = str(body.get("error") or body.get("message") or "").strip()
    if reason:
        existing = SyncConflict.get_or_none(
            (SyncConflict.event_id == event.event_id)
            & (SyncConflict.status == SyncConflict.STATUS_OPEN)
        )
        if existing is None:
            SyncConflict.create(
                event_id=event.event_id,
                event_type=event.event_type,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                payload=event.payload,
                reason=reason[:2000],
            )
    SyncService.mark_sent(event)
    return jsonify({"event_id": event.event_id, "result": result})


@sync_api.get("/status")
def sync_status():
    summary = SyncService.status_summary()
    summary["projections"] = {
        SyncProjection.RESOURCE_ORDER: SyncProjection.select()
        .where(SyncProjection.resource_type == SyncProjection.RESOURCE_ORDER)
        .count()
    }
    return jsonify(summary)
