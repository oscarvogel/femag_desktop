"""Agente publicador: snapshot de fabrica y cliente HTTPS (#804)."""

import io
import json
import urllib.error
from datetime import date
from decimal import Decimal

import pytest

from conftest import _master_data

from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.models.sync import SyncCursor
from app.services.sync_http_client import SyncHttpClient, SyncHttpError
from app.services.sync_order_publisher import SyncOrderPublisher


def _order(number=94001, *, with_destination=True):
    data = _master_data()
    order = LoadOrder.create(
        order_number=number,
        client=data["client"] if with_destination else None,
        delivery_address=data["address"] if with_destination else None,
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        status=LoadOrder.STATUS_ISSUED,
    )
    line = LoadOrderProduct.create(
        order=order,
        product=data["product"],
        quantity=100,
        unit="kg",
    )
    pallet = LoadOrderPallet.create(
        order=order,
        pallet_type=data["pallet"],
        sequence=1,
        weight=12.5,
    )
    return order, line, pallet, data


class _FakeClient:
    def __init__(self):
        self.snapshots = []

    def post_snapshot(self, snapshot):
        self.snapshots.append(snapshot)
        return {"accepted": len(snapshot["orders"])}


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.payload


class _FakeOpener:
    def __init__(self, payload=b'{"ok": true}'):
        self.payload = payload
        self.request = None
        self.timeout = None

    def open(self, request, timeout=None, **kwargs):
        self.request = request
        self.timeout = timeout
        return _FakeResponse(self.payload)


def test_build_order_payload_has_stable_uids_and_minimum_fields(db):
    order, line, pallet, data = _order()
    publisher = SyncOrderPublisher()

    first = publisher.build_order(order)
    second = publisher.build_order(order)

    assert first["order_uid"] == second["order_uid"]
    assert first["order_uid"]
    assert first["qr_token"] == order.qr_token
    assert first["order_number"] == 94001
    assert first["client"]["name"] == data["client"].name
    assert first["destination"]["city"] == data["address"].city
    assert first["lines"][0]["line_uid"] == second["lines"][0]["line_uid"]
    assert first["lines"][0]["product_name"] == data["product"].name
    assert first["pallets"][0]["pallet_uid"] == second["pallets"][0]["pallet_uid"]
    assert first["pallets"][0]["sequence"] == pallet.sequence


def test_publish_snapshot_sends_orders_and_updates_local_cursor(db):
    _order()
    client = _FakeClient()
    result = SyncOrderPublisher().publish_snapshot(client)

    assert len(client.snapshots) == 1
    assert len(client.snapshots[0]["orders"]) == 1
    assert result["orders"] == 1
    assert result["skipped"] == []
    cursor = SyncCursor.get(
        SyncCursor.stream == SyncCursor.STREAM_FACTORY_SNAPSHOT
    )
    assert cursor.cursor_value == client.snapshots[0]["cursor"]
    assert 0 < client.snapshots[0]["cursor"] <= 2_147_483_647


def test_snapshot_includes_closed_orders(db):
    order, _, _, _ = _order(number=94003)
    order.status = LoadOrder.STATUS_CLOSED
    order.save(only=[LoadOrder.status])
    client = _FakeClient()

    result = SyncOrderPublisher().publish_snapshot(client)

    assert result["orders"] == 1
    assert client.snapshots[0]["orders"][0]["status"] == "Cerrada"


def test_publisher_skips_order_without_client_and_destination(db):
    _order(number=94002, with_destination=False)
    client = _FakeClient()
    result = SyncOrderPublisher().publish_snapshot(client)

    assert result["orders"] == 0
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["order_number"] == 94002


def test_http_client_sends_bearer_token_and_parses_json():
    opener = _FakeOpener(b'{"accepted": 1}')
    client = SyncHttpClient(
        "https://sync.example/",
        "token-secreto",
        opener=opener,
    )

    result = client.post_snapshot({"orders": []})

    assert result == {"accepted": 1}
    assert opener.request.full_url == "https://sync.example/api/sync/v1/snapshots/orders"
    assert opener.request.get_method() == "POST"
    assert opener.request.get_header("Authorization") == "Bearer token-secreto"
    assert client.timeout == 90


def test_http_client_posts_managerial_snapshot():
    opener = _FakeOpener(b'{"accepted": true}')
    client = SyncHttpClient(
        "https://sync.example",
        "token",
        opener=opener,
    )

    result = client.post_managerial_snapshot({"schema_version": "1.0"})

    assert result == {"accepted": True}
    assert opener.request.full_url == (
        "https://sync.example/api/sync/v1/snapshots/managerial"
    )


def test_http_client_posts_repurchase_snapshot():
    opener = _FakeOpener(b'{"accepted": true}')
    client = SyncHttpClient(
        "https://sync.example",
        "token",
        opener=opener,
    )

    result = client.post_managerial_repurchase_snapshot({"schema_version": "1.0"})

    assert result == {"accepted": True}
    assert opener.request.full_url == (
        "https://sync.example/api/sync/v1/snapshots/managerial-repurchase"
    )


def test_http_client_rejects_http_without_explicit_override():
    with pytest.raises(ValueError):
        SyncHttpClient("http://sync.example", "token")

    client = SyncHttpClient(
        "http://sync.example",
        "token",
        opener=_FakeOpener(),
        allow_http=True,
    )
    assert client.base_url == "http://sync.example"


def test_http_client_maps_http_errors():
    class _ErrorOpener:
        def open(self, request, timeout=None, **kwargs):
            raise urllib.error.HTTPError(
                request.full_url,
                409,
                "conflict",
                {},
                io.BytesIO(json.dumps({"error": "version_conflict"}).encode()),
            )

    client = SyncHttpClient(
        "https://sync.example",
        "token",
        opener=_ErrorOpener(),
    )

    with pytest.raises(SyncHttpError) as exc:
        client.post_snapshot({})

    assert exc.value.status == 409
    assert "version_conflict" in exc.value.body


def test_http_client_retries_transient_snapshot_errors(monkeypatch):
    class _FlakyOpener:
        calls = 0

        def open(self, request, timeout=None, **kwargs):
            self.calls += 1
            if self.calls < 3:
                raise ConnectionResetError("remote closed")
            return _FakeResponse(b'{"accepted": 1}')

    monkeypatch.setattr(
        "app.services.sync_http_client.time.sleep", lambda _seconds: None
    )
    opener = _FlakyOpener()
    client = SyncHttpClient(
        "https://sync.example",
        "token",
        opener=opener,
    )

    assert client.post_snapshot({"orders": []}) == {"accepted": 1}
    assert opener.calls == 3


def test_snapshot_includes_pallet_and_loose_contents(db):
    data = _master_data()
    order = LoadOrder.create(
        order_number=94004,
        client=data["client"],
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        status=LoadOrder.STATUS_ISSUED,
    )
    destination = LoadOrderDestination.create(
        order=order,
        client=data["client"],
        delivery_address=data["address"],
        sequence=1,
    )
    LoadOrderProduct.create(
        order=order,
        destination=destination,
        product=data["product"],
        quantity=80,
        unit="bolsa",
        lote="LOTE-RENGLON",
        fecha_elaboracion=date(2026, 10, 20),
    )
    pallet = LoadOrderPallet.create(order=order, sequence=1)
    allocation = LoadOrderPalletAllocation.create(
        pallet=pallet,
        destination=destination,
        product=data["product"],
        quantity=60,
        peso_unitario_kg=Decimal("25"),
        lote="LOTE-PALLET",
        fecha_elaboracion=date(2026, 10, 21),
    )
    loose = LoadOrderLooseAllocation.create(
        order=order,
        destination=destination,
        product=data["product"],
        quantity=20,
        peso_unitario_kg=Decimal("25"),
        lote="LOTE-SUELTO",
        fecha_elaboracion=date(2026, 10, 22),
    )

    first = SyncOrderPublisher().build_order(order)
    second = SyncOrderPublisher().build_order(order)

    content = first["pallets"][0]["contents"][0]
    loose_content = first["loose_contents"][0]
    assert content["content_uid"] == second["pallets"][0]["contents"][0]["content_uid"]
    assert content["content_uid"]
    assert content["product_name"] == data["product"].name
    assert content["quantity"] == 60
    assert content["unit"] == "bolsa"
    assert content["lote"] == "LOTE-PALLET"
    assert content["fecha_elaboracion"] == "2026-10-21"
    assert content["client_name"] == data["client"].name
    assert loose_content["content_uid"]
    assert loose_content["lote"] == "LOTE-SUELTO"
    assert loose_content["fecha_elaboracion"] == "2026-10-22"
