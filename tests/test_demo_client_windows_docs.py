from pathlib import Path


def test_windows_demo_installer_script_documents_required_flow():
    script = Path("scripts/instalar_femag_demo.ps1").read_text(encoding="utf-8")
    docs = Path("docs/demo_cliente_windows.md").read_text(encoding="utf-8")

    assert "Git.Git" in script
    assert "Python.Python.3.12" in script
    assert "https://github.com/oscarvogel/femag_desktop.git" in script
    assert '[string]$Branch = "main"' in script
    assert "[string]$InstallDir" in script
    assert '$RepoDir = if ($InstallDir)' in script
    assert "codex/issue-73-load-order-integral-demo" not in script
    assert "requirements.txt" in script
    assert "FEMAG_DB_ENGINE=sqlite" in script
    assert "FEMAG_SQLITE_PATH=femag_demo.sqlite3" in script
    assert "FEMAG_DEMO=1" in script
    assert "backups\\issue_73_integral_demo.sqlite3" not in script
    assert "scripts\\init_db.py" in script
    assert "scripts\\issue_73_integral_demo.py" in script
    assert "app.main" in script
    assert "--smoke" in script
    assert "--demo-ui" in script

    assert "repo es privado" in docs
    assert "no el sistema productivo final" in docs
    assert "Orden de carga multi-cliente/multi-destino" in docs
    assert "main" in docs
    assert '-InstallDir "C:\\femag_desktop\\app"' in docs
