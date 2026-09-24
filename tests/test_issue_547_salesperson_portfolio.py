from datetime import date, timedelta


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
        created_by="issue547",
    )


def test_salesperson_portfolio_filters_current_client_assignment(db):
    from app.models.masters import Client, Salesperson
    from app.services.ledger_query_service import client_portfolio_rows

    luis = Salesperson.create(name="Luis 547")
    pedro = Salesperson.create(name="Pedro 547")
    client_luis = Client.create(
        name="Cliente Luis 547",
        cuit="30700000547",
        iva_condition="RI",
        salesperson=luis,
    )
    client_pedro = Client.create(
        name="Cliente Pedro 547",
        cuit="30700010547",
        iva_condition="RI",
        salesperson=pedro,
    )
    client_unassigned = Client.create(
        name="Cliente sin vendedor 547",
        cuit="30700020547",
        iva_condition="RI",
    )
    _movement(client_luis, 1000, ref="547:luis")
    _movement(client_pedro, 2000, ref="547:pedro")
    _movement(client_unassigned, 3000, ref="547:unassigned")

    luis_rows = client_portfolio_rows(salesperson_id=luis.id)
    assert [(row["client"].id, row["balance"]) for row in luis_rows] == [
        (client_luis.id, 1000.0)
    ]

    unassigned_rows = client_portfolio_rows(unassigned=True)
    assert [(row["client"].id, row["balance"]) for row in unassigned_rows] == [
        (client_unassigned.id, 3000.0)
    ]

    all_rows = client_portfolio_rows()
    assert {row["client"].id for row in all_rows} == {
        client_luis.id,
        client_pedro.id,
        client_unassigned.id,
    }


def test_reassigning_client_moves_complete_current_balance(db):
    from app.models.masters import Client, Salesperson
    from app.services.client_service import ClientService
    from app.services.ledger_query_service import client_portfolio_rows

    luis = Salesperson.create(name="Luis cartera 547")
    pedro = Salesperson.create(name="Pedro cartera 547")
    client = Client.create(
        name="Cliente cambia vendedor 547",
        cuit="30700030547",
        iva_condition="RI",
        salesperson=luis,
    )
    _movement(client, 12_500_000, ref="547:move")

    assert client_portfolio_rows(salesperson_id=luis.id)[0]["balance"] == 12_500_000.0

    ClientService("issue547").set_salesperson(client, pedro)

    assert client_portfolio_rows(salesperson_id=luis.id) == []
    pedro_rows = client_portfolio_rows(salesperson_id=pedro.id)
    assert len(pedro_rows) == 1
    assert pedro_rows[0]["balance"] == 12_500_000.0


def test_portfolio_due_buckets_consume_current_balance_oldest_first(db):
    from app.models.masters import Client, Salesperson
    from app.services.ledger_query_service import client_portfolio_rows

    today = date(2026, 9, 24)
    luis = Salesperson.create(name="Luis vencimientos 547")
    client = Client.create(
        name="Cliente vencimientos 547",
        cuit="30700040547",
        iva_condition="RI",
        salesperson=luis,
    )
    _movement(
        client,
        800,
        due_date=today - timedelta(days=5),
        ref="547:overdue",
    )
    _movement(
        client,
        700,
        due_date=today + timedelta(days=5),
        ref="547:due7",
    )
    _movement(client, -500, ref="547:payment")

    row = client_portfolio_rows(salesperson_id=luis.id, as_of=today)[0]

    assert row["balance"] == 1000.0
    assert row["overdue"] == 800.0
    assert row["due_7"] == 200.0


def test_portfolio_includes_active_zero_balance_clients_for_selected_salesperson(db):
    from app.models.masters import Client, Salesperson
    from app.services.ledger_query_service import client_portfolio_rows

    seller = Salesperson.create(name="Vendedor sin movimientos 547")
    client = Client.create(
        name="Cliente cero 547",
        cuit="30700050547",
        iva_condition="RI",
        salesperson=seller,
    )

    rows = client_portfolio_rows(salesperson_id=seller.id)

    assert len(rows) == 1
    assert rows[0]["client"].id == client.id
    assert rows[0]["balance"] == 0.0
    assert rows[0]["movements"] == 0
    assert rows[0]["overdue"] == 0.0
    assert rows[0]["due_7"] == 0.0


def test_portfolio_uses_grouped_queries_without_n_plus_one(db, monkeypatch):
    from app.models.masters import Client, Salesperson
    from app.services.ledger_query_service import client_portfolio_rows

    seller = Salesperson.create(name="Vendedor performance 547")
    for index in range(20):
        client = Client.create(
            name=f"Cliente performance {index:02d}",
            cuit=f"30700547{index:03d}",
            iva_condition="RI",
            salesperson=seller,
        )
        _movement(
            client,
            100 + index,
            due_date=date(2026, 9, 20),
            ref=f"547:perf:{index}",
        )

    calls = []
    original = db.execute_sql

    def counted(sql, params=None):
        calls.append(sql)
        return original(sql, params)

    monkeypatch.setattr(db, "execute_sql", counted)
    rows = client_portfolio_rows(
        salesperson_id=seller.id,
        as_of=date(2026, 9, 24),
    )

    assert len(rows) == 20
    assert len(calls) <= 3
    assert any("GROUP BY" in sql.upper() for sql in calls)
