from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_INFO = ROOT / "app" / "build_info.py"
BUILD_SCRIPT = ROOT / "scripts" / "build_production_installer.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "publish-production.yml"
PROMOTION_WORKFLOW = ROOT / ".github" / "workflows" / "promote-production.yml"
ISS = ROOT / "installer" / "FEMAG_Desktop.iss"
SPEC = ROOT / "installer" / "FEMAG_Desktop.spec"
UPDATE_SERVICE = ROOT / "app" / "services" / "update_service.py"
UPDATE_EXTENSION = ROOT / "app" / "ui" / "update_extension.py"
MAIN = ROOT / "app" / "main.py"


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


def test_main_merge_publishes_candidate_only_after_real_validation():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in workflow
    assert "- main" in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "VOGEL_RELEASES_TOKEN" in workflow
    assert "apps/femag/candidate.json" in workflow
    assert "femag-candidate" in workflow
    assert "channel = 'candidate'" in workflow
    assert "Frozen executable smoke test" in workflow
    assert "Frozen production health check" in workflow
    assert "Clean install and upgrade validation" in workflow
    assert "Configuration and secret safety check" in workflow
    assert "git add -- apps/femag/candidate.json" in workflow
    assert "git add -- apps/femag/latest.json" not in workflow
    assert "gh release upload latest" not in workflow


def test_promotion_is_manual_idempotent_and_promotes_same_bytes_with_previous():
    workflow = PROMOTION_WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "expected_version" in workflow
    assert "expected_sha256" in workflow
    assert "confirmation" in workflow
    assert "concurrency:" in workflow
    assert "femag-production-promotion" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "Download-And-Verify" in workflow
    assert "CANDIDATE_TAG: femag-candidate" in workflow
    assert "LATEST_TAG: latest" in workflow
    assert "PREVIOUS_TAG: femag-previous" in workflow
    assert "apps/femag/previous.json" in workflow
    assert "apps/femag/history.jsonl" in workflow
    assert "Candidate ya esta promovido exactamente" in workflow
    assert "VOGEL_RELEASES_TOKEN" in workflow


def test_pilot_channel_is_opt_in_and_approval_has_no_embedded_token():
    service = UPDATE_SERVICE.read_text(encoding="utf-8")
    extension = UPDATE_EXTENSION.read_text(encoding="utf-8")
    assert 'UPDATE_CHANNEL_ENV = "FEMAG_UPDATE_CHANNEL"' in service
    assert 'CANDIDATE_MANIFEST_URL' in service
    assert 'LATEST_MANIFEST_URL' in service
    assert 'candidate_receipt_matches' in service
    assert 'Aprobar esta versión para producción' in extension
    assert 'PermissionService.is_administrator' in extension
    assert 'run_production_health_check' in extension
    assert 'PROMOTION_WORKFLOW_URL' in extension
    assert 'VOGEL_RELEASES_TOKEN' not in extension
    assert 'ghp_' not in extension


def test_production_health_cli_is_available():
    main = MAIN.read_text(encoding="utf-8")
    assert '"--production-health-check"' in main
    assert "run_production_health_check" in main
