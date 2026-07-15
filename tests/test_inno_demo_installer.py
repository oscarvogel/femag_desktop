from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "installer" / "FEMAG_Desktop_Demo.iss"
SPEC = ROOT / "installer" / "FEMAG_Desktop_Demo.spec"
BUILD_SCRIPT = ROOT / "scripts" / "build_demo_installer.ps1"
ENTRYPOINT = ROOT / "app" / "demo_entrypoint.py"
DOC = ROOT / "docs" / "INSTALADOR_DEMO_INNO.md"


def test_inno_installer_is_standalone_and_demo_only() -> None:
    content = ISS.read_text(encoding="utf-8")

    assert '#define MyAppName "FEMAG Desktop DEMO"' in content
    assert "DefaultDirName={localappdata}\\Programs\\FEMAG Desktop DEMO" in content
    assert "OutputBaseFilename=FEMAG_Desktop_DEMO_Standalone_Setup" in content
    assert "PrivilegesRequired=lowest" in content
    assert 'Filename: "{app}\\FEMAG Desktop DEMO.exe"' in content
    assert "dist\\FEMAG Desktop DEMO\\*" in content
    for forbidden in ("git", "python.exe", "winget", "powershell", "github", "RepoUrl"):
        assert forbidden.lower() not in content.lower()


def test_frozen_entrypoint_forces_local_sqlite_demo() -> None:
    content = ENTRYPOINT.read_text(encoding="utf-8")

    assert 'os.environ["FEMAG_DB_ENGINE"] = "sqlite"' in content
    assert 'os.environ["FEMAG_DEMO"] = "1"' in content
    assert 'data_dir / "femag_demo.sqlite3"' in content
    assert 'args = sys.argv[1:] or ["--demo-ui"]' in content


def test_build_contract_packages_python_runtime_before_inno() -> None:
    spec = SPEC.read_text(encoding="utf-8")
    build = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert 'name="FEMAG Desktop DEMO"' in spec
    assert "PyInstaller" in build
    assert "FEMAG_Desktop_Demo.spec" in build
    assert "FEMAG_Desktop_Demo.iss" in build


def test_standalone_requirements_are_documented() -> None:
    content = DOC.read_text(encoding="utf-8")

    assert "FEMAG_Desktop_DEMO_Standalone_Setup.exe" in content
    assert "No requiere Git" in content
    assert "No requiere Python" in content
    assert "No requiere Internet" in content
    assert "no tiene firma digital" in content
