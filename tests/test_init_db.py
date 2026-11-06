from types import SimpleNamespace


def _target():
    from app.config.admin_target import AdminTarget

    return AdminTarget(
        settings=SimpleNamespace(
            db_engine="mysql",
            db_host="db.puesto.local",
            db_port=3306,
            db_name="femag_desktop",
            sqlite_path=None,
        ),
        secure_config=True,
    )


def test_init_db_runs_explicit_schema_preparation(monkeypatch, capsys):
    from scripts import init_db

    calls = []

    class Database:
        def connect(self, *, reuse_if_open):
            calls.append(("connect", reuse_if_open))

        def is_closed(self):
            return False

        def close(self):
            calls.append(("close",))

    database = Database()
    monkeypatch.setattr(init_db, "resolve_admin_target", _target)
    monkeypatch.setattr(
        init_db, "initialize_runtime_database", lambda _settings: database
    )
    monkeypatch.setattr(
        init_db,
        "ensure_runtime_schema",
        lambda target: calls.append(("ensure", target)),
    )

    assert init_db.main([]) == 0
    assert calls == [("connect", True), ("ensure", database), ("close",)]
    captured = capsys.readouterr()
    assert "Base destino: mysql db.puesto.local:3306/femag_desktop" in captured.out
    assert "Base FEMAG preparada correctamente" in captured.out


def test_init_db_reports_failure_and_closes_connection(monkeypatch, capsys):
    from scripts import init_db

    calls = []

    class Database:
        def connect(self, *, reuse_if_open):
            calls.append(("connect", reuse_if_open))

        def is_closed(self):
            return False

        def close(self):
            calls.append(("close",))

    database = Database()
    monkeypatch.setattr(init_db, "resolve_admin_target", _target)
    monkeypatch.setattr(
        init_db, "initialize_runtime_database", lambda _settings: database
    )
    monkeypatch.setattr(
        init_db,
        "ensure_runtime_schema",
        lambda _target: (_ for _ in ()).throw(RuntimeError("sensitive database detail")),
    )

    assert init_db.main([]) == 1
    assert calls == [("connect", True), ("close",)]
    captured = capsys.readouterr()
    assert "No se pudo preparar la base FEMAG" in captured.err
    assert "sensitive database detail" not in captured.err


def test_init_db_reports_configuration_failure(monkeypatch, capsys):
    from scripts import init_db

    monkeypatch.setattr(
        init_db,
        "resolve_admin_target",
        lambda: (_ for _ in ()).throw(ValueError("sensitive configuration detail")),
    )

    assert init_db.main([]) == 1
    captured = capsys.readouterr()
    assert "No se pudo resolver la base destino" in captured.err
    assert "sensitive configuration detail" not in captured.err
