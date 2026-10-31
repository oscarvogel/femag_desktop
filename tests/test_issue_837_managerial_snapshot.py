"""Snapshot gerencial: publicacion, API, lectura y permisos (#837)."""

from dataclasses import dataclass
from datetime import date
from uuid import uuid4

from app.models.sync import SyncCursor, SyncProjection
from app.reports.managerial_dashboard import ReportPeriod
from app.services.auth_service import AuthService
from app.services.managerial_snapshot_publisher import (
    ManagerialSnapshotPublisher,
)
from webapp import create_app
from webapp.managerial_dashboard_service import ManagerialDashboardService
from webapp.managerial_repurchase_service import ManagerialRepurchaseService

PASSWORD = "clave-de-prueba-123"
TOKEN = "token-de-prueba-sync"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@dataclass
class _Metric:
    current: float
    previous: float

    @property
    def variation_percent(self):
        if self.previous == 0:
            return None if self.current else 0.0
        return round((self.current - self.previous) / self.previous * 100, 1)


class _Dashboard:
    def snapshot(self, period):
        return type(
            "Snapshot",
            (),
            {
                "period": period,
                "previous_period": period.previous_equivalent(),
                "currency": "ARS",
                "valued_dispatches": _Metric(284_600_000, 253_200_000),
                "tonnes": _Metric(312.4, 289.0),
                "orders": _Metric(186, 178),
                "average_ticket": _Metric(1_530_000, 1_422_000),
                "monthly_evolution": tuple(
                    {
                        "period": f"2026-{month:02d}",
                        "label": f"{month:02d}/2026",
                        "total": 100_000_000 + month * 1_000_000,
                        "tonnes": 100.0 + month,
                        "orders": 10 + month,
                    }
                    for month in range(1, 11)
                )
                + (
                    {
                        "period": "2026-10",
                        "label": "10/2026",
                        "total": 284_600_000,
                        "tonnes": 312.4,
                        "orders": 186,
                    },
                ),
                "top_clients": (
                    {
                        "name": "Molinos del Litoral",
                        "total": 42_800_000,
                        "tonnes": 61.2,
                        "previous_total": 36_200_000,
                        "previous_tonnes": 55.0,
                        "variation_percent": 18.2,
                    },
                    {
                        "name": "Alimentos del Sur",
                        "total": 27_600_000,
                        "tonnes": 40.0,
                        "previous_total": 28_200_000,
                        "previous_tonnes": 41.0,
                        "variation_percent": -2.1,
                    },
                ),
                "top_products": (
                    {
                        "name": "Fecula nativa 10 kg",
                        "total": 78_400_000,
                        "tonnes": 78.4,
                        "previous_total": 71_000_000,
                        "previous_tonnes": 72.0,
                        "variation_percent": 9.4,
                    },
                ),
            },
        )()


class _Client:
    def __init__(self):
        self.snapshot = None

    def post_managerial_snapshot(self, snapshot):
        self.snapshot = snapshot
        return {"accepted": True}


def _snapshot():
    return {
        "schema_version": "1.0",
        "snapshot_id": str(uuid4()),
        "generated_at": "2026-10-30T12:00:00Z",
        "period": {
            "start": "2026-10-01",
            "end": "2026-10-30",
            "label": "Este mes",
        },
        "previous_period": {
            "start": "2026-09-01",
            "end": "2026-09-30",
            "label": "Este mes anterior",
        },
        "currency": "ARS",
        "kpis": {
            "valued_dispatches": {
                "current": 284_600_000,
                "previous": 253_200_000,
                "variation_percent": 12.4,
            },
            "tonnes": {
                "current": 312.4,
                "previous": 289.0,
                "variation_percent": 8.1,
            },
            "orders": {
                "current": 186,
                "previous": 178,
                "variation_percent": 4.5,
            },
            "average_ticket": {
                "current": 1_530_000,
                "previous": 1_422_000,
                "variation_percent": 7.6,
            },
        },
        "monthly_evolution": [
            {
                "period": "2026-09",
                "label": "Sep",
                "total": 296_000_000,
                "tonnes": 300.0,
                "orders": 180,
                "partial": False,
            },
            {
                "period": "2026-10",
                "label": "Oct",
                "total": 284_600_000,
                "tonnes": 312.4,
                "orders": 186,
                "partial": True,
            },
        ],
        "top_clients": [
            {
                "name": "Molinos del Litoral",
                "total": 42_800_000,
                "tonnes": 61.2,
                "previous_total": 36_200_000,
                "previous_tonnes": 55.0,
                "variation_percent": 18.2,
            },
            {
                "name": "Alimentos del Sur",
                "total": 27_600_000,
                "tonnes": 40.0,
                "previous_total": 28_200_000,
                "previous_tonnes": 41.0,
                "variation_percent": -2.1,
            },
        ],
        "top_products": [
            {
                "name": "Fecula nativa 10 kg",
                "total": 78_400_000,
                "tonnes": 78.4,
                "previous_total": 71_000_000,
                "previous_tonnes": 72.0,
                "variation_percent": 9.4,
            }
        ],
    }


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


def test_publisher_builds_aggregate_snapshot_without_raw_rows():
    publisher = ManagerialSnapshotPublisher(
        dashboard_service=_Dashboard(), min_interval_minutes=0
    )

    snapshot = publisher.build(as_of=date(2026, 10, 30))

    assert snapshot["schema_version"] == "1.0"
    assert snapshot["period"]["start"] == "2026-10-01"
    assert snapshot["kpis"]["valued_dispatches"]["current"] == 284_600_000
    assert snapshot["monthly_evolution"][-1]["partial"] is True
    assert snapshot["top_clients"][0]["name"] == "Molinos del Litoral"
    assert "lines" not in snapshot
    assert "orders" not in snapshot


def test_publisher_sets_managerial_cursor(db):
    client = _Client()
    publisher = ManagerialSnapshotPublisher(
        dashboard_service=_Dashboard(), min_interval_minutes=0
    )

    result = publisher.publish(client, as_of=date(2026, 10, 30))

    assert result["snapshot_id"] == client.snapshot["snapshot_id"]
    cursor = SyncCursor.get(
        SyncCursor.stream == SyncCursor.STREAM_FACTORY_MANAGERIAL
    )
    assert cursor.cursor_value > 0


def test_managerial_api_stores_latest_projection(db, monkeypatch):
    client = _app(monkeypatch).test_client()
    snapshot = _snapshot()

    response = client.post(
        "/api/sync/v1/snapshots/managerial",
        json=snapshot,
        headers=HEADERS,
    )

    assert response.status_code == 200
    projection = SyncProjection.get(
        (SyncProjection.resource_type == SyncProjection.RESOURCE_MANAGERIAL)
        & (SyncProjection.resource_uid == "latest")
    )
    assert projection.payload["snapshot_id"] == snapshot["snapshot_id"]
    assert projection.payload["kpis"]["orders"]["current"] == 186
    assert "lines" not in projection.payload


def test_managerial_api_requires_token(db, monkeypatch):
    client = _app(monkeypatch).test_client()

    response = client.post("/api/sync/v1/snapshots/managerial", json=_snapshot())

    assert response.status_code == 401


def test_managerial_api_rejects_incomplete_snapshot(db, monkeypatch):
    client = _app(monkeypatch).test_client()
    snapshot = _snapshot()
    snapshot.pop("kpis")

    response = client.post(
        "/api/sync/v1/snapshots/managerial",
        json=snapshot,
        headers=HEADERS,
    )

    assert response.status_code == 422


def test_managerial_view_formats_and_derives_insights(db):
    ManagerialDashboardService.apply_snapshot(_snapshot())

    view = ManagerialDashboardService.latest_view()

    assert view["period_label"] == "Octubre 2026"
    assert view["kpis"]["ventas"]["value"] == "$ 284,6 M"
    assert view["kpis"]["ventas"]["delta"] == "+12,4%"
    assert view["kpis"]["ventas"]["direction"] == "up"
    assert view["chart"][0]["value"] == 296.0
    assert view["chart"][-1]["value"] == 284.6
    assert view["top_clients"][0]["bar_percent"] == 100.0
    assert view["top_products"][0]["value"] == "78,4 TN"
    assert view["insights"][0]["value"] == "25%"
    assert view["insights"][-1]["label"] == "A vigilar"




def _repurchase_snapshot():
    return {
        "schema_version": "1.0",
        "snapshot_id": str(uuid4()),
        "generated_at": "2026-10-30T12:00:00Z",
        "period": {"start": "2026-10-01", "end": "2026-10-30", "label": "Este mes"},
        "previous_period": {"start": "2026-09-01", "end": "2026-09-30", "label": "Anterior"},
        "summary": {
            "previous_tonnes": 312.4,
            "current_tonnes": 270.8,
            "diff_tonnes": -41.6,
            "variation_percent": -3.1,
            "previous_total": 284_600_000,
            "current_total": 270_800_000,
            "buyers_previous": 4,
            "buyers_current": 3,
            "count_sin_recompra": 1,
            "count_redujeron": 1,
            "count_aumentaron": 1,
            "count_nuevos": 1,
            "count_sin_cambios": 0,
            "lost_tonnes": 20.0,
            "reduction_tonnes": -5.0,
            "increase_tonnes": 3.0,
            "new_tonnes": 10.0,
            "reconciled_diff_tonnes": -41.6,
            "reconciliation_ok": True,
        },
        "rows": [
            {
                "client_name": "CLIENTE PERDIDO",
                "salesperson_name": "Vendedor Uno",
                "previous_last_date": "2026-09-10",
                "current_last_date": None,
                "previous_tonnes": 20.0,
                "current_tonnes": 0.0,
                "diff_tonnes": -20.0,
                "variation_percent": -100.0,
                "previous_total": 20_000_000,
                "current_total": 0,
                "status": "sin_recompra",
            }
        ],
    }




def test_gerencia_manifest_is_installable(db):
    response = _app().test_client().get("/gerencia/manifest.webmanifest")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["name"] == "FEMAG Gerencia"
    assert payload["start_url"] == "/gerencia"
    assert payload["scope"] == "/"
    assert payload["display"] == "standalone"
    assert {icon["sizes"] for icon in payload["icons"]} >= {"192x192", "512x512"}


def test_gerencia_page_includes_pwa_registration(db):
    client = _app().test_client()
    _login(client)

    response = client.get("/gerencia")

    assert response.status_code == 200
    assert b"gerencia/manifest.webmanifest" in response.data
    assert b'id="pwa-install-button"' in response.data
    assert b"service-worker.js" in response.data
    assert b'href="/logout"' in response.data


def test_dashboard_v3_renders_waterfall_and_cohort(db):
    ManagerialDashboardService.apply_snapshot(_snapshot())
    ManagerialRepurchaseService.apply_snapshot(_repurchase_snapshot())
    client = _app().test_client()
    _login(client)

    response = client.get("/gerencia")

    assert response.status_code == 200
    assert "Puente de Variación de Volumen".encode() in response.data
    assert "Radiografía de Cartera".encode() in response.data
    assert b"CLIENTE PERDIDO" in response.data
    assert "Facturación Despachada".encode() in response.data


def test_dashboard_route_renders_for_administrator(db):
    ManagerialDashboardService.apply_snapshot(_snapshot())
    client = _app().test_client()
    _login(client)

    response = client.get("/gerencia")

    assert response.status_code == 200
    assert b"Octubre 2026" in response.data
    assert "Facturación Despachada".encode() in response.data
    assert b"Molinos del Litoral" in response.data
    assert b"Matriz de Productos Despachados" in response.data
    assert "Puente de Variación de Volumen".encode() in response.data


def test_dashboard_route_is_available_to_gerencia(db):
    ManagerialDashboardService.apply_snapshot(_snapshot())
    client = _app().test_client()
    _login(client, profile="Gerencia")

    response = client.get("/gerencia")

    assert response.status_code == 200
    assert "Monitor de Dirección Comercial".encode() in response.data


def test_dashboard_route_redirects_non_manager(db):
    client = _app().test_client()
    _login(client, profile="Secretaría")

    response = client.get("/gerencia", follow_redirects=True)

    assert response.status_code == 200
    assert b"Solo Gerencia puede ver el dashboard gerencial" in response.data


def test_dashboard_route_shows_empty_state_without_snapshot(db):
    client = _app().test_client()
    _login(client)

    response = client.get("/gerencia")

    assert response.status_code == 200
    assert b"Sin datos" in response.data
    assert b"este tablero se completa solo" in response.data
