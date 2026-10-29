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
