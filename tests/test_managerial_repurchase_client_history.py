"""Historial mensual de compras por cliente en el analisis de recompra."""

from calendar import monthrange
from datetime import date
from uuid import uuid4

from app.services.auth_service import AuthService
from webapp import create_app
from webapp.managerial_repurchase_service import ManagerialRepurchaseService

PASSWORD = "clave-de-prueba-123"


def _shift_month(value: date, offset: int) -> date:
    index = value.year * 12 + (value.month - 1) + offset
    return date(index // 12, index % 12 + 1, 1)


def _row(name, tonnes, total=0.0, salesperson="Vendedor Uno"):
    return {
        "client_name": name,
        "salesperson_name": salesperson,
        "previous_tonnes": 0.0,
        "current_tonnes": tonnes,
        "diff_tonnes": tonnes,
        "variation_percent": None,
        "previous_total": 0.0,
        "current_total": total,
        "previous_last_date": None,
        "current_last_date": "2026-03-20",
        "status": "compro_mas",
    }


def _snapshot(month: date, rows: list[dict]) -> dict:
    start = month
    end = date(month.year, month.month, monthrange(month.year, month.month)[1])
    previous_start = _shift_month(month, -1)
    previous_end = date(
        previous_start.year,
        previous_start.month,
        monthrange(previous_start.year, previous_start.month)[1],
    )
    current_tonnes = round(sum(row["current_tonnes"] for row in rows), 3)
    return {
        "schema_version": "1.0",
        "snapshot_id": str(uuid4()),
        "generated_at": f"{end.isoformat()}T23:00:00Z",
        "period": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "label": start.strftime("%B"),
        },
        "previous_period": {
            "start": previous_start.isoformat(),
            "end": previous_end.isoformat(),
            "label": previous_start.strftime("%B"),
        },
        "summary": {
            "previous_tonnes": 0.0,
            "current_tonnes": current_tonnes,
            "diff_tonnes": current_tonnes,
            "count_sin_recompra": 0,
            "count_redujeron": 0,
            "count_aumentaron": len(rows),
            "count_nuevos": 0,
            "reconciliation_ok": True,
        },
        "rows": rows,
    }


def _store(month: date, rows: list[dict]) -> None:
    ManagerialRepurchaseService.apply_snapshot(_snapshot(month, rows))


def _app():
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


def test_client_history_builds_months_and_fills_gaps(db):
    _store(date(2026, 1, 1), [_row("CLIENTE ALFA", 10.0, 5_000_000.0)])
    _store(date(2026, 2, 1), [_row("CLIENTE BETA", 4.0, 2_000_000.0)])
    _store(date(2026, 3, 1), [_row("CLIENTE ALFA", 20.0, 12_000_000.0)])

    view = ManagerialRepurchaseService.client_history(
        "  cliente   alfa ", "2026-03-01"
    )

    assert view["empty"] is False
    assert view["client"] == "CLIENTE ALFA"
    assert [point["tonnes"] for point in view["points"]] == [10.0, 0.0, 20.0]
    assert [point["short"] for point in view["points"]] == ["Ene", "Feb", "Mar"]
    assert view["total_tonnes"] == 30.0
    assert view["active_months"] == 2
    assert view["best"]["label"] == "Mar 2026"
    assert view["worst"]["label"] == "Ene 2026"
    assert view["points"][0]["variation_text"] == "Sin base"
    assert view["points"][1]["variation_text"] == "−100,0%"
    assert view["points"][2]["variation_text"] == "Sin base"


def test_client_history_limits_to_months_before_selected_period(db):
    for offset in range(4):
        month = _shift_month(date(2026, 1, 1), offset)
        _store(month, [_row("CLIENTE ALFA", 10.0, 5_000_000.0)])

    view = ManagerialRepurchaseService.client_history(
        "CLIENTE ALFA", "2026-02-01", months=12
    )

    assert [point["start"] for point in view["points"]] == [
        "2026-01-01",
        "2026-02-01",
    ]


def test_client_history_returns_empty_when_client_never_bought(db):
    _store(date(2026, 1, 1), [_row("CLIENTE BETA", 4.0, 2_000_000.0)])

    view = ManagerialRepurchaseService.client_history(
        "CLIENTE INEXISTENTE", "2026-01-01"
    )

    assert view["empty"] is True
    assert "no registra compras" in view["error"]


def test_client_history_route_returns_json_for_manager(db):
    _store(date(2026, 1, 1), [_row("CLIENTE ALFA", 10.0, 5_000_000.0)])
    _store(date(2026, 2, 1), [_row("CLIENTE ALFA", 20.0, 12_000_000.0)])
    client = _app().test_client()
    _login(client)

    response = client.get(
        "/gerencia/recompra/cliente",
        query_string={"cliente": "CLIENTE ALFA", "period": "2026-02-01"},
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["client"] == "CLIENTE ALFA"
    assert [point["tonnes"] for point in data["points"]] == [10.0, 20.0]
    assert data["total_tonnes_text"] == "30,00"


def test_client_history_route_rejects_non_manager(db):
    client = _app().test_client()
    _login(client, profile="Secretaría")

    response = client.get(
        "/gerencia/recompra/cliente",
        query_string={"cliente": "CLIENTE ALFA"},
    )

    assert response.status_code == 403


def test_client_history_route_requires_client_name(db):
    client = _app().test_client()
    _login(client)

    response = client.get("/gerencia/recompra/cliente")

    assert response.status_code == 400


def test_repurchase_page_renders_history_button_and_dialog(db):
    _store(date(2026, 3, 1), [_row("CLIENTE ALFA", 20.0, 12_000_000.0)])
    client = _app().test_client()
    _login(client)

    response = client.get("/gerencia/recompra", query_string={"period": "2026-03-01"})

    assert response.status_code == 200
    assert b"data-history-client" in response.data
    assert b"Ver meses" in response.data
    assert b"historial-cliente" in response.data
    assert b"Historial de compras" in response.data
