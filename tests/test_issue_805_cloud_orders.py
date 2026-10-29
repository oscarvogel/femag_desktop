"""La nube abre ordenes reales desde la proyeccion de sync (#805)."""

from uuid import uuid4

from app.services.sync_snapshot_service import SyncSnapshotService
from webapp import create_app


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


def test_projected_order_opens_by_qr_token(db):
    SyncSnapshotService.apply_snapshot(_snapshot(_order()))

    response = _app().test_client().get("/orden/token-real-fabrica")

    assert response.status_code == 200
    assert b"Orden #500" in response.data
    assert b"Cliente Fabrica" in response.data
    assert b"Fecula Fabrica" in response.data
    assert b"LOTE-FABRICA-1" in response.data
    assert b"28/10/2026" in response.data
    assert "Orden sincronizada desde la fábrica".encode() in response.data
    assert b'name="lote_' not in response.data
    assert b"Guardar lote y fecha" not in response.data


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


def test_projected_order_post_does_not_edit_yet(db):
    SyncSnapshotService.apply_snapshot(_snapshot(_order()))
    client = _app().test_client()

    response = client.post(
        "/orden/token-real-fabrica",
        data={"lote_1": "OTRO"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "próxima etapa".encode() in response.data
    assert b"LOTE-FABRICA-1" in response.data


def test_annulled_projected_order_is_rejected(db):
    order = _order()
    SyncSnapshotService.apply_snapshot(_snapshot(order))
    order["status"] = "Anulada"
    order["version"] = 2
    SyncSnapshotService.apply_snapshot(_snapshot(order, cursor=2))

    response = _app().test_client().get("/orden/token-real-fabrica")

    assert response.status_code == 409
    assert b"anulada" in response.data.lower()
