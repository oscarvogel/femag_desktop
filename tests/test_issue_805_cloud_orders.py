"""La nube abre y edita ordenes reales desde la proyeccion de sync (#805)."""

from uuid import uuid4

from app.models.sync import SyncOutbox, SyncProjection
from app.services.auth_service import AuthService
from app.services.sync_snapshot_service import SyncSnapshotService
from webapp import create_app
from webapp.projected_order_service import (
    get_projected_order_by_token,
    projected_order_lines,
)

PASSWORD = "clave-de-prueba-123"


def _order(status="Emitida", version=1, lote="LOTE-FABRICA-1"):
    return {
        "order_uid": str(uuid4()),
        "order_number": 500,
        "qr_token": "token-real-fabrica",
        "status": status,
        "version": version,
        "order_date": "2026-10-29",
        "published_at": "2026-10-29T12:00:00Z",
        "updated_at": "2026-10-29T12:00:00Z",
        "cancelled_at": None,
        "client": {"client_uid": str(uuid4()), "name": "Cliente Fabrica"},
        "destination": {
            "destination_uid": str(uuid4()),
            "city": "Posadas",
            "address": "Ruta Fabrica",
        },
        "lines": [
            {
                "line_uid": str(uuid4()),
                "product_name": "Fecula Fabrica",
                "quantity": 100,
                "unit": "kg",
                "lote": lote,
                "fecha_elaboracion": "2026-10-28",
            }
        ],
        "pallets": [{"pallet_uid": str(uuid4()), "sequence": 1, "type": "Comun"}],
    }


def _snapshot(order, cursor=1):
    return {
        "schema_version": "1.0",
        "snapshot_id": str(uuid4()),
        "generated_at": "2026-10-29T12:00:00Z",
        "cursor": cursor,
        "orders": [order],
    }


def _app():
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)
    return app


def _login(client):
    AuthService().create_user(
        "operador",
        PASSWORD,
        "Secretaría",
        display_name="operador",
        actor="test",
    )
    return client.post(
        "/login", data={"username": "operador", "password": PASSWORD}
    )


def _csrf(client, token):
    client.get(f"/orden/{token}")
    with client.session_transaction() as session:
        return session["femag_csrf_token"]


def test_projected_order_opens_by_qr_token(db):
    SyncSnapshotService.apply_snapshot(_snapshot(_order()))

    response = _app().test_client().get("/orden/token-real-fabrica")

    assert response.status_code == 200
    assert b"Orden #500" in response.data
    assert b"Cliente Fabrica" in response.data
    assert b"Fecula Fabrica" in response.data
    assert b"LOTE-FABRICA-1" in response.data
    assert b'value="2026-10-28"' in response.data
    assert "Orden sincronizada desde la fábrica".encode() in response.data
    assert b'name="lote_' in response.data
    assert b"Guardar lote y fecha" in response.data
    assert b"scanner-header" in response.data
    assert b"history.pushState" in response.data
    assert b"popstate" in response.data


def test_home_scanner_opens_projected_order(db):
    SyncSnapshotService.apply_snapshot(_snapshot(_order()))
    client = _app().test_client()

    response = client.post(
        "/",
        data={"qr": "token-real-fabrica"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Orden #500" in response.data


def test_projected_order_edit_queues_pending_event(db):
    order = _order()
    SyncSnapshotService.apply_snapshot(_snapshot(order))
    client = _app().test_client()
    _login(client)
    csrf = _csrf(client, "token-real-fabrica")
    projected = get_projected_order_by_token("token-real-fabrica")
    line = projected_order_lines(projected)[0]

    response = client.post(
        "/orden/token-real-fabrica",
        data={
            "csrf_token": csrf,
            f"lote_{line.id}": "LOTE-NUBE-1",
            f"fecha_{line.id}": "2026-10-29",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "pendiente de sincronización".encode() in response.data
    projection = SyncProjection.get(
        SyncProjection.resource_uid == order["order_uid"]
    )
    assert projection.payload["lines"][0]["lote"] == "LOTE-NUBE-1"
    pending = list(
        SyncOutbox.select().where(
            (SyncOutbox.event_type == "order_lote_fecha_updated")
            & (SyncOutbox.status == SyncOutbox.STATUS_PENDING)
        )
    )
    assert len(pending) == 1
    assert pending[0].payload["lote"] == "LOTE-NUBE-1"


def test_second_edit_updates_the_same_pending_event(db):
    order = _order()
    SyncSnapshotService.apply_snapshot(_snapshot(order))
    projected = get_projected_order_by_token("token-real-fabrica")
    line = projected_order_lines(projected)[0]
    client = _app().test_client()
    _login(client)
    csrf = _csrf(client, "token-real-fabrica")

    for lote in ("LOTE-1", "LOTE-2"):
        client.post(
            "/orden/token-real-fabrica",
            data={
                "csrf_token": csrf,
                f"lote_{line.id}": lote,
                f"fecha_{line.id}": "2026-10-29",
            },
        )

    pending = list(
        SyncOutbox.select().where(
            SyncOutbox.event_type == "order_lote_fecha_updated"
        )
    )
    assert len(pending) == 1
    assert pending[0].payload["lote"] == "LOTE-2"


def test_pending_lote_survives_next_snapshot(db):
    order = _order(lote="LOTE-VIEJO")
    SyncSnapshotService.apply_snapshot(_snapshot(order))
    projected = get_projected_order_by_token("token-real-fabrica")
    line = projected_order_lines(projected)[0]
    client = _app().test_client()
    _login(client)
    csrf = _csrf(client, "token-real-fabrica")
    client.post(
        "/orden/token-real-fabrica",
        data={
            "csrf_token": csrf,
            f"lote_{line.id}": "LOTE-NUBE",
            f"fecha_{line.id}": "2026-10-29",
        },
    )

    order["lines"][0]["lote"] = "LOTE-FABRICA-NUEVO"
    SyncSnapshotService.apply_snapshot(_snapshot(order, cursor=2))

    projection = SyncProjection.get(
        SyncProjection.resource_uid == order["order_uid"]
    )
    assert projection.payload["lines"][0]["lote"] == "LOTE-NUBE"


def test_annulled_projected_order_is_rejected(db):
    order = _order()
    SyncSnapshotService.apply_snapshot(_snapshot(order))
    order["status"] = "Anulada"
    order["version"] = 2
    SyncSnapshotService.apply_snapshot(_snapshot(order, cursor=2))

    response = _app().test_client().get("/orden/token-real-fabrica")

    assert response.status_code == 409
    assert b"anulada" in response.data.lower()
