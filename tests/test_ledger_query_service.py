from datetime import date, datetime, timezone

from conftest import _master_data


def _movement(client, *, source_ref: str, movement_date: date, created_at: datetime):
    from app.models.accounting import ClientAccountMovement

    return ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        amount=0,
        net_amount=0,
        discount_amount=0,
        vat_amount=0,
        total_amount=100,
        currency="ARS",
        movement_date=movement_date,
        description=source_ref,
        source_ref=source_ref,
        is_reversal=False,
        created_by="test",
        created_at=created_at,
    )


def test_movements_for_client_orders_by_movement_date_not_creation_order(db):
    from app.services.ledger_query_service import movements_for_client

    client = _master_data()["client"]

    created_first_but_later_date = _movement(
        client,
        source_ref="test:later-date",
        movement_date=date(2026, 9, 20),
        created_at=datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc),
    )
    created_later_but_earlier_date = _movement(
        client,
        source_ref="test:earlier-date",
        movement_date=date(2026, 9, 10),
        created_at=datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc),
    )

    movements = movements_for_client(client)

    assert [movement.id for movement in movements] == [
        created_later_but_earlier_date.id,
        created_first_but_later_date.id,
    ]


def test_movements_for_client_uses_creation_order_only_as_same_date_tiebreaker(db):
    from app.services.ledger_query_service import movements_for_client

    client = _master_data()["client"]
    same_date = date(2026, 9, 17)

    created_later = _movement(
        client,
        source_ref="test:same-date-later",
        movement_date=same_date,
        created_at=datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc),
    )
    created_first = _movement(
        client,
        source_ref="test:same-date-first",
        movement_date=same_date,
        created_at=datetime(2026, 9, 17, 8, 0, tzinfo=timezone.utc),
    )

    movements = movements_for_client(client)

    assert [movement.id for movement in movements] == [created_first.id, created_later.id]
