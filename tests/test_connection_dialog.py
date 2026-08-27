from app.ui import connection_dialog


def test_existing_runtime_configuration_skips_connection_dialog(monkeypatch):
    monkeypatch.setattr(connection_dialog, "has_runtime_configuration", lambda: True)
    monkeypatch.setattr(
        connection_dialog,
        "test_runtime_connection",
        lambda _connection: (_ for _ in ()).throw(AssertionError("must not validate on startup")),
    )

    class FailDialog:
        def __init__(self, *args, **kwargs):
            raise AssertionError("connection dialog must not open when config already exists")

    monkeypatch.setattr(connection_dialog, "ConnectionDialog", FailDialog)

    assert connection_dialog.ensure_runtime_configuration(force=False) is True


def test_force_configuration_still_opens_dialog(monkeypatch):
    monkeypatch.setattr(connection_dialog, "load_runtime_connection", lambda: None)

    calls = []

    class FakeDialog:
        def __init__(self, *, current=None, parent=None):
            calls.append((current, parent))

        def exec_(self):
            return 1

    monkeypatch.setattr(connection_dialog, "ConnectionDialog", FakeDialog)

    assert connection_dialog.ensure_runtime_configuration(force=True) is True
    assert len(calls) == 1
