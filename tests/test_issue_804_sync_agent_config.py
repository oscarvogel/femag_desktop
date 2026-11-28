"""Carga de sync.env del agente congelado (#804)."""

import os

import pytest


def test_sync_agent_loads_configured_env_file(monkeypatch, tmp_path):
    from app.jobs.sync_agent import _load_config

    config = tmp_path / "sync.env"
    config.write_text(
        "FEMAG_SYNC_BASE_URL=https://sync.example\n"
        "FEMAG_SYNC_API_TOKEN=token\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FEMAG_SYNC_ENV_FILE", str(config))
    monkeypatch.delenv("FEMAG_ENV_FILE", raising=False)
    monkeypatch.delenv("FEMAG_SYNC_BASE_URL", raising=False)
    monkeypatch.delenv("FEMAG_SYNC_API_TOKEN", raising=False)

    assert _load_config() == config
    assert os.environ["FEMAG_SYNC_BASE_URL"] == "https://sync.example"
    assert os.environ["FEMAG_ENV_FILE"] == str(config)


def test_sync_agent_fails_if_configured_env_file_is_missing(monkeypatch, tmp_path):
    from app.jobs.sync_agent import _load_config

    missing = tmp_path / "no-existe.env"
    monkeypatch.setenv("FEMAG_SYNC_ENV_FILE", str(missing))

    with pytest.raises(SystemExit):
        _load_config()


def test_sync_agent_routes_rates_command(monkeypatch):
    from app.jobs import sync_agent

    called = []
    monkeypatch.setattr(sync_agent, "_load_config", lambda: None)
    monkeypatch.setattr(sync_agent, "_configure_logging", lambda: None)
    monkeypatch.setattr(
        sync_agent, "run_rates", lambda: called.append(True) or 0
    )

    assert sync_agent.main(["--rates"]) == 0
    assert called == [True]


def test_sync_agent_updates_rates_once_per_day(monkeypatch, capsys):
    from app.jobs import sync_agent

    calls = []

    class _FakeDatabase:
        def connect(self, **kwargs):
            return None

        def is_closed(self):
            return False

        def close(self):
            return None

    class _FakePublisher:
        def __init__(self, *args, **kwargs):
            pass

        def pull_and_apply(self):
            return {}

        def publish_snapshot(self, client):
            return {"skipped": False}

        def should_publish(self):
            return False

        def should_publish_history(self):
            return False

        def publish(self, client):
            return {}

        def publish_history(self, client):
            return {}

    class _FakeResult:
        errors = ()

        def as_dict(self):
            return {"status": "ok", "registered": 7}

    monkeypatch.setattr(sync_agent, "initialize_runtime_database", lambda: _FakeDatabase())
    monkeypatch.setattr(sync_agent, "validate_sync_schema", lambda database: None)
    monkeypatch.setattr(sync_agent, "_client_from_env", lambda: object())
    monkeypatch.setattr(sync_agent, "SyncEventConsumer", _FakePublisher)
    monkeypatch.setattr(sync_agent, "SyncOrderPublisher", _FakePublisher)
    monkeypatch.setattr(sync_agent, "ManagerialSnapshotPublisher", _FakePublisher)
    monkeypatch.setattr(sync_agent, "ManagerialRepurchasePublisher", _FakePublisher)
    monkeypatch.setattr(sync_agent, "should_run_daily", lambda: True)
    monkeypatch.setattr(
        sync_agent,
        "run_daily_update",
        lambda: calls.append("rates") or _FakeResult(),
    )

    assert sync_agent.run_sync() == 0
    assert calls == ["rates"]
    assert '"rates"' in capsys.readouterr().out
