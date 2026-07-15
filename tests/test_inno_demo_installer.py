from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "installer" / "FEMAG_Desktop_Demo.iss"
LAUNCHER = ROOT / "installer" / "abrir_femag_demo.cmd"
DOC = ROOT / "docs" / "INSTALADOR_DEMO_INNO.md"


def test_inno_installer_is_explicitly_demo_only() -> None:
    content = ISS.read_text(encoding="utf-8")

    assert '#define MyAppName "FEMAG Desktop DEMO"' in content
    assert "DefaultDirName={localappdata}\\Programs\\FEMAG Desktop DEMO" in content
    assert "OutputBaseFilename=FEMAG_Desktop_DEMO_Setup" in content
    assert "PrivilegesRequired=lowest" in content
    assert "-SkipUi" in content
    assert "instalar_femag_demo.ps1" in content
    assert "FEMAG_DB_ENGINE=mysql" not in content


def test_demo_launcher_can_only_open_demo_ui() -> None:
    content = LAUNCHER.read_text(encoding="utf-8")

    assert "pythonw.exe" in content
    assert "-m app.main --demo-ui" in content
    assert "--ui" not in content.replace("--demo-ui", "")


def test_demo_installer_contract_is_documented() -> None:
    content = DOC.read_text(encoding="utf-8")

    assert "FEMAG_Desktop_DEMO_Setup.exe" in content
    assert "%LOCALAPPDATA%\\Programs\\FEMAG Desktop DEMO" in content
    assert "usuario" in content and "`demo`" in content
    assert "no tiene firma digital" in content
