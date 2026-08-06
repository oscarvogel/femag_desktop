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
    monkeypatch.setattr(init_db, "initialize_runtime_database", lambda: database)
    monkeypatch.setattr(init_db, "ensure_runtime_schema", lambda target: calls.append(("ensure", target)))

    assert init_db.main() == 0
    assert calls == [("connect", True), ("ensure", database), ("close",)]
    assert "Base FEMAG preparada correctamente" in capsys.readouterr().out


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
    monkeypatch.setattr(init_db, "initialize_runtime_database", lambda: database)
    monkeypatch.setattr(
        init_db,
        "ensure_runtime_schema",
        lambda _target: (_ for _ in ()).throw(RuntimeError("sensitive database detail")),
    )

    assert init_db.main() == 1
    assert calls == [("connect", True), ("close",)]
    captured = capsys.readouterr()
    assert "No se pudo preparar la base FEMAG" in captured.err
    assert "sensitive database detail" not in captured.err


def test_init_db_reports_configuration_failure(monkeypatch, capsys):
    from scripts import init_db

    monkeypatch.setattr(
        init_db,
        "initialize_runtime_database",
        lambda: (_ for _ in ()).throw(ValueError("sensitive configuration detail")),
    )

    assert init_db.main() == 1
    captured = capsys.readouterr()
    assert "No se pudo preparar la base FEMAG" in captured.err
    assert "sensitive configuration detail" not in captured.err
