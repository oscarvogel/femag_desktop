from datetime import date

from conftest import _master_data

from app.models.load_orders import LoadOrder, LoadOrderProduct
from webapp import create_app
from webapp.order_service import get_order_by_token, normalize_qr_token


def _order_with_line():
    data = _master_data()
    order = LoadOrder.create(
        order_number=91001,
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


def test_qr_payload_and_raw_token_resolve_same_order(db):
    order, _ = _order_with_line()

    assert normalize_qr_token(order.qr_payload()) == order.qr_token
    assert get_order_by_token(order.qr_payload()).id == order.id
    assert get_order_by_token(order.qr_token).id == order.id


def test_home_offers_camera_qr_scanner(db):
    app = create_app()
    app.config.update(TESTING=True)

    response = app.test_client().get("/")

    assert response.status_code == 200
    assert b"Escanear QR" in response.data
    assert b"BarcodeDetector" in response.data
    assert b"getUserMedia" in response.data
    assert b"qr_code" in response.data


def test_mobile_order_page_shows_order_and_product(db):
    order, _ = _order_with_line()
    app = create_app()
    app.config.update(TESTING=True)

    response = app.test_client().get(f"/orden/{order.qr_token}")

    assert response.status_code == 200
    assert b"Orden #91001" in response.data
    assert b"Fecula de mandioca" in response.data


def test_mobile_order_post_updates_lot_and_manufacture_date(db):
    order, line = _order_with_line()
    app = create_app()
    app.config.update(TESTING=True)

    response = app.test_client().post(
        f"/orden/{order.qr_token}",
        data={
            f"lote_{line.id}": "LOTE-2026-08",
            f"fecha_{line.id}": "2026-08-27",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    line = LoadOrderProduct.get_by_id(line.id)
    assert line.lote == "LOTE-2026-08"
    assert line.fecha_elaboracion == date(2026, 8, 27)
    assert b"guardados" in response.data


def test_unknown_token_returns_404(db):
    app = create_app()
    app.config.update(TESTING=True)

    response = app.test_client().get("/orden/token-inexistente")

    assert response.status_code == 404
    assert b"No se pudo abrir la orden" in response.data


def test_health_reports_database_connected(db):
    app = create_app()
    app.config.update(TESTING=True)

    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"database": True, "status": "ok"}
