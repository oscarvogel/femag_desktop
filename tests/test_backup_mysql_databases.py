from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "backup_mysql_databases.py"
SPEC = importlib.util.spec_from_file_location("backup_mysql_databases", SCRIPT_PATH)
backup_mysql_databases = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = backup_mysql_databases
SPEC.loader.exec_module(backup_mysql_databases)


def test_accessible_databases_excludes_mysql_system_schemas(monkeypatch):
    class Cursor:
        def execute(self, query):
            assert query == "SHOW DATABASES"

        def fetchall(self):
            return [("mysql",), ("femag",), ("sys",), ("reportes",)]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(backup_mysql_databases.pymysql, "connect", lambda **_kwargs: connection)

    databases = backup_mysql_databases.accessible_databases(
        backup_mysql_databases.RuntimeConnection("server", 3306, "femag", "user", "secret")
    )

    assert databases == ["femag", "reportes"]
    assert connection.closed is True


def test_parse_args_defaults_to_the_femag_local_backup_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    monkeypatch.setattr(backup_mysql_databases, "default_config_dir", lambda: tmp_path / "FEMAG Desktop")

    args = backup_mysql_databases.parse_args([])

    assert args.backup_dir == tmp_path / "FEMAG Desktop" / "backups" / "mysql"


def test_create_backup_writes_one_dump_and_manifest_per_database(monkeypatch, tmp_path):
    calls = []

    def fake_dump(connection, database, destination, *, mysqldump_path):
        calls.append((connection, database, destination, mysqldump_path))
        destination.write_text(f"dump {database}", encoding="utf-8")
        return backup_mysql_databases.DatabaseDump(database, str(destination), "success")

    monkeypatch.setattr(backup_mysql_databases.shutil, "which", lambda _path: "mysqldump.exe")
    monkeypatch.setattr(backup_mysql_databases, "dump_database", fake_dump)
    instant = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
    connection = backup_mysql_databases.RuntimeConnection("server", 3306, "femag", "user", "secret")

    run_dir, results = backup_mysql_databases.create_backup(
        connection,
        tmp_path,
        databases=["femag", "reportes diarios"],
        mysqldump_path="mysqldump.exe",
        now=instant,
    )

    assert run_dir == tmp_path / "20260908-120000"
    assert [call[2].name for call in calls] == ["femag.sql", "reportes_diarios.sql"]
    assert [result.status for result in results] == ["success", "success"]
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert [entry["database"] for entry in manifest["databases"]] == ["femag", "reportes diarios"]


def test_create_backup_uses_python_exporter_when_mysqldump_is_not_available(monkeypatch, tmp_path):
    calls = []

    def fake_python_dump(connection, database, destination, *, mysqldump_path):
        calls.append((database, mysqldump_path))
        destination.write_text("python dump", encoding="utf-8")
        return backup_mysql_databases.DatabaseDump(database, str(destination), "success")

    monkeypatch.setattr(backup_mysql_databases.shutil, "which", lambda _path: None)
    monkeypatch.setattr(backup_mysql_databases, "dump_database_with_python", fake_python_dump)

    _, results = backup_mysql_databases.create_backup(
        backup_mysql_databases.RuntimeConnection("server", 3306, "femag", "user", "secret"),
        tmp_path,
        databases=["femag"],
        now=datetime(2026, 9, 8, 12, 1, tzinfo=timezone.utc),
    )

    assert calls == [("femag", "mysqldump")]
    assert results[0].status == "success"


def test_dump_database_keeps_failed_dump_out_of_backup_directory(monkeypatch, tmp_path):
    class Completed:
        returncode = 1
        stderr = "access denied"

    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        return Completed()

    monkeypatch.setattr(backup_mysql_databases.subprocess, "run", fake_run)
    destination = tmp_path / "femag.sql"

    result = backup_mysql_databases.dump_database(
        backup_mysql_databases.RuntimeConnection("server", 3306, "femag", "user", "secret"),
        "femag",
        destination,
        mysqldump_path="mysqldump.exe",
    )

    assert result.status == "error"
    assert not destination.exists()
    assert not (tmp_path / "femag.sql.tmp").exists()
    assert "secret" not in captured["command"]
    assert captured["environment"]["MYSQL_PWD"] == "secret"
