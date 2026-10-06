from __future__ import annotations


def test_schedule_application_quit_defers_quit_to_next_qt_cycle(monkeypatch):
    import app.ui.application_lifecycle_extension as lifecycle

    calls: list[tuple[int, object]] = []

    class FakeTimer:
        @staticmethod
        def singleShot(delay_ms, callback):
            calls.append((delay_ms, callback))

    class FakeApp:
        def __init__(self):
            self.quit_calls = 0

        def quit(self):
            self.quit_calls += 1

    app = FakeApp()
    monkeypatch.setattr(lifecycle, "QTimer", FakeTimer)

    lifecycle._schedule_application_quit(app)

    assert app.quit_calls == 0
    assert calls == [(0, app.quit)]
