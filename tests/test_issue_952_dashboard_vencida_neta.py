"""
Regresion del issue #952: la tarjeta de cobranzas del dashboard muestra la
exposicion exigible por cliente y no la suma bruta de los documentos vencidos.
"""

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


def _client(cuit: str, name: str):
    from app.models.masters import Client

    return Client.create(name=name, cuit=cuit, iva_condition="RI")


def test_issue_952_exposicion_vencida_no_supera_el_saldo_del_cliente(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.collection_exposure_service import CollectionExposureService

    today = date.today()
    client = _client("30888888881", "Cliente pago parcial")

    # Documento vencido de 1000, pero el cliente pago 600.
    _movement(client, amount=1000, due_date=today - timedelta(days=10), source_ref="952-overdue")
    _movement(
        client,
        amount=-600,
        due_date=None,
        source_ref="952-payment",
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
    )

    exposure = CollectionExposureService().snapshot(today=today)

    assert exposure.overdue_amount == 400
    assert exposure.overdue_clients == 1


def test_issue_952_cliente_con_credito_no_aporta_deuda_vencida(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.collection_exposure_service import CollectionExposureService

    today = date.today()
    client = _client("30888888882", "Cliente con credito")

    _movement(client, amount=500, due_date=today - timedelta(days=3), source_ref="952-credit-overdue")
    _movement(
        client,
        amount=-800,
        due_date=None,
        source_ref="952-credit",
        movement_type=ClientAccountMovement.TYPE_MANUAL_CREDIT,
    )

    exposure = CollectionExposureService().snapshot(today=today)

    assert exposure.overdue_amount == 0
    assert exposure.overdue_clients == 0


def test_issue_952_cliente_que_pago_todo_no_queda_vencido(db):
    from app.models.accounting import ClientAccountMovement
    from app.services.collection_exposure_service import CollectionExposureService

    today = date.today()
    client = _client("30888888883", "Cliente al dia")

    _movement(client, amount=900, due_date=today - timedelta(days=1), source_ref="952-paid-overdue")
    _movement(
        client,
        amount=-900,
        due_date=None,
        source_ref="952-paid-payment",
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
    )

    exposure = CollectionExposureService().snapshot(today=today)

    assert exposure.overdue_amount == 0
    assert exposure.overdue_clients == 0


def test_issue_952_las_ventanas_siguientes_descontan_lo_vencido(db):
    from app.services.collection_exposure_service import CollectionExposureService

    today = date.today()
    client = _client("30888888884", "Cliente cascada")

    _movement(client, amount=400, due_date=today - timedelta(days=5), source_ref="952-cascada-overdue")
    _movement(client, amount=300, due_date=today, source_ref="952-cascada-today")
    _movement(client, amount=200, due_date=today + timedelta(days=3), source_ref="952-cascada-7")
    _movement(client, amount=500, due_date=today + timedelta(days=20), source_ref="952-cascada-30")

    exposure = CollectionExposureService().snapshot(today=today)

    # Saldo 1400. Vencido 400, remanente 1000; hoy 300, remanente 700;
    # 7 dias 200; 30 dias acumulados (200 + 500 = 700) contra el remanente 700.
    assert exposure.overdue_amount == 400
    assert exposure.due_today_amount == 300
    assert exposure.next_7_amount == 200
    assert exposure.next_30_amount == 700


def test_issue_952_cada_cliente_se_limita_a_su_propio_saldo(db):
    from app.services.collection_exposure_service import CollectionExposureService

    today = date.today()
    impagable = _client("30888888885", "Cliente impagable")
    solvente = _client("30888888886", "Cliente solvente")

    _movement(impagable, amount=1000, due_date=today - timedelta(days=20), source_ref="952-cliente-a")
    _movement(solvente, amount=1000, due_date=today - timedelta(days=20), source_ref="952-cliente-b")

    exposure = CollectionExposureService().snapshot(today=today)

    # Los dos deben 1000: el saldo de cada uno es su propia base.
    assert exposure.overdue_amount == 2000
    assert exposure.overdue_clients == 2


def test_issue_952_dashboard_muestra_exposicion_y_conteo_de_clientes(db):
    from app.models.accounting import ClientAccountMovement
    from app.ui.dashboard import DashboardService

    today = date.today()
    client = _client("30888888887", "Cliente dashboard")

    _movement(client, amount=2000, due_date=today - timedelta(days=4), source_ref="952-dash-overdue")
    _movement(
        client,
        amount=-1500,
        due_date=None,
        source_ref="952-dash-payment",
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
    )

    snapshot = DashboardService().collection_snapshot(today=today)

    assert snapshot["overdue_amount"] == 500
    assert snapshot["overdue_clients"] == 1
    assert snapshot["debtor_balance"] == 500
    assert snapshot["debtor_clients"] == 1


def test_issue_952_la_tarjeta_no_muestra_mas_que_el_saldo_deudor(db):
    from app.models.accounting import ClientAccountMovement
    from app.ui.dashboard import DashboardService

    today = date.today()
    client = _client("30888888888", "Cliente techo")

    # Documentos vencidos por 3000 con solo 1200 de saldo real.
    _movement(client, amount=3000, due_date=today - timedelta(days=8), source_ref="952-techo")
    _movement(
        client,
        amount=-1800,
        due_date=None,
        source_ref="952-techo-payment",
        movement_type=ClientAccountMovement.TYPE_PAYMENT,
    )

    spec = DashboardService().view_spec()
    cards = {card.title: card for card in spec.collection_cards}

    assert cards["Deuda vencida"].amount == 1200
    assert cards["Deuda vencida"].amount <= cards["Saldo deudor clientes"].amount
    assert cards["Deuda vencida"].count == 1
    assert cards["Deuda vencida"].unit == "cliente"
    assert cards["Deuda vencida"].unit_plural == "clientes"
    assert cards["Deuda vencida"].tooltip


def test_issue_952_sin_base_la_tarjeta_queda_en_cero(db):
    from app.ui.dashboard import DashboardService

    snapshot = DashboardService().collection_snapshot()

    assert snapshot["overdue_amount"] == 0
    assert snapshot["overdue_clients"] == 0
    assert snapshot["debtor_balance"] == 0


def test_issue_952_la_tarjeta_de_vencidos_muestra_clientes(db):
    from PyQt5.QtWidgets import QApplication, QPushButton

    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.ui.desktop_app import FemagDesktopWindow

    app = QApplication.instance() or QApplication([])
    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_issue_952", password_hash="x", profile=profile)

    window = FemagDesktopWindow(user=user, demo_mode=True)
    app.processEvents()

    card = window.findChild(QPushButton, "dashboardOverdueBudgetsCard")

    assert card is not None
    assert "Deuda vencida" in card.text()
    assert "presupuesto" not in card.text()
    assert "cliente" in card.text()
    assert card.toolTip()

    window.close()
