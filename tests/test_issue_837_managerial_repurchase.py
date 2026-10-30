"""Snapshot de recompra: publicacion, API, vista y permisos (#837)."""

from datetime import date

from app.models.sync import SyncCursor, SyncProjection
from app.services.auth_service import AuthService
from app.services.managerial_repurchase_publisher import (
    ManagerialRepurchasePublisher,
)
from webapp import create_app
from webapp.managerial_repurchase_service import ManagerialRepurchaseService

PASSWORD = "clave-de-prueba-123"
TOKEN = "token-de-prueba-sync"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


class _Dashboard:
    def product_client_repurchase(self, current, previous):
        return [
            {
                "client_id": 1,
                "client_name": "CLIENTE ALFA",
                "product_id": 10,
                "product_name": "Fecula 10 kg",
                "salesperson_name": "Vendedor Uno",
                "previous_kilos": 28500.0,
                "current_kilos": 0.0,
                "previous_tonnes": 28.5,
                "current_tonnes": 0.0,
                "diff_tonnes": -28.5,
                "previous_total": 28500000.0,
                "current_total": 0.0,
                "previous_last_date": "2026-09-10",
                "current_last_date": None,
                "status": "sin_recompra",
            },
            {
                "client_id": 1,
                "client_name": "CLIENTE ALFA",
                "product_id": 11,
                "product_name": "Fecula 1 kg",
                "salesperson_name": "",
                "previous_kilos": 10000.0,
                "current_kilos": 0.0,
                "previous_tonnes": 10.0,
                "current_tonnes": 0.0,
                "diff_tonnes": -10.0,
                "previous_total": 10000000.0,
                "current_total": 0.0,
                "previous_last_date": "2026-09-12",
                "current_last_date": None,
                "status": "sin_recompra",
            },
            {
                "client_id": 2,
                "client_name": "CLIENTE BETA",
                "product_id": 10,
                "product_name": "Fecula 10 kg",
                "salesperson_name": "Vendedor Dos",
                "previous_kilos": 10000.0,
                "current_kilos": 12000.0,
                "previous_tonnes": 10.0,
                "current_tonnes": 12.0,
                "diff_tonnes": 2.0,
                "previous_total": 9000000.0,
                "current_total": 11000000.0,
                "previous_last_date": "2026-09-20",
                "current_last_date": "2026-10-20",
                "status": "compro_mas",
            },
            {
                "client_id": 3,
                "client_name": "CLIENTE GAMMA",
                "product_id": 12,
                "product_name": "Almidon 25 kg",
                "salesperson_name": "",
                "previous_kilos": 0.0,
                "current_kilos": 5000.0,
                "previous_tonnes": 0.0,
                "current_tonnes": 5.0,
                "diff_tonnes": 5.0,
                "previous_total": 0.0,
                "current_total": 4000000.0,
                "previous_last_date": None,
                "current_last_date": "2026-10-25",
                "status": "nuevo",
            },
        ]


def _snapshot():
    return ManagerialRepurchasePublisher(
        dashboard_service=_Dashboard(), min_interval_minutes=0
    ).build(as_of=date(2026, 10, 30))


def _app(monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setenv("FEMAG_SYNC_API_TOKEN", TOKEN)
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)
    return app


def _login(client, profile="Administrador"):
    AuthService().create_user(
        "gerente",
        PASSWORD,
        profile,
        display_name="Gerente",
        actor="test",
    )
    return client.post(
        "/login", data={"username": "gerente", "password": PASSWORD}
    )


def test_repurchase_publisher_aggregates_clients_and_summary(db):
    snapshot = _snapshot()
    rows = {row["client_name"]: row for row in snapshot["rows"]}
    summary = snapshot["summary"]

    assert len(rows) == 3
    assert rows["CLIENTE ALFA"]["previous_tonnes"] == 38.5
    assert rows["CLIENTE ALFA"]["status"] == "sin_recompra"
    assert rows["CLIENTE BETA"]["status"] == "compro_mas"
    assert rows["CLIENTE GAMMA"]["status"] == "nuevo"
    assert summary["count_sin_recompra"] == 1
    assert summary["count_aumentaron"] == 1
    assert summary["count_nuevos"] == 1
    assert summary["previous_tonnes"] == 48.5
    assert summary["current_tonnes"] == 17.0
    assert summary["diff_tonnes"] == -31.5
    assert summary["reconciliation_ok"] is True


def test_repurchase_publisher_sets_cursor(db):
    class _Client:
        def __init__(self):
            self.snapshot = None

        def post_managerial_repurchase_snapshot(self, snapshot):
            self.snapshot = snapshot
            return {"accepted": True}

    client = _Client()
    ManagerialRepurchasePublisher(
        dashboard_service=_Dashboard(), min_interval_minutes=0
    ).publish(client, as_of=date(2026, 10, 30))

    assert client.snapshot["rows"]
    cursor = SyncCursor.get(
        SyncCursor.stream == SyncCursor.STREAM_FACTORY_REPURCHASE
    )
    assert cursor.cursor_value > 0


def test_repurchase_api_stores_latest_snapshot(db, monkeypatch):
    client = _app(monkeypatch).test_client()
    snapshot = _snapshot()

    response = client.post(
        "/api/sync/v1/snapshots/managerial-repurchase",
        json=snapshot,
        headers=HEADERS,
    )

    assert response.status_code == 200
    projection = SyncProjection.get(
        (SyncProjection.resource_type == SyncProjection.RESOURCE_REPURCHASE)
        & (SyncProjection.resource_uid == "latest")
    )
    assert projection.payload["snapshot_id"] == snapshot["snapshot_id"]
    assert projection.payload["summary"]["count_sin_recompra"] == 1


def test_repurchase_api_requires_token(db, monkeypatch):
    client = _app(monkeypatch).test_client()

    response = client.post(
        "/api/sync/v1/snapshots/managerial-repurchase",
        json=_snapshot(),
    )

    assert response.status_code == 401


def test_repurchase_view_formats_summary_and_rows(db):
    ManagerialRepurchaseService.apply_snapshot(_snapshot())

    view = ManagerialRepurchaseService.latest_view()

    assert view["empty"] is False
    assert view["previous_tonnes"] == "48,50"
    assert view["current_tonnes"] == "17,00"
    assert view["diff_tonnes"] == "−31,500"
    assert view["count_sin"] == 1
    assert view["rows"][0]["client"] == "CLIENTE ALFA"
    assert view["rows"][0]["previous_tonnes"] == "38,500"
    assert view["rows"][0]["status_label"] == "Sin recompra"
    assert view["rows"][0]["last_purchase"] == "12/09/2026"
    assert view["compare_percent"] == 35.1


def test_repurchase_route_renders_for_admin(db):
    ManagerialRepurchaseService.apply_snapshot(_snapshot())
    client = _app().test_client()
    _login(client)

    response = client.get("/gerencia/recompra")

    assert response.status_code == 200
    assert b"Clientes vs. mes anterior" in response.data
    assert b"CLIENTE ALFA" in response.data
    assert b"Sin recompra" in response.data
    assert b"filtro-cliente" in response.data
    assert b"tabla-recompra" in response.data


def test_repurchase_route_is_available_to_gerencia(db):
    ManagerialRepurchaseService.apply_snapshot(_snapshot())
    client = _app().test_client()
    _login(client, profile="Gerencia")

    response = client.get("/gerencia/recompra")

    assert response.status_code == 200
    assert "Análisis de recompra".encode() in response.data


def test_repurchase_route_redirects_non_manager(db):
    client = _app().test_client()
    _login(client, profile="Secretaría")

    response = client.get("/gerencia/recompra", follow_redirects=True)

    assert response.status_code == 200
    assert "Solo Gerencia puede ver el análisis de recompra".encode() in response.data


def test_repurchase_route_shows_empty_state(db):
    client = _app().test_client()
    _login(client)

    response = client.get("/gerencia/recompra")

    assert response.status_code == 200
    assert b"Sin datos" in response.data
    assert b"El informe se va a completar solo" in response.data
