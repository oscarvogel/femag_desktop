from datetime import date, timedelta
from unittest.mock import patch


def _movement(client, amount, *, due_date=None, ref):
    from app.models.accounting import ClientAccountMovement

    return ClientAccountMovement.create(
        client=client,
        movement_type=(
            ClientAccountMovement.TYPE_MANUAL_DEBIT
            if amount >= 0
            else ClientAccountMovement.TYPE_PAYMENT
        ),
        total_amount=amount,
        currency="ARS",
        movement_date=date(2026, 9, 24),
        due_date=due_date,
        description=ref,
        source_ref=ref,
        created_by="issue551",
    )


def test_issue_551_portfolio_uses_one_grouped_query_and_preserves_buckets(db, monkeypatch):
    from app.models.masters import Client, Salesperson
    from app.services.ledger_query_service import client_portfolio_rows

    today = date(2026, 9, 24)
    luis = Salesperson.create(name="Luis performance 551")
    client = Client.create(
        name="Cliente performance 551",
        cuit="30700000551",
        iva_condition="RI",
        salesperson=luis,
    )
    _movement(
        client,
        800,
        due_date=today - timedelta(days=2),
        ref="551:overdue",
    )
    _movement(
        client,
        700,
        due_date=today + timedelta(days=3),
        ref="551:due7",
    )
    _movement(client, -500, ref="551:payment")

    calls = []
    original = db.execute_sql

    def counted(sql, params=None):
        calls.append(sql)
        return original(sql, params)

    monkeypatch.setattr(db, "execute_sql", counted)

    rows = client_portfolio_rows(as_of=today)

    assert len(calls) == 1
    assert "GROUP BY" in calls[0].upper()
    row = next(entry for entry in rows if entry["client"].id == client.id)
    assert row["salesperson_id"] == luis.id
    assert row["balance"] == 1000.0
    assert row["movements"] == 3
    assert row["overdue"] == 800.0
    assert row["due_7"] == 200.0


def test_issue_551_salesperson_filter_reuses_loaded_snapshot(db):
    from PyQt5.QtWidgets import QApplication

    from app.models.masters import Client, Salesperson
    from app.services import ledger_query_service
    from app.ui import customer_ledger
    from app.ui.customer_ledger import CustomerLedgerPage

    app = QApplication.instance() or QApplication([])
    luis = Salesperson.create(name="Luis UI 551")
    pedro = Salesperson.create(name="Pedro UI 551")
    client_luis = Client.create(
        name="Cliente Luis UI 551",
        cuit="30700010551",
        iva_condition="RI",
        salesperson=luis,
    )
    client_pedro = Client.create(
        name="Cliente Pedro UI 551",
        cuit="30700020551",
        iva_condition="RI",
        salesperson=pedro,
    )
    _movement(client_luis, 1500, ref="551:luis")
    _movement(client_pedro, 2500, ref="551:pedro")

    with patch.object(
        customer_ledger,
        "client_portfolio_rows",
        wraps=ledger_query_service.client_portfolio_rows,
    ) as portfolio_mock:
        page = CustomerLedgerPage(current_user="issue551_ui")
        app.processEvents()

        initial_calls = portfolio_mock.call_count
        assert initial_calls == 1

        luis_index = page.salesperson_filter.findData(luis.id)
        assert luis_index >= 0
        page.salesperson_filter.setCurrentIndex(luis_index)
        page._on_salesperson_changed()
        app.processEvents()

        assert portfolio_mock.call_count == initial_calls
        assert page.clients_table.rowCount() == 1
        assert "Cliente Luis UI 551" in page.clients_table.item(0, 0).text()
        assert "Cartera: <b>$1,500.00</b>" in page.totals_label.text()

        pedro_index = page.salesperson_filter.findData(pedro.id)
        assert pedro_index >= 0
        page.salesperson_filter.setCurrentIndex(pedro_index)
        page._on_salesperson_changed()
        app.processEvents()

        assert portfolio_mock.call_count == initial_calls
        assert page.clients_table.rowCount() == 1
        assert "Cliente Pedro UI 551" in page.clients_table.item(0, 0).text()
        assert "Cartera: <b>$2,500.00</b>" in page.totals_label.text()

        page.close()
        page.deleteLater()
