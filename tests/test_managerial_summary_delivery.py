from datetime import date


def test_managerial_summary_reuses_dashboard_and_account_risk(db):
    from app.services.managerial_summary_service import ManagerialSummaryService

    summary = ManagerialSummaryService().build(as_of=date(2026, 9, 20))

    assert summary.as_of == date(2026, 9, 20)
    assert summary.today_snapshot.period.start == date(2026, 9, 20)
    assert summary.month_snapshot.period.start == date(2026, 9, 1)
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
