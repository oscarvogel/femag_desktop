"""Consumidor de eventos cloud -> fabrica (#804/#805)."""

from datetime import date

from conftest import _master_data

from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
)
from app.models.sync import SyncConflict, SyncCursor, SyncEntityMap, SyncInbox
from app.services.sync_event_consumer import SyncEventConsumer
from app.services.sync_service import SyncService


class _FakeClient:
    def __init__(self, events):
        self.events = events
        self.acks = []

    def get_events(self, cursor=0, limit=50):
        return {"events": self.events, "next_cursor": cursor}

    def ack_event(self, event_id, result, error=None):
        self.acks.append((event_id, result, error))
        return {"event_id": event_id, "result": result}


def _factory_order():
    data = _master_data()
    order = LoadOrder.create(
        order_number=95001,
        client=data["client"],
        delivery_address=data["address"],
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
    order_map = SyncService.ensure_entity_uid(
        "order", order.id
    )
    line_map = SyncService.ensure_entity_uid(
        "order_line", line.id
    )
    return order, line, order_map, line_map


def _event(order_map, line_map, *, expected=1, lote="LOTE-NUBE"):
    return {
        "event_id": "evento-lote-1",
        "event_type": "order_lote_fecha_updated",
        "origin": "cloud",
        "aggregate_type": "order_line",
        "aggregate_id": line_map.global_uid,
        "aggregate_version": expected,
        "cursor": 1,
        "occurred_at": "2026-10-29T12:00:00Z",
        "payload": {
            "order_uid": order_map.global_uid,
            "line_uid": line_map.global_uid,
            "lote": lote,
            "fecha_elaboracion": "2026-10-29",
            "expected_version": expected,
        },
    }


def test_consumer_applies_lote_and_fecha(db):
    order, line, order_map, line_map = _factory_order()
    client = _FakeClient([_event(order_map, line_map)])

    result = SyncEventConsumer(client).pull_and_apply()

    assert result["applied"] == 1
    line = LoadOrderProduct.get_by_id(line.id)
    assert line.lote == "LOTE-NUBE"
    assert line.fecha_elaboracion == date(2026, 10, 29)
    assert SyncInbox.get(SyncInbox.event_id == "evento-lote-1").status == "applied"
    assert client.acks == [("evento-lote-1", "applied", None)]
    assert SyncCursor.get(SyncCursor.stream == SyncCursor.STREAM_CLOUD).cursor_value == 1


def test_consumer_rejects_annulled_order(db):
    order, line, order_map, line_map = _factory_order()
    order.status = LoadOrder.STATUS_ANNULLED
    order.save(only=[LoadOrder.status])
    client = _FakeClient([_event(order_map, line_map)])

    result = SyncEventConsumer(client).pull_and_apply()

    assert result["rejected"] == 1
    assert LoadOrderProduct.get_by_id(line.id).lote is None
    assert client.acks[0][1] == "rejected"
    assert SyncConflict.select().where(SyncConflict.status == "open").count() == 1


def test_consumer_detects_version_conflict(db):
    order, line, order_map, line_map = _factory_order()
    order_map.local_version = 2
    order_map.save(only=[order_map.__class__.local_version])
    client = _FakeClient([_event(order_map, line_map, expected=1)])

    result = SyncEventConsumer(client).pull_and_apply()

    assert result["conflicts"] == 1
    assert LoadOrderProduct.get_by_id(line.id).lote is None
    assert client.acks[0][1] == "conflict"
    assert SyncConflict.select().where(SyncConflict.status == "open").count() == 1


def test_consumer_does_not_apply_duplicate_event_twice(db):
    order, line, order_map, line_map = _factory_order()
    client = _FakeClient([_event(order_map, line_map)])

    SyncEventConsumer(client).pull_and_apply()
    SyncEventConsumer(client).pull_and_apply()

    assert SyncInbox.select().count() == 1
    assert len(client.acks) == 2
    assert client.acks[1][1] == "applied"


def test_consumer_rejects_unsupported_event(db):
    order, line, order_map, line_map = _factory_order()
    event = _event(order_map, line_map)
    event["event_type"] = "order_request_created"
    client = _FakeClient([event])

    result = SyncEventConsumer(client).pull_and_apply()

    assert result["rejected"] == 1
    assert client.acks[0][1] == "rejected"

def _content_event(order_map, content_map, *, content_type="pallet", lote="LOTE-CONTENIDO"):
    return {
        "event_id": f"evento-contenido-{content_type}",
        "event_type": "order_content_lote_fecha_updated",
        "origin": "cloud",
        "aggregate_type": "pallet_content" if content_type == "pallet" else "loose_content",
        "aggregate_id": content_map.global_uid,
        "aggregate_version": 1,
        "cursor": 1,
        "occurred_at": "2026-10-29T12:00:00Z",
        "payload": {
            "order_uid": order_map.global_uid,
            "content_uid": content_map.global_uid,
            "content_type": content_type,
            "lote": lote,
            "fecha_elaboracion": "2026-10-29",
            "expected_version": 1,
        },
    }


def test_consumer_applies_pallet_content_event(db):
    order, line, order_map, _ = _factory_order()
    destination = LoadOrderDestination.create(
        order=order,
        client=order.client,
        delivery_address=order.delivery_address,
        sequence=1,
    )
    pallet = LoadOrderPallet.create(order=order, sequence=1)
    allocation = LoadOrderPalletAllocation.create(
        pallet=pallet,
        destination=destination,
        product=line.product,
        quantity=60,
        peso_unitario_kg=25,
    )
    content_map = SyncService.ensure_entity_uid(
        SyncEntityMap.ENTITY_PALLET_CONTENT, allocation.id
    )
    client = _FakeClient([_content_event(order_map, content_map)])

    result = SyncEventConsumer(client).pull_and_apply()

    assert result["applied"] == 1
    allocation = LoadOrderPalletAllocation.get_by_id(allocation.id)
    assert allocation.lote == "LOTE-CONTENIDO"
    assert allocation.fecha_elaboracion == date(2026, 10, 29)
    assert client.acks[0][1] == "applied"


def test_consumer_applies_loose_content_event(db):
    order, line, order_map, _ = _factory_order()
    destination = LoadOrderDestination.create(
        order=order,
        client=order.client,
        delivery_address=order.delivery_address,
        sequence=1,
    )
    allocation = LoadOrderLooseAllocation.create(
        order=order,
        destination=destination,
        product=line.product,
        quantity=20,
        peso_unitario_kg=25,
    )
    content_map = SyncService.ensure_entity_uid(
        SyncEntityMap.ENTITY_LOOSE_CONTENT, allocation.id
    )
    client = _FakeClient(
        [_content_event(order_map, content_map, content_type="loose")]
    )

    result = SyncEventConsumer(client).pull_and_apply()

    assert result["applied"] == 1
    allocation = LoadOrderLooseAllocation.get_by_id(allocation.id)
    assert allocation.lote == "LOTE-CONTENIDO"
    assert allocation.fecha_elaboracion == date(2026, 10, 29)
    assert client.acks[0][1] == "applied"
