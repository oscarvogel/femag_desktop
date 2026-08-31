from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "installer" / "FEMAG_Desktop.iss"
SPEC = ROOT / "installer" / "FEMAG_Desktop.spec"
BUILD = ROOT / "scripts" / "build_production_installer.ps1"
ENTRYPOINT = ROOT / "app" / "production_entrypoint.py"
DOC = ROOT / "docs" / "INSTALADOR_PRODUCCION.md"
DEPLOY = ROOT / "DEPLOY.md"


def test_production_installer_has_no_database_credentials() -> None:
    content = ISS.read_text(encoding="utf-8")

    assert '#define MyAppName "FEMAG Desktop Produccion"' in content
    assert "UninstallDisplayName={#MyAppName}" in content
    assert "FEMAG_Desktop_Produccion_Setup" in content
    assert "DefaultDirName={localappdata}\\Programs\\FEMAG Desktop" in content
    for secret_name in ("DB_PASSWORD", "DB_USER", "DB_HOST", "real_mysql_password"):
        assert secret_name not in content


def test_uninstaller_does_not_remove_user_configuration() -> None:
    content = ISS.read_text(encoding="utf-8")

    assert "[UninstallDelete]" not in content
    assert "%LOCALAPPDATA%\\FEMAG Desktop" not in content
    assert 'Parameters: "--configure"' in content


def test_production_bundle_uses_production_entrypoint() -> None:
    spec = SPEC.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    build = BUILD.read_text(encoding="utf-8")

    assert '"../app/production_entrypoint.py"' in spec
    assert 'name="FEMAG Desktop"' in spec
    assert 'os.environ["FEMAG_SECURE_CONFIG"] = "1"' in entrypoint
    assert "args = sys.argv[1:]" in entrypoint
    assert 'args = args or ["--ui"]' in entrypoint
    assert "FEMAG_Desktop.spec" in build
    assert "FEMAG_Desktop.iss" in build


def test_production_bundle_includes_reportlab_barcode_submodules() -> None:
    spec = SPEC.read_text(encoding="utf-8")

    assert 'collect_submodules("reportlab.graphics.barcode")' in spec
    assert 'collect_data_files("reportlab")' in spec


def test_secure_first_run_is_documented() -> None:
    content = DOC.read_text(encoding="utf-8")

    assert "Windows DPAPI" in content
    assert "CurrentUser" in content
    assert "connection.credential" in content
    assert "Los arranques normales no crean ni modifican tablas" in content
    assert "no tiene firma digital" in content
    assert "politica corporativa" in content


def test_each_production_build_uses_timestamp_version() -> None:
    build = BUILD.read_text(encoding="utf-8")
    iss = ISS.read_text(encoding="utf-8")
    deploy = DEPLOY.read_text(encoding="utf-8")

    assert 'Get-Date -Format "yyyy.MM.dd.HH.mm.ss"' in build
    assert 'app\\build_version.py' in build
    assert '"/DMyAppVersion=$BuildVersion"' in build
    assert "DMyOutputBaseFilename" not in build
    assert "OutputBaseFilename=FEMAG_Desktop_Produccion_Setup" in iss
    assert "AAAA.MM.DD.HH.MM.SS" in deploy
    assert "FEMAG_Desktop_Produccion_Setup.exe" in deploy
