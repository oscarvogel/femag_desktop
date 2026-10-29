"""Endurecimiento HTTPS y limite de intentos de login de la webapp (#803)."""

from datetime import timedelta

from conftest import _master_data

from app.models.load_orders import LoadOrder
from app.services.auth_service import AuthService
from webapp import create_app
from webapp.auth import MAX_FAILED_LOGINS, SESSION_LIFETIME

PASSWORD = "clave-de-prueba-123"


def _order(number=93001):
    data = _master_data()
    return LoadOrder.create(
        order_number=number,
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
    )


def test_https_sets_secure_cookie_session_lifetime_and_headers(db, monkeypatch):
    monkeypatch.setenv("FEMAG_WEB_PUBLIC_URL", "https://femag.example")
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)
    order = _order()

    response = app.test_client().get(
        f"/orden/{order.qr_token}", base_url="https://femag.example"
    )

    assert response.status_code == 200
    assert app.permanent_session_lifetime == SESSION_LIFETIME == timedelta(hours=12)
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert "camera=(self)" in response.headers["Permissions-Policy"]
    assert response.headers["Strict-Transport-Security"].startswith("max-age=")
    cookie = response.headers["Set-Cookie"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_http_does_not_force_secure_cookie_or_hsts(db, monkeypatch):
    monkeypatch.delenv("FEMAG_WEB_PUBLIC_URL", raising=False)
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)
    order = _order(number=93002)

    response = app.test_client().get(f"/orden/{order.qr_token}")

    assert response.status_code == 200
    cookie = response.headers["Set-Cookie"]
    assert "Secure" not in cookie
    assert "HttpOnly" in cookie
    assert "Strict-Transport-Security" not in response.headers


def test_login_is_blocked_after_repeated_failures(db, monkeypatch):
    monkeypatch.delenv("FEMAG_WEB_PUBLIC_URL", raising=False)
    AuthService().create_user(
        "operador",
        PASSWORD,
        "Secretaría",
        display_name="operador",
        actor="test",
    )
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)
    client = app.test_client()

    for _ in range(MAX_FAILED_LOGINS):
        response = client.post(
            "/login",
            data={"username": "operador", "password": "clave-incorrecta"},
        )
        assert response.status_code == 200

    blocked = client.post(
        "/login",
        data={"username": "operador", "password": PASSWORD},
    )

    assert blocked.status_code == 429
    assert b"Demasiados intentos" in blocked.data
    with client.session_transaction() as session:
        assert "femag_username" not in session
