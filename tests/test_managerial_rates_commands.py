"""El EXE gerencial enruta los comandos de cotizaciones (#969/#970)."""

from __future__ import annotations

import sys
import types

import pytest

from app import managerial_summary_entrypoint as entrypoint


def _fake_module(name: str, calls: list[list[str]]):
    module = types.ModuleType(name)

    def main(argv=None):
        calls.append(list(argv or []))
        return 17

    module.main = main
    return module


@pytest.fixture(autouse=True)
def _restore_env(monkeypatch):
    previous = sys.argv
    monkeypatch.setenv("FEMAG_ENV_FILE", "")
    try:
        yield
    finally:
        sys.argv = previous


def test_run_routes_update_rates(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    runtime_calls: list[bool] = []
    monkeypatch.setattr(
        entrypoint,
        "configure_production_runtime",
        lambda: runtime_calls.append(True) or tmp_path,
    )
    monkeypatch.setitem(
        sys.modules,
        "app.jobs.update_exchange_rates",
        _fake_module("app.jobs.update_exchange_rates", calls),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["FEMAG_Managerial_Summary.exe", "--update-rates", "--json"],
    )

    assert entrypoint.run() == 17
    assert calls == [["--json"]]
    assert runtime_calls == []


def test_run_routes_import_rates(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    monkeypatch.setattr(entrypoint, "configure_production_runtime", lambda: tmp_path)
    monkeypatch.setitem(
        sys.modules,
        "app.jobs.import_historical_exchange_rates",
        _fake_module("app.jobs.import_historical_exchange_rates", calls),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "FEMAG_Managerial_Summary.exe",
            "--import-rates",
            "--budgets",
            "--dry-run",
            "--types",
            "oficial",
        ],
    )

    assert entrypoint.run() == 17
    assert calls == [["--budgets", "--dry-run", "--types", "oficial"]]


def test_run_keeps_managerial_default(monkeypatch, tmp_path):
    calls: list[list[str]] = []
    monkeypatch.setattr(entrypoint, "configure_production_runtime", lambda: tmp_path)
    monkeypatch.setitem(
        sys.modules,
        "app.jobs.send_managerial_summary",
        _fake_module("app.jobs.send_managerial_summary", calls),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["FEMAG_Managerial_Summary.exe", "--daily"],
    )

    assert entrypoint.run() == 17
    assert calls == [["--daily"]]
