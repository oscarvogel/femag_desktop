"""QR de orden con URL configurable y escritura protegida (#801)."""

from datetime import date

import pytest

from conftest import _master_data

from app.models.audit import AuditLog
from app.models.load_orders import LoadOrder, LoadOrderProduct
from app.services.auth_service import AuthService
from app.services.webapp_configuration_service import (
    WebappConfigurationError,
    WebappConfigurationService,
    normalize_public_url,
)
from webapp import create_app
from webapp.order_service import InvalidQrPayloadError, normalize_qr_token

PASSWORD = "clave-de-prueba-123"


def _order_with_line():
    data = _master_data()
    order = LoadOrder.create(
        order_number=80101,
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
    )
    line = LoadOrderProduct.create(
        order=order,
        product=data["product"],
        quantity=100,
        unit="kg",
    )
    return order, line


def _app():
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)
    return app


def _create_user(username="operador"):
    return AuthService().create_user(
        username,
        PASSWORD,
        "Secretaría",
        display_name=username,
        actor="test",
    )


def _login(client, username="operador"):
    return client.post("/login", data={"username": username, "password": PASSWORD})


def _csrf_after_get(client, token):
    client.get(f"/orden/{token}")
    with client.session_transaction() as session:
        return session["femag_csrf_token"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("http://192.168.0.111:8000", "http://192.168.0.111:8000"),
        ("http://192.168.0.111:8000/", "http://192.168.0.111:8000"),
        (" https://femag.lan ", "https://femag.lan"),
        ("", ""),
    ],
)
def test_normalize_public_url_accepts_valid_base(raw, expected):
    assert normalize_public_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "192.168.0.111:8000",
        "ftp://femag.lan",
        "http://",
        "http://femag.lan:99999",
        "http://femag.lan/api",
        "http://usuario:clave@femag.lan",
        "http://femag.lan/?x=1",
    ],
)
def test_normalize_public_url_rejects_invalid_base(raw):
    with pytest.raises(WebappConfigurationError):
        normalize_public_url(raw)


def test_service_persists_base_and_builds_order_url(db):
    saved = WebappConfigurationService.save_public_url("http://192.168.0.111:8000/")

    assert saved == "http://192.168.0.111:8000"
    assert WebappConfigurationService.public_url() == saved
    assert WebappConfigurationService.order_url("token-abc") == (
        "http://192.168.0.111:8000/orden/token-abc"
    )

    WebappConfigurationService.save_public_url("")
    assert WebappConfigurationService.public_url() == ""
    assert WebappConfigurationService.order_url("token-abc") == ""


def test_normalize_qr_token_accepts_new_url_and_legacy_payload():
    assert normalize_qr_token("http://192.168.0.111:8000/orden/token-abc") == "token-abc"
    assert normalize_qr_token("/orden/token-abc") == "token-abc"
    assert normalize_qr_token("FEMAG:LOAD_ORDER:token-abc") == "token-abc"
    assert normalize_qr_token("token-abc") == "token-abc"


def test_normalize_qr_token_rejects_foreign_url():
    with pytest.raises(InvalidQrPayloadError):
        normalize_qr_token("https://otro-sitio.com/otra-cosa/token-abc")


def test_post_without_login_does_not_change_lot(db):
    order, line = _order_with_line()
    client = _app().test_client()

    response = client.post(
        f"/orden/{order.qr_token}",
        data={
            f"lote_{line.id}": "LOTE-SIN-LOGIN",
            f"fecha_{line.id}": "2026-08-27",
        },
    )

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert LoadOrderProduct.get_by_id(line.id).lote is None


def test_post_without_csrf_is_rejected(db):
    order, line = _order_with_line()
    _create_user()
    client = _app().test_client()
    _login(client)

    response = client.post(
        f"/orden/{order.qr_token}",
        data={
            f"lote_{line.id}": "LOTE-SIN-CSRF",
            f"fecha_{line.id}": "2026-08-27",
        },
    )

    assert response.status_code == 400
    assert LoadOrderProduct.get_by_id(line.id).lote is None


def test_post_with_login_and_csrf_updates_and_audits(db):
    order, line = _order_with_line()
    _create_user()
    client = _app().test_client()
    _login(client)
    csrf = _csrf_after_get(client, order.qr_token)

    response = client.post(
        f"/orden/{order.qr_token}",
        data={
            "csrf_token": csrf,
            f"lote_{line.id}": "LOTE-2026-08",
            f"fecha_{line.id}": "2026-08-27",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    line = LoadOrderProduct.get_by_id(line.id)
    assert line.lote == "LOTE-2026-08"
    assert line.fecha_elaboracion == date(2026, 8, 27)

    rows = list(AuditLog.select().where(AuditLog.action == "carga de lote"))
    assert len(rows) == 1
    assert rows[0].user == "operador"
    assert rows[0].module == "Despachos"
    assert rows[0].workstation == "127.0.0.1"
    assert rows[0].new_value["orden"] == 80101
    assert rows[0].new_value["renglones"][0]["lote"] == "LOTE-2026-08"
