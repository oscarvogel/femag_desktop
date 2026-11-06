"""Los scripts de administracion deben apuntar a la base del puesto (#685)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INIT_DB = ROOT / "scripts" / "init_db.py"
IMPORT_DGR = ROOT / "scripts" / "import_dgr_reference.py"


def _clean_env(tmp_path: Path, *, database: Path) -> dict[str, str]:
    home = tmp_path / "localappdata"
    home.mkdir()
    env_file = tmp_path / "demo.env"
    env_file.write_text(
        "FEMAG_DEMO=1\n"
        "FEMAG_DB_ENGINE=sqlite\n"
        f"FEMAG_SQLITE_PATH={database.as_posix()}\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    for key in (
        "FEMAG_SECURE_CONFIG",
        "FEMAG_DEMO",
        "FEMAG_DB_ENGINE",
        "FEMAG_SQLITE_PATH",
        "FEMAG_ENV_FILE",
    ):
        env.pop(key, None)
    env["LOCALAPPDATA"] = str(home)
    env["FEMAG_ENV_FILE"] = str(env_file)
    return env


def _run(script: Path, args=(), *, tmp_path: Path, database: Path):
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=ROOT,
        env=_clean_env(tmp_path, database=database),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )


def test_admin_target_rejects_demo_sqlite(monkeypatch, tmp_path):
    from app.config.admin_target import (
        describe_admin_target,
        require_mysql_target,
        resolve_admin_target,
    )

    monkeypatch.setattr(
        "app.config.secure_credentials.has_runtime_configuration", lambda: False
    )
    monkeypatch.delenv("FEMAG_SECURE_CONFIG", raising=False)
    monkeypatch.setenv("FEMAG_DEMO", "1")
    monkeypatch.setenv("FEMAG_DB_ENGINE", "sqlite")
    monkeypatch.setenv("FEMAG_SQLITE_PATH", str(tmp_path / "demo.sqlite3"))
    monkeypatch.setenv("FEMAG_ENV_FILE", str(tmp_path / "missing.env"))

    target = resolve_admin_target()

    assert target.is_mysql is False
    assert describe_admin_target(target).startswith("sqlite ")
    error = require_mysql_target(target)
    assert error is not None
    assert "SQLite" in error
    assert "no a la base MySQL" in error
    assert require_mysql_target(target, allow_sqlite=True) is None


def test_admin_target_with_secure_config_is_mysql_without_password(monkeypatch):
    from app.config.admin_target import describe_admin_target, resolve_admin_target
    from app.config.secure_credentials import RuntimeConnection

    connection = RuntimeConnection(
        host="db.puesto.local",
        port=3307,
        database="femag_desktop",
        user="femag",
        password="clave-super-secreta",
    )
    monkeypatch.setattr(
        "app.config.secure_credentials.has_runtime_configuration", lambda: True
    )
    monkeypatch.setattr(
        "app.config.secure_credentials.load_runtime_connection", lambda: connection
    )

    target = resolve_admin_target()

    assert target.is_mysql is True
    assert target.secure_config is True
    described = describe_admin_target(target)
    assert "db.puesto.local:3307/femag_desktop" in described
    assert "clave-super-secreta" not in described


def test_init_db_refuses_demo_sqlite_without_touching_it(tmp_path):
    database = tmp_path / "demo.sqlite3"

    result = _run(INIT_DB, tmp_path=tmp_path, database=database)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "Base destino: sqlite" in result.stdout
    assert "no a la base MySQL" in result.stderr
    assert database.exists() is False


def test_init_db_prepares_demo_only_with_explicit_flag(tmp_path):
    database = tmp_path / "demo.sqlite3"

    result = _run(
        INIT_DB, ["--allow-sqlite"], tmp_path=tmp_path, database=database
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Base FEMAG preparada correctamente" in result.stdout
    assert database.exists() is True


def test_import_dgr_refuses_demo_sqlite_before_reading_files(tmp_path):
    database = tmp_path / "demo.sqlite3"
    fake_dbf = tmp_path / "paises.dbf"

    result = _run(
        IMPORT_DGR,
        ["--paises", str(fake_dbf)],
        tmp_path=tmp_path,
        database=database,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "Base destino: sqlite" in result.stdout
    assert "no a la base MySQL" in result.stderr
    assert database.exists() is False
