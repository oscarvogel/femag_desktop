"""#911: la ficha de orden pide login antes de cargar lote y fechas.

Sin sesión, el operador no debe ver el formulario: si lo completa y guarda
después, el POST lo manda al login y se pierde todo lo cargado.
"""

import pytest

from conftest import _master_data

from app.models.load_orders import LoadOrder, LoadOrderProduct
from app.services.auth_service import AuthService
from webapp import create_app

PASSWORD = "clave-de-prueba-123"


def _app():
    app = create_app(secret_key="secreto-de-prueba")
    app.config.update(TESTING=True)
    return app


def _create_user(username="operador"):
    AuthService().create_user(
        username,
        PASSWORD,
        "Secretaría",
        display_name=username,
        actor="test",
    )


def _login(client, username="operador", next_url=None):
    url = "/login"
    if next_url:
        url = f"{url}?next={next_url}"
    return client.post(url, data={"username": username, "password": PASSWORD})


def _order():
    data = _master_data()
    order = LoadOrder.create(
        order_number=91101,
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


def test_orden_local_sin_sesion_pide_login_antes_de_mostrar_la_carga(db):
    order, _ = _order()
    client = _app().test_client()

    response = client.get(f"/orden/{order.qr_token}")

    assert response.status_code == 302
    assert (
        response.headers["Location"]
        == f"/login?next=/orden/{order.qr_token}"
    )
    assert b'name="lote_' not in response.data


def test_login_desde_la_orden_vuelve_a_la_ficha_con_la_carga(db):
    order, line = _order()
    _create_user()
    client = _app().test_client()

    response = _login(client, next_url=f"/orden/{order.qr_token}")

    assert response.status_code == 302
    assert response.headers["Location"] == f"/orden/{order.qr_token}"

    page = client.get(response.headers["Location"])

    assert page.status_code == 200
    assert f'name="lote_n{line.id}_0"'.encode() in page.data
    assert b"Guardar lote y fechas" in page.data


@pytest.mark.parametrize(
    "next_url",
    [
        "https://otro-sitio.com/orden/token",
        "//otro-sitio.com/orden/token",
    ],
)
def test_login_no_acepta_un_next_externo(db, next_url):
    _create_user()
    client = _app().test_client()

    response = _login(client, next_url=next_url)

    assert response.status_code == 302
    assert response.headers["Location"] == "/produccion"


def test_post_sin_sesion_no_escribe_y_manda_al_login(db):
    order, line = _order()
    client = _app().test_client()

    response = client.post(
        f"/orden/{order.qr_token}",
        data={
            f"lote_n{line.id}_0": "LOTE-SIN-LOGIN",
            f"fecha_n{line.id}_0": "2026-11-10",
        },
    )

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert LoadOrderProduct.get_by_id(line.id).lote is None
