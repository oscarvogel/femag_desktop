from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_INFO = ROOT / "app" / "build_info.py"
BUILD_SCRIPT = ROOT / "scripts" / "build_production_installer.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "publish-production.yml"
ISS = ROOT / "installer" / "FEMAG_Desktop.iss"
SPEC = ROOT / "installer" / "FEMAG_Desktop.spec"


def test_development_build_identity_is_inert():
    content = BUILD_INFO.read_text(encoding="utf-8")
    assert 'APP_ID = "development"' in content
    assert 'BUILD_VERSION = "0.0.0.0.0.0"' in content


def test_production_build_injects_femag_identity_without_changing_historical_installer():
    build = BUILD_SCRIPT.read_text(encoding="utf-8")
    iss = ISS.read_text(encoding="utf-8")
    assert 'APP_ID = `"femag`"' in build
    assert 'Get-Date -Format "yyyy.MM.dd.HH.mm.ss"' in build
    assert 'FEMAG_Desktop_Produccion_Setup.exe' in build
    assert 'AppId={{10F03F3B-BA11-4F61-88DA-14DD2AA30EF4}' in iss
    assert 'DefaultDirName={localappdata}\\Programs\\FEMAG Desktop' in iss


def test_pyinstaller_keeps_known_femag_packaging_requirements():
    spec = SPEC.read_text(encoding="utf-8")
    assert 'collect_submodules("pyqt5libs")' in spec
    assert 'collect_data_files("pyqt5libs")' in spec
    assert 'collect_submodules("reportlab.graphics.barcode")' in spec
    assert 'collect_data_files("reportlab")' in spec
    assert 'app/ui/assets/branding' in spec


def test_publish_workflow_only_publishes_from_main_and_keeps_femag_isolated():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in workflow
    assert "branches:" in workflow
    assert "- main" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "VOGEL_RELEASES_TOKEN" in workflow
    assert "apps/femag/latest.json" in workflow
    assert "FEMAG_Desktop_Produccion_Setup.exe" in workflow
    assert "Frozen executable smoke test" in workflow
    assert "Configuration and secret safety check" in workflow
    assert "UTF8Encoding($false)" in workflow
    assert "git add -- apps/femag/latest.json" in workflow
