from datetime import date


def _valued_dispatch(
    *,
    number: int,
    order_date: date,
    total: float,
    client=None,
    product=None,
):
    """Crea una orden efectiva con un valorizado, para mover los KPIs del dashboard."""
    from app.models.load_orders import (
        LoadOrder,
        LoadOrderDestination,
        LoadOrderProduct,
    )
    from app.models.masters import (
        Carrier,
        Client,
        ClientAddress,
        Driver,
        Product,
        Truck,
    )

    client = client or Client.create(
        name=f"Cliente {number}",
        cuit=f"3071234{number:04d}",
        iva_condition="RI",
    )
    address = client.addresses.get() if client.addresses.count() else ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address=f"Ruta {number}",
    )
    product = product or Product.create(name=f"Producto {number}", unit="kg")
    order = LoadOrder.create(
        order_number=number,
        date=order_date,
        client=client,
        delivery_address=address,
        carrier=Carrier.create(name=f"Transportista {number}"),
        driver=Driver.create(name=f"Chofer {number}"),
        truck=Truck.create(domain=f"T{number:05d}"),
        status=LoadOrder.STATUS_ISSUED,
    )
    destination = LoadOrderDestination.create(
        order=order,
        client=client,
        delivery_address=address,
        sequence=1,
    )
    LoadOrderProduct.create(
        order=order,
        destination=destination,
        product=product,
        quantity=1000,
        unit=product.unit,
        neto_subtotal=total,
        neto_gravado=total,
        total=total,
    )
    return order


def test_variation_text_cubre_alza_baja_ideas_y_sin_base_comparable():
    from types import SimpleNamespace

    from app.reports.managerial_dashboard import MetricComparison, ReportPeriod
    from app.services.managerial_summary_service import _variation_text

    snapshot = SimpleNamespace(
        previous_period=ReportPeriod(date(2026, 8, 1), date(2026, 8, 20), "Este mes anterior")
    )

    # El -32,2% es el que marco el dueno en el Dashboard Gerencial. El texto
    # lleva el rango comparado para que el numero se pueda auditar por WhatsApp,
    # donde no esta la tarjeta del dashboard al lado.
    assert _variation_text(MetricComparison(67_800.0, 100_000.0), snapshot) == (
        "-32,2% vs 01/08/2026 → 20/08/2026"
    )
    assert _variation_text(MetricComparison(112_300.0, 100_000.0), snapshot) == (
        "+12,3% vs 01/08/2026 → 20/08/2026"
    )
    assert _variation_text(MetricComparison(0.0, 0.0), snapshot) == (
        "0,0% vs 01/08/2026 → 20/08/2026"
    )
    assert _variation_text(MetricComparison(50_000.0, 0.0), snapshot) == "Sin base comparable"


def test_whatsapp_informa_la_variacion_de_despachos_del_mes(db):
    from app.services.managerial_summary_service import ManagerialSummaryService

    # Corte 20/09/2026: el mes va del 01/09 al 20/09 y el período equivalente
    # anterior del 01/08 al 20/08 (mismo rango de días del mes anterior, no los
    # 20 días previos), por eso las dos órdenes caen en esas ventanas.
    _valued_dispatch(number=1, order_date=date(2026, 8, 20), total=100_000.0)
    _valued_dispatch(number=2, order_date=date(2026, 9, 10), total=67_800.0)

    service = ManagerialSummaryService()
    summary = service.build(as_of=date(2026, 9, 20))

    assert summary.month_snapshot.previous_period.start == date(2026, 8, 1)
    assert summary.month_snapshot.previous_period.end == date(2026, 8, 20)
    assert summary.month_snapshot.valued_dispatches.previous == 100_000.0
    assert summary.month_snapshot.valued_dispatches.variation_percent == -32.2

    whatsapp = service.render_whatsapp(summary)

    assert (
        "📅 Acumulado del mes: $ 67,8 mil (-32,2% vs 01/08/2026 → 20/08/2026)" in whatsapp
    )


def test_whatsapp_sin_periodo_anterior_no_inventa_un_porcentaje(db):
    from app.services.managerial_summary_service import ManagerialSummaryService

    _valued_dispatch(number=3, order_date=date(2026, 9, 10), total=67_800.0)

    service = ManagerialSummaryService()
    summary = service.build(as_of=date(2026, 9, 20))

    assert summary.month_snapshot.valued_dispatches.variation_percent is None
    assert (
        "📅 Acumulado del mes: $ 67,8 mil (Sin base comparable)"
        in service.render_whatsapp(summary)
    )


def test_managerial_summary_reuses_dashboard_and_account_risk(db):
    from app.services.managerial_summary_service import ManagerialSummaryService

    summary = ManagerialSummaryService().build(as_of=date(2026, 9, 20))

    assert summary.as_of == date(2026, 9, 20)
    from app.models.load_orders import LoadOrder

    assert summary.today_snapshot.period.start == date(2026, 9, 20)
    assert summary.month_snapshot.period.start == date(2026, 9, 1)
    assert summary.today_snapshot.effective_statuses == (
        LoadOrder.STATUS_ISSUED,
        LoadOrder.STATUS_CLOSED,
    )
    assert summary.month_snapshot.effective_statuses == (
        LoadOrder.STATUS_ISSUED,
        LoadOrder.STATUS_CLOSED,
    )
    assert summary.risk_result.filters.as_of == date(2026, 9, 20)


def test_managerial_summary_email_and_whatsapp_are_executive_and_consistent(db):
    from app.services.managerial_summary_service import ManagerialSummaryService

    service = ManagerialSummaryService()
    summary = service.build(as_of=date(2026, 9, 20))

    email = service.render_email_html(summary)
    whatsapp = service.render_whatsapp(summary)

    assert "FEMAG · INFORMACIÓN GERENCIAL" in email
    assert "Despachos hoy" in email
    assert "Saldo clientes" in email
    assert "Vence en 7 días" in email
    assert "Cuenta corriente y deuda vencida" in email
    assert "Clientes con deuda" in email
    assert "Clientes vencidos" in email
    assert "Vence en 15 días" in email
    assert "Vence en 30 días" in email
    assert "10 mayores deudas vencidas" in email
    assert "FEMAG · Resumen gerencial" in whatsapp
    assert "*Actividad*" in whatsapp
    assert "*Cartera*" in whatsapp
    assert "Próx. 7 días" in whatsapp


def test_managerial_whatsapp_requires_explicit_instance(db):
    from app.services.managerial_summary_service import ManagerialSummaryService

    service = ManagerialSummaryService()
    summary = service.build(as_of=date(2026, 9, 20))

    try:
        service.send_whatsapp(summary, phone="5491112345678", instance_id="")
    except ValueError as exc:
        assert "instancia de WhatsApp gerencial" in str(exc)
    else:
        raise AssertionError("Debe exigir una instancia gerencial explícita")


def test_managerial_delivery_config_reads_dedicated_environment(monkeypatch):
    from app.services.managerial_summary_service import ManagerialDeliveryConfig

    monkeypatch.setenv("FEMAG_MANAGERIAL_EMAIL", "dueno@example.com")
    monkeypatch.setenv("FEMAG_MANAGERIAL_WHATSAPP", "5491112345678")
    monkeypatch.setenv("FEMAG_MANAGERIAL_WHATSAPP_INSTANCE", "vogel_consultoria")
    monkeypatch.setenv("FEMAG_MANAGERIAL_AUTO_ENABLED", "true")

    config = ManagerialDeliveryConfig.from_env()

    assert config.email == "dueno@example.com"
    assert config.phone == "5491112345678"
    assert config.whatsapp_instance_id == "vogel_consultoria"
    assert config.auto_enabled is True


def test_managerial_summary_cli_modes():
    from app.jobs.send_managerial_summary import build_parser

    parser = build_parser()

    assert parser.parse_args(["--health-check"]).health_check is True
    assert parser.parse_args(["--send-now"]).send_now is True
    assert parser.parse_args(["--daily"]).daily is True


def test_managerial_summary_cli_rejects_multiple_modes():
    import pytest

    from app.jobs.send_managerial_summary import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--send-now", "--daily"])


def test_managerial_whatsapp_client_uses_dedicated_credentials(monkeypatch):
    from app.services.managerial_summary_service import ManagerialDeliveryConfig

    monkeypatch.setenv("FEMAG_MANAGERIAL_WHATSAPP_INSTANCE", "gerencial")
    monkeypatch.setenv("FEMAG_MANAGERIAL_WHATSAPP_API_URL", "https://wa.example.com/")
    monkeypatch.setenv("FEMAG_MANAGERIAL_WHATSAPP_API_KEY", "managerial-key")

    client = ManagerialDeliveryConfig.from_env().whatsapp_client()

    assert client.config.base_url == "https://wa.example.com"
    assert client.config.api_key == "managerial-key"
    assert client.config.instance_id == "gerencial"


def test_compact_money_uses_thousands_separator_for_millions():
    from app.services.managerial_summary_service import _compact_money

    assert _compact_money(1_677_330_000) == "$ 1.677,33 M"
    assert _compact_money(834_270_000) == "$ 834,27 M"


def test_whatsapp_zero_activity_is_readable(db):
    from app.services.managerial_summary_service import ManagerialSummaryService

    service = ManagerialSummaryService()
    summary = service.build(as_of=date(2026, 9, 20))

    # El texto no debe exponer una linea tecnica con 0,000 TN y 0 cargas.
    whatsapp = service.render_whatsapp(summary)
    if "Despachos hoy: $ 0,00" in whatsapp:
        assert "🚚 Sin despachos registrados hoy" in whatsapp


def test_normalize_delivery_status():
    from app.services.managerial_summary_service import normalize_delivery_status

    assert normalize_delivery_status("sent") == "sent"
    assert normalize_delivery_status("delivered") == "sent"
    assert normalize_delivery_status("read") == "sent"
    assert normalize_delivery_status("accepted") == "accepted"
    assert normalize_delivery_status("queued") == "accepted"
    assert normalize_delivery_status("processing") == "accepted"
    assert normalize_delivery_status("failed") == "failed"
    assert normalize_delivery_status("error") == "failed"
    assert normalize_delivery_status("") == "unknown"
    assert normalize_delivery_status(None) == "unknown"
    assert normalize_delivery_status("algo-raro") == "unknown"


def test_record_delivery_preserves_provider_status_and_normalizes(db):
    from app.services.managerial_summary_service import ManagerialSummaryService

    service = ManagerialSummaryService()
    row = service.record_delivery(
        mode="automatic",
        channel="whatsapp",
        recipient="5491112345678",
        status="processing",
        provider_message_id="msg-1",
        run_key="managerial:2026-11-07:whatsapp",
    )
    assert row.status == "accepted"
    assert row.provider_status == "processing"
    assert row.provider_message_id == "msg-1"
    assert row.finished_at is not None

    sent = service.record_delivery(
        mode="manual",
        channel="email",
        recipient="dueno@example.com",
        status="sent",
    )
    assert sent.status == "sent"
    assert sent.provider_status is None


def test_reconcile_stale_deliveries_marks_old_transient_only(db):
    from datetime import timedelta

    from app.models.base import utc_now
    from app.models.system import ManagerialSummaryDelivery
    from app.services.managerial_summary_service import ManagerialSummaryService

    now = utc_now()
    old = ManagerialSummaryDelivery.create(
        mode="automatic",
        channel="whatsapp",
        recipient="x",
        status="processing",
        created_at=now - timedelta(hours=48),
    )
    recent = ManagerialSummaryDelivery.create(
        mode="automatic",
        channel="whatsapp",
        recipient="x",
        status="queued",
        created_at=now - timedelta(hours=1),
    )
    sent = ManagerialSummaryDelivery.create(
        mode="automatic",
        channel="whatsapp",
        recipient="x",
        status="sent",
        created_at=now - timedelta(hours=48),
    )

    count = ManagerialSummaryService().reconcile_stale_deliveries(
        max_age_hours=24, now=now
    )

    assert count == 1
    old = ManagerialSummaryDelivery.get_by_id(old.id)
    recent = ManagerialSummaryDelivery.get_by_id(recent.id)
    sent = ManagerialSummaryDelivery.get_by_id(sent.id)
    assert old.status == "unknown"
    assert old.provider_status == "processing"
    assert "24 h" in (old.error or "")
    assert old.finished_at is not None
    assert recent.status == "queued"
    assert sent.status == "sent"


def test_delivery_health_reports_missing_stale_and_ok(db):
    from datetime import timedelta

    from app.models.base import utc_now
    from app.models.system import ManagerialSummaryDelivery
    from app.services.managerial_summary_service import ManagerialSummaryService

    service = ManagerialSummaryService()
    assert service.delivery_health()["state"] == "missing"

    ManagerialSummaryDelivery.create(
        mode="automatic",
        channel="whatsapp",
        recipient="x",
        status="sent",
        created_at=utc_now() - timedelta(hours=48),
    )
    health = service.delivery_health(max_age_hours=36)
    assert health["state"] == "stale"
    assert health["pending"] == 0

    ManagerialSummaryDelivery.create(
        mode="automatic",
        channel="email",
        recipient="x",
        status="accepted",
        created_at=utc_now(),
    )
    health = service.delivery_health(max_age_hours=36)
    assert health["state"] == "ok"


def test_already_sent_uses_run_key(db):
    from app.jobs.send_managerial_summary import _already_sent
    from app.models.system import ManagerialSummaryDelivery

    assert _already_sent("managerial:2026-11-07:whatsapp") is False
    ManagerialSummaryDelivery.create(
        run_key="managerial:2026-11-07:whatsapp",
        mode="automatic",
        channel="whatsapp",
        recipient="x",
        status="sent",
    )
    assert _already_sent("managerial:2026-11-07:whatsapp") is True
    assert _already_sent("managerial:2026-11-08:whatsapp") is False


def test_managerial_summary_cli_includes_reconcile():
    from app.jobs.send_managerial_summary import build_parser

    assert build_parser().parse_args(["--reconcile"]).reconcile is True
