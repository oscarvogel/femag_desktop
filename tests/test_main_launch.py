def test_main_without_smoke_starts_desktop_launcher(monkeypatch):
    import app.main as main_module

    calls = []

    def fake_run_desktop_app():
        calls.append("started")
        return 0

    monkeypatch.setattr(main_module, "run_desktop_app", fake_run_desktop_app)

    assert main_module.main([]) == 0
    assert calls == ["started"]
