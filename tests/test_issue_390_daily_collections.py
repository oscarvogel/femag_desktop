from datetime import date

from app.models.accounting import ClientAccountMovement
from app.models.masters import Client
from app.models.payments import ClientPayment, ClientPaymentDetail
from app.reports.daily_collections import DailyCollectionsFilters, DailyCollectionsReportService
from app.services.client_payment_service import ClientPaymentService


def _client() -> Client:
    return Client.create(
        name="Cliente Informe 390",
        cuit="30700000390",
        iva_condition="RI",
    )


def test_compound_payment_is_split_by_method_without_double_counting_receipt(db):
    client = _client()
    payment = ClientPaymentService(current_user="admin").register_compound_payment(
        client=client,
        payment_date=date(2026, 9, 4),
        details=[
            {"method": "efectivo", "amount": 500},
            {
                "method": "retenciones_percepciones",
                "amount": 125,
                "reference": "IIBB-390",
            },
        ],
        observations="Cobranza issue 390",
    )

    result = DailyCollectionsReportService().report(
        DailyCollectionsFilters(date(2026, 9, 4), date(2026, 9, 4))
    )

    assert len(result.collection_rows) == 2
    assert {row["payment_id"] for row in result.collection_rows} == {payment.id}
    assert result.totals.collected == 625
    assert result.totals.active_payments == 1
    assert result.totals.clients == 1
    assert dict(result.collections_by_method) == {
        "Efectivo": 500,
        "Retenciones / Percepciones": 125,
    }
    assert len(result.movement_rows) == 1
    assert result.movement_rows[0]["credit"] == 625
    assert result.movement_rows[0]["balance"] == -625


def test_payment_method_filter_uses_detail_amount_and_keeps_receipt_auditable(db):
    client = _client()
    ClientPaymentService(current_user="admin").register_compound_payment(
        client=client,
        payment_date=date(2026, 9, 4),
        details=[
            {"method": "efectivo", "amount": 300},
            {"method": "transferencia", "amount": 700, "reference": "TR-390"},
        ],
    )

    result = DailyCollectionsReportService().report(
        DailyCollectionsFilters(
            date(2026, 9, 4),
            date(2026, 9, 4),
            payment_method="transferencia",
        )
    )

    assert len(result.collection_rows) == 1
    assert result.collection_rows[0]["amount"] == 700
    assert result.collection_rows[0]["payment_total"] == 1000
    assert result.collection_rows[0]["reference"] == "TR-390"
    assert result.totals.collected == 700
    assert result.totals.active_payments == 1


def test_historical_payment_without_movement_date_uses_receipt_date(db):
    client = _client()
    payment = ClientPaymentService(current_user="cajero").register_payment(
        client=client,
        amount=250,
        payment_date=date(2026, 8, 31),
        method="efectivo",
    )
    movement = ClientAccountMovement.get(
        (ClientAccountMovement.payment == payment)
        & (ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_PAYMENT)
    )
    movement.movement_date = None
    movement.save()

    result = DailyCollectionsReportService().report(
        DailyCollectionsFilters(
            date(2026, 8, 31),
            date(2026, 8, 31),
            client_id=client.id,
            created_by="cajero",
        )
    )

    assert len(result.movement_rows) == 1
    assert result.movement_rows[0]["date"] == date(2026, 8, 31)
    assert result.movement_rows[0]["credit"] == 250


def test_annulled_receipt_is_visible_but_excluded_from_effective_collected_total(db):
    client = _client()
    payment = ClientPaymentService(current_user="admin").register_payment(
        client=client,
        amount=400,
        payment_date=date(2026, 9, 4),
        method="efectivo",
    )
    payment.status = ClientPayment.STATUS_ANNULLED
    payment.save()
    original = ClientAccountMovement.get(
        (ClientAccountMovement.payment == payment)
        & (ClientAccountMovement.movement_type == ClientAccountMovement.TYPE_PAYMENT)
    )
    ClientAccountMovement.create(
        client=client,
        payment=payment,
        movement_type=ClientAccountMovement.TYPE_PAYMENT_REVERSAL,
        amount=400,
        net_amount=400,
        total_amount=400,
        currency="ARS",
        movement_date=date(2026, 9, 4),
        description="Anulación recibo test 390",
        source_ref=f"ClientPayment:{payment.id}:annulment:test390",
        is_reversal=True,
        reverses=original,
        created_by="admin",
    )

    result = DailyCollectionsReportService().report(
        DailyCollectionsFilters(date(2026, 9, 4), date(2026, 9, 4))
    )
    reversals = DailyCollectionsReportService().report(
        DailyCollectionsFilters(
            date(2026, 9, 4),
            date(2026, 9, 4),
            reversals_only=True,
        )
    )

    assert len(result.collection_rows) == 1
    assert result.collection_rows[0]["status"] == ClientPayment.STATUS_ANNULLED
    assert result.totals.collected == 0
    assert [row["movement_type"] for row in reversals.movement_rows] == [
        ClientAccountMovement.TYPE_PAYMENT_REVERSAL
    ]
