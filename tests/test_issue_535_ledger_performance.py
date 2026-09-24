from datetime import date
from unittest.mock import patch

from conftest import _master_data


def _count_sql(monkeypatch, db):
    calls = []
    original = db.execute_sql

    def counted(sql, params=None):
        calls.append(sql)
        return original(sql, params)

    monkeypatch.setattr(db, "execute_sql", counted)
    return calls


def test_issue_535_client_balances_uses_grouped_query_not_full_scan(db, monkeypatch):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.services.ledger_query_service import client_balances

    client_a = Client.create(
        name="Cliente A",
        cuit="30777775351",
        iva_condition="RI",
    )
    client_b = Client.create(
        name="Cliente B",
        cuit="30777775352",
        iva_condition="RI",
    )
    for index in range(50):
        ClientAccountMovement.create(
            client=client_a,
            movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
            total_amount=100.10,
            currency="ARS",
            movement_date=date(2026, 9, 1),
            description=f"A {index}",
            source_ref=f"issue-535:a:{index}",
            created_by="test",
        )
        ClientAccountMovement.create(
            client=client_b,
            movement_type=ClientAccountMovement.TYPE_MANUAL_CREDIT,
            total_amount=-20.02,
            currency="ARS",
            movement_date=date(2026, 9, 1),
            description=f"B {index}",
            source_ref=f"issue-535:b:{index}",
            created_by="test",
        )

    queries = _count_sql(monkeypatch, db)
    balances = client_balances()

    assert len(queries) == 1
    assert "SUM" in queries[0].upper()
    assert "GROUP BY" in queries[0].upper()

    by_name = {entry["client"].name: entry for entry in balances}
    assert by_name["Cliente A"]["movements"] == 50
    assert by_name["Cliente A"]["balance"] == 5005.00
    assert by_name["Cliente B"]["movements"] == 50
    assert by_name["Cliente B"]["balance"] == -1001.00


def test_issue_535_movements_prefetch_payment_and_load_order(db, monkeypatch):
    from app.models.accounting import ClientAccountMovement
    from app.models.load_orders import LoadOrder
    from app.models.payments import ClientPayment
    from app.services.ledger_query_service import movements_for_client

    data = _master_data()
    client = data["client"]
    order = LoadOrder.create(
        order_number=535001,
        client=client,
        delivery_address=data["address"],
        carrier=data["carrier"],
        driver=data["driver"],
        truck=data["truck"],
        status=LoadOrder.STATUS_ISSUED,
        created_by="test",
    )
    payment = ClientPayment.create(
        receipt_number="REC-00535001",
        client=client,
        amount=250,
        method=ClientPayment.METHOD_CASH,
        created_by="test",
    )
    ClientAccountMovement.create(
        client=client,
        load_order=order,
        movement_type=ClientAccountMovement.TYPE_LOAD_ORDER,
        total_amount=1000,
        currency="ARS",
        movement_date=date(2026, 9, 1),
        description="Orden",
        source_ref="issue-535:order",
        created_by="test",
    )
    ClientAccountMovement.create(
        client=client,
        payment=payment,
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
        total_amount=-250,
        currency="ARS",
        movement_date=date(2026, 9, 2),
        description="Pago",
        source_ref="issue-535:payment",
        created_by="test",
    )

    queries = _count_sql(monkeypatch, db)
    movements = movements_for_client(client)

    assert len(queries) == 1
    assert movements[0].load_order.order_number == 535001
    assert movements[1].payment.receipt_number == "REC-00535001"
    assert len(queries) == 1


def test_issue_535_search_filters_cached_snapshot_without_requery(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.services import ledger_query_service
    from app.ui import customer_ledger
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    client = Client.create(
        name="Cliente Performance",
        cuit="30777775353",
        iva_condition="RI",
    )
    ClientAccountMovement.create(
        client=client,
        movement_type=ClientAccountMovement.TYPE_MANUAL_DEBIT,
        total_amount=1234.56,
        currency="ARS",
        movement_date=date(2026, 9, 1),
        description="Movimiento",
        source_ref="issue-535:ui",
        created_by="test",
    )

    with patch.object(
        customer_ledger,
        "client_portfolio_rows",
        wraps=ledger_query_service.client_portfolio_rows,
    ) as portfolio_mock, patch.object(
        customer_ledger,
        "movements_for_client",
        wraps=ledger_query_service.movements_for_client,
    ) as movements_mock:
        page = CustomerLedgerPage(current_user="admin")
        app.processEvents()

        portfolio_calls = portfolio_mock.call_count
        movement_calls = movements_mock.call_count
        assert portfolio_calls >= 1
        assert movement_calls >= 1

        page.search_input.setText("Cliente")
        app.processEvents()
        page.search_input.setText("Cliente Perf")
        app.processEvents()
        page.only_with_balance.setChecked(True)
        app.processEvents()

        assert portfolio_mock.call_count == portfolio_calls
        assert movements_mock.call_count == movement_calls
        assert page.clients_table.rowCount() == 1
        assert page.detail_balance.text() == "$1,234.56"


def test_issue_535_detail_reuses_loaded_running_balance():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "ui" / "customer_ledger.py"
    ).read_text(encoding="utf-8")
    block = source.split("    def _on_client_selected", 1)[1].split(
        "    def _selected_client", 1
    )[0]

    assert "client_balance(" not in block
    assert "movements_for_client(client)" in block
    assert "running_balance(movements)" in block
    assert "balances[-1] if balances else 0.0" in block
