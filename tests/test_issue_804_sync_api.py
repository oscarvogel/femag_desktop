"""API de sincronizacion: auth de maquina, snapshots, eventos y ACK (#804)."""

from uuid import uuid4

from app.models.sync import (
    SyncConflict,
    SyncCursor,
    SyncOutbox,
    SyncProjection,
)
from app.services.sync_service import SyncService
from webapp import create_app

TOKEN = "token-de-prueba-sync"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _app(monkeypatch, token=TOKEN):
    monkeypatch.setenv("FEMAG_SYNC_API_TOKEN", token)
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)
    return app


def _order(uid=None, token="qr-token-1", version=2):
    uid = uid or str(uuid4())
    return {
        "order_uid": uid,
        "order_number": 990001,
        "qr_token": token,
        "status": "Emitida",
        "version": version,
        "order_date": "2026-10-29",
        "published_at": "2026-10-29T12:00:00Z",
        "updated_at": "2026-10-29T12:00:00Z",
        "cancelled_at": None,
        "client": {"client_uid": str(uuid4()), "name": "Cliente Demo"},
        "destination": {
            "destination_uid": str(uuid4()),
            "city": "Posadas",
            "address": "Ruta Demo",
        },
        "lines": [
            {
                "line_uid": str(uuid4()),
                "product_name": "Fecula Demo",
                "quantity": 100,
                "unit": "kg",
                "lote": None,
                "fecha_elaboracion": None,
            }
        ],
        "pallets": [],
    }


def _snapshot(orders=None, cursor=7):
    return {
        "schema_version": "1.0",
        "snapshot_id": str(uuid4()),
        "generated_at": "2026-10-29T12:00:00Z",
        "cursor": cursor,
        "orders": orders if orders is not None else [_order()],
    }


def test_snapshot_requires_machine_token(db, monkeypatch):
    client = _app(monkeypatch).test_client()

    assert client.post("/api/sync/v1/snapshots/orders", json=_snapshot()).status_code == 401
    assert (
        client.post(
            "/api/sync/v1/snapshots/orders",
            json=_snapshot(),
            headers={"Authorization": "Bearer incorrecto"},
        ).status_code
        == 401
    )


def test_snapshot_is_disabled_without_token_env(db, monkeypatch):
    monkeypatch.delenv("FEMAG_SYNC_API_TOKEN", raising=False)
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)

    response = app.test_client().post(
        "/api/sync/v1/snapshots/orders",
        json=_snapshot(),
        headers=HEADERS,
    )

    assert response.status_code == 503
    assert response.get_json()["error"] == "sync_disabled"


def test_snapshot_creates_projection_and_factory_cursor(db, monkeypatch):
    client = _app(monkeypatch).test_client()
    order = _order()

    response = client.post(
        "/api/sync/v1/snapshots/orders",
        json=_snapshot([order], cursor=12),
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.get_json()["created"] == 1
    projection = SyncProjection.get(
        SyncProjection.resource_uid == order["order_uid"]
    )
    assert projection.qr_token == order["qr_token"]
    assert projection.order_number == 990001
    assert projection.version == 2
    assert projection.payload["lines"][0]["product_name"] == "Fecula Demo"
    assert SyncCursor.get(SyncCursor.stream == SyncCursor.STREAM_FACTORY).cursor_value == 12


def test_snapshot_is_idempotent_and_rejects_older_versions(db, monkeypatch):
    client = _app(monkeypatch).test_client()
    order = _order(version=2)

    first = client.post(
        "/api/sync/v1/snapshots/orders",
        json=_snapshot([order]),
        headers=HEADERS,
    )
    again = client.post(
        "/api/sync/v1/snapshots/orders",
        json=_snapshot([order]),
        headers=HEADERS,
    )
    older = client.post(
        "/api/sync/v1/snapshots/orders",
        json=_snapshot([_order(uid=order["order_uid"], version=1)]),
        headers=HEADERS,
    )
    newer = client.post(
        "/api/sync/v1/snapshots/orders",
        json=_snapshot([_order(uid=order["order_uid"], version=3)]),
        headers=HEADERS,
    )

    assert first.status_code == 200
    assert again.status_code == 200
    assert older.status_code == 409
    assert older.get_json()["error"] == "version_conflict"
    assert newer.status_code == 200
    assert SyncProjection.select().count() == 1
    assert SyncProjection.get().version == 3


def test_snapshot_rejects_qr_token_collision(db, monkeypatch):
    client = _app(monkeypatch).test_client()
    first = _order(uid=str(uuid4()), token="token-compartido")

    assert (
        client.post(
            "/api/sync/v1/snapshots/orders",
            json=_snapshot([first]),
            headers=HEADERS,
        ).status_code
        == 200
    )

    second = _order(uid=str(uuid4()), token="token-compartido")
    response = client.post(
        "/api/sync/v1/snapshots/orders",
        json=_snapshot([second]),
        headers=HEADERS,
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "token_conflict"
    assert SyncProjection.select().count() == 1


def test_snapshot_requires_qr_token(db, monkeypatch):
    client = _app(monkeypatch).test_client()
    order = _order()
    order.pop("qr_token")

    response = client.post(
        "/api/sync/v1/snapshots/orders",
        json=_snapshot([order]),
        headers=HEADERS,
    )

    assert response.status_code == 422
    assert response.get_json()["error"] == "invalid_snapshot"


def _enqueue_event():
    event, _ = SyncService.enqueue_event(
        event_type="order_lote_fecha_updated",
        aggregate_type="order_line",
        aggregate_id="linea-uid",
        payload={"lote": "LOTE-1"},
    )
    return event


def test_pull_events_and_ack_applied(db, monkeypatch):
    client = _app(monkeypatch).test_client()
    event = _enqueue_event()

    pulled = client.get("/api/sync/v1/events?cursor=0", headers=HEADERS)
    assert pulled.status_code == 200
    body = pulled.get_json()
    assert len(body["events"]) == 1
    assert body["events"][0]["event_id"] == event.event_id
    assert body["events"][0]["cursor"] == event.id
    assert body["next_cursor"] == event.id

    ack = client.post(
        f"/api/sync/v1/events/{event.event_id}/ack",
        json={"result": "applied"},
        headers=HEADERS,
    )
    assert ack.status_code == 200
    assert SyncOutbox.get_by_id(event.id).status == SyncOutbox.STATUS_SENT
    assert client.get("/api/sync/v1/events?cursor=0", headers=HEADERS).get_json()["events"] == []


def test_ack_conflict_creates_review_queue(db, monkeypatch):
    client = _app(monkeypatch).test_client()
    event = _enqueue_event()

    response = client.post(
        f"/api/sync/v1/events/{event.event_id}/ack",
        json={"result": "conflict", "error": "La orden cambió en fábrica."},
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert SyncConflict.select().where(SyncConflict.status == "open").count() == 1
    assert SyncOutbox.get_by_id(event.id).status == SyncOutbox.STATUS_SENT


def test_status_endpoint_reports_projections_cursors_and_queues(db, monkeypatch):
    client = _app(monkeypatch).test_client()
    client.post(
        "/api/sync/v1/snapshots/orders",
        json=_snapshot([_order()], cursor=9),
        headers=HEADERS,
    )
    _enqueue_event()

    response = client.get("/api/sync/v1/status", headers=HEADERS)

    assert response.status_code == 200
    body = response.get_json()
    assert body["projections"][SyncProjection.RESOURCE_ORDER] == 1
    assert body["outbox"][SyncOutbox.STATUS_PENDING] == 1
    assert body["cursors"][SyncCursor.STREAM_FACTORY]["cursor"] == 9
