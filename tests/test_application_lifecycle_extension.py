from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "app" / "ui" / "application_lifecycle_extension.py"
MAIN = ROOT / "app" / "main.py"


def test_login_does_not_quit_qapplication_before_main_window() -> None:
    content = EXTENSION.read_text(encoding="utf-8")

    assert "app.setQuitOnLastWindowClosed(False)" in content
    assert "app.setQuitOnLastWindowClosed(True)" in content
    assert "original_login_init" in content
    assert "original_main_init" in content


def test_application_lifecycle_extension_is_installed() -> None:
    content = MAIN.read_text(encoding="utf-8")

    assert "install_application_lifecycle_extension" in content
    assert "install_application_lifecycle_extension()" in content
