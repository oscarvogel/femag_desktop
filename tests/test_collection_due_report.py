from datetime import date, timedelta

from app.models.accounting import ClientAccountMovement
from app.models.load_orders import LoadOrder
from app.reports.collection_due_report import (
    CollectionDueFilters,
    CollectionDueReportService,
    STATUS_NEXT_30,
    STATUS_NEXT_7,
    STATUS_OVERDUE,
    STATUS_TODAY,
)


def _movement(data, *, due_date, amount, order_number, reversal=False):
    order = LoadOrder.create(
        order_number=order_number,
        date=due_date - timedelta(days=30),
        client=data["client"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
    )
    original = ClientAccountMovement.create(
        client=data["client"],
        load_order=order,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        amount=amount,
        net_amount=amount,
        total_amount=amount,
        movement_date=order.date,
        due_date=due_date,
        description=f"OC-{order_number}",
        source_ref=f"LoadOrder:{order.id}",
        is_reversal=False,
    )
    if reversal:
        ClientAccountMovement.create(
            client=data["client"],
            load_order=order,
            movement_type=ClientAccountMovement.TYPE_LOAD_ORDER_REVERSAL,
            amount=-amount,
            net_amount=-amount,
            total_amount=-amount,
            movement_date=order.date,
            due_date=due_date,
            description=f"Reverso OC-{order_number}",
            source_ref=f"LoadOrder:{order.id}",
            is_reversal=True,
            reverses=original,
        )
    return original


def test_status_buckets():
    service = CollectionDueReportService()
    today = date(2026, 9, 7)
    assert service.status_for(today - timedelta(days=1), today=today) == STATUS_OVERDUE
    assert service.status_for(today, today=today) == STATUS_TODAY
    assert service.status_for(today + timedelta(days=7), today=today) == STATUS_NEXT_7
    assert service.status_for(today + timedelta(days=8), today=today) == STATUS_NEXT_30


def test_report_totals_filters_and_ignores_reversed(db):
    from conftest import _master_data

    data = _master_data()
    today = date(2026, 9, 7)
    _movement(data, due_date=today - timedelta(days=2), amount=100, order_number=1)
    _movement(data, due_date=today, amount=200, order_number=2)
    _movement(data, due_date=today + timedelta(days=5), amount=300, order_number=3)
    _movement(data, due_date=today + timedelta(days=20), amount=400, order_number=4)
    _movement(data, due_date=today + timedelta(days=3), amount=999, order_number=5, reversal=True)

    result = CollectionDueReportService().report(CollectionDueFilters(), today=today)

    assert [row["order_number"] for row in result.rows] == [1, 2, 3, 4]
    assert result.totals.overdue == 100
    assert result.totals.due_today == 200
    assert result.totals.next_7_days == 300
    assert result.totals.next_30_days == 700
    assert result.totals.filtered_total == 1000

    overdue = CollectionDueReportService().report(
        CollectionDueFilters(status=STATUS_OVERDUE),
        today=today,
    )
    assert len(overdue.rows) == 1
    assert overdue.rows[0]["order_number"] == 1
