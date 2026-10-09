from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy_webapp_server.ps1"
ENV_TEMPLATE = ROOT / "scripts" / "webapp-server.env.example"
WINDOWS_GUIDE = ROOT / "docs" / "WEBAPP_SERVER_WINDOWS.md"


def test_webapp_server_deployment_is_redeployable_and_keeps_mysql_local():
    content = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert '"/MIR"' in content
    assert "FEMAG_AUTO_MIGRATE_SCHEMA=0" in content
    assert "127.0.0.1" in content
    assert "FEMAG Webapp QR" in content
    assert "Wait-ForHealthCheck" in content
    assert "*.credential" in content
    assert '".env"' in content


def test_webapp_server_configuration_template_has_no_real_credential():
    content = ENV_TEMPLATE.read_text(encoding="utf-8")

    assert "DB_PASSWORD=REEMPLAZAR_POR_CLAVE_SEGURA" in content
    assert "FEMAG_AUTO_MIGRATE_SCHEMA=0" in content
    assert "DB_HOST=127.0.0.1" in content


def test_windows_deployment_guide_covers_first_install_and_redeploy():
    content = WINDOWS_GUIDE.read_text(encoding="utf-8")

    assert "## Primera instalación" in content
    assert "## Re-despliegue" in content
    assert "Caddy" in content
    assert "/health" in content
