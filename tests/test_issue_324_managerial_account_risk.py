from datetime import date, timedelta


def _movement(ClientAccountMovement, client, *, amount, due_date, source_ref, movement_type="manual_debit", is_reversal=False, reverses=None):
    return ClientAccountMovement.create(
        client=client,
        movement_type=movement_type,
        amount=amount,
        total_amount=amount,
        currency="ARS",
        movement_date=date(2026, 8, 1),
        due_date=due_date,
        description=source_ref,
        source_ref=source_ref,
        is_reversal=is_reversal,
        reverses=reverses,
    )


def test_consolidated_balance_and_overdue_match_dashboard(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.reports.managerial_account_risk import AccountRiskFilters, ManagerialAccountRiskService

    client = Client.create(name="Cliente Riesgo", cuit="30999999991", iva_condition="RI")
    as_of = date(2026, 8, 24)
    _movement(ClientAccountMovement, client, amount=1000, due_date=as_of - timedelta(days=20), source_ref="debit:1")
    _movement(ClientAccountMovement, client, amount=-250, due_date=None, source_ref="payment:1", movement_type="payment")

    service = ManagerialAccountRiskService()
    result = service.report(AccountRiskFilters(as_of=as_of))
    dashboard_balance, dashboard_overdue = service.dashboard_totals(as_of=as_of)

    assert result.totals.balance == 750
    assert result.totals.overdue == 750
    assert result.totals.balance == dashboard_balance
    assert result.totals.overdue == dashboard_overdue
    assert result.rows[0]["max_days_overdue"] == 20


def test_reversal_is_counted_once_and_future_buckets_do_not_exceed_balance(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.reports.managerial_account_risk import AccountRiskFilters, ManagerialAccountRiskService

    client = Client.create(name="Cliente Reversos", cuit="30999999992", iva_condition="RI")
    as_of = date(2026, 8, 24)
    original = _movement(ClientAccountMovement, client, amount=500, due_date=as_of + timedelta(days=5), source_ref="manual:1")
    _movement(
        ClientAccountMovement,
        client,
        amount=-500,
        due_date=as_of + timedelta(days=5),
        source_ref="manual:1:reversal",
        movement_type="manual_debit_reversal",
        is_reversal=True,
        reverses=original,
    )
    _movement(ClientAccountMovement, client, amount=300, due_date=as_of + timedelta(days=12), source_ref="manual:2")

    row = ManagerialAccountRiskService().report(AccountRiskFilters(as_of=as_of)).rows[0]

    assert row["balance"] == 300
    assert row["overdue"] == 0
    assert row["due_7"] == 0
    assert row["due_15"] == 300
    assert row["due_30"] == 300


def test_filters_debt_overdue_and_due_window(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.reports.managerial_account_risk import AccountRiskFilters, ManagerialAccountRiskService

    as_of = date(2026, 8, 24)
    overdue = Client.create(name="Vencido", cuit="30999999993", iva_condition="RI")
    future = Client.create(name="Futuro", cuit="30999999994", iva_condition="RI")
    clean = Client.create(name="Sin deuda", cuit="30999999995", iva_condition="RI")
    _movement(ClientAccountMovement, overdue, amount=200, due_date=as_of - timedelta(days=2), source_ref="o:1")
    _movement(ClientAccountMovement, future, amount=400, due_date=as_of + timedelta(days=6), source_ref="f:1")

    service = ManagerialAccountRiskService()
    overdue_result = service.report(AccountRiskFilters(as_of=as_of, debt_state="overdue"))
    due_7_result = service.report(AccountRiskFilters(as_of=as_of, due_window_days=7))
    clean_result = service.report(AccountRiskFilters(as_of=as_of, debt_state="without_debt"))

    assert [row["client_name"] for row in overdue_result.rows] == ["Vencido"]
    assert [row["client_name"] for row in due_7_result.rows] == ["Futuro"]
    assert "Sin deuda" in [row["client_name"] for row in clean_result.rows]


def test_account_risk_html_contains_kpis_and_rankings(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.reports.managerial_account_risk import AccountRiskFilters, ManagerialAccountRiskService
    from app.reports.managerial_account_risk_html import ManagerialAccountRiskHtmlReport

    as_of = date(2026, 8, 24)
    client = Client.create(name="Cliente HTML", cuit="30999999996", iva_condition="RI")
    _movement(ClientAccountMovement, client, amount=900, due_date=as_of - timedelta(days=1), source_ref="html:1")

    service = ManagerialAccountRiskService()
    result = service.report(AccountRiskFilters(as_of=as_of))
    html = ManagerialAccountRiskHtmlReport(service=service).render(result)

    assert "Cuenta corriente y deuda vencida" in html
    assert "Mayor exposición" in html
    assert "Mayor deuda vencida" in html
    assert "Cliente HTML" in html
