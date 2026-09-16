from datetime import date, timedelta


def _movement(client, *, amount: float, due_date=None, source_ref: str, movement_type=None):
    from app.models.accounting import ClientAccountMovement

    return ClientAccountMovement.create(
        client=client,
        movement_type=movement_type or ClientAccountMovement.TYPE_LOAD_ORDER,
        amount=amount,
        net_amount=amount,
        discount_amount=0,
        vat_amount=0,
        total_amount=amount,
        currency="ARS",
        movement_date=date.today(),
        due_date=due_date,
        description=source_ref,
        source_ref=source_ref,
        is_reversal=False,
    )


def test_issue_443_dashboard_collection_snapshot_uses_due_dates_and_real_ledger_balance(db):
    from app.models.accounting import ClientAccountMovement
    from app.models.masters import Client
    from app.ui.dashboard import DashboardService

    today = date.today()
    client = Client.create(name="Cliente cobranzas", cuit="30777777779", iva_condition="RI")

    _movement(client, amount=1000, due_date=today - timedelta(days=5), source_ref="due-overdue")
    _movement(client, amount=500, due_date=today, source_ref="due-today")
    _movement(client, amount=700, due_date=today + timedelta(days=3), source_ref="due-next7")
    _movement(client, amount=900, due_date=today + timedelta(days=20), source_ref="due-next30")
    _movement(
        client,
        amount=-200,
        due_date=None,
        source_ref="payment-general",
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
    )

    snapshot = DashboardService().collection_snapshot(today=today)

    assert snapshot["overdue_amount"] == 1000
    assert snapshot["overdue_count"] == 1
    assert snapshot["due_today_amount"] == 500
    assert snapshot["due_today_count"] == 1
    assert snapshot["next_7_amount"] == 700
    assert snapshot["next_7_count"] == 1
    assert snapshot["next_30_amount"] == 1600
    assert snapshot["next_30_count"] == 2

    # El saldo real usa toda la cuenta corriente, incluyendo el pago general.
    assert snapshot["debtor_balance"] == 2900
    assert snapshot["debtor_clients"] == 1
    assert snapshot["overdue_rows"][0]["client_name"] == "Cliente cobranzas"
    assert snapshot["upcoming_rows"][0]["due_date"] == today


def test_issue_443_view_spec_exposes_collection_cards(db):
    from app.models.masters import Client
    from app.ui.dashboard import DashboardService

    today = date.today()
    client = Client.create(name="Cliente tarjeta", cuit="30666666669", iva_condition="RI")
    _movement(client, amount=1250, due_date=today - timedelta(days=1), source_ref="card-overdue")

    spec = DashboardService().view_spec()
    cards = {card.title: card for card in spec.collection_cards}

    assert set(cards) == {
        "Presupuestos vencidos",
        "Vence hoy",
        "Próximos 7 días",
        "Próximos 30 días",
        "Saldo deudor clientes",
    }
    assert cards["Presupuestos vencidos"].amount == 1250
    assert cards["Presupuestos vencidos"].count == 1
    assert cards["Saldo deudor clientes"].amount == 1250
    assert cards["Saldo deudor clientes"].route_key == "customer_ledger"


def test_issue_443_dashboard_renders_collection_widgets(db):
    from PyQt5.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QTableWidget, QWidget

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_issue_443", password_hash="x", profile=profile)

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    overdue_card = window.findChild(QPushButton, "dashboardOverdueBudgetsCard")
    due_today_card = window.findChild(QPushButton, "dashboardDueTodayCard")
    next_7_card = window.findChild(QPushButton, "dashboardNext7Card")
    next_30_card = window.findChild(QPushButton, "dashboardNext30Card")
    debtor_card = window.findChild(QPushButton, "dashboardDebtorBalanceCard")
    overdue_table = window.findChild(QTableWidget, "dashboardOverdueTable")
    upcoming_table = window.findChild(QTableWidget, "dashboardUpcomingTable")

    assert overdue_card is not None
    assert due_today_card is not None
    assert next_7_card is not None
    assert next_30_card is not None
    assert debtor_card is not None
    assert overdue_table is not None and overdue_table.minimumHeight() >= 210
    assert upcoming_table is not None and upcoming_table.minimumHeight() >= 210
    assert window.findChild(QWidget, "dashboardPage") is not None
    assert window.findChild(QFrame, "dashboardQuickActions") is not None
    assert window.findChild(QFrame, "dashboardMetricCard") is not None
    assert window.findChild(QLabel, "dashboardHeading") is not None
    planned_f150 = window.findChild(QPushButton, "dashboardF150")
    assert planned_f150 is not None and not planned_f150.isEnabled()
    assert planned_f150.property("dashboardState") == "planned"

    window.close()


def test_issue_443_due_report_dashboard_presets(db):
    from app.ui.collection_due_report import CollectionDueReportDialog
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    dialog = CollectionDueReportDialog()

    dialog.apply_dashboard_preset("today")
    assert dialog.status_combo.currentData() == "Vence hoy"
    assert dialog.date_from.date() == dialog.date_to.date()

    dialog.apply_dashboard_preset("next_7")
    assert dialog.status_combo.currentData() is None
    assert dialog.date_from.date().daysTo(dialog.date_to.date()) == 6

    dialog.close()
